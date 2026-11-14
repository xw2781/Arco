# ArcRho API Agent Reference

## Package Scope

The package lives under `python-api/` and imports as `arcrho_api`.

Phase one covers:

- ArcRho Server root validation.
- Project listing/opening.
- Reserving-class scoped access.
- DFM method discovery, load, create, mutate, and save.
- Production DFM helper methods used by reserve-review notebooks.

Phase one does not cover full dataset generation, Excel preview automation, RPC bridge orchestration, BF/Cape Cod/Result Selection APIs, or full Vector/Triangle editing.

## Public Entry Points

```python
from arcrho_api import ArcRhoClient

client = ArcRhoClient()
project = client.project("Project Name")
rc = project.reserving_class(r"Segment\Path")
dfm = rc.dfm("Method Name")
```

`ArcRhoClient()` uses the default server root resolved by `arcrho_api.config`, the canonical owner of that resolution: the `ARCRHO_SERVER_ROOT`/`ARCRHO_RUNTIME_SERVER_ROOT` environment overrides, then the ArcRho host app config file `%APPDATA%\Arco\workspace_paths.json`, then the running ArcRho desktop app's own workspace root, then the packaged default `E:\Arco Server` when it holds a `projects` folder. Use `set_server_root(path)` to update that shared host config, `get_server_root()` to inspect it, `reload_server_root()` to retry app discovery, or pass `ArcRhoClient(path)` for a one-off explicit root.

Legacy migration:

```python
from arcrho_api.migration import ArcRhoSession

session = ArcRhoSession()
session.set_project("Project Name")
session.set_reserving_class(r"Segment\Path")
dfm = session.DFM("Method Name")
```

## Gateway Client

`arcrho_api.gateway.GatewayClient` sends the same signed reads, mutations and hosted saves the desktop app sends, using the running user's own Gateway credential (`%APPDATA%\Arco\arcrho_gateway.json`). Arco does not need to be open, the save runs the canonical server-side service including its dependent walk, and the audit log records the script's user. Prefer it over the local app URL in `arcrho_api.ui` for data work: on a shared machine that URL can reach another user's app, which then saves under their name.

```python
from arcrho_api.gateway import GatewayClient

gateway = GatewayClient()
rs = gateway.read("result_selection_load", project_name=p, reserving_class=rc, method_name=name)
gateway.save("result_selection_method", p, rc, rs["method"], rs["sidecar"]["notes"], rs["method_revision"])
```

`read` and `mutate` take any kind registered in `arcrho_workspace_read_contract` and `arcrho_workspace_mutation_contract`; `save` takes any `SAVE_JOB_KINDS` entry with the service's arguments after the project and reserving class. A refusal raises `GatewayError` carrying the HTTP status, such as 423 while a dependent walk holds the class (poll the `propagation_busy` read before saving).

## DFM JSON Contract

The canonical grouped GUI shape is self-contained:

```text
json format = arcrho-dfm-method-by-tab-v2
details tab
data tab
ratios tab
results tab
method metadata
```

`details tab.name` is the method-file identity, `details tab.output dataset` is the output CSV/sidecar identity, and `details tab.output type` is the Vector Dataset Type. DFM notes are stored only in the declared output dataset sidecar's top-level `notes` field, not in method JSON. That field is the rendered text every reader sees; when the note was written with `{...}` placeholders in the app, the sidecar's `notes_source` holds the raw text behind it. `DfmMethod.notes` reads the rendered text and `DfmMethod.notes_source` the raw one; `update_notes()` replaces the notes and drops the source, `add_notes()` appends its plain text to both.

V2 embeds the complete input triangle snapshot, Ratio Basis snapshot, calculated ratio/average state, ultimate vector, formatting, and source revisions. It does not persist absolute input/output CSV paths. Ratio-cell notes remain in method JSON; Method Notes, Audit, status, and dependency graph remain in the output sidecar.

Save behavior:

- Normalize and recalculate through `arcrho_api.dfm_contract`.
- Update `method metadata.last modified` only for owned user changes and keep a separate `data refreshed` timestamp.
- Maintain independent owned, derived, and publication revisions.
- Write with a temporary file and atomic replace.
- Rebuild each reserving-class folder's `index.json`.
- Refuse writes when the client is `read_only=True`.
- Refresh dependent DFM v2 methods and expose refreshed output identities and nonblocking branch warnings through `DfmMethod.refreshed_dfm_outputs`, `DfmMethod.propagation_warnings`, `TriangleCacheResult.refreshed_dfm_outputs`, and `TriangleCacheResult.propagation_warnings`.

The standalone package does not contain the app server's calculated-dataset or Result Selection evaluators. If a DFM propagation wave reaches either method type, the public API preserves its current publication, marks the branch Review Needed, and returns a warning. The complete DFM -> calculated dataset -> Result Selection cascade runs in the app-server workflow.

DFM cell notes use the grouped `ratios tab.cell notes` shape keyed by visible row label, then visible development label. Use `set_cell_note(row_label, development, note)`, `clear_cell_notes_for_development(development)`, or `set_selected_average_cell_note(development, note, clear_column=True)` for average-formula notes.

User Entry formulas store the cached numeric value and authoritative formula text in aligned `average formulas.values` and `average formulas.inputs`. The canonical payload also carries aligned `average formulas.display inputs` for display-only dataset axis labels; calculations and dependency parsing must continue to use `inputs`. Use `set_user_formula(formula, value, development)` to write the calculation fields so the GUI shows the same calculated User Entry value while retaining the decomposed formula.

## Filename Rules

DFM methods are stored as:

```text
projects/<project>/data/<ReservingClassFolder>/methods/DFM@<Name>.json
```

ArcRhoTri dataset CSV files live under:

```text
projects/<project>/data/<ReservingClassFolder>/datasets/<DatasetName>.csv
```

Dataset sidecar metadata lives under:

```text
projects/<project>/data/<ReservingClassFolder>/sidecars/<DatasetName>.json
```

The reserving-class filename component uses `^` for Windows-invalid filename characters. The method-name component uses `_` for invalid filename characters.

## ArcBot Agent Helper

ArcBot should prefer one bundled inspection call for DFM read/planning work:

```powershell
python -m arcrho_api.agent --file active-method.json inspect --include summary,average-formulas
python -m arcrho_api.agent --file active-method.json inspect --include summary,average-formulas,ratio-triangle --origin 2020
```

The `inspect` command returns `DfmMethod.agent_inspect` with requested components and optional ratio rows in one JSON payload. Use edit helpers such as `exclude-ratio`, `include-ratio`, `select-average`, or `set-user-entry` only when modifying the temp file, then run `validate` after an edit. Avoid repeated `summary` or `component` reads in the same ArcBot turn.

## Testing

From repo root:

```powershell
python python-api\tools\run_with_timeout.py --timeout 115 -- python -m unittest discover -s python-api\tests
```
