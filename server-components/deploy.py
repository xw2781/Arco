"""Request a component build and deploy from the machine that owns the server.

A deploy performed from a client machine spends almost all of its time writing
the frozen build across the workspace share. This CLI instead sends the source
and lets the ArcRho Build Listener build and deploy locally, then streams the
listener's log back and exits non-zero if anything failed — which is what makes
it usable from a script or an agent rather than only by hand.

    python server-components/deploy.py                 # every stale component
    python server-components/deploy.py bridge engine   # named components
    python server-components/deploy.py --stale         # report only, build nothing
    python server-components/deploy.py --ref main      # build a pushed ref, no patch

Exit codes: 0 success (or nothing to do), 1 the build or deploy failed,
2 a usage or precondition problem, 3 no listener is running on the server.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Iterable, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ENGINE_SRC = REPOSITORY_ROOT / "server-components" / "src"
if str(ENGINE_SRC) not in sys.path:
    sys.path.insert(0, str(ENGINE_SRC))

from arcrho_build_components import (  # noqa: E402
    BUILD_CLONE_MARKER,
    COMPONENTS,
    COMPONENT_KEYS,
    DEPLOY_ROOT,
    Component,
    build_freshness,
    component_by_key,
    stale_components,
    workspace_drive_is_local,
)
from arcrho_build_request_contract import (  # noqa: E402
    SOURCE_MODE_REF,
    SOURCE_MODE_WORKING_TREE,
    BuildListenerUnavailable,
    BuildRequestContractError,
    build_build_request,
    build_log_path,
    build_payload_path,
    build_request_path,
    build_status_is_terminal,
    ensure_build_protocol_directories,
    new_request_id,
    read_build_status,
    require_live_listener,
    write_json_atomic,
)
from arcrho_gateway.user_guide import GUIDE_SOURCE  # noqa: E402

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PATCH_MEMBER_NAME = "changes.patch"
UNTRACKED_PREFIX = "untracked/"
POLL_SECONDS = 2.0
DEFAULT_TIMEOUT_SECONDS = 3600.0
LISTENER_START_TIMEOUT_SECONDS = 90.0
PAYLOAD_PREVIEW_LIMIT = 12

EXIT_OK = 0
EXIT_BUILD_FAILED = 1
EXIT_USAGE = 2
EXIT_NO_LISTENER = 3


class DeployRequestError(RuntimeError):
    """Raised for a precondition the caller can fix."""


def _git(
    *arguments: str,
    repository: Path = REPOSITORY_ROOT,
    check: bool = True,
    strip: bool = True,
) -> str:
    """Run one git command and return its output.

    ``strip`` is the default because almost every caller wants a single bare
    value -- a commit id, a file list. A patch is the exception. Its last line
    may be a context line that is a single space, and trimming that leaves the
    final hunk one line shorter than its own header claims, which ``git apply``
    rejects as ``corrupt patch`` rather than as a hunk that did not apply.
    """

    completed = subprocess.run(
        ["git", *arguments],
        cwd=str(repository),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    if completed.returncode != 0:
        if check:
            raise DeployRequestError(
                f"git {' '.join(arguments)} failed: "
                f"{(completed.stderr or completed.stdout or '').strip()}"
            )
        return ""
    output = completed.stdout or ""
    return output.strip() if strip else output


def _repository_relative_roots(components: Sequence[Component]) -> list[str]:
    """The repository trees whose contents these components freeze.

    Sending only these keeps a working-tree payload at kilobytes, and keeps
    unrelated local edits out of a server-side build.
    """

    paths: set[Path] = set()
    if any(component.key == "gateway" for component in components):
        # Published beside the executable; documentation edits alone do not
        # make the frozen Gateway stale.
        paths.add(GUIDE_SOURCE.relative_to(REPOSITORY_ROOT))
    for component in components:
        for root in (component.source_dir, *component.freshness_source_dirs):
            try:
                paths.add(root.resolve().relative_to(REPOSITORY_ROOT.resolve()))
            except ValueError:
                continue
    # Drop any path already covered by an ancestor, so git gets a minimal set.
    minimal: list[Path] = []
    for path in sorted(paths, key=lambda item: len(item.parts)):
        if any(path == kept or kept in path.parents for kept in minimal):
            continue
        minimal.append(path)
    return [path.as_posix() for path in minimal]


def _base_commit(repository: Path = REPOSITORY_ROOT) -> str:
    """The newest commit the server clone can already resolve.

    Diffing from the merge base with the remote rather than from HEAD means a
    local commit that has not been pushed still reaches the server inside the
    patch, so an agent never has to push just to deploy.
    """

    head = _git("rev-parse", "HEAD", repository=repository)
    for candidate in ("origin/HEAD", "origin/main", "origin/master"):
        remote = _git(
            "rev-parse", "--verify", f"{candidate}^{{commit}}", repository=repository, check=False
        )
        if not remote:
            continue
        base = _git("merge-base", head, remote, repository=repository, check=False)
        if base:
            return base
    return head


def _build_payload(
    roots: Sequence[str],
    base_commit: str,
    destination: Path,
    *,
    repository: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    """Zip the working-tree delta for ``roots``.

    The patch carries every tracked change since ``base_commit`` — committed or
    not — and untracked files ride along verbatim, because a new module that has
    never been committed is exactly the kind of change an agent needs to deploy.

    The returned file lists are what the caller shows the user. A working-tree
    deploy ships the *whole* tree's state under those roots, including edits
    somebody else is making at the same time, so what is being sent has to be
    visible rather than implied.
    """

    patch = _git(
        "diff",
        "--binary",
        base_commit,
        "--",
        *roots,
        repository=repository,
        check=False,
        strip=False,
    )
    changed = [
        line.strip()
        for line in _git(
            "diff", "--name-only", base_commit, "--", *roots, repository=repository, check=False
        ).splitlines()
        if line.strip()
    ]
    untracked = [
        line.strip()
        for line in _git(
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            *roots,
            repository=repository,
            check=False,
        ).splitlines()
        if line.strip()
    ]
    if not patch.strip() and not untracked:
        return {"archive": None, "size": 0, "changed": [], "untracked": []}

    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if patch.strip():
            # git already terminates its last line; a second newline would turn
            # the final context line into something git apply cannot parse.
            archive.writestr(
                PATCH_MEMBER_NAME, patch if patch.endswith("\n") else patch + "\n"
            )
        for relative in untracked:
            source = repository / relative
            if not source.is_file():
                continue
            archive.write(source, f"{UNTRACKED_PREFIX}{relative}")
    return {
        "archive": destination,
        "size": destination.stat().st_size,
        "changed": changed,
        "untracked": untracked,
    }


def _report_payload(payload: dict[str, Any], base_commit: str) -> None:
    """Print exactly which files this deploy will send to the server."""

    files = [*payload["changed"], *payload["untracked"]]
    print(
        f"Source delta: {payload['size'] / 1024:.1f} KB against {base_commit[:12]} "
        f"({len(payload['changed'])} changed, {len(payload['untracked'])} new)"
    )
    for relative in files[:PAYLOAD_PREVIEW_LIMIT]:
        print(f"  {relative}")
    if len(files) > PAYLOAD_PREVIEW_LIMIT:
        print(f"  ... and {len(files) - PAYLOAD_PREVIEW_LIMIT} more")


def _resolve_components(names: Iterable[str]) -> list[Component]:
    resolved: list[Component] = []
    for name in names:
        key = str(name).strip().lower()
        if key == "all":
            return list(COMPONENTS)
        try:
            component = component_by_key(key)
        except KeyError as exc:
            raise DeployRequestError(str(exc)) from exc
        if component not in resolved:
            resolved.append(component)
    return resolved


def _print_stale() -> int:
    print(f"Deploy root: {DEPLOY_ROOT}")
    for component in COMPONENTS:
        print(f"  {component.key:<13} {build_freshness(component)}")
    stale = stale_components()
    if stale:
        print("\nStale: " + ", ".join(component.key for component in stale))
    else:
        print("\nEvery deployed component is up to date.")
    return EXIT_OK


def _stream_log(server_root: Path, request_id: str, offset: int, limit: int) -> int:
    """Print whatever the listener has appended past ``offset``."""

    if limit <= offset:
        return offset
    path = build_log_path(server_root, request_id)
    try:
        with path.open("rb") as stream:
            stream.seek(offset)
            chunk = stream.read(max(0, limit - offset))
    except OSError:
        return offset
    if not chunk:
        return offset
    text = chunk.decode("utf-8", errors="replace")
    for line in text.splitlines():
        print(line)
    return offset + len(chunk)


def _wait_for_result(server_root: Path, request_id: str, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    offset = 0
    last_status = ""
    while True:
        status = read_build_status(server_root, request_id)
        if status is not None:
            offset = _stream_log(server_root, request_id, offset, int(status.get("log_bytes") or 0))
            current = str(status.get("status") or "")
            if current != last_status:
                last_status = current
                message = str(status.get("message") or "")
                print(f"[{current}] {message}" if message else f"[{current}]")
            if build_status_is_terminal(status):
                return status
        if time.monotonic() > deadline:
            raise DeployRequestError(
                f"Timed out after {int(timeout_seconds)}s waiting for the build result. "
                f"The listener may still be working; check the status file for {request_id}."
            )
        time.sleep(POLL_SECONDS)


def build_clones(repository_root: Path = REPOSITORY_ROOT) -> list[Path]:
    """Sibling clones marked as the listener's own, which nobody edits."""

    return sorted(marker.parent.parent for marker in repository_root.parent.glob(f"*/.git/{BUILD_CLONE_MARKER}"))


def _start_server_listener(server_root: Path) -> list[dict[str, Any]]:
    """On the Server PC, start the Build Manager from the build clone and wait for it to listen.

    Started from that clone, the Manager turns listening on by itself (see
    auto_listen_decision), so the one human step disappears where it is safe to
    skip. Anywhere else, or with no single marked clone, nothing is started.
    """

    if not workspace_drive_is_local(server_root):
        return []
    clones = build_clones()
    if len(clones) != 1:
        print(f"Not starting a listener: expected one clone marked .git/{BUILD_CLONE_MARKER}, found {len(clones)}.")
        return []
    launcher = clones[0] / "server-components" / "build_manager.bat"
    print(f"No listener is running; starting the Build Manager from {clones[0]}.")
    subprocess.Popen(["cmd", "/c", str(launcher)], cwd=launcher.parent, creationflags=CREATE_NO_WINDOW)
    deadline = time.monotonic() + LISTENER_START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            return require_live_listener(server_root)
        except BuildListenerUnavailable:
            time.sleep(POLL_SECONDS)
    return []


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="deploy.py",
        description="Build and deploy ArcRho components on the ArcRho Server machine.",
    )
    parser.add_argument(
        "components",
        nargs="*",
        help=f"Components to build ({', '.join(COMPONENT_KEYS)}, or 'all'). "
        "Defaults to every stale component.",
    )
    parser.add_argument("--stale", action="store_true", help="Report freshness and exit.")
    parser.add_argument(
        "--ref",
        default="",
        help="Build this pushed git ref instead of the local working tree.",
    )
    parser.add_argument("--no-wait", action="store_true", help="Submit and exit without waiting.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Seconds to wait for the result (default {int(DEFAULT_TIMEOUT_SECONDS)}).",
    )
    parser.add_argument("--json", action="store_true", help="Print the final status as JSON.")
    arguments = parser.parse_args(argv)

    if arguments.stale:
        return _print_stale()

    server_root = Path(DEPLOY_ROOT)
    try:
        if arguments.components:
            components = _resolve_components(arguments.components)
        else:
            components = stale_components()
            if not components:
                print("Every deployed component is up to date; nothing to build.")
                return EXIT_OK
            print("Stale components: " + ", ".join(item.key for item in components))

        try:
            listeners = require_live_listener(server_root)
        except BuildListenerUnavailable as exc:
            listeners = _start_server_listener(server_root)
            if not listeners:
                print(str(exc), file=sys.stderr)
                return EXIT_NO_LISTENER
        listener_names = ", ".join(str(item.get("Server") or "listener") for item in listeners)
        print(f"Listener: {listener_names}")

        user_name = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
        request_id = new_request_id(user_name)
        ensure_build_protocol_directories(server_root)

        payload_name = ""
        if arguments.ref:
            source_mode = SOURCE_MODE_REF
            base_commit = ""
        else:
            source_mode = SOURCE_MODE_WORKING_TREE
            base_commit = _base_commit()
            roots = _repository_relative_roots(components)
            with tempfile.TemporaryDirectory() as scratch:
                staged = Path(scratch) / "payload.zip"
                payload = _build_payload(roots, base_commit, staged)
                if payload["archive"] is not None:
                    destination = build_payload_path(server_root, request_id)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(payload["archive"].read_bytes())
                    payload_name = destination.name
                    _report_payload(payload, base_commit)
                else:
                    print(f"No local changes; building {base_commit[:12]} as committed")

        request = build_build_request(
            request_id=request_id,
            components=[item.key for item in components],
            source_mode=source_mode,
            base_commit=base_commit,
            ref=arguments.ref,
            payload_name=payload_name,
            user_name=user_name,
            machine=os.environ.get("COMPUTERNAME") or "",
            known_roles=COMPONENT_KEYS,
        )
        # The payload must already be in place: the listener claims a request as
        # soon as it appears and reads the payload beside it.
        write_json_atomic(build_request_path(server_root, request_id), request)
        print(f"Queued {request_id}: {', '.join(item.key for item in components)}")

        if arguments.no_wait:
            return EXIT_OK

        status = _wait_for_result(server_root, request_id, arguments.timeout)
    except (DeployRequestError, BuildRequestContractError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE

    if arguments.json:
        print(json.dumps(status, indent=2))
    if str(status.get("status")) == "success":
        print(f"Done: {status.get('message')}")
        return EXIT_OK
    print(f"Build failed: {status.get('message')}", file=sys.stderr)
    return EXIT_BUILD_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
