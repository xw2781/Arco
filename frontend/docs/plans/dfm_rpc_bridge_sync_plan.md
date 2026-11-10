# DFM RPC Bridge Sync Request System Plan

Version: v0.4
Last updated: 2026-05-10

---

## 1. Goal

Add a DFM-level sync workflow that sends the current DFM method context to the data-engine through the existing request-file bridge, waits for a returned method JSON, compares it with the local method JSON, and presents one contextual action based on which version is newer.

The feature should start from a new Sync button in `dfmTabBar`.

---

## 2. Existing System Context

Relevant current behavior:

1. Dataset Viewer already sends bridge request files through app-server routes under `/arcrho/tri`.
2. The backend builds a flat `Function = ArcoTri` JSON request, writes a `.json` request file under the configured requests directory, and waits for the expected data file.
3. DFM method save/load already persists the core method JSON locally under:

   ```text
   <server_root_path>\projects\<project_name>\methods\<DFM method filename>.json
   ```

4. Current DFM method JSON already includes:

   ```json
   {
     "json format": "arcrho-dfm-method-by-tab-v1",
     "details tab": {
       "name": "",
       "output type": "",
       "input triangle": "",
       "origin length": 12,
       "development length": 12,
       "decimal places": 4
     },
     "data tab": {
       "origin labels": [],
       "development labels": [],
       "input data triangle values": [],
       "input data triangle csv path": ""
     },
     "ratios tab": {
       "ratio triangle": {
         "origin labels": [],
         "development labels": [],
         "ratio values": [],
         "excluded": []
       },
       "average formulas": {
         "label": [],
         "custom average formula settings": {
           "averageType": [],
           "base": [],
           "periods": [],
           "exclude": []
         },
         "selected": [],
         "values": []
       }
     },
     "results tab": {
       "ultimate vector": [],
       "ultimate ratio decimal places": 2,
       "ratio basis dataset": ""
     },
     "method metadata": {
       "last modified": ""
     }
   }
   ```

5. DFM local method JSON filenames are name-only within a project/reserving-class pair:

   ```text
   DFM@<reserving_class_path_with_caret_separators>@<DFM Name>.json
   ```

   Origin Length and Development Length are stored inside the local method JSON under the canonical keys `origin length` and `development length`. A DFM instance is identified solely by `Name` within the selected project/reserving-class pair, so the same Name cannot represent multiple DFMs with different period lengths or input triangles.

RPC bridge response and status filenames remain length-qualified because the remote data-engine request contract still expects the requested period lengths in the expected return path:

```text
DFM@<reserving_class_path_with_caret_separators>@<DFM Name>@<origin_length>@<development_length>.json
```

Old local DFM filenames and JSON files are explicitly out of scope.

---

## 3. Proposed User Workflow

1. User opens a DFM tab.
2. User clicks Sync in `dfmTabBar`.
3. If the current DFM tab has unsaved edits, frontend asks whether to save and proceed:
   - Save and Proceed: save the current local method JSON, then continue sync.
   - Cancel: stop sync and leave local state unchanged.
4. Frontend gathers the full Details page state:
   - Project
   - Reserving Class
   - DFM Name
   - Output Vector
   - Input Triangle
   - Origin Length
   - Development Length
   - Decimal Places
5. Frontend calls a new backend route to create a request file in:

   ```text
   <server_root_path>\requests\RPC bridge
   ```

6. Backend writes a request file similar to Dataset Viewer request files. The request includes Details page fields plus `DataPath`.
7. Backend waits for the expected returned JSON in:

   ```text
   <server_root_path>\projects\<project_name>\methods\RPC bridge\<DFM method filename>.json
   ```

8. When returned JSON appears, backend compares local and remote file metadata and returns:
   - Local path
   - Local `last modified` timestamp from JSON
   - Remote path
   - Remote `last modified` timestamp from JSON
   - Which file appears latest
   - Whether either file is missing
9. Frontend shows a draggable and resizable floating compare window with Local/Remote Server version cards. The cards resize with the window, their snapshot content scrolls internally when space is tight, and the Notes preview expands vertically from its 42px minimum height up to 300px when extra space is available. Local always appears on the left and Remote Server always appears on the right, while the `NEW` seal is based on JSON `last modified` timestamps:
   - Each card shows the source side (`Local` or `Remote Server`) in a top-left framed label with dark blue border and light blue fill, `last modified` timestamp, ratio selection snapshot, average formula names, and notes preview. JSON file paths are not shown in the comparison window.
   - The newer card shows a `NEW` seal instead of a warning banner.
   - Excluded ratio-triangle snapshots preserve `0`/`1`/`2` values; `2` cells are masked, cells use a wide rectangular shape, common exclusions are dark grey, exclusions added in the new version are green only on the new card, exclusions removed from the old version are red only on the old card, the green legend appears only on the new card, the red legend appears only on the old card, and each visible cell tooltip shows the same origin/development labels used by the Ratios triangle table.
   - Notes snapshots highlight deleted text from the older source with a red background and newly added text from the newer source with a green background.
   - User can select either `Local` or `Remote Server`.
   - If the selected version is local, the primary button says `Keep Using Local` and the app keeps the local JSON unchanged without sending `Function = SyncDFM`.
   - If the selected version is remote, the primary button says `Use Remote Version` and the app sends `Update Local DFM`.
   - After the user chooses either version action, the comparison window closes and a smaller same-style DFM Sync message box shows waiting/final status.
   - If JSON `last modified` timestamps are equal: show `Local and remote are already in sync` and no primary action.
   - If remote JSON is missing: tell the user the remote DFM JSON is missing and show no primary action.
10. User confirms the contextual action:
   - `Keep Using Local`: keep the local JSON unchanged and delete the returned remote RPC JSON; do not send a `Function = SyncDFM` request.
   - `Update Local DFM`: overwrite local JSON with remote JSON, then reload/apply the method into the current DFM tab.
11. Backend deletes the RPC bridge JSON file immediately after the user confirms a final local/remote action.
12. App marks the DFM state clean after successful overwrite and reload.

---

## 4. Request File Draft

Use flat JSON like the existing bridge requests. Proposed content:

```json
{
  "Function": "DFM",
  "ProjectName": "<project_name>",
  "Path": "<full_reserving_class_path>",
  "MethodName": "<DFM Name>",
  "OutputVector": "<output_vector>",
  "InputTriangle": "<input_triangle>",
  "OriginLength": 12,
  "DevelopmentLength": 12,
  "DecimalPlaces": 4,
  "DataPath": "<expected_remote_json_path>",
  "UserName": "<current_user>"
}
```

The initial `Function = DFM` request file should include Details page information plus `DataPath`. The `DataPath` value points to the expected remote DFM method JSON:

```text
<server_root_path>\projects\<project_name>\methods\RPC bridge\DFM@<full_reserving_class_path>@<DFM Name>@<origin_length>@<development_length>.json
```

Confirmed request function name: `DFM`.

`Function = SyncDFM` is retained only for explicit remote-update workflows. The `Keep Using Local` comparison action does not send this request.

```text
Function = SyncDFM
ProjectName = <project_name>
Path = <full_reserving_class_path>
MethodName = <DFM Name>
OutputVector = <output_vector>
InputTriangle = <input_triangle>
OriginLength = <origin_length>
DevelopmentLength = <development_length>
DecimalPlaces = <decimal_places>
DataPath = <expected_sync_status_json_path>
UserName = <current_user>
```

The `SyncDFM` expected return path should point to a status JSON whose filename starts with `SyncDFM`, for example:

```text
<server_root_path>\projects\<project_name>\methods\RPC bridge\SyncDFM@<full_reserving_class_path>@<DFM Name>@<origin_length>@<development_length>.json
```

The `SyncDFM` status JSON should include a message that tells the frontend whether the remote update passed or failed:

```json
{
  "ok": true,
  "status": "passed",
  "message": "Remote DFM status updated."
}
```

---

## 5. Returned JSON Contract Draft

The returned JSON from data-engine should be accepted if it contains at least:

```json
{
  "json format": "arcrho-dfm-method-by-tab-v1",
  "ratios tab": {
    "ratio triangle": {
      "excluded": [[1, 0], [1, 1]]
    },
    "average formulas": {
      "label": ["Volume - all"],
      "custom average formula settings": {
        "averageType": ["custom"],
        "base": ["volume"],
        "periods": ["all"],
        "exclude": [0]
      },
      "selected": [[1, 1]]
    }
  },
  "method metadata": {
    "last modified": "2026-05-10T12:00:00.000Z"
  }
}
```

Recommended canonical full payload:

```json
{
  "json format": "arcrho-dfm-method-by-tab-v1",
  "details tab": {
    "name": "",
    "output type": "",
    "input triangle": "",
    "origin length": 12,
    "development length": 12,
    "decimal places": 4
  },
  "data tab": {
    "origin labels": [],
    "development labels": [],
    "input data triangle values": [],
    "input data triangle csv path": ""
  },
  "ratios tab": {
    "ratio triangle": {
      "origin labels": [],
      "development labels": [],
      "ratio values": [],
      "excluded": []
    },
    "average formulas": {
      "label": [],
      "custom average formula settings": {
        "averageType": [],
        "base": [],
        "periods": [],
        "exclude": []
      },
      "selected": [],
      "values": []
    }
  },
  "results tab": {
    "ultimate vector": [],
    "ultimate ratio decimal places": 2,
    "ratio basis dataset": ""
  },
  "method metadata": {
    "last modified": ""
  }
}
```

Use only the canonical DFM method JSON keys shown above. `average formulas` is the persisted formula row identity/metadata object; `summary rows`, `summary order`, and `summary hidden` are not part of the contract. Old files and alias spellings are intentionally out of scope.

---

## 6. Backend Design

Add new files instead of putting feature logic into existing service files:

1. `frontend/app_server/schemas/dfm_rpc_bridge.py`
   - Pydantic request/response schemas.
   - Input validation for project, reserving class, method name, lengths, and timeout.

2. `frontend/app_server/services/dfm_rpc_bridge_service.py`
   - Build local method path.
   - Build remote RPC bridge method path.
   - Build remote SyncDFM status path.
   - Build and write request file under `config.REQUEST_DIR\RPC bridge`.
   - Wait for expected returned JSON.
   - Keep local JSON unchanged and delete the returned remote RPC JSON when the user confirms `Keep Using Local`.
   - Read file metadata and JSON `last modified` metadata.
   - Compare JSON `last modified` timestamps.
   - Copy the remote version over local method JSON with an atomic replace when the user confirms `Update Local DFM`.
   - Delete the remote RPC bridge JSON after the final user action.

3. `frontend/app_server/api/dfm_rpc_bridge_router.py`
   - Thin FastAPI router.
   - Routes:

     ```text
     POST /dfm/rpc-bridge/sync
     POST /dfm/rpc-bridge/compare
     POST /dfm/rpc-bridge/apply
     POST /dfm/rpc-bridge/keep-local
     POST /dfm/rpc-bridge/update-remote
     ```

4. `frontend/app_server/api/__init__.py` or current router registration point
   - Include the new router.

Backend route behavior:

1. `POST /dfm/rpc-bridge/sync`
   - Writes request file.
   - Waits for remote JSON until timeout.
   - Returns comparison metadata.
   - Includes `DataPath` in the request file.

2. `POST /dfm/rpc-bridge/compare`
   - Does not send a request.
   - Recomputes paths and returns current local/remote JSON `last modified` timestamps.

3. `POST /dfm/rpc-bridge/apply`
   - Copies remote JSON over local JSON after `Update Local DFM`.
   - Returns updated local JSON payload for frontend reload.
   - Deletes the remote RPC bridge JSON after the action completes.

4. `POST /dfm/rpc-bridge/update-remote`
   - Writes a new `Function = SyncDFM` request file using Details page fields plus `DataPath`.
   - `DataPath` points to an expected status JSON whose filename starts with `SyncDFM`.
   - Waits for the `SyncDFM` status JSON until timeout.
   - Returns the request file path, status JSON path, pass/fail flag, and status message.
   - Deletes the existing remote RPC bridge JSON after the action completes.

5. `POST /dfm/rpc-bridge/keep-local`
   - Does not write a request file.
   - Keeps local JSON and current in-app DFM state unchanged.
   - Deletes the existing remote RPC bridge JSON after the action completes.

Path rules:

1. Use `app_server.config` for root, projects, and requests locations.
2. Do not hard-code `E:\Arco Server`.
3. Create `requests\RPC bridge` and `methods\RPC bridge` if needed.
4. Use existing DFM filename sanitization rules with the standardized filename order `@<origin_length>@<development_length>`.
5. Update existing local DFM filename helpers to use the same standardized order. Do not add migration fallback for old filenames.

---

## 7. Frontend Design

Add new files instead of placing new feature logic into existing DFM files:

1. `frontend/ui/method_pages/dfm/dfm_rpc_bridge_client.js`
   - Build Details page snapshot.
   - Call backend sync/compare/apply routes.
   - Reuse current DFM path/name/length helper exports where possible.
   - If the DFM tab is dirty, ask the user whether to save and proceed before sending the request.

2. `frontend/ui/method_pages/dfm/dfm_rpc_bridge_dialog.js`
   - Floating compare window.
   - Shows local and remote JSON `last modified` timestamps, with Local on the left and Remote Server on the right.
   - Shows a `NEW` seal on the latest version card.
   - Shows excluded ratio-triangle differences with masked `2` cells, dark grey common exclusions, green newly excluded cells on the new card, and red removed exclusions on the old card.
   - Closes the large comparison window after a version action is selected and shows a smaller same-style DFM Sync message box for waiting/final status.
   - Buttons: one contextual primary action, Refresh, Cancel.
   - Primary label proposal:
     - `Keep Using Local` when local JSON is newer.
     - `Use Remote Version` when remote JSON is newer.

3. `frontend/ui/method_pages/dfm/dfm_rpc_bridge_tabbar.js`
   - Creates and wires the Sync button in `dfmTabBar`.
   - Keeps tab bar UI changes isolated.

4. Optional: `frontend/ui/method_pages/dfm/dfm_rpc_bridge.css`
   - Only if the dialog styling grows enough to justify a separate stylesheet.

Minimal changes to existing files:

1. `frontend/ui/method_pages/dfm/dfm.html`
   - Include a stable mount point or import the new pathbar module.
   - If possible, do not add large inline CSS.

2. `frontend/ui/method_pages/dfm/dfm_main.js` or `frontend/ui/method_pages/dfm/dfm_tabs_orchestrator.js`
   - Import and initialize the new pathbar module.

3. `frontend/ui/method_pages/dfm/dfm_persistence.js`
   - Export a small reusable `applyDfmMethodPayload(payload, options)` helper if current load logic cannot be reused cleanly from the new file.
   - Keep the new RPC UI code out of persistence.
   - Update local DFM save/load filename generation from `@<development_length>@<origin_length>` to `@<origin_length>@<development_length>`.

Preferred reload strategy after remote overwrite:

1. Backend returns the remote JSON payload after copying it over local.
2. Frontend applies that payload using the same logic used by existing DFM local load.
3. Frontend rerenders ratios/results/notes and posts a status message.
4. Backend deletes the remote RPC bridge JSON after the final action completes.

Preferred keep-local strategy when local is newer:

1. Frontend asks the user to confirm `Keep Using Local`.
2. Backend deletes the stale remote DFM RPC bridge JSON.
3. Backend does not write a `Function = SyncDFM` request.
4. Frontend leaves local JSON and in-app DFM state unchanged.
5. Frontend shows a final kept-local status message.

---

## 8. Timestamp Comparison

Use the canonical `last modified` property inside each DFM JSON file. Local DFM JSON writes this value on each GUI save event. Remote DFM JSON is expected to include the same key from data-engine. Filesystem modified times may still be returned as secondary metadata, but they do not decide which version is latest.

Comparison states:

1. `remote_latest`: remote file exists and remote JSON `last modified` > local JSON `last modified`.
2. `local_latest`: local file exists and local JSON `last modified` > remote JSON `last modified`.
3. `same_time`: both exist and JSON `last modified` timestamps are equal within a small tolerance; show `Local and remote are already in sync` in the floating UI with no primary action.
4. `remote_missing`: local exists, remote missing; tell the user the remote DFM JSON is missing and show no primary action.
5. `local_missing`: should not occur because the app saves the current DFM tab before proceeding. Treat it as an error if encountered.
6. `both_missing`: should not occur after save-and-proceed. Treat it as an error if encountered.

UI should display both:

1. Raw path
2. Localized `last modified` timestamp text
3. Latest/missing state

---

## 9. Validation and Error Handling

Backend should return clear 4xx/5xx errors:

1. `400`: missing Details page fields.
2. `404`: project folder not found.
3. `408` or success payload with `status = "timeout"`: request sent but remote JSON did not appear in time.
4. `409`: invalid comparison/apply state or filename collision.
5. `423`: local or remote file locked.
6. `500`: invalid JSON or unexpected filesystem failure.

Frontend should:

1. Disable Sync while one sync is running.
2. Show elapsed wait state.
3. Keep existing dirty-state semantics.
4. If the current DFM tab is dirty, ask the user whether to save and proceed before creating the request.
5. Reload/apply data only after backend confirms write success.

---

## 10. Documentation and Release Updates

Implementation should also update:

1. `frontend/docs/ui/dfm.md`
   - Add manual behavior for DFM RPC Bridge Sync.

2. `frontend/docs/app_server/domains/dfm_rpc_bridge.md`
   - New backend domain doc for routes and file contracts.

3. `frontend/docs/runtime/config_paths.md`
   - Document `requests\RPC bridge` and `methods\RPC bridge`.

4. `frontend/changes/unreleased/<date>-dfm-rpc-bridge-sync.json`
   - User-facing release fragment.

5. Generated docs indexes:

   ```text
   python tools/docs_index_builder.py --write
   python tools/docs_index_builder.py --check
   ```

---

## 11. Test Plan

Backend tests:

1. Path construction for local and remote method JSON.
2. Request file content and target folder, including `DataPath`.
3. Timeout behavior when remote JSON is absent.
4. JSON `last modified` comparison states.
5. Remote-to-local overwrite with invalid/locked/missing files.
6. Local-newer flow calls `keep-local` without writing a `Function = SyncDFM` request.
7. RPC bridge JSON deletion after `Keep Using Local` and `Update Local DFM` actions.
8. Local DFM filename generation uses `DFM@<ReservingClass>@<Name>.json`.

Frontend tests/manual verification:

1. Sync button appears in `dfmTabBar` and does not disturb tab selection.
2. Click sends expected request payload.
3. Floating compare window shows local and remote JSON `last modified` timestamps.
4. When local JSON is newer, primary button label is `Keep Using Local`.
5. When remote JSON is newer, primary button label is `Use Remote Version`.
6. `Keep Using Local` leaves local JSON unchanged, deletes the remote RPC JSON, and does not send `Function = SyncDFM`.
7. `Update Local DFM` overwrites local JSON and updates ratios, averages, and notes in the current DFM tab.
8. Dirty local DFM changes trigger a save-and-proceed prompt before request creation.
9. Request files contain Details page fields plus `DataPath`.
10. Equal `last modified` timestamp state shows `Local and remote are already in sync` with no primary action.
11. Remote-missing state tells the user the remote DFM JSON is missing with no primary action.

---

## 12. Implementation Phases

Phase 1: Backend bridge foundation

1. Add schema/service/router files.
2. Register router.
3. Add backend unit tests or compile-level validation.

Phase 2: Frontend sync UI

1. Add pathbar Sync button module.
2. Add client module for backend routes.
3. Add floating compare dialog module.
4. Reuse or extract DFM method apply logic.

Phase 3: Docs and verification

1. Update DFM UI and backend docs.
2. Add release fragment.
3. Run docs index builder.
4. Run available tests and app smoke checks.

---

## 13. Confirmed Decisions

Confirmed for implementation:

1. Request file uses `Function = DFM`.
2. DFM method JSON filenames always use `@<origin_length>@<development_length>`.
3. Existing local DFM filename generation will be changed to the same order.
4. Old local DFM filenames and JSON alias keys are not supported by this feature.
5. If current DFM tab is edited but unsaved, ask whether to save and proceed.
6. Initial `Function = DFM` request file includes Details page fields plus `DataPath`.
7. RPC bridge JSON file is deleted immediately after the final user action in the UI.
8. Version selection is replaced by one contextual action button:
   - `Keep Using Local` when local JSON is newer.
   - `Use Remote Version` when remote JSON is newer.
9. `Keep Using Local` does not send `Function = SyncDFM`; it keeps local JSON unchanged and deletes the remote RPC JSON.
10. Equal `last modified` timestamps show `Local and remote are already in sync` with no primary action.
11. Remote-missing state only informs the user; no action is shown.
12. Local JSON should never be missing because the app saves the current DFM tab before proceeding.

Remaining implementation assumptions:

1. Keep caret replacement for reserving class paths in filenames because raw backslashes cannot be filename characters on Windows.
2. Use an 8-second default wait timeout.
3. Show the floating compare window immediately with a waiting state.
4. Returned DFM JSON uses canonical keys only; old files and alias spellings are intentionally out of scope.
5. Keep request `.json` files for audit/debug; only delete the returned RPC bridge JSON.

---

## 14. Implementation Defaults

Use these defaults unless changed before implementation:

1. Use `Function = DFM`.
2. Use local and remote DFM filename order `@<origin_length>@<development_length>`.
3. Use existing DFM filename sanitization with caret-separated reserving class paths.
4. Use an 8-second timeout for DFM RPC sync.
5. Prompt to save and proceed when the current DFM tab has unsaved edits.
6. Include Details page fields plus `DataPath` in request files.
7. Use one contextual primary button instead of separate version-selection buttons:
   - `Keep Using Local` for local-newer comparisons.
   - `Use Remote Version` for remote-newer comparisons.
8. `Keep Using Local` leaves local JSON unchanged, deletes the remote RPC JSON, and does not send `Function = SyncDFM`.
9. `Update Local DFM` overwrites local JSON with the returned remote JSON and reloads the current DFM tab.
10. Show the floating window immediately with waiting state, then update it when remote JSON arrives.
11. Returned DFM JSON uses canonical keys only; old files and alias spellings are intentionally out of scope.
12. Keep request `.json` files for audit/debug and delete the returned RPC bridge JSON after final user action.
13. Equal `last modified` timestamps show `Local and remote are already in sync` with no primary action.
14. Remote-missing state tells the user the remote DFM JSON is missing with no primary action.
