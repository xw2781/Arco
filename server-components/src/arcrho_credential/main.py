"""Give this PC its own Arco Gateway credential.

The Excel add-in starts this helper the first time it finds no credential on
the machine, so an Excel-only user is never set up by hand. The work itself is
``arcrho_api.hosted_save_enrollment.enroll_once``: this file only says which
Gateway to sign up at and where the credential goes, then prints one line
about what happened.

Windows sign-in is the authentication. The Gateway's sign-up route proves who
is asking with a Negotiate handshake and answers with that user's own secret;
nothing is read from the server's folder. The add-in is tied to production, so
the address is production's: ``--url``, else the address the desktop app keeps
for its production server.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = BASE_DIR.parents[2]
API_SOURCE = REPOSITORY_ROOT / "python-api" / "src"
if not getattr(sys, "frozen", False) and str(API_SOURCE) not in sys.path:
    sys.path.insert(0, str(API_SOURCE))

from arcrho_api.config import DEFAULT_PROFILE_ID, config_dir, load_workspace_config  # noqa: E402
from arcrho_api.hosted_save_enrollment import enroll_once  # noqa: E402
from arcrho_hosted_save_http_contract import CLIENT_CONFIG_FILE_NAME  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install this Windows user's Arco Gateway credential."
    )
    # The add-in still passes the workspace folder; the helper no longer reads it.
    parser.add_argument("workspace_root", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("--url", help="The Gateway address to sign up at.")
    return parser


def production_gateway_url() -> str:
    """The address the desktop app keeps for its production server, or ``""``."""

    profiles = load_workspace_config()["profiles"]
    production = next((p for p in profiles if p["id"] == DEFAULT_PROFILE_ID), {})
    return production.get("gateway_url", "")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = enroll_once(
        gateway_url=args.url or production_gateway_url(),
        client_output=config_dir() / CLIENT_CONFIG_FILE_NAME,
    )
    status = result["status"]
    if status == "enrolled":
        print(f"ArcRho credential installed: {result['path']}")
        return 0
    if status == "existing":
        print(f"ArcRho credential already present: {result['path']}")
        return 0
    if status == "not_configured":
        print("No Gateway address is known; open Arco once to set the server, or pass --url.")
        return 1
    print(f"ArcRho credential not installed: {result['reason']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
