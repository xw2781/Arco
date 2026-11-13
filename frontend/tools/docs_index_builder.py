#!/usr/bin/env python3
"""Build and maintain documentation indexes for ArcRho.

This tool implements a semi-automatic documentation workflow:
- `--scaffold-missing`: create missing docs skeleton files.
- `--write`: update generated docs and AUTO-GEN blocks.
- `--check`: verify docs are up-to-date and links resolve.

Only AUTO-GEN blocks are rewritten. MANUAL blocks are never touched.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"

EXCLUDED_DIRS = {
    ".cache",
    "node_modules",
    "node-portable",
    "node-v24.13.0-win-x64",
    "dist",
    "python_dist",
    "python_build",
    "__pycache__",
    ".pytest_cache",
    "local_workspace_log",
}

SECTIONS = [
    "Purpose",
    "Entry Points",
    "Key Files",
    "External Interfaces",
    "Data/State/Caches",
    "Common Change Tasks",
    "Known Risks",
]

AUTO_BLOCK_RE = re.compile(
    r"<!-- AUTO-GEN:BEGIN (?P<label>[^>]+) -->\n(?P<body>.*?)\n<!-- AUTO-GEN:END -->",
    flags=re.DOTALL,
)
MD_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

FRONTEND_ENTRY_HTMLS = [
    "ui/index.html",
    "ui/file_explorer/file_explorer.html",
    "ui/server/server.html",
    "ui/dashboard/dashboard.html",
    "ui/dataset_viewer/dataset_viewer.html",
    "ui/method_pages/dfm/dfm.html",
    "ui/method_pages/bornhuetter_ferguson/bornhuetter_ferguson.html",
    "ui/method_pages/cape_cod/cape_cod.html",
    "ui/method_pages/bootstrap/bootstrap.html",
    "ui/method_pages/stochastic_consolidation/stochastic_consolidation.html",
    "ui/method_pages/berquist_sherman/berquist_sherman.html",
    "ui/method_pages/result_selection/result_selection.html",
    "ui/workflow/workflow.html",
    "ui/project_settings/project_settings.html",
    "ui/project_instance/project_instance.html",
    "ui/arcode/main.html",
    "ui/arcode/notebook-editor/index.html",
    "ui/arcode/code-editor/index.html",
]

FRONTEND_PURPOSE_MAX_LINES = 6
FRONTEND_PURPOSE_MAX_CHARS = 900


@dataclass(frozen=True)
class ModuleDocSpec:
    path: str
    title: str
    manual_sections: Mapping[str, str]
    auto_sections: Mapping[str, str]


@dataclass(frozen=True)
class RouteEntry:
    domain: str
    router_file: str
    method: str
    path: str
    handler: str
    request_model: str
    request_schema: str
    services: Tuple[str, ...]


@dataclass(frozen=True)
class FrontendEntrypoint:
    html_path: str
    external_scripts: Tuple[str, ...]
    inline_imports: Tuple[str, ...]


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    size: int


def to_posix(path: Path) -> str:
    return path.as_posix()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    norm = text.replace("\r\n", "\n")
    if not norm.endswith("\n"):
        norm += "\n"
    path.write_text(norm, encoding="utf-8")


def maybe_write_text(path: Path, text: str) -> bool:
    norm = text.replace("\r\n", "\n")
    if not norm.endswith("\n"):
        norm += "\n"
    if path.exists():
        current = read_text(path)
        if current == norm:
            return False
    write_text(path, norm)
    return True


def rel_link(from_doc: str, target_repo_path: str) -> str:
    src_dir = (REPO_ROOT / from_doc).parent
    dst = REPO_ROOT / target_repo_path
    return to_posix(Path(os.path.relpath(dst, src_dir)))


def md_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    if not rows:
        return "_No records found._"
    out = []
    out.append("| " + " | ".join(headers) + " |")
    out.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        safe = [cell.replace("\n", "<br>") for cell in row]
        out.append("| " + " | ".join(safe) + " |")
    return "\n".join(out)


def dedent(text: str) -> str:
    return textwrap.dedent(text).strip()


def render_module_doc(spec: ModuleDocSpec) -> str:
    lines: List[str] = [f"# {spec.title}", ""]
    for section in SECTIONS:
        lines.append(f"## {section}")
        if section in spec.auto_sections:
            label = spec.auto_sections[section]
            lines.append(f"<!-- AUTO-GEN:BEGIN {label} -->")
            lines.append("_Run `python tools/docs_index_builder.py --write` to refresh this section._")
            lines.append("<!-- AUTO-GEN:END -->")
        else:
            body = spec.manual_sections.get(section, "TBD.")
            lines.append("<!-- MANUAL:BEGIN -->")
            lines.append(body.strip())
            lines.append("<!-- MANUAL:END -->")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def apply_auto_blocks(text: str, autogen: Mapping[str, str]) -> str:
    def _replace(match: re.Match[str]) -> str:
        label = match.group("label").strip()
        if label not in autogen:
            return match.group(0)
        payload = autogen[label].strip()
        return f"<!-- AUTO-GEN:BEGIN {label} -->\n{payload}\n<!-- AUTO-GEN:END -->"

    return AUTO_BLOCK_RE.sub(_replace, text)


def extract_auto_labels(text: str) -> List[str]:
    return [m.group("label").strip() for m in AUTO_BLOCK_RE.finditer(text)]


def annotation_to_str(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node).strip()
    except Exception:
        return ""


def function_request_model(fn: ast.FunctionDef, schema_aliases: Mapping[str, str]) -> Tuple[str, str]:
    annotated_args = [arg for arg in fn.args.args if arg.annotation is not None]
    if not annotated_args:
        return "", ""
    preferred = next((a for a in annotated_args if a.arg in {"req", "request", "payload", "body"}), annotated_args[0])
    model = annotation_to_str(preferred.annotation)
    if not model:
        return "", ""
    model_name = model.split("[", 1)[0].split("|", 1)[0].strip()
    schema_path = schema_aliases.get(model_name, "")
    return model, schema_path


def call_root_and_attrs(node: ast.AST) -> Tuple[str, Tuple[str, ...]]:
    if isinstance(node, ast.Name):
        return node.id, ()
    if not isinstance(node, ast.Attribute):
        return "", ()
    attrs: List[str] = []
    cur: ast.AST = node
    while isinstance(cur, ast.Attribute):
        attrs.append(cur.attr)
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return "", ()
    attrs.reverse()
    return cur.id, tuple(attrs)


def parse_app_server_routes() -> List[RouteEntry]:
    api_dir = REPO_ROOT / "app_server" / "api"
    if not api_dir.exists():
        return []

    routes: List[RouteEntry] = []
    router_files = sorted(p for p in api_dir.glob("*_router.py") if p.name != "__init__.py")
    allowed_methods = {"get", "post", "put", "patch", "delete", "options", "head"}

    for router_file in router_files:
        text = read_text(router_file)
        try:
            tree = ast.parse(text, filename=str(router_file))
        except SyntaxError:
            continue

        domain = router_file.stem.removesuffix("_router")
        router_rel = to_posix(router_file.relative_to(REPO_ROOT))
        service_aliases: Dict[str, str] = {}
        schema_aliases: Dict[str, str] = {}

        for node in tree.body:
            if not isinstance(node, ast.ImportFrom):
                continue
            module = node.module or ""

            if module == "app_server.services":
                for alias in node.names:
                    local = alias.asname or alias.name
                    service_aliases[local] = alias.name
            elif module.startswith("app_server.services."):
                svc_mod = module.split(".")[-1]
                for alias in node.names:
                    local = alias.asname or alias.name
                    if alias.name.endswith("_service"):
                        service_aliases[local] = alias.name
                    else:
                        service_aliases[local] = f"{svc_mod}.{alias.name}"

            if module.startswith("app_server.schemas."):
                schema_mod = module.split(".")[-1]
                for alias in node.names:
                    local = alias.asname or alias.name
                    schema_aliases[local] = f"app_server/schemas/{schema_mod}.py"

        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue

            for deco in node.decorator_list:
                if not isinstance(deco, ast.Call):
                    continue
                if not isinstance(deco.func, ast.Attribute):
                    continue
                if not isinstance(deco.func.value, ast.Name):
                    continue
                if deco.func.value.id != "router":
                    continue

                method = deco.func.attr.lower()
                if method not in allowed_methods:
                    continue

                path = ""
                if deco.args and isinstance(deco.args[0], ast.Constant) and isinstance(deco.args[0].value, str):
                    path = deco.args[0].value
                if not path:
                    continue

                request_model, request_schema = function_request_model(node, schema_aliases)

                used_services: set[str] = set()
                for sub in ast.walk(node):
                    if not isinstance(sub, ast.Call):
                        continue
                    root, attrs = call_root_and_attrs(sub.func)
                    if not root or root not in service_aliases:
                        continue
                    canonical = service_aliases[root]
                    if attrs:
                        canonical = f"{canonical}.{'.'.join(attrs)}"
                    used_services.add(canonical)

                routes.append(
                    RouteEntry(
                        domain=domain,
                        router_file=router_rel,
                        method=method.upper(),
                        path=path,
                        handler=node.name,
                        request_model=request_model,
                        request_schema=request_schema,
                        services=tuple(sorted(used_services)),
                    )
                )

    routes.sort(key=lambda r: (r.domain, r.path, r.method, r.handler))
    return routes


SCRIPT_TAG_RE = re.compile(r"<script\b(?P<attrs>[^>]*)>(?P<body>.*?)</script>", flags=re.IGNORECASE | re.DOTALL)
SRC_ATTR_RE = re.compile(r"""src\s*=\s*["']([^"']+)["']""", flags=re.IGNORECASE)
IMPORT_STMT_RE = re.compile(r"""(?<![\w$])import\s+(?:[^;()]*?\s+from\s+)?["']([^"']+)["']""")
DYN_IMPORT_RE = re.compile(r"""import\(\s*["']([^"']+)["']\s*\)""")


def parse_frontend_entrypoints() -> Dict[str, FrontendEntrypoint]:
    out: Dict[str, FrontendEntrypoint] = {}
    for rel in FRONTEND_ENTRY_HTMLS:
        path = REPO_ROOT / rel
        if not path.exists():
            out[rel] = FrontendEntrypoint(rel, tuple(), tuple())
            continue
        text = read_text(path)
        external: List[str] = []
        imports: set[str] = set()
        for match in SCRIPT_TAG_RE.finditer(text):
            attrs = match.group("attrs") or ""
            body = match.group("body") or ""
            src_match = SRC_ATTR_RE.search(attrs)
            if src_match:
                external.append(src_match.group(1))
            for imp in IMPORT_STMT_RE.findall(body):
                imports.add(imp.strip())
            for imp in DYN_IMPORT_RE.findall(body):
                imports.add(imp.strip())
        out[rel] = FrontendEntrypoint(
            html_path=rel,
            external_scripts=tuple(sorted(dict.fromkeys(external))),
            inline_imports=tuple(sorted(imports)),
        )
    return out


# Feature modules receive `fetch` as an injected `fetchImpl`, so match both spellings.
FETCH_RE = re.compile(r"""(?:fetch|fetchImpl)\(\s*["'`]([^"'`]+)["'`]""")
POST_MESSAGE_TYPE_RE = re.compile(r"""type\s*:\s*["']([^"']+)["']""")


def parse_js_interface_patterns(paths: Sequence[str]) -> Tuple[List[str], List[str]]:
    endpoints: set[str] = set()
    message_types: set[str] = set()
    for rel in paths:
        p = REPO_ROOT / rel
        if not p.exists():
            continue
        text = read_text(p)
        for endpoint in FETCH_RE.findall(text):
            endpoint = endpoint.strip()
            if endpoint:
                endpoints.add(endpoint)
        for msg in POST_MESSAGE_TYPE_RE.findall(text):
            msg = msg.strip()
            if msg.startswith("arcrho:"):
                message_types.add(msg)
    return sorted(endpoints), sorted(message_types)


def collect_manifest() -> List[ManifestEntry]:
    entries: List[ManifestEntry] = []
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and d != ".git"]
        root_path = Path(root)
        for name in files:
            file_path = root_path / name
            rel = file_path.relative_to(REPO_ROOT)
            if any(part in EXCLUDED_DIRS for part in rel.parts):
                continue
            # Exclude generated-doc outputs to keep manifest deterministic.
            if len(rel.parts) >= 2 and rel.parts[0] == "docs" and rel.parts[1] == "generated":
                continue
            try:
                size = file_path.stat().st_size
            except OSError:
                size = -1
            entries.append(ManifestEntry(path=to_posix(rel), size=size))
    entries.sort(key=lambda x: x.path)
    return entries


def parse_config_signals() -> Tuple[List[str], List[str]]:
    cfg = REPO_ROOT / "app_server" / "config.py"
    if not cfg.exists():
        return [], []
    text = read_text(cfg)
    try:
        tree = ast.parse(text, filename=str(cfg))
    except SyntaxError:
        return [], []

    functions: List[str] = []
    constants: List[str] = []

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            name = node.name
            if "path" in name or "dir" in name or name.startswith("get_") or name in {"load_workspace_paths", "refresh_runtime_paths"}:
                functions.append(name)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id.isupper():
                    constants.append(tgt.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id.isupper():
                constants.append(node.target.id)

    return sorted(dict.fromkeys(functions)), sorted(dict.fromkeys(constants))


def parse_package_json() -> Dict[str, object]:
    p = REPO_ROOT / "package.json"
    if not p.exists():
        return {}
    try:
        return json.loads(read_text(p))
    except json.JSONDecodeError:
        return {}


FRONTEND_DOC_META: Mapping[str, Dict[str, object]] = {
    "shell": {
        "doc": "docs/ui/shell.md",
        "html": ["ui/index.html"],
        "files": [
            ("ui/index.html", "Main desktop shell page and menu structure."),
            ("ui/shell/ui_shell.js", "Shell bootstrap and controller composition."),
            ("ui/shell/shell_state.js", "Shell tab state persistence and invariants."),
            ("ui/shell/tab_actions.js", "Tab open/close/activate/float/dock actions."),
            ("ui/shell/tab_strip.js", "Docked tab strip rendering, reordering, plus menu, and tab context menu."),
            ("ui/shell/shell_content.js", "Home, iframe host, and floating content layout orchestration."),
            ("ui/shell/iframe_host.js", "Iframe creation, URL construction, and iframe event bridge."),
            ("ui/shell/floating_tabs.js", "In-shell floating tab window movement, resize, chrome, and layering."),
            ("ui/shell/shell_menus.js", "Shell menubar state, command dispatch, and scoped menu visibility."),
            ("ui/shell/shell_hotkeys.js", "Global shell hotkey routing."),
            ("ui/shell/shell_messages.js", "Cross-frame shell message handling."),
            ("ui/shell/shell_preferences.js", "Zoom, app font, force rebuild, and tooltip preferences."),
            ("ui/shell/root_path_settings.js", "Server Connection root path settings modal."),
            ("ui/shell/workflow_host_actions.js", "Workflow import and shell-side workflow helpers."),
            ("ui/shell/app_lifecycle.js", "Refresh, restart, shutdown, and app confirmation flows."),
            ("ui/shell/titlebar_controls.js", "Electron titlebar minimize, maximize, close, and drag-restore controls."),
            ("ui/shell/server_badge.js", "Title-bar badge naming this window's server whenever it is not production; opens the Server tab."),
            ("ui/shell/status_bar.js", "Status bar text, the Sign in again action, clock, and timestamp helpers."),
            ("ui/shell/shell_context.js", "Shared shell dependency registry."),
            ("electron/preload.js", "Renderer-safe host bridge APIs."),
            ("electron/main.js", "Window lifecycle and shell-to-host wiring."),
        ],
    },
    "file_explorer": {
        "doc": "docs/ui/file_explorer.md",
        "html": ["ui/file_explorer/file_explorer.html"],
        "files": [
            ("ui/file_explorer/file_explorer.html", "File Explorer iframe entrypoint and two-pane layout."),
            ("ui/file_explorer/file_explorer.js", "Favorite-folder, navigation, file-list, and open-action controller."),
            ("ui/file_explorer/file_explorer_model.js", "Favorite-folder schema plus file normalization, filtering, sorting, and formatting helpers."),
            ("ui/file_explorer/file_explorer.css", "File Explorer sidebar, details table, state, menu, and dialog styling."),
            ("ui/shared/file-icons/fileIconResolver.js", "Canonical shared common-file-type icon resolver."),
            ("electron/preload.js", "Renderer-safe folder preferences, listing, watch, and open APIs."),
            ("electron/main.js", "Desktop favorite persistence, metadata listing, folder watching, and read-only Excel opening."),
        ],
    },
    "server": {
        "doc": "docs/ui/server.md",
        "html": ["ui/server/server.html"],
        "files": [
            ("ui/server/server.html", "Server tab iframe entrypoint: server list, add form, components panel with start and stop, confirmation dialog."),
            ("ui/server/server.js", "Server tab controller: listing, health, add server, the switch request to the shell, component polling while on screen, and start and stop."),
            ("ui/server/server_model.js", "Pure rules for rows, labels, set-at-launch, add validation, switch and sign-in messages, the title-bar badge, component groups, and start/stop progress."),
            ("ui/server/server.css", "Server tab styling on the shared theme tokens."),
            ("ui/shell/shell_messages.js", "Shell side of a switch: unsaved-changes guard, activation, and restart."),
            ("app_server/services/server_profile_service.py", "Server profile listing, health probe, folder inspection, activation, sign in again, component-status transport, and start/stop of a server on this PC."),
            ("app_server/services/server_component_status_service.py", "Component heartbeats and stop switches of the server folder this process serves."),
        ],
    },
    "dashboard": {
        "doc": "docs/ui/dashboard.md",
        "html": ["ui/dashboard/dashboard.html"],
        "files": [
            ("ui/dashboard/dashboard.html", "Dashboards tab iframe entrypoint: the dashboard list and the open dashboard's frame."),
            ("ui/dashboard/dashboard_main.js", "Page state and every change to it: list, open, save, undo, pages, filters, library, data sources, and the ArcBot hooks."),
            ("ui/dashboard/dashboard_model.js", "The dashboard document: normalization, widget types, grid layout rules, defaults, and the ArcBot view of it."),
            ("ui/dashboard/dashboard_data.js", "Query engine: filters, grouping, aggregations including latest, calculations, comparisons, and number formats."),
            ("ui/dashboard/dashboard_charts.js", "SVG and HTML renderers for every widget type, the shared tooltip, and the table view."),
            ("ui/dashboard/dashboard_canvas.js", "The 12-column canvas: drawing, pointer-captured move and resize, and drops from the library and field lists."),
            ("ui/dashboard/dashboard_inspector.js", "The selected widget's properties as pick lists, text boxes and switches, and the field list."),
            ("ui/dashboard/dashboard_sources.js", "Data source dialog for Arco datasets, the Arco source table, a CSV file, or a SQL query."),
            ("ui/dashboard/dashboard_controls.js", "App-styled pick lists, modal, prompt and confirm dialogs, and structural glyphs."),
            ("ui/dashboard/dashboard_api.js", "App-server calls the page makes."),
            ("ui/dashboard/dashboard.css", "Page styling on the shared theme tokens, plus the chart colour tokens for Light and Dark."),
            ("ui/dashboard/icons/dashboard_icons.css", "Widget-type, field-kind and toolbar icon mapping."),
            ("app_server/services/dashboard_service.py", "Dashboard files, the library, and loading a data source into a table."),
            ("app_server/services/dashboard_data_service.py", "Project data as flat tables; the two Server-hosted dashboard reads."),
            ("app_server/default_dashboards/library.json", "The built-in library of widgets and chart templates."),
            ("../tools/build_sample_dashboards.py", "Rebuilds the sample dashboards that ship with the app."),
        ],
    },
    "dataset": {
        "doc": "docs/ui/dataset.md",
        "html": ["ui/dataset_viewer/dataset_viewer.html"],
        "files": [
            ("ui/dataset_viewer/dataset_viewer.html", "Dataset Viewer HTML entrypoint."),
            ("ui/dataset_viewer/dataset_viewer_main.js", "Dataset Viewer page composition and feature coordinator."),
            ("ui/dataset_viewer/dataset_viewer_view.js", "Dataset Viewer markup and DOM mounting."),
            ("ui/dataset_viewer/dataset_viewer.css", "Dataset Viewer-only chart, relationship, and page styling."),
            ("ui/dataset_viewer/tabs/dataset_chart_tab.js", "Dataset Viewer Chart-tab adapter."),
            ("ui/shared/tabs/data/data_tab_controller.js", "Stable host-neutral Data-tab facade and composition root."),
            ("ui/shared/tabs/data/data_tab_host_controller.js", "Data-tab host messages, dependency previews, and run-session bridge."),
            ("ui/shared/tabs/data/data_tab_details_controller.js", "Data-tab formula, relationships, audit, and chrome controller."),
            ("ui/shared/tabs/data/data_tab_inputs_controller.js", "Data-tab project, reserving-class, and dataset input controller."),
            ("ui/shared/tabs/data/data_tab_preferences_controller.js", "Data-tab preferences, saved inputs, and browsing-history controller."),
            ("ui/shared/tabs/data/data_tab_request_controller.js", "Data-tab request payload, period, and validation controller."),
            ("ui/shared/tabs/data/data_tab_persistence_controller.js", "Data-tab sidecar, dirty, save, close, Notes, and Links controller."),
            ("ui/shared/tabs/data/data_tab_dirty_state.js", "Data-tab dirty and save-eligibility rules, including unsaved drafts."),
            ("ui/shared/tabs/data/dataset_grid_view.js", "Reusable Dataset/DFM grid rendering."),
            ("ui/shared/tabs/data/dataset_grid_interactions.js", "Reusable Dataset/DFM grid interactions."),
            ("ui/shared/tabs/data/dataset_grid_placeholder.js", "Reusable Dataset/DFM grid loading, empty, and error states."),
            ("ui/shared/tabs/data/data_tab.css", "Reusable Data-tab presentation."),
            ("ui/shared/components/pickers/dataset_name_picker.js", "Shared dataset-name picker."),
            ("ui/shared/dataset/dataset_origin_labels.js", "Shared dataset origin-label utilities."),
            ("ui/shared/dataset/dataset_api.js", "Client wrappers for dataset endpoints."),
        ],
    },
    "dfm": {
        "doc": "docs/ui/dfm.md",
        "html": ["ui/method_pages/dfm/dfm.html"],
        "files": [
            ("ui/method_pages/dfm/dfm.html", "DFM container page with tab slots."),
            ("ui/method_pages/dfm/dfm_main.js", "DFM bootstrapping and orchestrator loader."),
            ("ui/method_pages/dfm/dfm_tabs_orchestrator.js", "DFM tabs orchestration and message handling."),
            ("ui/method_pages/dfm/dfm_data_tab_adapter.js", "DFM adapter for the host-neutral Data tab."),
            ("ui/method_pages/dfm/dfm_details.js", "Details tab logic and title syncing."),
            ("ui/method_pages/dfm/dfm_ratios_tab.js", "Ratios tab calculations and controls."),
            ("ui/method_pages/dfm/dfm_ratios_summary_table.js", "Stable Ratios-summary facade and render scheduler."),
            ("ui/method_pages/dfm/ratios_summary/summary_runtime.js", "Ratios-summary shared dependencies and lifecycle state."),
            ("ui/method_pages/dfm/ratios_summary/summary_model.js", "Ratios-summary selection, row, and formula model."),
            ("ui/method_pages/dfm/ratios_summary/summary_formula_bar.js", "Ratios-summary formula-bar and edit-session controller."),
            ("ui/method_pages/dfm/ratios_summary/summary_excel.js", "Ratios-summary Excel refresh and external-link controller."),
            ("ui/method_pages/dfm/ratios_summary/summary_excel_validation.js", "Ratios-summary Excel link validation, freshness, and broken-reference marking."),
            ("ui/method_pages/dfm/ratios_summary/summary_entries.js", "Ratios-summary User Entry persistence and recalculation controller."),
            ("ui/method_pages/dfm/ratios_summary/summary_interactions.js", "Ratios-summary selection, context-menu, and direct-edit interactions."),
            ("ui/method_pages/dfm/dfm_results_tab.js", "Results table rendering and CSV export."),
            ("ui/method_pages/dfm/dfm_persistence.js", "DFM template/pattern persistence."),
            ("ui/shared/tabs/data/data_tab_controller.js", "Host-neutral Data-tab coordinator consumed by DFM."),
        ],
        "interface_files": [
            "ui/shared/tabs/data/data_tab_host_controller.js",
            "ui/shared/tabs/data/data_tab_details_controller.js",
            "ui/shared/tabs/data/data_tab_inputs_controller.js",
            "ui/shared/tabs/data/data_tab_preferences_controller.js",
            "ui/shared/tabs/data/data_tab_request_controller.js",
            "ui/shared/tabs/data/data_tab_persistence_controller.js",
            "ui/shared/tabs/data/data_tab_dirty_state.js",
        ],
    },
    "bornhuetter_ferguson": {
        "doc": "docs/ui/bornhuetter_ferguson.md",
        "html": ["ui/method_pages/bornhuetter_ferguson/bornhuetter_ferguson.html"],
        "files": [
            ("ui/method_pages/bornhuetter_ferguson/bornhuetter_ferguson.html", "Bornhuetter Ferguson iframe page."),
            ("ui/method_pages/bornhuetter_ferguson/bornhuetter_ferguson_main.js", "BF state, persistence, calculation, and tab coordination."),
            ("ui/method_pages/bornhuetter_ferguson/bornhuetter_ferguson_chart.js", "BF Chart-tab renderer."),
        ],
    },
    "cape_cod": {
        "doc": "docs/ui/cape_cod.md",
        "html": ["ui/method_pages/cape_cod/cape_cod.html"],
        "files": [
            ("ui/method_pages/cape_cod/cape_cod.html", "Cape Cod iframe page."),
            ("ui/method_pages/cape_cod/cape_cod_main.js", "Cape Cod state, persistence, calculation, and tab coordination."),
            ("ui/method_pages/cape_cod/cape_cod_ratios_chart.js", "Cape Cod Ratios-tab renderer."),
        ],
    },
    "bootstrap": {
        "doc": "docs/ui/bootstrap.md",
        "html": ["ui/method_pages/bootstrap/bootstrap.html"],
        "files": [
            ("ui/method_pages/bootstrap/bootstrap.html", "Bootstrap iframe page."),
            ("ui/method_pages/bootstrap/bootstrap_main.js", "Bootstrap state, load/save flow, rendering, and tab coordination."),
            ("ui/method_pages/bootstrap/bootstrap_page_model.js", "Pure settings, residual-flag, Targets-row, and Results-view rules the page and its tests share."),
            ("ui/method_pages/bootstrap/bootstrap_method_api.js", "Bootstrap load/simulate/ladder/save transport adapter."),
            ("ui/method_pages/bootstrap/bootstrap_residual_chart.js", "Residuals-tab scatter renderer."),
            ("ui/shared/components/reserve_range/reserve_range_model.js", "Results views shared with the Stochastic Consolidation page: rows, columns, ladder, clipboard, fan bands, distribution markers."),
            ("ui/shared/components/reserve_range/reserve_range_table.js", "Shared Results summary-table and full-ladder markup."),
            ("ui/shared/components/reserve_range/reserve_distribution_chart.js", "Shared Results distribution chart of the total with the chosen percentiles marked."),
            ("ui/shared/components/reserve_range/reserve_fan_chart.js", "Shared Results fan chart of the mean and percentile bands by origin."),
        ],
    },
    "stochastic_consolidation": {
        "doc": "docs/ui/stochastic_consolidation.md",
        "html": ["ui/method_pages/stochastic_consolidation/stochastic_consolidation.html"],
        "files": [
            ("ui/method_pages/stochastic_consolidation/stochastic_consolidation.html", "Stochastic Consolidation iframe page."),
            ("ui/method_pages/stochastic_consolidation/stochastic_consolidation_main.js", "Stochastic Consolidation state, load/consolidate/save flow, rendering, and tab coordination."),
            ("ui/method_pages/stochastic_consolidation/stochastic_consolidation_page_model.js", "Pure settings, correlation-matrix, segment-check, run-state, and segment-breakdown rules the page and its tests share."),
            ("ui/method_pages/stochastic_consolidation/stochastic_consolidation_method_api.js", "Stochastic Consolidation load/consolidate/candidates/save transport adapter."),
            ("ui/shared/components/reserve_range/reserve_range_model.js", "Results views shared with the Bootstrap page."),
            ("ui/shared/components/reserve_range/reserve_range_table.js", "Shared Results summary-table and full-ladder markup."),
            ("ui/shared/components/reserve_range/reserve_distribution_chart.js", "Shared Results distribution chart."),
            ("ui/shared/components/reserve_range/reserve_fan_chart.js", "Shared Results fan chart."),
        ],
    },
    "berquist_sherman": {
        "doc": "docs/ui/berquist_sherman.md",
        "html": ["ui/method_pages/berquist_sherman/berquist_sherman.html"],
        "files": [
            ("ui/method_pages/berquist_sherman/berquist_sherman.html", "Shared annual B&S method page."),
            ("ui/method_pages/berquist_sherman/berquist_sherman_main.js", "B&S state, persistence, source preview, and tab coordination."),
            ("ui/method_pages/berquist_sherman/settlement_rate_calculation.js", "Settlement Rate Adjustment calculation engine."),
            ("ui/method_pages/berquist_sherman/case_reserve_adequacy_calculation.js", "Case Reserve Adequacy Adjustment calculation engine."),
            ("ui/shared/dataset/berquist_sherman_contract.js", "Canonical B&S labels and storage identities."),
        ],
    },
    "workflow": {
        "doc": "docs/ui/workflow.md",
        "html": ["ui/workflow/workflow.html"],
        "files": [
            ("ui/workflow/workflow.html", "Workflow page layout and containers."),
            ("ui/workflow/workflow_main.js", "Workflow editing logic, save/load events."),
            ("ui/shared/components/context_menu/context_menu.js", "Context menu helper utilities."),
            ("ui/shared/components/pickers/reserving_class_picker.js", "Shared reserving-class tree selector."),
        ],
    },
    "project_settings": {
        "doc": "docs/ui/project_settings.md",
        "html": ["ui/project_settings/project_settings.html"],
        "files": [
            ("ui/project_settings/project_settings.html", "Project settings workspace and panels."),
            ("ui/project_settings/project_settings.css", "Project settings shared shell and reusable feature styling."),
            ("ui/project_settings/project_settings_skeleton.css", "Shared loading-skeleton tokens, bar, and placeholder rows."),
            ("ui/project_settings/project_settings_summary.css", "Source Data summary styling."),
            ("ui/project_settings/project_settings_field_mapping.css", "Field Mapping styling."),
            ("ui/project_settings/project_settings_dataset_types.css", "Dataset Types styling."),
            ("ui/project_settings/project_settings_reserving_class_types.css", "Reserving Class Types styling."),
            ("ui/project_settings/project_settings_data_processing_rules.css", "Data Processing Rules styling."),
            ("ui/project_settings/project_settings.js", "Project settings coordinator and API calls."),
            ("ui/project_settings/project_settings_project_map.js", "Project map document, folder structure, and tree data store."),
            ("ui/project_settings/project_settings_tree_view.js", "Project Explorer tree rendering, drag-and-drop, and view state."),
            ("ui/project_settings/project_settings_project_ops.js", "Project and virtual-folder create/rename/duplicate/delete flows."),
            ("ui/project_settings/project_settings_duplicate_job.js", "Project-duplication status polling, transient retries, and terminal-state handling."),
            ("ui/project_settings/project_settings_general_settings.js", "Boundary-month parsing and General Settings persistence."),
            ("ui/project_settings/project_settings_table_columns.js", "Shared table column sizing, resizing, and scroll activity."),
            ("ui/project_settings/project_settings_source_data.js", "Source Data panel rendering and column distribution previews."),
            ("ui/project_settings/project_settings_field_mapping.js", "Field mapping feature module."),
            ("ui/project_settings/project_settings_dataset_types.js", "Dataset types feature module."),
            ("ui/project_settings/project_settings_reserving_class_types.js", "Reserving class types feature module."),
            ("ui/project_settings/project_settings_data_processing_rules.js", "Data-processing rule editor, validation, and persistence UI module."),
            ("ui/project_settings/project_settings_audit.js", "Audit log UI helper."),
            ("ui/project_settings/project_settings_skeleton.js", "Shared loading-skeleton row builder for the ribbon tables."),
        ],
    },
    "project_instance": {
        "doc": "docs/ui/project_instance.md",
        "html": ["ui/project_instance/project_instance.html"],
        "files": [
            ("ui/project_instance/project_instance.html", "Project instance tab layout."),
            ("ui/project_instance/project_instance.js", "Project instance module entrypoint."),
            ("ui/project_instance/project_instance_boot.js", "Project instance bootstrap and module composition."),
            ("ui/project_instance/project_instance_context.js", "Shared Project Instance DOM, constants, and mutable state context."),
            ("ui/project_instance/project_instance_utils.js", "Shared Project Instance text, path, motion, and numeric helpers."),
            ("ui/project_instance/project_instance_loading.js", "Project Instance status, zoom, host frame style, and page loading helpers."),
            ("ui/project_instance/project_instance_dataset_cache.js", "Cached dataset lookup, toolbar status, table preference, and disk-change watcher logic."),
            ("ui/project_instance/project_instance_dataset_table.js", "Dataset table rendering, filters, grouping, sorting, selection, and row actions."),
            ("ui/project_instance/project_instance_dataset_add_picker.js", "Add Dataset picker sorting, filtering, search, drag/resize, and row selection."),
            ("ui/project_instance/project_instance_path_panel.js", "Reserving-class path panel loading, selection, persistence, and resizing."),
            ("ui/project_instance/project_instance_excel_links.js", "Excel Link Manager nested-window host: opens the window and handles its retarget messages."),
            ("ui/project_instance/excel_links_window.html", "Excel Link Manager nested-window page."),
            ("ui/project_instance/excel_links_window.js", "Excel link inventory, row actions, and workbook retargeting."),
            ("ui/project_instance/excel_links_table.js", "Excel link detail-row table: column widths, resizing, and per-column filters."),
            ("ui/project_instance/project_instance_dependency_graph.js", "Dependency Graph nested-window host: opens the window and tells it to redraw after a table reload."),
            ("ui/project_instance/dependency_graph_window.html", "Dependency Graph nested-window page."),
            ("ui/project_instance/dependency_graph_window.js", "Dependency Graph diagram: hosted graph load, scroll-surface pan/zoom, click-to-select chain, double-click-to-open, the box right-click menu, and port lists."),
            ("ui/project_instance/dependency_graph_layout.js", "Dependency Graph layered layout, ordering, edge routing, reach, and the default hide of unread datasets."),
            ("ui/project_instance/project_instance_windows.js", "Floating Dataset and DFM window lifecycle, geometry, dirty state, and restore snapshots."),
            ("ui/project_instance/project_instance_hidden_tabs.js", "Hidden floating-window tab strip, menu, drop target, and dock animations."),
            ("ui/project_instance/project_instance_messages.js", "Shell and nested DFM message routing plus keyboard command forwarding."),
            ("ui/dataset_viewer/dataset_viewer.html", "Reused Dataset Viewer page for floating dataset windows."),
            ("ui/shared/dataset/dataset_types_source.js", "Shared dataset type payload loader and normalizer."),
            ("ui/shared/components/pickers/reserving_class_picker.js", "Shared reserving-class lookup, filter, shortcut, and favorite-folder picker."),
            ("ui/shared/components/pickers/path_tree_picker.js", "Shared path tree body renderer used by the embedded reserving-class picker."),
        ],
    },
    "arcode": {
        "doc": "docs/ui/arcode.md",
        "html": ["ui/arcode/main.html", "ui/arcode/notebook-editor/index.html", "ui/arcode/code-editor/index.html"],
        "files": [
            ("ui/arcode/main.html", "Arcode workspace app frame and menus."),
            ("ui/arcode/main.js", "Arcode shell, tabs, explorer, file opening, and command routing."),
            ("ui/arcode/main.css", "Arcode workspace and tab shell styling."),
            ("ui/arcode/notebook-editor/index.html", "Arcode notebook editor page layout."),
            ("ui/arcode/notebook-editor/core.js", "Notebook state, cell model, and command-mode helpers."),
            ("ui/arcode/notebook-editor/cells.js", "Cell rendering, selection, markdown, and drag/drop behavior."),
            ("ui/arcode/notebook-editor/execution.js", "Notebook cell execution, streaming output, and cancellation handling."),
            ("ui/arcode/notebook-editor/shortcuts.js", "Notebook keyboard shortcut parsing, customization, and persistence."),
            ("ui/arcode/notebook-editor/panels.js", "Notebook sidebar, TOC, and variables panels."),
            ("ui/arcode/notebook-editor/notebook-io.js", "Notebook save/open and `.ipynb` import/export helpers."),
            ("ui/arcode/shared/editor_framework.js", "Generic editor page runtime: chrome, file lifecycle, run/stop/restart commands, panel, and ArcBot contract."),
            ("ui/arcode/shared/editor_framework.css", "Shared editor page chrome: command strip, icon commands, context bar, banner, and panel."),
            ("ui/arcode/code-editor/index.html", "Plain code/text editor page host."),
            ("ui/arcode/code-editor/index.js", "Scripting mode for the editor framework: local Python run, ArcRho macro routing, interrupt, and session restart."),
            ("ui/arcode/shared/sql_engines.js", "Canonical SQL engine descriptors: routes, wording, profile fields, and context chips."),
            ("ui/arcode/shared/sql_mode.js", "SQL mode for the editor framework: connection picker, query run, results grid, and reconnect."),
            ("ui/arcode/shared/sql_mode.css", "SQL editor additions: connection picker, connection chips, and results grid."),
            ("ui/arcode/snowflake-console/index.html", "Snowflake SQL editor page host."),
            ("ui/arcode/snowflake-console/index.js", "Snowflake engine selection for the shared SQL mode."),
            ("ui/arcode/sql-server-console/index.html", "SQL Server SQL editor page host."),
            ("ui/arcode/sql-server-console/index.js", "SQL Server engine selection for the shared SQL mode."),
            ("ui/arcode/database-connections/dialog.js", "Settings > Database Connections dialog: per-engine profile add, edit, rename, default, test, and remove."),
            ("ui/arcode/database-connections/database-connections.css", "Database Connections dialog, engine tabs, profile list, and form styling."),
            ("ui/arcode/shared/editor_shared.js", "Shared Arcode editor host bridge, path, tab message, revision, and scripting session helpers."),
        ],
    },
    "ai_assistant": {
        "doc": "docs/ui/ai_assistant.md",
        "html": [],
        "files": [
            ("ui/ai-assistant/index.js", "Shared ArcBot widget behavior and host-configurable message/storage contracts."),
            ("ui/ai-assistant/template.js", "Idempotent assistant launcher and panel DOM creation."),
            ("ui/ai-assistant/assistant.css", "Shared assistant launcher, panel, composer, message, history, and activity styling."),
            ("ui/ai-assistant/skills.js", "ArcBot skill contracts, SQL formatting client, and structured SQL review schema."),
            ("ui/ai-assistant/run-gate.js", "Single-owner gate preventing overlapping chat and skill runs."),
            ("ui/ai-assistant/select-menu.js", "App-styled listbox over the settings Model and Reasoning selects."),
            ("ui/ai-assistant/accounts.js", "Settings Account pickers for switching, adding, and signing in to ArcBot accounts."),
            ("ui/ai-assistant/arcrho.js", "ArcRho host adapter for arcrho messages, storage keys, and DFM edit approval."),
            ("ui/ai-assistant/arcode.js", "Arcode host adapter for arcode notebook context messages and storage keys."),
        ],
    },
}

BACKEND_DOMAIN_META: Mapping[str, Dict[str, object]] = {
    "workflow": {
        "doc": "docs/app_server/domains/workflow.md",
        "files": [
            ("app_server/api/workflow_router.py", "HTTP routes for workflow save/load/default dirs."),
            ("app_server/services/workflow_service.py", "Workflow file I/O operations."),
            ("app_server/schemas/workflow.py", "Workflow request models."),
        ],
    },
    "dashboard": {
        "doc": "docs/app_server/domains/dashboard.md",
        "files": [
            ("app_server/api/dashboard_router.py", "HTTP routes for dashboard files, the library, and data source loading."),
            ("app_server/services/dashboard_service.py", "Dashboard and library files, per-project merging, CSV and SQL sources."),
            ("app_server/services/dashboard_data_service.py", "The table shape, grouping, and the two Server-hosted project reads."),
            ("app_server/schemas/dashboard.py", "Dashboard request models."),
        ],
    },
    "workspace_paths": {
        "doc": "docs/app_server/domains/workspace_paths.md",
        "files": [
            ("app_server/api/workspace_paths_router.py", "Read/update workspace path config."),
            ("app_server/config.py", "Config loader and runtime path refresh."),
            ("app_server/schemas/workspace_paths.py", "Workspace path request models."),
            ("app_server/services/server_profile_service.py", "Server profiles: list, add, activate, sign in again, what a switch does in this process, and start/stop of a server on this PC."),
        ],
    },
    "app_control": {
        "doc": "docs/app_server/domains/app_control.md",
        "files": [
            ("app_server/api/app_control_router.py", "Restart/shutdown control endpoints."),
            ("app_server/config.py", "Flag-file paths for app control."),
            ("app_launcher.py", "Launcher process watching control flags."),
            ("electron/main.js", "Electron host restart/shutdown integration."),
        ],
    },
    "audit_log": {
        "doc": "docs/app_server/domains/audit_log.md",
        "files": [
            ("app_server/api/audit_log_router.py", "Audit read/write routes."),
            ("app_server/services/audit_service.py", "Audit persistence helpers and locking."),
            ("app_server/schemas/audit_log.py", "Audit write payload schema."),
            ("app_server/config.py", "Audit file constants and lock objects."),
        ],
    },
    "dataset": {
        "doc": "docs/app_server/domains/dataset.md",
        "files": [
            ("app_server/api/dataset_router.py", "Dataset query and save routes."),
            ("app_server/services/dataset_service.py", "Dataset in-memory operations."),
            ("app_server/services/class_folder_scan_cache.py", "Scandir-validated caches for reserving-class sidecar/CSV reads."),
            ("app_server/services/dataset_dependency_graph_service.py", "Whole reserving-class dependency graph: index rows as nodes, sidecar precedents as edges."),
            ("app_server/schemas/dataset.py", "Dataset request models."),
            ("ui/shared/dataset/dataset_api.js", "Frontend client wrapper for dataset API."),
        ],
    },
    "result_selection": {
        "doc": "docs/app_server/domains/result_selection.md",
        "files": [
            ("app_server/api/result_selection_router.py", "Aggregate Result Selection load/save routes."),
            ("app_server/services/result_selection_service.py", "V2 contract validation, persistence, and eager dependency refresh."),
            ("app_server/schemas/result_selection.py", "Result Selection load/save request models."),
            ("ui/method_pages/result_selection/result_selection_json_contract.js", "Canonical frontend v2 payload builder."),
        ],
    },
    "bornhuetter_ferguson": {
        "doc": "docs/app_server/domains/bornhuetter_ferguson.md",
        "files": [
            ("app_server/api/bornhuetter_ferguson_router.py", "Aggregate BF load/save routes."),
            ("app_server/services/bornhuetter_ferguson_service.py", "V3 contract persistence, transactional publication, and eager dependency refresh."),
            ("app_server/schemas/bornhuetter_ferguson.py", "BF identity and revision-aware save request models."),
            ("ui/method_pages/bornhuetter_ferguson/bornhuetter_ferguson_main.js", "BF page state and aggregate persistence flow."),
            ("ui/method_pages/bornhuetter_ferguson/bornhuetter_ferguson_json_contract.js", "Canonical browser-side v3 payload builder."),
            ("ui/method_pages/bornhuetter_ferguson/bornhuetter_ferguson_method_api.js", "Aggregate BF transport adapter."),
        ],
    },
    "cape_cod": {
        "doc": "docs/app_server/domains/cape_cod.md",
        "files": [
            ("app_server/api/cape_cod_router.py", "Aggregate Cape Cod load/save routes."),
            ("app_server/services/cape_cod_service.py", "V1 contract persistence, transactional publication, and eager dependency refresh."),
            ("app_server/schemas/cape_cod.py", "Cape Cod identity and revision-aware save request models."),
            ("ui/method_pages/cape_cod/cape_cod_main.js", "Cape Cod page state and aggregate persistence flow."),
            ("ui/method_pages/cape_cod/cape_cod_json_contract.js", "Canonical browser-side v1 payload builder."),
            ("ui/method_pages/cape_cod/cape_cod_method_api.js", "Aggregate Cape Cod transport adapter."),
        ],
    },
    "bootstrap": {
        "doc": "docs/app_server/domains/bootstrap.md",
        "files": [
            ("app_server/api/bootstrap_router.py", "Aggregate Bootstrap load/simulate/ladder/save/refresh routes."),
            ("app_server/services/bootstrap_service.py", "V1 contract persistence, transactional publication, and eager dependency refresh."),
            ("app_server/schemas/bootstrap.py", "Bootstrap identity, run-only simulate, finer ladder, and revision-aware save request models."),
        ],
    },
    "stochastic_consolidation": {
        "doc": "docs/app_server/domains/stochastic_consolidation.md",
        "files": [
            ("app_server/api/stochastic_consolidation_router.py", "Stochastic Consolidation load/consolidate/candidates/save routes."),
            ("app_server/services/stochastic_consolidation_service.py", "Cross-class segment reads, freshness report, run without writing, and transactional publication."),
            ("app_server/schemas/stochastic_consolidation.py", "Stochastic Consolidation identity, run, picker and revision-aware save request models."),
        ],
    },
    "excel": {
        "doc": "docs/app_server/domains/excel.md",
        "files": [
            ("app_server/api/excel_router.py", "Excel COM automation routes."),
            ("app_server/services/excel_service.py", "Excel process interaction logic."),
            ("app_server/schemas/excel.py", "Excel request payload schemas."),
        ],
    },
    "excel_link": {
        "doc": "docs/app_server/domains/excel_link.md",
        "files": [
            ("app_server/api/excel_link_router.py", "Reserving-class Excel link list/retarget routes."),
            ("app_server/services/excel_link_service.py", "Excel link scan, workbook grouping, and reference retargeting."),
            ("app_server/schemas/excel_link.py", "Excel link request payload schemas."),
        ],
    },
    "arcrho": {
        "doc": "docs/app_server/domains/arcrho.md",
        "files": [
            ("app_server/api/arcrho_router.py", "ArcRho tri/precheck/header endpoints."),
            ("app_server/services/arcrho_runtime_service.py", "ArcRho processing and project listing."),
            ("app_server/services/engine_calculation_service.py", "Engine request publish-and-wait exchange and its Gateway transport."),
            ("app_server/schemas/arcrho.py", "ArcRho request schemas."),
        ],
    },
    "project_settings": {
        "doc": "docs/app_server/domains/project_settings.md",
        "files": [
            ("app_server/api/project_settings_router.py", "Project settings CRUD and folder ops routes."),
            ("app_server/services/project_settings_service.py", "Project settings persistence service."),
            ("app_server/schemas/project_settings.py", "Project settings request schemas."),
            ("ui/project_settings/project_settings.js", "Frontend caller for project settings endpoints."),
        ],
    },
    "table_summary": {
        "doc": "docs/app_server/domains/table_summary.md",
        "files": [
            ("app_server/api/table_summary_router.py", "Table summary read/refresh routes."),
            ("app_server/services/table_summary_service.py", "CSV summary generation and cache validity."),
            ("app_server/services/reserving_class_service.py", "Optional refresh chaining."),
            ("app_server/schemas/table_summary.py", "Table summary refresh schema."),
        ],
    },
    "source_table": {
        "doc": "docs/app_server/domains/source_table.md",
        "files": [
            ("app_server/api/source_table_router.py", "Import source profile, connection test, and import routes."),
            ("app_server/services/source_table_service.py", "Project-owned master table copy and SQL Server import."),
            (
                "app_server/services/source_table_upload_service.py",
                "Upload of a source only the client can read, and its server-side commit.",
            ),
            ("app_server/schemas/source_table.py", "Import source request schemas."),
            (
                "../python-api/src/arcrho_api/source_table_contract.py",
                "Canonical master-table layout and source_import.json schema.",
            ),
        ],
    },
    "field_mapping": {
        "doc": "docs/app_server/domains/field_mapping.md",
        "files": [
            ("app_server/api/field_mapping_router.py", "Field mapping read/save routes."),
            ("app_server/services/field_mapping_service.py", "Field mapping persistence and validation."),
            ("app_server/schemas/field_mapping.py", "Field mapping request schema."),
        ],
    },
    "dataset_types": {
        "doc": "docs/app_server/domains/dataset_types.md",
        "files": [
            ("app_server/api/dataset_types_router.py", "Dataset type catalog read/save routes."),
            ("app_server/services/dataset_types_service.py", "Dataset type storage and normalization."),
            ("app_server/schemas/dataset_types.py", "Dataset type save schema."),
        ],
    },
    "dependent_propagation": {
        "doc": "docs/app_server/domains/dependent_propagation.md",
        "files": [
            ("app_server/api/dependent_propagation_router.py", "Submit/status routes for Engine propagation jobs."),
            ("app_server/services/dependent_propagation_service.py", "Job submission, heartbeat preflight, status validation."),
            ("app_server/schemas/dependent_propagation.py", "Typed propagation job submit/status models."),
            ("ui/shared/services/dependent_propagation_job.js", "Shared UI poller for propagation job progress."),
        ],
    },
    "object_change_watch": {
        "doc": "docs/app_server/domains/object_change_watch.md",
        "files": [
            ("app_server/api/object_change_watch_router.py", "Stat-only object fingerprint route."),
            ("app_server/services/object_change_watch_service.py", "Dataset/method fingerprint resolution and tokens."),
            ("app_server/schemas/object_change_watch.py", "Typed fingerprint request/response models."),
            ("ui/shared/services/object_change_watch.js", "Shared open-window change-watch poller."),
            ("ui/shared/tabs/data/data_tab_change_watch_port.js", "Data-tab host port for save/run boundaries."),
        ],
    },
    "data_processing_rules": {
        "doc": "docs/app_server/domains/data_processing_rules.md",
        "files": [
            ("app_server/api/data_processing_rules_router.py", "Rule read, validate, and revision-safe save routes."),
            ("app_server/services/data_processing_rules_service.py", "Rule validation, persistence, audit, options, and processing hashes."),
            ("app_server/schemas/data_processing_rules.py", "Typed data-processing rule request models."),
            ("app_server/config.py", "Rule filename, format, algorithm version, and project path helper."),
        ],
    },
    "reserving_class": {
        "doc": "docs/app_server/domains/reserving_class.md",
        "files": [
            ("app_server/api/reserving_class_router.py", "Reserving-class routes for values/tree/preferences/types."),
            ("app_server/services/reserving_class_service.py", "Cache generation, refresh, and preference persistence."),
            ("app_server/schemas/reserving_class.py", "Reserving class request models."),
            ("ui/shared/components/pickers/reserving_class_picker.js", "Frontend caller for reserving-class endpoints."),
        ],
    },
    "ui_automation": {
        "doc": "docs/app_server/domains/ui_automation.md",
        "files": [
            ("app_server/api/ui_automation_router.py", "Local UI automation command endpoints."),
            ("app_server/services/ui_automation_service.py", "In-memory command queue and completion handling."),
            ("app_server/schemas/ui_automation.py", "UI automation command request and result schemas."),
            ("ui/shell/ui_automation.js", "Shell-side command polling and execution."),
        ],
    },
    "snowflake": {
        "doc": "docs/app_server/domains/snowflake.md",
        "files": [
            ("app_server/api/snowflake_router.py", "Snowflake connection, test, reset, and query routes."),
            ("app_server/services/snowflake_service.py", "Connection profile loading and Snowflake query execution."),
            ("app_server/services/sql_console_results.py", "Row limit and driver-cell conversion shared by the SQL consoles."),
            ("app_server/schemas/scripting.py", "Snowflake request models shared with scripting schemas."),
            ("ui/arcode/snowflake-console/index.js", "Arcode Snowflake SQL editor page."),
            ("ui/arcode/shared/sql_engines.js", "Canonical Snowflake and SQL Server engine descriptors shared by the editors and the connections dialog."),
        ],
    },
    "sql_server": {
        "doc": "docs/app_server/domains/sql_server.md",
        "files": [
            ("app_server/api/sql_server_router.py", "SQL Server connection, test, reset, and query routes."),
            ("app_server/services/sql_server_service.py", "Connection profile store and SQL Server query execution."),
            ("app_server/services/mssql_odbc.py", "Canonical ODBC driver selection and Windows connection string."),
            ("app_server/services/sql_console_results.py", "Row limit and driver-cell conversion shared by the SQL consoles."),
            ("app_server/schemas/sql_server.py", "SQL Server connection and query request models."),
            ("ui/arcode/sql-server-console/index.js", "Arcode SQL Server editor page."),
            ("ui/arcode/shared/sql_engines.js", "Canonical Snowflake and SQL Server engine descriptors shared by the editors and the connections dialog."),
            ("ui/arcode/database-connections/dialog.js", "Arcode Database Connections dialog, which edits both engines' profiles."),
        ],
    },
    "sql_formatting": {
        "doc": "docs/app_server/domains/sql_formatting.md",
        "files": [
            ("app_server/api/sql_formatting_router.py", "Thin SQL formatting preview route."),
            ("app_server/services/sql_formatting_service.py", "Shared formatter lifetime and request delegation."),
            ("app_server/services/sql_formatting/engine.py", "Canonical parser-backed formatter and atomic safety gates."),
            ("app_server/services/sql_formatting/version.py", "Canonical SQLFluff distribution and version requirement."),
            ("app_server/services/sql_formatting/advisories.py", "Canonical-lexer SQL advisory rules."),
            ("app_server/schemas/sql_formatting.py", "Typed preview, diagnostic, advisory, nested-region, and safety contracts."),
            ("ui/ai-assistant/skills.js", "Shared Arcode and ArcBot SQL formatting client contract."),
        ],
    },
}


def module_specs() -> Dict[str, ModuleDocSpec]:
    specs: Dict[str, ModuleDocSpec] = {}

    specs["docs/INDEX.md"] = ModuleDocSpec(
        path="docs/INDEX.md",
        title="ArcRho Documentation Index",
        manual_sections={
            "Purpose": dedent(
                """
                This is the top-level navigation hub for code agents.

                System map:
                - Electron host/runtime: `electron/main.js`, `electron/preload.js`, `app_shell.py`.
                - Frontend pages/features: shell + dataset + DFM + workflow + project settings + scripting console.
                - App-server API: FastAPI app in `app_server/main.py` with domain routers in `app_server/api`.
                - Runtime/config state: path resolution and cache constants in `app_server/config.py`.
                """
            ),
            "Entry Points": dedent(
                """
                | Question | Where to start |
                | --- | --- |
                | Add or modify an app-server API endpoint | [`app_server/INDEX.md`](app_server/INDEX.md) |
                | Trace a page to app-server endpoints | [`ui/INDEX.md`](ui/INDEX.md) |
                | Update path/config behavior | [`runtime/config_paths.md`](runtime/config_paths.md) |
                | Troubleshoot packaging/build | [`build/packaging.md`](build/packaging.md) |
                | Inspect machine-generated inventories | [`generated/app_server_routes.md`](generated/app_server_routes.md), [`generated/frontend_entrypoints.md`](generated/frontend_entrypoints.md), [`generated/file_manifest.md`](generated/file_manifest.md) |
                """
            ),
            "External Interfaces": dedent(
                """
                Tooling interfaces introduced by this documentation system:
                - CLI: `python tools/docs_index_builder.py --scaffold-missing|--write|--check`
                - Marker contract:
                  - `<!-- AUTO-GEN:BEGIN ... --> ... <!-- AUTO-GEN:END -->`
                  - `<!-- MANUAL:BEGIN --> ... <!-- MANUAL:END -->`
                """
            ),
            "Data/State/Caches": dedent(
                """
                Runtime/cache references are centralized in:
                - [`runtime/config_paths.md`](runtime/config_paths.md)
                - [`runtime/data_cache_files.md`](runtime/data_cache_files.md)
                """
            ),
            "Common Change Tasks": dedent(
                """
                High-frequency workflows:
                1. Add/modify API endpoint: [`app_server/INDEX.md`](app_server/INDEX.md) -> target domain file under `app_server/domains/`.
                2. Trace page -> API -> service: [`ui/INDEX.md`](ui/INDEX.md) then follow linked app-server domain files.
                3. Update config/path behavior: [`runtime/config_paths.md`](runtime/config_paths.md).
                4. Package/build troubleshooting: [`build/packaging.md`](build/packaging.md).
                """
            ),
            "Known Risks": dedent(
                """
                - Documentation can drift if `--write` is not run after route/page changes.
                - AUTO-GEN blocks are deterministic; manual edits must stay inside MANUAL blocks.
                """
            ),
        },
        auto_sections={
            "Key Files": "root.key_files",
        },
    )

    specs["docs/ui/INDEX.md"] = ModuleDocSpec(
        path="docs/ui/INDEX.md",
        title="Frontend Index",
        manual_sections={
            "Purpose": dedent(
                """
                Frontend module map for page entrypoints, shell orchestration, and feature-specific scripts.
                """
            ),
            "External Interfaces": dedent(
                """
                - App-server HTTP interface via `fetch(...)` calls.
                - Cross-iframe messaging via `window.postMessage` (`arcrho:*` message types).
                """
            ),
            "Data/State/Caches": dedent(
                """
                - Shell/tab state persisted in browser storage (`localStorage`, IndexedDB handles DB).
                - Per-page state lives in each iframe module.
                """
            ),
            "Common Change Tasks": dedent(
                """
                1. Shell tab lifecycle change -> [`shell.md`](shell.md).
                2. File Explorer behavior change -> [`file_explorer.md`](file_explorer.md).
                3. Dataset behavior change -> [`dataset.md`](dataset.md).
                4. DFM behavior change -> [`dfm.md`](dfm.md).
                5. Workflow editor change -> [`workflow.md`](workflow.md).
                6. Project settings flow change -> [`project_settings.md`](project_settings.md).
                7. Arcode scripting app or notebook/editor change -> [`arcode.md`](arcode.md).
                8. Shared ArcBot widget change -> [`ai_assistant.md`](ai_assistant.md).
                """
            ),
            "Known Risks": dedent(
                """
                - Shell/iframe messaging changes can break hotkeys and dirty-state sync.
                - Endpoint path changes in JS can silently break page-level features.
                """
            ),
        },
        auto_sections={
            "Entry Points": "frontend.index.entry_points",
            "Key Files": "frontend.index.key_files",
        },
    )

    specs["docs/app_server/INDEX.md"] = ModuleDocSpec(
        path="docs/app_server/INDEX.md",
        title="App Server Index",
        manual_sections={
            "Purpose": dedent(
                """
                App-server domain map for FastAPI routers, schemas, and services.
                """
            ),
            "External Interfaces": dedent(
                """
                - Public interface is HTTP routes mounted by `app_server/main.py`.
                - Internal interface is router -> service -> filesystem/state helpers.
                """
            ),
            "Data/State/Caches": dedent(
                """
                - Path and cache constants are centralized in `app_server/config.py`.
                - Several domains persist JSON caches under project folders or AppData.
                """
            ),
            "Common Change Tasks": dedent(
                """
                1. Add route: update one router file under `app_server/api`, schema under `app_server/schemas`, and service under `app_server/services`.
                2. Change payload contract: update schema first, then router/service.
                3. Change project path behavior: sync with [`../runtime/config_paths.md`](../runtime/config_paths.md).
                """
            ),
            "Known Risks": dedent(
                """
                - File-based persistence and path assumptions are sensitive to environment setup.
                - Domain cross-calls (for example, table summary -> reserving class refresh) can add side effects.
                """
            ),
        },
        auto_sections={
            "Entry Points": "app_server.index.entry_points",
            "Key Files": "app_server.index.key_files",
        },
    )

    frontend_manual = {
        "shell": {
            "purpose": "Shell-level tab/iframe host for all feature pages.",
            "external": "- Communicates with child iframes via `arcrho:*` postMessage events.\n- Invokes app-server endpoints for workflow import helpers and configuration endpoints.\n- Uses Electron host bridge for Server Connection folder browsing and first-time `Arco Server` drive detection.",
            "data": "- Persists tab state, zoom, and toggles in `localStorage`.\n- Tracks popped-out tabs via `BroadcastChannel`.",
            "tasks": "1. Add a new tab type: update tab creation + iframe source logic in `ui_shell.js`.\n2. Add shell menu action: wire menu item + action handler + hotkey map.",
            "risks": "- DOM replacement in shell can invalidate iframe references.\n- Unsaved-state handling must stay consistent for close/close-all flows.",
        },
        "file_explorer": {
            "purpose": "Standard ArcRho tab for browsing local files with a customizable Favorite folders sidebar and a persistent details list.",
            "external": "- Opened from the Home File Explorer card as one restorable `file_explorer` shell tab.\n- Uses the Electron preload bridge for folder selection, directory listings, file opening, reveal/copy actions, and folder watches.\n- Receives explicit shell visibility messages so background or minimized tabs do not keep a live folder watcher.",
            "data": "- Persists ordered favorite-folder paths and user nicknames in `%APPDATA%\\ArcRho\\prefs\\home_folders.json`; browser local storage is a non-Electron fallback.\n- Requests file size and modified-time metadata only for File Explorer listings so existing Arcode listing payloads remain compatible.\n- Uses `ui/shared/file-icons/` as the canonical resolver, mapping, and asset package shared with Arcode.",
            "tasks": "1. Change File Explorer behavior or layout: update `ui/file_explorer/` and focused tests together.\n2. Change shell tab lifecycle: update Home launch, tab actions, iframe host, visibility messaging, and shell docs together.\n3. Change folder/file host operations: preserve existing preload IPC names and update Electron main/preload plus integration tests.",
            "risks": "- Folder paths can become inaccessible or disappear while pinned; these must remain visible as favorites and surface recoverable list errors.\n- File opening is delegated to desktop associations; Excel read-only opening requires the explicit `/r` host path.\n- Watchers must stop while the tab is hidden and be replaced when navigation changes folders.",
        },
        "server": {
            "purpose": "Server tab: lists the servers this PC knows by name and Gateway address, marks the one in use, adds a server from its folder, and switches between them by restarting the app.",
            "external": "- Opened from the Home Server card or the Server Connection dialog as one restorable `server` shell tab.\n- Reads `GET /server_profiles`, `GET /server_profiles/health` (the app server probes each Gateway) and `GET /server_profiles/inspect`, and adds with `POST /server_profiles`.\n- Switches by posting `arcrho:server-switch` to the shell, which refuses while any tab is dirty, activates the profile, runs the ordinary restart, and answers with `arcrho:server-switch-result`.\n- Uses the host `pickFolder` bridge when present; the folder text field is the fallback.",
            "data": "- Holds no state of its own; the profile list lives in `%APPDATA%\\ArcRho\\workspace_paths.json`, owned by `arcrho_api.config`.\n- While a launch override is set (`set_at_launch`), shows that server as `Set at launch` and turns switching and adding off.\n- The Components panel is a placeholder until component status lands.",
            "tasks": "1. Change what a row shows: update `server_model.js`, `server.js`, and `tests/server_tab.test.mjs` together.\n2. Change what a switch does: update the shell handler in `shell_messages.js`, the activate route, and both test files.",
            "risks": "- A switch restarts the app server; it must stay blocked while any tab holds unsaved changes.\n- Never save profiles from a `launch-app` session; the routes refuse with 409 and the page disables the controls.",
        },
        "dashboard": {
            "purpose": "Dashboards tab: build and view interactive charts over Arco project data, a CSV file, or a SQL query, without code. A dashboard is one file with data sources, pages, and widgets on a grid.",
            "external": "- Opened from the Home Dashboards card as a restorable `dashboard` shell tab, one tab per dashboard file.\n- Calls the `/dashboard/*` routes and the existing project, reserving-class, dataset and SQL connection listings.\n- Reports its file, name and unsaved state to the shell with `arcrho:dashboard-state`, and answers ArcBot's context, apply and revert messages.",
            "data": "- A dashboard is a `.arcdash` JSON file in the user's `Documents\\ArcRho\\dashboards` folder; samples ship read-only with the app.\n- Each data source may keep the last table it returned, so a dashboard opens without waiting for the server.",
            "tasks": "1. Add a widget type: `WIDGET_TYPES` in `dashboard_model.js`, a renderer in `dashboard_charts.js`, an icon, and a library entry.\n2. Add an aggregation or format: `dashboard_data.js`, the lists in `dashboard_model.js`, and `tests/dashboard_data.test.mjs`.",
            "risks": "- A cumulative triangle column must be aggregated with `latest`, never summed across development periods.\n- Charts keep one axis and at most eight series; do not add a second y-axis.",
        },
        "dataset": {
            "purpose": "Dataset editing/analysis page used inside shell tabs.",
            "external": "- Calls app-server dataset/book/arcrho endpoints.\n- Sends status/hotkey/close signals to parent shell.",
            "data": "- Uses in-page mutable state for active dataset and selection.\n- Reads project metadata from app_server endpoints.",
            "tasks": "1. Add a new app-server call: update fetch call and API wrappers.\n2. Change Data-tab behavior: update the coordinated modules under `ui/shared/tabs/data/` and the relevant feature adapter.",
            "risks": "- Formula or patch changes can cause silent data drift.\n- Endpoint mismatches break runtime flows without compile-time safety.",
        },
        "dfm": {
            "purpose": "DFM feature (details/ratios/results/notes) on top of dataset context.",
            "external": "- Exchanges `arcrho:*` messages with shell and workflow iframe.\n- Reuses dataset APIs and reserving class selectors.",
            "data": "- Persists ratio selection/templates via DFM persistence modules.\n- Tracks dirty flags and active DFM tab state.",
            "tasks": "1. Add a DFM tab capability: update orchestrator + tab module.\n2. Modify ratio/result behavior: sync `dfm_ratios_tab.js` and `dfm_results_tab.js`.",
            "risks": "- Cross-tab sync is message-driven and easy to desynchronize.\n- Persistence schema changes can break saved templates.",
        },
        "bornhuetter_ferguson": {
            "purpose": "Bornhuetter Ferguson method page for combining latest, development-pattern, and prior inputs into ultimate values.",
            "external": "- Opens inside Project Instance as a nested method iframe.\n- Exchanges explicit `arcrho:*` messages with its host.",
            "data": "- Persists BF method JSON and generated vector outputs.\n- Tracks feature-local source, calculation, dirty, and tab state.",
            "tasks": "1. Change BF calculations or persistence: update `ui/method_pages/bornhuetter_ferguson/bornhuetter_ferguson_main.js`.\n2. Change BF chart behavior: update `bornhuetter_ferguson_chart.js` in the same feature directory.",
            "risks": "- Source period alignment affects calculated ultimates.\n- Dirty-state and close messages must remain coordinated with Project Instance.",
        },
        "cape_cod": {
            "purpose": "Cape Cod method page replicating the ResQ Generalised Cape Cod method from latest, exposure, and prior-ultimate inputs.",
            "external": "- Opens inside Project Instance as a nested method iframe.\n- Exchanges explicit `arcrho:*` messages with its host.",
            "data": "- Persists Cape Cod method JSON and generated vector outputs.\n- Tracks feature-local source, trend/decay parameter, dirty, and tab state.",
            "tasks": "1. Change Cape Cod calculations or persistence: update the canonical python contract first, then mirror `ui/method_pages/cape_cod/cape_cod_json_contract.js`.\n2. Change Ratios chart behavior: update `cape_cod_ratios_chart.js` in the same feature directory.",
            "risks": "- The JS calculation mirror must stay identical to `arcrho_api/cape_cod_contract.py` or saves are rejected.\n- Trend-rate auto-fit clears manual trend-factor overrides; changing that ordering breaks ResQ parity.",
        },
        "bootstrap": {
            "purpose": "Bootstrap method page: an over-dispersed Poisson bootstrap of a DFM, scaled onto a target ultimate.",
            "external": "- Opens inside Project Instance as a nested method iframe.\n- Loads and saves through the `/bootstrap/*` routes; the server re-simulates on every save.",
            "data": "- Edits only the owned settings of the persisted `arcrho-bootstrap-v4` method; every derived value comes from the last save.\n- Tracks dirty, run-state, and tab state locally.",
            "tasks": "1. Change what a tab edits: update `bootstrap_page_model.js` and its round-trip test.\n2. Change layout or controls: update `bootstrap.html`, `bootstrap.css`, and `bootstrap_main.js` together.",
            "risks": "- A setting the page writes must be one `apply_owned_patch` accepts, or the save silently ignores it.\n- Dirty-state and close messages must remain coordinated with Project Instance.",
        },
        "stochastic_consolidation": {
            "purpose": "Stochastic Consolidation method page: combines the simulated reserves of Bootstrap methods in other reserving classes into one total range with chosen correlations.",
            "external": "- Opens inside Project Instance as a nested method iframe.\n- Loads, consolidates without writing, lists segment candidates, and saves through the `/stochastic-consolidation/*` routes.",
            "data": "- Edits only the owned settings of the persisted `arcrho-stochastic-consolidation-v4` method; every derived value comes from a run.\n- Tracks dirty, run-state, unsaved-run, and tab state locally.",
            "tasks": "1. Change what a tab edits: update `stochastic_consolidation_page_model.js` and its round-trip test.\n2. Change a Results view: update the shared `reserve_range` modules, which the Bootstrap page also uses.",
            "risks": "- A setting the page writes must be one `apply_owned_patch` accepts, or the save silently ignores it.\n- The segment checks mirror the server's; a new refusal on the server needs its inline reason here too.",
        },
        "berquist_sherman": {
            "purpose": "Annual Berquist Sherman method page for settlement-rate and case-reserve-adequacy adjustments.",
            "external": "- Opens inside Project Instance as a nested method iframe.\n- Loads named annual datasets and exchanges dependency preview messages with its host.",
            "data": "- Persists one small method JSON, one final triangle CSV, and one output sidecar.\n- Recalculates in memory when a matching source preview changes.",
            "tasks": "1. Change a B&S formula in its pure calculation module and update the COL parity fixture test.\n2. Change B&S persistence or page behavior in `berquist_sherman_main.js` while preserving the shared contract module.",
            "risks": "- Source triangle shapes and annual period metadata must agree.\n- Canonical method labels, prefixes, and source kinds must stay aligned with migration and the dataset index.",
        },
        "workflow": {
            "purpose": "Workflow editor page and save/load orchestration.",
            "external": "- Calls `/workflow/*` app-server routes.\n- Coordinates with shell and embedded dataset/DFM iframes via message bridge.",
            "data": "- Persists workflow tab state using per-instance storage keys.\n- Uses imported/exported `.arcwf` payloads.",
            "tasks": "1. Extend workflow payload: update `workflow_main.js`, app-server schema/service, and save/load compatibility.\n2. Add sidebar behavior: update `workflow.html` + resize/collapse handlers.",
            "risks": "- Save/load compatibility regressions across older workflow files.\n- Dirty-state propagation to shell can become inconsistent.",
        },
        "project_settings": {
            "purpose": "Project settings workspace (folders, mappings, dataset types, reserving class types, and data-processing rules).",
            "external": "- Calls `/project_settings/*`, `/table_summary*`, `/data_processing_rules*`, and related endpoints.\n- Posts title/status events to shell.",
            "data": "- Reads/writes settings payloads and folder structures.\n- Coordinates feature modules for mapping/type/rule editors.",
            "tasks": "1. Add settings source behavior: update source key logic + endpoint calls.\n2. Update one feature pane: modify corresponding `project_settings_*` module.",
            "risks": "- Folder rename/duplicate/delete flows have rollback branches.\n- Large settings payload edits can impact response timing.",
        },
        "project_instance": {
            "purpose": "Project instance workspace for browsing one project's reserving-class paths and dataset types.",
            "external": "- Opened by shell as a `project_instance` iframe tab.\n- Calls shared dataset-types and reserving-class path endpoints through existing frontend helpers.\n- Embeds the existing Dataset Viewer page in draggable in-tab windows.",
            "data": "- Uses the shell-persisted project name/folder/table path as tab inputs.\n- Keeps the selected reserving-class path in page memory and passes it into new dataset viewer windows.",
            "tasks": "1. Change project instance launch behavior: update Project Settings sender and shell message/tab routing together.\n2. Change dataset-window behavior: update `project_instance.js` while preserving the reused Dataset Viewer page contract.",
            "risks": "- Nested dataset iframes post messages to the project instance page before reaching the shell.\n- Dataset viewer query parameters must remain compatible with normal top-level dataset tabs.",
        },
        "arcode": {
            "purpose": "Canonical Arcode workspace for notebooks, scripts, SQL files, execution output, file explorer, and assistant context.",
            "external": "- Opened by ArcRho through the Electron `openArcodeWindow` bridge or as standalone `ARCRHO_APP_MODE=arcode`.\n- Uses `/scripting/*` app-server routes for execution, variables, preferences, and notebook persistence.\n- Sends `arcode:*` status and command messages between the Arcode shell and notebook-editor iframes.",
            "data": "- Stores Arcode recent files, workspace folders, zoom, and tab-local notebook drafts in browser storage.\n- Saves notebooks and scripts through Electron host file APIs or under the user scripting directory by default.\n- Standalone Arcode mode uses `Documents\\Arcode\\scripts` and `%APPDATA%\\Arcode` defaults.",
            "tasks": "1. Change Arcode shell behavior: update `ui/arcode/main.js`, Electron host APIs, and docs together.\n2. Change notebook model or persistence: update `ui/arcode/notebook-editor/*`, app-server scripting routes if needed, and docs together.\n3. Change standalone packaging: update `electron-builder.arcode.json`, `build/arcode_server.spec`, package scripts, and build docs.",
            "risks": "- Keyboard handling is sensitive to edit mode, command mode, IME/composition, and Monaco focus.\n- Multi-cell selection, queueing, markdown folding, and drag/drop share state and can regress each other.\n- ArcRho macros rely on ArcRho-only scripting macro endpoints that are intentionally excluded from the standalone Arcode route surface.",
        },
        "ai_assistant": {
            "purpose": "Shared ArcBot widget package used by both the ArcRho shell and Arcode shell.",
            "external": "- Hosts configure the widget through `ui/ai-assistant/arcrho.js` or `ui/ai-assistant/arcode.js`.\n- Uses Electron preload `codexAssistant*` APIs without changing IPC names.\n- Exchanges assistant context/update messages with active iframes using host-specific namespaces.",
            "data": "- Uses host-specific storage prefixes so ArcRho keeps `arcrho_ai_assistant_*` keys and Arcode keeps `arcode_ai_assistant_*` keys.\n- Persists chat/session data through the existing Electron assistant host APIs.\n- Creates the assistant DOM once per host page at runtime.",
            "tasks": "1. Change shared assistant UI or behavior: update `ui/ai-assistant/index.js`, `template.js`, `assistant.css`, and this doc together.\n2. Change host-specific message/storage behavior: update the matching adapter and all producers/consumers for that namespace.",
            "risks": "- The widget is shared by two app shells, so hardcoded app names, storage keys, or message namespaces can regress one host.\n- ArcRho DFM edit approval must stay disabled in Arcode and enabled only through the ArcRho adapter.",
        },
    }

    for name in FRONTEND_DOC_META:
        manual = frontend_manual[name]
        specs[f"docs/ui/{name}.md"] = ModuleDocSpec(
            path=f"docs/ui/{name}.md",
            title=f"Frontend: {name.replace('_', ' ').title()}",
            manual_sections={
                "Purpose": manual["purpose"],
                "External Interfaces": manual["external"],
                "Data/State/Caches": manual["data"],
                "Common Change Tasks": manual["tasks"],
                "Known Risks": manual["risks"],
            },
            auto_sections={
                "Entry Points": f"frontend.{name}.entry_points",
                "Key Files": f"frontend.{name}.key_files",
            },
        )

    backend_manual = {
        "workflow": (
            "Workflow file save/load domain.",
            "- Consumed primarily by `workflow_main.js`.\n- Uses typed request models in `app_server/schemas/workflow.py`.",
            "- Reads/writes workflow files under configured workflow directory.",
            "1. Add a workflow route: update router + schema + service.\n2. Keep backward compatibility when changing saved payload shape.",
            "- File I/O errors and path permissions are common failure modes.",
        ),
        "dashboard": (
            "Dashboard files, the reusable library, and the tables a dashboard charts.",
            "- Consumed by the Dashboards page (`ui/dashboard`).\n- Project data is read on the server host through the registered `dashboard_dataset_table` and `dashboard_source_table` workspace reads; a CSV file and a SQL query are read on this PC.",
            "- Dashboards are `.arcdash` files in `config.DASHBOARD_DIR`; samples and the built-in library ship in `config.DEFAULT_DASHBOARDS_DIR`.\n- A table holds at most 100,000 rows; a larger grouping is refused, not cut.",
            "1. Add a data source kind: `SOURCE_KINDS` and `load_source` in `dashboard_service.py`, the source dialog, and a test.\n2. Change the table shape only in `dashboard_data_service.table_payload`.",
            "- A project read must stay a read: `read_source_table` never imports, and `read_dataset_table` loads each dataset at the period it is stored at.",
        ),
        "workspace_paths": (
            "Runtime workspace path read/update domain.",
            "- Used by shell root-path settings modal.\n- Triggers `config.refresh_runtime_paths()` on updates.\n- `GET /workspace_paths` reports whether the AppData config file already exists so the shell can detect first-time setup.",
            "- Persists config in `%APPDATA%\\ArcRho\\workspace_paths.json`.\n- Uses built-in defaults until Server Connection is saved.",
            "1. Add config field: update schema + router serialization + config readers.\n2. Rename config fields by updating producers, consumers, and docs together.",
            "- Invalid path config writes can impact all path-dependent domains.",
        ),
        "app_control": (
            "Application lifecycle control domain (restart/shutdown flags).",
            "- Called by shell app control actions.\n- Coordinated with launcher/electron host watchers.",
            "- Uses flag files under project root.",
            "1. Add lifecycle action: define flag contract and watcher handling in launcher/host.",
            "- Incorrect flag behavior can cause app restart loops.",
        ),
        "audit_log": (
            "Audit log read/write domain for project actions.",
            "- Called from settings/type update flows.\n- Service enforces safe append logic.",
            "- Stores rolling JSON audit records with lock protection.",
            "1. Add audit event fields: update schema and writer helper together.",
            "- Lock/file contention may surface under concurrent writes.",
        ),
        "dataset": (
            "Dataset retrieval/patch domain for in-memory dataset instances.",
            "- Called by Dataset Viewer/DFM frontend flows via `ui/shared/dataset/dataset_api.js`.",
            "- Uses in-memory dataset map and patch payloads.",
            "1. Change patch semantics: align schema, service patch rules, and frontend expectations.",
            "- Patch operations can introduce subtle data integrity issues.",
        ),
        "result_selection": (
            "Self-contained Result Selection v2 load, save, and eager dependency-refresh domain.",
            "- Used by the Result Selection method page and its ResQ bridge.\n- Current loads aggregate one method JSON and its output sidecar.",
            "- Persists Result Selection method JSON, output vector CSV variants, and an output dataset sidecar with dependency edges.",
            "1. Change the v2 payload only across every producer and the exact parity test.\n2. Preserve two-file current loads and failure-safe eager refresh behavior.",
            "- Broken reverse edges or bypassing durable ArcRho save paths can prevent automatic refresh.",
        ),
        "bornhuetter_ferguson": (
            "Self-contained Bornhuetter Ferguson v3 load, save, and eager dependency-refresh domain.",
            "- Used by the BF method page.\n- Current loads aggregate one method JSON and its raw output sidecar; earlier BF formats are rejected without dependency reads.",
            "- Persists the complete BF method snapshot, native/coarser output vector CSVs, and its output sidecar with dependency edges and a matching publication revision.",
            "1. Change the v3 payload only across every producer and exact parity test.\n2. Preserve the two-file current load and failure-safe, bounded eager refresh behavior.",
            "- Out-of-band source edits bypass managed propagation; failed refresh branches retain their last valid publication and remain Review Needed.",
        ),
        "cape_cod": (
            "Self-contained Cape Cod v1 load, save, and eager dependency-refresh domain.",
            "- Used by the Cape Cod method page.\n- Current loads aggregate one method JSON and its raw output sidecar, plus the derived as-if ultimates triangle.",
            "- Persists the complete Cape Cod method snapshot, native/coarser output vector CSVs, and its output sidecar with dependency edges and a matching publication revision.",
            "1. Change the v1 payload only across every producer and exact parity test.\n2. Preserve the two-file current load and failure-safe, bounded eager refresh behavior.",
            "- Out-of-band source edits bypass managed propagation; failed refresh branches retain their last valid publication and remain Review Needed.",
        ),
        "bootstrap": (
            "Self-contained Bootstrap v1 load, save, and eager dependency-refresh domain.",
            "- Used by the Bootstrap method page.\n- Current loads aggregate one method JSON and its raw output sidecar; the precedent DFM is read as a method rather than a dataset.",
            "- Persists the complete Bootstrap method snapshot, native/coarser output vector CSVs, and its output sidecar with dependency edges and a matching publication revision. Simulated reserves are never persisted: only the seed, the simulation count, and a summary.",
            "1. Change the v1 payload only across every producer and exact parity test.\n2. Resolve the DFM method to the dataset it publishes before touching the dependency graph.",
            "- Out-of-band source edits bypass managed propagation; failed refresh branches retain their last valid publication and remain Review Needed.",
        ),
        "stochastic_consolidation": (
            "Stochastic Consolidation load, run, segment picker and save domain; its segments are Bootstrap methods in other reserving classes.",
            "- Used by the Stochastic Consolidation method page.",
            "- Persists the method JSON, native/coarser output vector CSVs, and an output sidecar whose precedents name each segment's class. Simulations are never persisted.",
            "1. Change the payload only in `arcrho_api/stochastic_consolidation_contract.py` and its parity tests.\n2. Keep every segment read addressed by the segment's own reserving class.",
            "- Cross-class propagation is deferred; a changed segment is reported on open, not refreshed.",
        ),
        "excel": (
            "Excel automation domain (selection reads and workbook operations).",
            "- Called by interactive Excel-based workflows.",
            "- Runtime depends on local Excel automation availability.",
            "1. Add automation method: schema + router + service must stay aligned.",
            "- Excel COM timing and environment dependencies are fragile.",
        ),
        "excel_link": (
            "Reserving-class Excel link inventory and workbook retargeting domain.",
            "- Called by the Project Instance Excel Link Manager window.",
            "- Rewrites saved dataset sidecar and DFM method reference text without touching stored values.",
            "1. Add link source kinds: extend the scan/rewrite pair while keeping reference syntax mirrored with the frontend parser.",
            "- The Python reference parser must stay in sync with `ui/shared/integrations/excel_reference.js`.",
        ),
        "arcrho": (
            "ArcRho calculations/precheck domain.",
            "- Called by dataset/workflow actions requiring ArcRho processing.",
            "- Integrates headers/project listing and tri execution endpoints.",
            "1. Add new ArcRho operation: keep precheck/execute contracts explicit.",
            "- Long-running computations need robust error messaging.",
        ),
        "project_settings": (
            "Project settings source and folder-structure management domain.",
            "- Heavily used by `project_settings.js` UI flows.",
            "- Handles folder CRUD and settings JSON writes.",
            "1. Add source key support: update router path params + service source resolution.",
            "- Folder operation rollbacks can leave partial state when interrupted.",
        ),
        "table_summary": (
            "Table summary generation/cache and refresh domain.",
            "- Used by project settings and reserving class refresh workflows.",
            "- Can trigger reserving class value refresh as side effect.",
            "1. Change refresh contract: align request schema and downstream reserve refresh behavior.",
            "- Cache invalidation and side-effect refresh can impact performance.",
        ),
        "source_table": (
            "Project-owned imported source table domain.",
            "- Used by project settings Source Data, every app-server table reader, and the data engine.",
            "- Owns <project>/source/master_table.csv and source/source_import.json.",
            "1. Add an import source or profile field: extend arcrho_api/source_table_contract.py first.",
            "- The imported copy is the only table downstream consumers read.",
        ),
        "field_mapping": (
            "Field mapping persistence domain for project settings.",
            "- Used by project settings field mapping feature.",
            "- Stores mapping files under project folders.",
            "1. Add mapping attributes: update schema, service validation, and UI module.",
            "- Invalid mappings propagate into reserving class/dataset processing.",
        ),
        "dataset_types": (
            "Dataset types catalog domain.",
            "- Used by project settings dataset types panel and dependent flows.",
            "- Persists dataset type definitions under project folders.",
            "1. Add type metadata field: align schema, service normalization, and frontend editor.",
            "- Type schema drift can break downstream interpretation logic.",
        ),
        "dependent_propagation": (
            "Engine-hosted dependent propagation job domain: saves write only the saved object, then enqueue one durable `ArcRhoRefreshDependents` job that Arco Engine executes on the server host.",
            "- Canonical contract module `python-api/src/arcrho_dependent_propagation_contract.py` owns the request/status schemas, `requests/dependent_propagation/` folder layout, reserving-class lease (5 s heartbeat, 300 s stale takeover), and the live-Engine heartbeat preflight (fresh `runtime/instances/arcrho_engine/*.json` mtime within 60 s).\n- Engine worker `server-components/src/arcrho_engine/dependent_propagation.py` claims the reserving-class lease, drains and merges queued requests for the same class (`merged_into` statuses), runs the canonical `calculated_dataset_service.recalculate_dependents` walk with per-tier progress, and retains the request file until a validated terminal status exists.\n- Every save flow (DFM, Result Selection, Bornhuetter Ferguson, Cape Cod, Bootstrap, dataset sidecar/grid saves, runtime cache writes, dataset-type formula changes) preflights `require_engine_available()` before writing anything; no live Engine blocks the save with a message box and unsaved work stays in the editor.\n- Server-host in-process producers (ResQ migration, public Python API) keep walking in-process but hold the same reserving-class lease.",
            "- Transient runtime files under `<server-root>/requests/dependent_propagation/{requests,statuses,locks}`; statuses follow the project-duplication retention policy (retained, no automatic pruning).\n- Save responses carry `propagation: {job_id, status: \"queued\"}`, or `{status: \"unchanged\"}` for no-op saves whose publication revision did not change.",
            "1. Change the job contract: update the canonical contract module first, then the Engine worker, app-server service, UI poller, and tests together.\n2. Add a propagation-triggering save flow: preflight the Engine, mark reachable downstream review-needed, then `enqueue_save_propagation`; never run the walk inline on a client.",
            "- Failed jobs are not auto-retried: downstream methods stay Review Needed until the next save or manual refresh re-enqueues a walk.\n- A plain filesystem cannot atomically fence the stale-lease takeover race; the generous thresholds make it acceptable (same residual gap as project duplication).",
        ),
        "object_change_watch": (
            "Open-window change-watch domain: a dataset window or method page polls a stat-only fingerprint of the object it opened and shows a one-time advisory alert when another user or an automation process (including the Engine dependent-propagation job) rewrites it.",
            "- `POST /object_change/fingerprint` stats the watched files only and returns `{files, token}`; it never reads a payload.\n- `dataset_sidecar_status_service.method_json_path` is the single owner of the method-type-to-filename-prefix rule.\n- The shared UI poller `ui/shared/services/object_change_watch.js` compares tokens on an interval, fires `onChange` once, and exposes `pause`/`resume`/`rebase` so self-saves are never reported.",
            "- Stateless: each request is one or two `os.stat` calls; the baseline token lives in the open window.",
            "1. Watch a new object kind: extend the service's kind dispatch and give the page a poller via `createObjectChangeWatch`/`createMethodObjectChangeWatchController`, pausing around its save flow.",
            "- The alert is advisory: detection latency is the poll interval plus SMB attribute-cache lag, and a change landing between open and the first poll baseline is not reported.",
        ),
        "data_processing_rules": (
            "Project-scoped custom row-filter rule validation and persistence domain.",
            "- Used by Project Settings to load, validate, and save data-processing rules.\n- Generated-cache provenance consumes the same processing configuration hash.",
            "- Persists versioned `data_processing_rules.json` files with optimistic revisions, atomic writes, per-path locks, and audit entries.",
            "1. Add an operator: align schema, service, data engine, Project Settings, and docs.\n2. Change processing-hash inputs only as a coordinated cache-contract update.",
            "- Invalid or stale references must remain visible to Project Settings, and generated caches must not bypass processing-hash checks.",
        ),
        "reserving_class": (
            "Reserving class values/tree/preferences/types domain.",
            "- Consumed by dataset, DFM, and project settings features.\n- Exposes refresh and cache children endpoints.",
            "- Uses multiple JSON cache files and AppData preference files with lock protection.",
            "1. Add a reserving-class endpoint: keep schema/service lock logic consistent.\n2. Change cache structure: update readers/writers and UI consumers together.",
            "- High route volume and file-lock contention make regression risk higher here.",
        ),
        "ui_automation": (
            "Local UI automation command bridge for Python macros and scripts.",
            "- Consumed by `arcrho_api.ui` helpers and the shell polling executor.\n- Commands are typed and routed through explicit shell/page handlers.",
            "- Keeps pending commands in memory only; no ArcRho Server request files or project data are written.",
            "1. Add a UI automation command: update schema/service if needed, shell executor, page handler, Python helper, and docs together.",
            "- Commands depend on active UI state and should fail clearly when the expected page/window is not active.",
        ),
        "snowflake": (
            "Snowflake SQL execution domain for Arcode.",
            "- `GET /snowflake/connections` returns local connection profiles and connector availability.\n- `POST /snowflake/query` and `/snowflake/test-connection` execute SQL through the app-server runtime.",
            "- Stores connection profiles in `%APPDATA%\\Arcode\\snowflake_connections.json` in Arcode mode and can seed the default profile from `E:\\XWSpace\\Snowflake Config.txt`.",
            "1. Add a Snowflake route: keep schemas in `app_server/schemas/scripting.py`, router delegation, and `snowflake_service` behavior aligned.\n2. Change connection storage: update `config.py`, this domain doc, and Arcode UI callers together.",
            "- Query execution requires `snowflake-connector-python`; missing connectors must return explicit user-facing errors.",
        ),
        "sql_server": (
            "SQL Server connection profiles and T-SQL execution for the Arcode SQL Server console.",
            "- `GET /sqlserver/connections` returns the per-user profiles, the stored default, and whether an ODBC driver is available.\n- `POST /sqlserver/connections` adds, edits, or renames one profile; `POST /sqlserver/connections/delete` removes one.\n- `POST /sqlserver/query` and `/sqlserver/test-connection` execute T-SQL as the caller's Windows identity.",
            "- Stores profiles in `%APPDATA%\\Arcode\\sql_server_connections.json` in Arcode mode and the ArcRho per-user config folder otherwise. This is not the ArcRho Server's shared server/database history used by Project Settings Source Data.\n- Profiles hold a name, server, database, and authentication mode only; no credential is ever written.\n- A query opens and closes its own connection, so no session state survives between runs.",
            "1. Change the profile payload: update `sql_server_service` normalization, `config.py`, the connection manager client, and this doc together.\n2. Change how a connection is opened: change `mssql_odbc` only, so the Project Settings source-table import stays identical.",
            "- Only Windows authentication is wired up; the SQL login mode is rejected until it is implemented.\n- Execution is not read-only: a batch runs with autocommit, so a user's statement can change data their Windows account may change.\n- Results are capped and reported as truncated; the grid is for inspection, not export.",
        ),
        "sql_formatting": (
            "Parser-backed, dialect-aware SQL formatting previews shared by Arcode and ArcBot.",
            "- `POST /arcode/sql/format-preview` accepts exact source text, an explicit `tsql` or `snowflake` dialect, and nested-`OPENQUERY` mode.\n- Responses include exact hashes, proposed text, structured diagnostics/advisories, engine metadata, and safety gates.",
            "- Formatting is request-local and never persists editor text.\n- One process-level formatter instance serializes access to the canonical pinned SQLFluff runtime.\n- The canonical lexer owns both protected-text safety checks and deterministic advisories.",
            "1. Change the formatter contract only across schema, router, service, both Arcode clients, ArcBot skill, tests, packaging, and docs.\n2. Preserve fail-closed atomic output, exact hashes, protected regions, token equivalence, and whole-document idempotence.",
            "- Parser acceptance and token preservation do not prove intended business semantics or performance.\n- The canonical SQLFluff runtime and its package data/metadata must remain pinned in both PyInstaller bundles.",
        ),
    }

    for domain in BACKEND_DOMAIN_META:
        purpose, external, data_state, tasks, risks = backend_manual[domain]
        specs[f"docs/app_server/domains/{domain}.md"] = ModuleDocSpec(
            path=f"docs/app_server/domains/{domain}.md",
            title=f"App Server Domain: {domain}",
            manual_sections={
                "Purpose": purpose,
                "External Interfaces": external,
                "Data/State/Caches": data_state,
                "Common Change Tasks": tasks,
                "Known Risks": risks,
            },
            auto_sections={
                "Entry Points": f"app_server.{domain}.entry_points",
                "Key Files": f"app_server.{domain}.key_files",
            },
        )

    specs["docs/runtime/config_paths.md"] = ModuleDocSpec(
        path="docs/runtime/config_paths.md",
        title="Runtime: Config and Path Resolution",
        manual_sections={
            "Purpose": "Document path/config setup, AppData-backed workspace path persistence, and runtime path refresh behavior.",
            "External Interfaces": "- Frontend shell settings modal calls `/workspace_paths` routes.\n- App-server modules import `app_server.config` for runtime path resolution.\n- On first-time setup, the Electron shell searches `D:\\Arco Server` through `Z:\\Arco Server` and fills the Server Connection root path when found.",
            "Data/State/Caches": "- `%APPDATA%\\ArcRho\\workspace_paths.json` is the persistent user-local source-of-truth for workspace root/path mapping.\n- If the AppData workspace path file does not exist yet, the app uses built-in defaults until the Server Connection setting is saved.\n- Runtime globals in `app_server/config.py` are refreshed from config.\n- User-local fixed paths are also refreshed in `app_server/config.py`, including workflow export path (`~/Documents/ArcRho/workflows`), scripting notebook path (`~/Documents/ArcRho/scripts`), and Macro window path (`~/Documents/ArcRho/macros`).",
            "Common Change Tasks": "1. Add a new configurable path: update the AppData `workspace_paths.json` contract + `app_server/config.py` getters.\n2. Change path refresh behavior: validate all services that depend on runtime globals.",
            "Known Risks": "- Path changes affect every filesystem-backed domain.\n- Environment-specific path assumptions can break packaged deployments.",
        },
        auto_sections={
            "Entry Points": "runtime.config_paths.entry_points",
            "Key Files": "runtime.config_paths.key_files",
        },
    )

    specs["docs/runtime/data_cache_files.md"] = ModuleDocSpec(
        path="docs/runtime/data_cache_files.md",
        title="Runtime: Data and Cache Files",
        manual_sections={
            "Purpose": "Index cache/data files and refresh points used by app-server services.",
            "External Interfaces": "- Cache refresh is exposed via route endpoints and service calls.\n- Several caches are project-folder scoped; others are user AppData scoped.",
            "Data/State/Caches": "- File names and limits are defined in `app_server/config.py` constants.\n- Refresh endpoints can clear and rebuild cache files.",
            "Common Change Tasks": "1. Add cache file constant: update config, service readers/writers, and this index.\n2. Change refresh logic: verify endpoint side effects and lock behavior.",
            "Known Risks": "- Cache invalidation bugs can surface as stale or mismatched UI data.\n- File locking can fail writes under concurrent access.",
        },
        auto_sections={
            "Entry Points": "runtime.data_cache_files.entry_points",
            "Key Files": "runtime.data_cache_files.key_files",
        },
    )

    specs["docs/build/packaging.md"] = ModuleDocSpec(
        path="docs/build/packaging.md",
        title="Build and Packaging",
        manual_sections={
            "Purpose": "Document Electron + Python packaging inputs and scripts.",
            "External Interfaces": "- Node scripts from `package.json` drive build orchestration.\n- PyInstaller spec (`build/server.spec`) builds app-server executable artifacts.\n- `build/release/release_notes.py` validates unreleased change fragments and generates versioned release notes in `docs/releases/`.\n- ArcRho packaging preserves electron-builder's built-in NSIS file installation path and compiles an isolated native-bar progress observer.",
            "Data/State/Caches": "- Build outputs: `dist/`, `python_build/`, `python_dist/`.\n- Installer settings live in `package.json`, `build/installer/installer.nsh`, `build/installer/installer_progress_helper.cs`, and `build/installer/patch_nsis_installer_progress.js`.\n- Release tracking data lives under `changes/unreleased/`, `changes/archive/`, and `docs/releases/`.",
            "Common Change Tasks": "1. Update app packaging metadata: edit `package.json` `build` block.\n2. Update bundled app server: edit `build/server.spec` and verify `extraResources` mappings.\n3. Add or update unreleased change fragments in `changes/unreleased/` before packaging a release.\n4. Run `E:\\XWSpace\\Build ArcRho App\\build_app_one_click.bat` for a normal build; it requests a fresh ZIP and auto-increments the patch version.\n5. If electron-builder is reinstalled or upgraded, rerun `npm run build:electron` or the one-click workflow; both paths reapply the ArcRho NSIS installer-progress patch before packaging.",
            "Known Risks": "- Packaging excludes can accidentally omit runtime files.\n- Divergence between dev and packaged paths causes startup failures.\n- electron-builder NSIS implementation changes can break the ArcRho installer-progress patch; `build/installer/patch_nsis_installer_progress.js` fails fast when upstream templates no longer match a supported form.\n- ArcRho installer packaging requires the Windows .NET Framework 4 C# compiler for the isolated progress observer.",
        },
        auto_sections={
            "Entry Points": "build.packaging.entry_points",
            "Key Files": "build.packaging.key_files",
        },
    )

    return specs


def conventions_doc() -> str:
    return dedent(
        """
        # Documentation Conventions

        ## Purpose
        This project uses a semi-automatic documentation system for code agents.

        ## Required Section Template
        Module/submodule index files should use these sections in order:
        1. `Purpose`
        2. `Entry Points`
        3. `Key Files`
        4. `External Interfaces`
        5. `Data/State/Caches`
        6. `Common Change Tasks`
        7. `Known Risks`

        ## Marker Contract
        AUTO-GEN blocks are managed by `tools/docs_index_builder.py`:

        ```md
        <!-- AUTO-GEN:BEGIN label -->
        ...
        <!-- AUTO-GEN:END -->
        ```

        MANUAL blocks are hand-maintained:

        ```md
        <!-- MANUAL:BEGIN -->
        ...
        <!-- MANUAL:END -->
        ```

        Rule:
        - The script may update only AUTO-GEN blocks.
        - The script must not rewrite MANUAL blocks.
        - Frontend module `Purpose` sections should stay under 6 nonblank lines and 900 characters; move behavior details to focused sections or source-specific docs.

        ## Naming and Placement
        - All docs live under `docs/`.
        - Frontend indexes: `docs/ui/`.
        - App-server indexes: `docs/app_server/` and `docs/app_server/domains/`.
        - Runtime/config indexes: `docs/runtime/`.
        - Build indexes: `docs/build/`.
        - Generated inventories: `docs/generated/`.

        ## Update Workflow
        1. `python tools/docs_index_builder.py --scaffold-missing`
        2. `python tools/docs_index_builder.py --write`
        3. `python tools/docs_index_builder.py --check`
        """
    ) + "\n"


def generated_readme_doc() -> str:
    return dedent(
        """
        # Generated Documentation Files

        These files are fully generated by `tools/docs_index_builder.py`:
        - `docs/generated/app_server_routes.md`
        - `docs/generated/frontend_entrypoints.md`
        - `docs/generated/file_manifest.md`

        Do not hand-edit generated files; re-run:
        - `python tools/docs_index_builder.py --write`

        Generated files are checked by:
        - `python tools/docs_index_builder.py --check`
        """
    ) + "\n"


def generated_placeholder(title: str) -> str:
    return f"# {title}\n\n_Run `python tools/docs_index_builder.py --write` to generate this file._\n"


def scaffold_templates() -> Dict[str, str]:
    templates: Dict[str, str] = {}
    for path, spec in module_specs().items():
        templates[path] = render_module_doc(spec)

    templates["docs/CONVENTIONS.md"] = conventions_doc()
    templates["docs/GENERATED_README.md"] = generated_readme_doc()
    templates["docs/generated/app_server_routes.md"] = generated_placeholder("App Server Route Inventory")
    templates["docs/generated/frontend_entrypoints.md"] = generated_placeholder("Frontend Entrypoint Inventory")
    templates["docs/generated/file_manifest.md"] = generated_placeholder("Repository File Manifest")
    return templates


def render_key_files_block(doc_path: str, files: Sequence[Tuple[str, str]]) -> str:
    rows: List[str] = []
    for repo_file, desc in files:
        link = rel_link(doc_path, repo_file)
        exists = (REPO_ROOT / repo_file).exists()
        status = "" if exists else " _(missing)_"
        rows.append(f"- [`{repo_file}`]({link}) - {desc}{status}")
    if not rows:
        return "_No key files configured._"
    return "\n".join(rows)


def routes_by_domain(routes: Sequence[RouteEntry]) -> Dict[str, List[RouteEntry]]:
    out: Dict[str, List[RouteEntry]] = {}
    for route in routes:
        out.setdefault(route.domain, []).append(route)
    for domain in out:
        out[domain].sort(key=lambda r: (r.path, r.method, r.handler))
    return out


def render_route_table_for_doc(doc_path: str, routes: Sequence[RouteEntry]) -> str:
    rows: List[List[str]] = []
    for r in routes:
        schema_cell = "-"
        if r.request_schema:
            schema_cell = f"[`{r.request_schema}`]({rel_link(doc_path, r.request_schema)})"
        services = ", ".join(f"`{svc}`" for svc in r.services) if r.services else "-"
        rows.append(
            [
                f"`{r.method}`",
                f"`{r.path}`",
                f"`{r.handler}`",
                f"`{r.request_model}`" if r.request_model else "-",
                schema_cell,
                services,
            ]
        )
    return md_table(["Method", "Path", "Handler", "Request Model", "Schema", "Service Calls"], rows)


def render_frontend_entrypoint_block(entrypoints: Mapping[str, FrontendEntrypoint], html_files: Sequence[str]) -> str:
    lines: List[str] = []
    for html in html_files:
        info = entrypoints.get(html)
        if info is None:
            lines.append(f"- `{html}`: not found.")
            continue
        ext = ", ".join(f"`{x}`" for x in info.external_scripts) if info.external_scripts else "_none_"
        imp = ", ".join(f"`{x}`" for x in info.inline_imports) if info.inline_imports else "_none_"
        lines.append(f"- `{html}`: external scripts {ext}; inline imports {imp}.")
    if not lines:
        return "_No entrypoints configured._"
    return "\n".join(lines)


def render_frontend_index_entrypoints(entrypoints: Mapping[str, FrontendEntrypoint]) -> str:
    rows: List[List[str]] = []
    for html in FRONTEND_ENTRY_HTMLS:
        info = entrypoints.get(html)
        ext_count = len(info.external_scripts) if info else 0
        imp_count = len(info.inline_imports) if info else 0
        ext = f"{ext_count} external script{'s' if ext_count != 1 else ''}" if ext_count else "-"
        imp = f"{imp_count} inline import{'s' if imp_count != 1 else ''}" if imp_count else "-"
        rows.append([f"`{html}`", ext, imp])
    return md_table(["HTML Entrypoint", "External Scripts", "Inline Imports"], rows)


def render_app_server_index_entrypoints(doc_path: str, by_domain: Mapping[str, Sequence[RouteEntry]]) -> str:
    rows: List[List[str]] = []
    for domain in sorted(BACKEND_DOMAIN_META):
        routes = list(by_domain.get(domain, []))
        router = f"app_server/api/{domain}_router.py"
        router_cell = f"[`{router}`]({rel_link(doc_path, router)})"
        doc_file = f"docs/app_server/domains/{domain}.md"
        doc_cell = f"[`{domain}.md`]({rel_link(doc_path, doc_file)})"
        rows.append([f"`{domain}`", router_cell, str(len(routes)), doc_cell])
    return md_table(["Domain", "Router", "Route Count", "Domain Index"], rows)


def render_root_key_files(doc_path: str) -> str:
    files = [
        ("docs/ui/INDEX.md", "Frontend module index."),
        ("docs/app_server/INDEX.md", "App-server domain index."),
        ("docs/runtime/config_paths.md", "Runtime config and path index."),
        ("docs/runtime/data_cache_files.md", "Runtime cache/data file index."),
        ("docs/build/packaging.md", "Build and packaging index."),
        ("docs/generated/app_server_routes.md", "Generated route inventory."),
        ("docs/generated/frontend_entrypoints.md", "Generated frontend entrypoint inventory."),
        ("docs/generated/file_manifest.md", "Generated repository file manifest."),
    ]
    return render_key_files_block(doc_path, files)


def render_app_server_index_key_files(doc_path: str) -> str:
    files = [
        ("app_server/main.py", "FastAPI app creation, router registration, static mount."),
        ("app_server/api/__init__.py", "Router exports consumed by app startup."),
        ("app_server/config.py", "Runtime path/config constants and helpers."),
        ("app_server/helpers.py", "Cross-domain utility helpers."),
    ]
    return render_key_files_block(doc_path, files)


def render_frontend_index_key_files(doc_path: str) -> str:
    files = [
        ("docs/ui/shell.md", "Shell tab host index."),
        ("docs/ui/file_explorer.md", "File Explorer feature index."),
        ("docs/ui/server.md", "Server tab index."),
        ("docs/ui/dataset.md", "Dataset feature index."),
        ("docs/ui/dfm.md", "DFM feature index."),
        ("docs/ui/bornhuetter_ferguson.md", "Bornhuetter Ferguson method-page index."),
        ("docs/ui/cape_cod.md", "Cape Cod method-page index."),
        ("docs/ui/bootstrap.md", "Bootstrap method-page index."),
        ("docs/ui/stochastic_consolidation.md", "Stochastic Consolidation method-page index."),
        ("docs/ui/berquist_sherman.md", "Berquist Sherman method-page index."),
        ("docs/ui/result_selection.md", "Result Selection method-page index."),
        ("docs/ui/workflow.md", "Workflow feature index."),
        ("docs/ui/project_settings.md", "Project settings feature index."),
        ("docs/ui/arcode.md", "Arcode scripting workspace feature index."),
        ("docs/ui/ai_assistant.md", "Shared ArcBot assistant widget index."),
    ]
    return render_key_files_block(doc_path, files)


def render_runtime_config_entrypoints(path_functions: Sequence[str], workspace_path_routes: Sequence[RouteEntry]) -> str:
    lines: List[str] = []
    if path_functions:
        lines.append("- Path/config helper functions in `app_server/config.py`:")
        lines.extend([f"  - `{name}`" for name in path_functions])
    else:
        lines.append("- No config helper functions discovered.")

    if workspace_path_routes:
        lines.append("- Workspace path config routes:")
        for r in workspace_path_routes:
            lines.append(f"  - `{r.method}` `{r.path}` handled by `{r.handler}`")
    return "\n".join(lines)


def render_runtime_data_entrypoints(routes: Sequence[RouteEntry]) -> str:
    refresh_routes = [r for r in routes if "refresh" in r.path or "cache" in r.path or "summary" in r.path]
    refresh_routes.sort(key=lambda r: (r.path, r.method))
    if not refresh_routes:
        return "_No refresh/cache routes detected._"
    rows = [[f"`{r.method}`", f"`{r.path}`", f"`{r.domain}`", f"`{r.handler}`"] for r in refresh_routes]
    return md_table(["Method", "Path", "Domain", "Handler"], rows)


def render_runtime_data_key_files(doc_path: str, constants: Sequence[str]) -> str:
    cache_constants = [c for c in constants if c.endswith("_FILE") or c.endswith("_LOCK")]
    lines = [render_key_files_block(doc_path, [("app_server/config.py", "Cache/data file names and lock constants.")])]
    if cache_constants:
        lines.append("")
        lines.append("Cache/lock constants detected:")
        lines.extend([f"- `{c}`" for c in cache_constants])
    return "\n".join(lines).strip()


def render_runtime_config_key_files(doc_path: str) -> str:
    files = [
        ("app_server/config.py", "Primary runtime path + config module, including AppData workspace path persistence."),
        ("app_server/api/workspace_paths_router.py", "HTTP interface for workspace path updates."),
        ("app_server/main.py", "App bootstrap and static path mounting."),
    ]
    return render_key_files_block(doc_path, files)


def render_build_entrypoints(package_info: Mapping[str, object]) -> str:
    scripts = package_info.get("scripts", {}) if isinstance(package_info.get("scripts"), dict) else {}
    main = package_info.get("main", "")
    rows: List[List[str]] = []
    for name in sorted(scripts):
        rows.append([f"`npm run {name}`", f"`{scripts[name]}`"])
    body = []
    body.append(md_table(["Script", "Command"], rows))
    if main:
        body.append("")
        body.append(f"Electron main entry: `{main}`")
    return "\n".join(body).strip()


def render_build_key_files(doc_path: str) -> str:
    files = [
        ("package.json", "Build scripts, Electron builder config, installer metadata."),
        ("build/server.spec", "PyInstaller spec for Python app-server executable."),
        ("build/server_entry.py", "PyInstaller entrypoint for the bundled app server."),
        ("build/write_backend_artifact_manifest.py", "Build-time identity manifest for the complete collected backend bundle."),
        ("build/release/release_notes.py", "Release fragment validator and versioned release note generator."),
        ("electron/main.js", "Electron main process entry."),
        ("app_launcher.py", "Python host launcher used by packaged runtime."),
        ("build/installer/installer.nsh", "NSIS custom installer script include."),
        ("build/installer/patch_nsis_installer_progress.js", "Build-time helper that restores NSIS's built-in file installation path and compiles the progress observer before electron-builder runs."),
        ("build/installer/installer_progress_helper.cs", "Isolated Windows UI observer that derives installer percentage and time remaining from the native progress control."),
        ("build/build_app_via_local_workspace.bat", "Shared build body for both release entry points; prepares a local workspace from the source ZIP, or builds in place when ARCRHO_BUILD_IN_PLACE is set, and runs the complete package build."),
        ("build/build_app_from_local_repo.bat", "Single-PC release entry point; builds in place from this repository and commits the release bookkeeping it produces."),
        ("build/helpers/convert_icon.js", "Build helper for regenerating Windows icon assets."),
    ]
    return render_key_files_block(doc_path, files)


def build_autogen_blocks(
    routes: Sequence[RouteEntry],
    entrypoints: Mapping[str, FrontendEntrypoint],
    path_functions: Sequence[str],
    constants: Sequence[str],
    package_info: Mapping[str, object],
) -> Dict[str, str]:
    by_domain = routes_by_domain(routes)
    blocks: Dict[str, str] = {}

    blocks["root.key_files"] = render_root_key_files("docs/INDEX.md")
    blocks["frontend.index.entry_points"] = render_frontend_index_entrypoints(entrypoints)
    blocks["frontend.index.key_files"] = render_frontend_index_key_files("docs/ui/INDEX.md")
    blocks["app_server.index.entry_points"] = render_app_server_index_entrypoints("docs/app_server/INDEX.md", by_domain)
    blocks["app_server.index.key_files"] = render_app_server_index_key_files("docs/app_server/INDEX.md")

    for name, meta in FRONTEND_DOC_META.items():
        html_files = meta["html"]  # type: ignore[index]
        file_specs = meta["files"]  # type: ignore[index]
        interface_files = meta.get("interface_files", [])  # type: ignore[union-attr]
        js_files = list(dict.fromkeys(
            [path for path, _ in file_specs if path.endswith(".js")]
            + [str(path) for path in interface_files]
        ))
        endpoints, messages = parse_js_interface_patterns(js_files)

        entry_block = render_frontend_entrypoint_block(entrypoints, html_files)
        if endpoints:
            entry_block += "\n\nDetected `fetch(...)` targets in key JS files:\n"
            entry_block += "\n".join(f"- `{e}`" for e in endpoints)
        if messages:
            entry_block += "\n\nDetected `arcrho:*` message types in key JS files:\n"
            entry_block += "\n".join(f"- `{m}`" for m in messages)

        blocks[f"frontend.{name}.entry_points"] = entry_block
        blocks[f"frontend.{name}.key_files"] = render_key_files_block(meta["doc"], file_specs)  # type: ignore[index]

    for domain, meta in BACKEND_DOMAIN_META.items():
        domain_routes = by_domain.get(domain, [])
        blocks[f"app_server.{domain}.entry_points"] = render_route_table_for_doc(meta["doc"], domain_routes)  # type: ignore[index]
        blocks[f"app_server.{domain}.key_files"] = render_key_files_block(meta["doc"], meta["files"])  # type: ignore[index]

    workspace_path_routes = by_domain.get("workspace_paths", [])
    blocks["runtime.config_paths.entry_points"] = render_runtime_config_entrypoints(path_functions, workspace_path_routes)
    blocks["runtime.config_paths.key_files"] = render_runtime_config_key_files("docs/runtime/config_paths.md")
    blocks["runtime.data_cache_files.entry_points"] = render_runtime_data_entrypoints(routes)
    blocks["runtime.data_cache_files.key_files"] = render_runtime_data_key_files("docs/runtime/data_cache_files.md", constants)
    blocks["build.packaging.entry_points"] = render_build_entrypoints(package_info)
    blocks["build.packaging.key_files"] = render_build_key_files("docs/build/packaging.md")

    return blocks


def render_app_server_routes_generated(routes: Sequence[RouteEntry]) -> str:
    by_domain = routes_by_domain(routes)
    lines: List[str] = []
    lines.append("# App Server Route Inventory")
    lines.append("")
    lines.append("Generated by `python tools/docs_index_builder.py --write`.")
    lines.append("")
    summary_rows: List[List[str]] = []
    for domain in sorted(BACKEND_DOMAIN_META):
        domain_routes = by_domain.get(domain, [])
        router = f"app_server/api/{domain}_router.py"
        summary_rows.append(
            [
                f"`{domain}`",
                f"`{router}`",
                str(len(domain_routes)),
                f"[Open Domain Index](../app_server/domains/{domain}.md)",
            ]
        )
    lines.append("## Domain Summary")
    lines.append(md_table(["Domain", "Router", "Routes", "Domain Doc"], summary_rows))
    lines.append("")
    for domain in sorted(BACKEND_DOMAIN_META):
        lines.append(f"## {domain}")
        lines.append("")
        domain_routes = by_domain.get(domain, [])
        lines.append(render_route_table_for_doc("docs/generated/app_server_routes.md", domain_routes))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_frontend_entrypoints_generated(entrypoints: Mapping[str, FrontendEntrypoint]) -> str:
    lines: List[str] = []
    lines.append("# Frontend Entrypoint Inventory")
    lines.append("")
    lines.append("Generated by `python tools/docs_index_builder.py --write`.")
    lines.append("")
    rows: List[List[str]] = []
    for html in FRONTEND_ENTRY_HTMLS:
        info = entrypoints.get(html, FrontendEntrypoint(html, tuple(), tuple()))
        rows.append(
            [
                f"`{html}`",
                ", ".join(f"`{x}`" for x in info.external_scripts) or "-",
                ", ".join(f"`{x}`" for x in info.inline_imports) or "-",
            ]
        )
    lines.append("## Summary")
    lines.append(md_table(["HTML Entrypoint", "External Scripts", "Inline Imports"], rows))
    lines.append("")
    for html in FRONTEND_ENTRY_HTMLS:
        info = entrypoints.get(html, FrontendEntrypoint(html, tuple(), tuple()))
        lines.append(f"## {html}")
        lines.append("")
        ext = info.external_scripts or ("(none)",)
        imp = info.inline_imports or ("(none)",)
        lines.append("- External scripts:")
        for item in ext:
            lines.append(f"  - `{item}`")
        lines.append("- Inline imports:")
        for item in imp:
            lines.append(f"  - `{item}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_manifest_generated(entries: Sequence[ManifestEntry]) -> str:
    top_counts: Dict[str, int] = {}
    for e in entries:
        first = e.path.split("/", 1)[0] if "/" in e.path else "(root)"
        top_counts[first] = top_counts.get(first, 0) + 1

    lines: List[str] = []
    lines.append("# Repository File Manifest")
    lines.append("")
    lines.append("Generated by `python tools/docs_index_builder.py --write`.")
    lines.append("")
    lines.append("Excluded directories: " + ", ".join(f"`{d}`" for d in sorted(EXCLUDED_DIRS)))
    lines.append("")
    lines.append("## Top-Level Counts")
    summary_rows = [[f"`{k}`", str(v)] for k, v in sorted(top_counts.items())]
    lines.append(md_table(["Top-Level Segment", "File Count"], summary_rows))
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def generated_docs_payload(
    routes: Sequence[RouteEntry],
    entrypoints: Mapping[str, FrontendEntrypoint],
    manifest: Sequence[ManifestEntry],
) -> Dict[str, str]:
    return {
        "docs/generated/app_server_routes.md": render_app_server_routes_generated(routes),
        "docs/generated/frontend_entrypoints.md": render_frontend_entrypoints_generated(entrypoints),
        "docs/generated/file_manifest.md": render_manifest_generated(manifest),
    }


def scaffold_missing(templates: Mapping[str, str]) -> List[str]:
    created: List[str] = []
    for rel in sorted(templates):
        path = REPO_ROOT / rel
        if path.exists():
            continue
        write_text(path, templates[rel])
        created.append(rel)
    return created


def apply_write(templates: Mapping[str, str]) -> Tuple[List[str], List[str]]:
    created = scaffold_missing(templates)

    routes = parse_app_server_routes()
    entrypoints = parse_frontend_entrypoints()
    manifest = collect_manifest()
    path_functions, constants = parse_config_signals()
    package_info = parse_package_json()

    blocks = build_autogen_blocks(routes, entrypoints, path_functions, constants, package_info)
    generated_files = generated_docs_payload(routes, entrypoints, manifest)

    changed: List[str] = []

    for rel, payload in generated_files.items():
        if maybe_write_text(REPO_ROOT / rel, payload):
            changed.append(rel)

    for rel in sorted(module_specs().keys()):
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        src = read_text(path)
        dst = apply_auto_blocks(src, blocks)
        if dst != src:
            write_text(path, dst)
            changed.append(rel)

    return created, sorted(dict.fromkeys(changed))


def validate_docs_links() -> List[str]:
    broken: List[str] = []
    if not DOCS_ROOT.exists():
        return ["docs/ directory does not exist."]
    md_files = sorted(DOCS_ROOT.rglob("*.md"))
    for md in md_files:
        text = read_text(md)
        for link in MD_LINK_RE.findall(text):
            target = link.strip()
            if not target:
                continue
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if target.startswith("#"):
                continue
            target = target.split("#", 1)[0].strip()
            if not target:
                continue
            resolved = (md.parent / target).resolve()
            if not resolved.exists():
                broken.append(f"{to_posix(md.relative_to(REPO_ROOT))}: broken link -> {link}")
    return broken


def extract_manual_section(text: str, section: str) -> Optional[str]:
    pattern = re.compile(
        rf"^## {re.escape(section)}\n<!-- MANUAL:BEGIN -->\n(?P<body>.*?)\n<!-- MANUAL:END -->",
        flags=re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        return None
    return match.group("body").strip()


def validate_frontend_purpose_sections() -> List[str]:
    issues: List[str] = []
    for meta in FRONTEND_DOC_META.values():
        rel = str(meta["doc"])
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        body = extract_manual_section(read_text(path), "Purpose")
        if body is None:
            continue
        nonblank_lines = [line for line in body.splitlines() if line.strip()]
        if len(nonblank_lines) > FRONTEND_PURPOSE_MAX_LINES or len(body) > FRONTEND_PURPOSE_MAX_CHARS:
            issues.append(
                f"{rel}: Purpose section is too long "
                f"({len(nonblank_lines)} lines, {len(body)} chars; "
                f"limit {FRONTEND_PURPOSE_MAX_LINES} lines / {FRONTEND_PURPOSE_MAX_CHARS} chars)"
            )
    return issues


def run_check(templates: Mapping[str, str]) -> Tuple[int, List[str]]:
    issues: List[str] = []

    for rel in sorted(templates):
        if not (REPO_ROOT / rel).exists():
            issues.append(f"Missing required file: {rel}")

    routes = parse_app_server_routes()
    entrypoints = parse_frontend_entrypoints()
    manifest = collect_manifest()
    path_functions, constants = parse_config_signals()
    package_info = parse_package_json()

    blocks = build_autogen_blocks(routes, entrypoints, path_functions, constants, package_info)
    generated_files = generated_docs_payload(routes, entrypoints, manifest)

    for rel, expected in generated_files.items():
        path = REPO_ROOT / rel
        if not path.exists():
            issues.append(f"Missing generated file: {rel}")
            continue
        actual = read_text(path)
        if actual != expected:
            issues.append(f"Generated file is stale: {rel}")

    for rel, spec in module_specs().items():
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        actual = read_text(path)
        labels = set(extract_auto_labels(actual))
        required = set(spec.auto_sections.values())
        missing_labels = sorted(required - labels)
        for label in missing_labels:
            issues.append(f"Missing AUTO-GEN label `{label}` in {rel}")
        expected = apply_auto_blocks(actual, blocks)
        if expected != actual:
            issues.append(f"AUTO-GEN blocks are stale: {rel}")

    issues.extend(validate_docs_links())
    issues.extend(validate_frontend_purpose_sections())
    return (1 if issues else 0), issues


def print_list(title: str, items: Iterable[str]) -> None:
    print(title)
    for item in items:
        print(f"- {item}")


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="ArcRho documentation index builder")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scaffold-missing", action="store_true", help="Create missing docs skeleton files")
    group.add_argument("--write", action="store_true", help="Update generated docs and AUTO-GEN blocks")
    group.add_argument("--check", action="store_true", help="Check if docs are up-to-date")
    args = parser.parse_args(argv)

    templates = scaffold_templates()

    if args.scaffold_missing:
        created = scaffold_missing(templates)
        if created:
            print_list("Created files:", created)
        else:
            print("No missing files.")
        return 0

    if args.write:
        created, changed = apply_write(templates)
        if created:
            print_list("Created files:", created)
        if changed:
            print_list("Updated files:", changed)
        else:
            print("No changes.")
        return 0

    code, issues = run_check(templates)
    if code == 0:
        print("Documentation is up-to-date.")
        return 0
    print_list("Documentation check failed:", issues)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
