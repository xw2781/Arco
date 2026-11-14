# ArcRho Python API

`arcrho-api` is a first-party Python package for scripting ArcRho project and DFM workflows against an ArcRho Server root folder.

```python
from arcrho_api import ArcRhoClient

client = ArcRhoClient()
project = client.project("Current Reserve Review")
rc = project.reserving_class(r"Auto\Private Passenger")

dfm = rc.dfm("Paid Loss Ultimate")
dfm.clear()
dfm.exclude_covid_years()
dfm.set_selected_average("Simple - 3")
dfm.set_selected_average_cell_note(1, "Selected before adjustments.", clear_column=True)
dfm.save()
```

The package resolves the same server root the ArcRho host app uses, in this order: the `ARCRHO_SERVER_ROOT`/`ARCRHO_RUNTIME_SERVER_ROOT` environment overrides, the host config file `%APPDATA%\Arco\workspace_paths.json`, the workspace root reported by the running ArcRho desktop app, and finally the packaged default `E:\Arco Server` when it exists and holds a `projects` folder. The last two steps are tried once per process; call `reload_server_root()` to retry them. Because the host config file is only written when a user saves ArcRho Server Connection, a fresh client install resolves through the running app instead of failing. You can still pass a root explicitly, or update the shared host config from Python:

```python
from arcrho_api import ArcRhoClient, get_server_root, set_server_root

set_server_root(r"E:\Arco Server")
print(get_server_root())
client = ArcRhoClient()
```

The package is read/write by default, but writes are explicit: mutations stay in memory until `save()` is called. Use `read_only=True` for audit/exploration workflows.

```python
client = ArcRhoClient(r"E:\Arco Server", read_only=True)
```

For legacy notebook migration, `ArcRhoSession` provides a context-bound style with familiar names:

```python
from arcrho_api.migration import ArcRhoSession

session = ArcRhoSession(r"E:\Arco Server")
session.set_project("Current Reserve Review")
session.set_reserving_class(r"Auto\Private Passenger")

dfm = session.DFM("Paid Loss Ultimate")
dfm.ex_COVID_AY()
dfm.set_selected_estimate("Simple - 3")
dfm.save()
```

## UI Automation Helpers

When the ArcRho app is running locally, Python macros, notebooks, and external scripts can send typed UI commands to the shell:

```python
from arcrho_api import ArcRhoUI

ui = ArcRhoUI()
ui.wait_for_app(timeout_sec=10)
ui.message_box("Notebook started.", title="ArcRho UI Automation")
progress = ui.progress_bar(title="Long Import", total=3, label="Importing datasets")
progress.update(completed=1, label="Imported Paid Loss")
window = ui.project_instance.open_dataset("Paid Loss")
window.maximize()
print(window.properties.as_dict())
window.restore()
ui.project_instance.reload_dataset_table()
progress.close(auto_close_ms=1000)
```

UI automation targets active app state. For example, `open_dataset_in_active_project_instance(...)` requires an active Project Instance page with a reserving-class path selected.
The object-style API mirrors familiar COM automation patterns: `ArcRhoUI().project_instance.open_dataset(...)` returns an `ArcRhoWindow` with methods such as `activate()`, `maximize()`, `restore()`, `minimize()`, and `close()`, plus current-state properties such as `title`, `is_active`, `is_hidden`, `is_maximized`, and `is_dirty`. Use `ArcRhoUI().project_instance.reload_dataset_table()` after scripts write dataset files that the active Project Instance page should show immediately.
The app URL is resolved automatically: an explicit `ArcRhoUI(app_url=...)` argument wins, then the `ARCRHO_APP_URL` (or `ARCRHO_HOST`/`ARCRHO_PORT`) environment variables, then the per-user `%APPDATA%\Arco\app_endpoint.json` discovery file the desktop app writes at startup (which covers the case where the default port was taken and the app fell back to a free local port), and finally the default `http://127.0.0.1:28765`. That file lists every running app, newest first; the newest live one is used unless `ArcRhoUI(pid=...)`, `ArcRhoUI(port=...)` or the `ARCRHO_APP_PID` environment variable names another, and `arcrho_api.ui.running_apps()` lists them.

### Run a saved or unsaved macro source in the active ArcRho DFM

Arcode bundles `arcrho_api` and its own Python runtime, so users do not need a system Python installation. In a Python editor, use **Run** (or Ctrl+Enter). Arcode automatically executes source with an `<arcrho-macro>` metadata block or top-level `run_macro(...)` entry point against the live unsaved DFM in the open ArcRho window; other Python runs in Arcode's local session. The file can live anywhere and does not need to appear in ArcRho's Macro panel.

The same bridge is available programmatically:

```python
from arcrho_api import ArcRhoUI

ui = ArcRhoUI()
result = ui.macros.run_file(r"E:\My ArcRho Work\apply_growth_adjustments.py")
print(result["message"])
```

For an unsaved editor buffer, call `ui.macros.run_source(source, filename="draft.py", source_path=...)`. ArcRho captures the exact active DFM, runs the conventional `run_macro(active_dfm, active_context)` entry point (also accepting `main(...)`), then applies the returned/mutated payload only if the captured DFM is still open and unchanged. UI-only scripts can run with no active DFM and receive `active_dfm=None`; a returned DFM payload is rejected in that case. Source execution times out after 120 seconds without an activity heartbeat, and unchanged DFM state is not reapplied or marked dirty. Maintained macros can wrap trusted long-running service calls with the injected `run_trusted_macro_call()` helper to avoid per-line tracing overhead while using `check_macro_cancelled()` or `report_macro_activity()` at cooperative checkpoints. A script's saved parent folder is available for sibling imports. Third-party dependencies still need to be part of the packaged app runtime.

The `Import ResQ Reserving Class` macro requires at least one fresh Arco Engine heartbeat before it connects to ResQ or changes project data. Generated datasets are submitted to `<ArcRho Server>/requests` using the same request contract as the Excel add-in; the migration does not start or import a private data-engine. It publishes generated requests as a batch so the running worker pool can process them concurrently, then writes engine sidecars through the same `arcrho_api.engine_dataset_sidecar_contract` used by the frontend runtime and rebuilds the final reserving-class index. Engine-owned sidecars do not copy ResQ axis labels or formulas; cached frontend reads hydrate those values from the project header and Dataset Type contracts. The links they carry come from the same place the app's do: `resq_migration.catalog` reads every formula through `arcrho_api.dataset_type_contract`, so a dataset type the Engine builds from a formula over other types lists those types as its precedents and is listed as their dependent, exactly as `calculated_dataset_service.sidecar_graph_fields` writes it. A generated formula's precedents are filtered to the instances the reserving class holds, because the Engine rebuilds it from the source table rather than from those caches; an app-calculated dataset keeps naming a missing input. `frontend/tests/test_engine_dataset_sidecar_contract.py` pins the two producers to the same full payload.

ArcBot uses the same package through a compact command helper. For DFM inspection, prefer the bundled `inspect` command so summary, components, and optional ratio rows are returned in one call:

```powershell
python -m arcrho_api.agent --file active-method.json inspect --include summary,average-formulas,ratio-triangle --origin 2020
```

## Demo Data

The `ABC_Group_Quarterly_Review_202608` demo project takes its four import tables (Loss, Claim Counts, Premium, Exposure) from a seeded generator that ships with the package, so anyone can write them again byte for byte:

```powershell
python -m arcrho_api.demo_data.abc_group --output "C:\Temp\abc_tables" --seed 20260831
```

ABC Insurance Group is fictional: claims are simulated one by one with report and settlement lags, case reserves, ALAE, salvage and subrogation, and some states are entered late so their triangles are short. Shared shocks (by accident year, calendar year and month) and a heavy-tailed large-loss share give the triangles the development volatility of real data, and the vehicle lines carry the industry's COVID-19 pattern: the 2020 frequency drop, shelter-in-place premium paybacks, court-closure settlement delays and the later severity and theft surges. `tools/build_abc_group_demo_project.py` in the repository builds the project from these tables.

## Installing From ArcRho

This installation is only needed for external IDEs or Python environments. Arcode already includes the API and a compatible Python runtime.

ArcRho release builds ship a pip-installable wheel in the app resources folder:

```powershell
python -m pip install "<ArcRho install folder>\resources\python_packages\arcrho_api-0.2.1-py3-none-any.whl"
```

Development builds can create the same wheel without network access:

```powershell
python python-api\tools\build_wheel.py --out-dir python-api\dist
python -m pip install python-api\dist\arcrho_api-0.2.1-py3-none-any.whl
```

API-only releases can publish the wheel to the shared ArcRho Server packages folder without rebuilding the desktop app:

```powershell
python-api\tools\publish_package.bat --version 0.1.1
py -3.10 -m pip install --upgrade "E:\Arco Server\packages\arcrho_api-latest.whl"
```

Set `PYTHON_API_PACKAGE_DIR` or pass `--package-dir` to publish somewhere other than `E:\Arco Server\packages`.
