# Arco Excel Add-in

`Arco.xlam` is loaded from the Arco Server share, so every user runs the
version that is on the share. Version 4.0.0 reads saved Arco results from the
workbook and loads missing results when a formula is entered or edited. Server
requests use HTTP; no worksheet function reads project data from the share.

The VBA source of record is [`src_vba/`](src_vba); the `.xlam` is built from it.

## Saved workbook results

Use **Refresh Worksheet** or **Refresh Workbook** to fetch current results,
then save the workbook. Its hidden `_ArcRhoCache` sheet holds one result array
per distinct request, including headers and project settings, with the snapshot
format and refresh time. Existing worksheet formulas stay in place.

Another user can open the saved workbook and read the same results without
dataset requests, source freshness checks, or Engine calculations. Ordinary
Excel recalculation uses that workbook's snapshot; other spreadsheet formulas
continue to calculate normally.

Typing, editing, or pasting an Arco formula loads any missing request as soon
as the entry is complete and adds the result to the workbook snapshot. This
includes changing the formula's explicit project name. If the same request is
already saved, the formula uses it without contacting the server or enrolling
the PC. Use a Refresh command when you want to update those existing results.
Workbooks created before 3.0.0 need one successful refresh and save to acquire
a snapshot for their existing formulas.

Repeated requests share one fetched result during refresh. A failed or cancelled
refresh preserves the previous snapshot. Refresh Worksheet updates that sheet's
requests while retaining saved requests used elsewhere in the workbook. Save
the workbook after refreshing or adding formulas to share the new values.
Snapshot data contains no credentials or raw source tables.

Either Refresh command ends by recalculating every formula in the refreshed
workbook, so ordinary formulas that depend on Arco results show the new values
as well, whichever calculation mode the workbook uses. This costs the same as
pressing F9 with that workbook open; other open workbooks are not recalculated
beyond what F9 would already do.

## Writing Arco formulas

**Insert Function** on the ribbon opens a panel for writing any Arco formula.
Pick a function on the left; its arguments appear on the right, required ones
in bold, each with a one-line description and its default. Reserving-class
paths, dataset names (triangles or vectors, as the function needs), projects,
TRUE/FALSE, and period lengths are chosen from lists; typing into a list box
narrows it. Any argument can instead take a cell: type its address, or choose
**Select a cell...** at the top of its list. Start an entry with `=` to write
any other expression. The panel shows the finished formula and inserts it into
the selected cell, where it loads like a typed formula. Opened on a cell holding
an Arco formula, or on its spilled results, the panel loads that formula for
editing; **Load from cell** does the same for whichever cell is selected while
the panel is open, replacing what the panel holds. Excel's own function
dialog (fx) shows the same descriptions under **Arco Tools**.

The panel, **Select Datasets**, and **Load Reserving Classes** share one set of
lists read from the Arco Server in a single request: the project names, and
for a project its reserving classes that hold data and its dataset types. They
are kept for the Excel session, so a picker opened again fills at once; the
panel's **Refresh lists** reads them again. Load Reserving Classes offers, at
each level, only the values found under the levels chosen above it. **Connect
and Login** lists the server's projects on the settings sheet and turns
**Default Project Name** into a dropdown of them. A blank Default Project Name
becomes the latest project: the one with the newest Development End Date, and
among those the first registered, so an original wins over its later copies. Select Datasets and Load
Reserving Classes also update an `ArcoTriCell`, `ArcoTriDiag`, `ArcoTriOrigin`,
or `ArcoVecCell` formula in the selected cell, not only `ArcoTri` and `ArcoVec`.

## Repairing workbook references

The **Reset Add-in References** ribbon button opens a compact form for the active
workbook. Choose the target add-in from the dropdown, then **Update workbook**.
**Arco Excel add-in** is always the default and uses the mapped-drive release
location. **64-bit ResQ add-in** changes both the path and supported function
names to ResQ, using `C:\Program Files\Willis Towers Watson\ResQ\Addins\ResQ.xlam`.
ResQ is enabled only on `NE7SASWPN02`. On other PCs the option is muted with
"Only available on NE7SASWPN02", and the update routine rejects ResQ conversion.

The repair covers formulas on visible and hidden sheets and workbook- and
sheet-scoped defined names. It replaces supported `ResQ`, `ArcRho`, and `ADAS`
function names with `Arco` names, and retargets ResQ's 32/64-bit installation
paths, old UNC links, and beta links. Arguments, quoted text, table columns,
unrelated workbook links, and unsupported function names stay intact.
`ReferenceFormulaRepair.bas` owns the supported rename mapping;
`ReferenceRepair.bas` owns the default target and workbook update flow.

The existing progress window shows the sheet name and number, cells checked,
formula ranges found, and update progress. Formula discovery reads cells in
batches and handles each legacy array once. Cancel during scanning leaves all
formulas unchanged; cancel during updating reports how many changes were made.
The form has no preview or separate Close button; use its window X to dismiss it.
Protected sheets/names and legacy array formulas whose replacement exceeds
Excel's 255-character `FormulaArray` limit are reported without changing them.
Legacy array rectangles and dynamic spills are preserved. If an add-in with
the target filename is already loaded from a different location, load it from
the desired location first; Excel otherwise binds the formula to the open copy.

Updating recalculates the workbook from its saved data without starting a
server refresh. Use **Refresh Workbook** if the repaired formulas need data,
then save. The form does not save the workbook or install an add-in. Excel may
display a loaded add-in's formulas without a path; the chosen file remains in
the saved workbook's links.

The simplified form and ResQ target are available in add-in 4.1.1, released on September 21, 2026.
Restart Excel to load the shared release.

## Server refresh policy

- A dataset with a sidecar is read as published from the CSV named by the
  sidecar. Excel never rewrites that CSV or its metadata. Manual/input and
  generated datasets support coarser periods in memory with the same
  cumulative/calendar mode. A generated dataset asked for at a finer period, a
  non-multiple, or another mode is calculated by the Engine from its source
  table into a technical cache beside the publication, which stays as it is.
  Calculated and method outputs require their published shape, because
  aggregating a calculated ratio can change its meaning. A missing publication
  or an unsupported shape must be refreshed or corrected in the frontend; the
  message names the published and requested periods.
- A generated request without a sidecar reuses a matching technical cache while
  its source-table identity and processing configuration remain unchanged.
  Otherwise the server regenerates it without creating a permanent sidecar.
- Temporary calculated requests evaluate their formulas from published
  permanent inputs and current temporary inputs without publishing datasets.
- A propagation job covering the class asks the refresh to retry when the job
  has finished. Published values are the last successful publication; Excel
  does not repair a failed propagation job.

The old **always refresh** / `removeData` setting has been removed. Refresh
commands follow the server policy for every dataset.

## What this PC needs

- **The workspace share.** The add-in itself is loaded from it, and the shared
  library files listed at the end still come from it. Project data does not.
- **A credential for the Arco Server**, at
  `%APPDATA%\Arco\arcrho_gateway.json`. The add-in installs one for itself the
  first time an entered formula or a refresh needs server access, so reading a
  saved workbook needs no enrollment.

## The credential

The file holds this Windows user's name, the address of the Arco Server's
Gateway, and a secret. The helper gets it from the Gateway's sign-up route: the
Gateway proves who is asking with a Windows sign-in and answers with that
user's own secret only. The address is the one the desktop app keeps for its
production server, so a PC signs up once the app has been pointed at the server
(or with `--url <address>`). Nothing is read from the server's folder.

**It installs itself when server access is first needed.** When an entered
formula has no saved result, or a refresh starts, and no credential file exists,
the add-in runs `apps\Arco Credential\Arco Credential.exe`
from the share, hidden, and waits for it, with
`Setting this PC up to read Arco data ...` in the loading window. The whole
enrollment is paid once on a PC that has never had a credential. Opening and
recalculating a saved snapshot does not run the helper.

Three things about that first run are deliberate:

- It is tried **once per Excel session**. A PC away from the office pays one
  short enrollment failure, and never one per formula.
- It is skipped without a word when **the share cannot be reached**.
- A credential file that says `"enabled": false` is a **deliberate opt-out** and
  is left exactly as it is. A new data request reports that the PC is not
  configured; previously saved values remain available.

**On the rare PC where the first run does not work**, run the helper by hand from
a command prompt, handing it the workspace folder:

```
"\\Ne7saswpn02\e\Arco Server\apps\Arco Credential\Arco Credential.exe" "\\Ne7saswpn02\e\Arco Server"
```

It prints one line and exits non-zero when it installed nothing:

| Line | What it means |
| :--- | :--- |
| `ArcRho credential installed: <path>` | Done. Restart Excel, then refresh the workbook. |
| `ArcRho credential already present: <path>` | A credential file is already here and was left alone, whatever it says. |
| `ArcRho Server has no Gateway address for clients to use.` | The server is not yet configured to be reached by clients. Ask the Arco team. |
| `ArcRho credential not installed: <reason>` | The share or the Gateway could not be reached, or the registry could not be written. The reason is Windows' own. Nothing was written, so it is safe to try again. |

## Checking this PC

With the add-in loaded, run `CheckArcRhoGateway` in the Immediate window
(`Alt+F11`, then `Ctrl+G`). It signs one fixed request, then talks to the server
this PC is pointed at, and prints a line for each part:

| Line | What a working PC shows |
| :--- | :--- |
| `vector digest` | `match` |
| `vector signature` | `match` |
| `credential` | the user name and server address, or `none on this PC` |
| `health` | `200` |
| `capabilities` | `200` and the list of what this server serves |
| `signed request` | `400` — the signature was accepted and the deliberately unreadable request was then refused. `401` would mean the signature itself was refused. |

`cscript //nologo excel-addin\tools\verify_gateway_signing.vbs` checks the
signing half alone, without Excel and without sending anything.

## What each failure message means

### While loading or refreshing results

Refresh failures appear in Excel's status bar and preserve the previous
snapshot. A failed formula-entry load also leaves previously saved results
available. An existing formula absent from the snapshot during ordinary
recalculation displays
`(Arco: Refresh Worksheet or Refresh Workbook to load saved data.)`.

| Message | Cause and what to do |
| :--- | :--- |
| `This PC is not set up to load Arco data.` / `This PC is not set up to refresh Arco data.` | No usable credential on this PC: enrollment did not succeed, or the file says `"enabled": false`. Run the helper by hand as above, then restart Excel. |
| `Ask the Arco team to update the Arco Server.` | The server this PC reaches does not serve dataset figures over HTTP. The server has to be updated. |
| `(Arco Server not reached: <reason>)` | The request never arrived. The reason is Windows' own — a timeout, a refused connection, no network. `no answer` means the server closed the connection without a reply. |
| `(Arco Server <status>: <message>)` | The server answered and refused. The message is the server's own; the status says what kind of refusal it was. |
| `(Arco Server sent an answer this add-in could not read.)` | The reply was not the JSON the add-in expects, which usually means something other than the Arco Server answered on that address. |
| `(Arco Server answered without the dataset's figures.)` | The server accepted the request and reported success but sent no figures. |
| `Arco error <number>: <description>` | The add-in itself failed inside Excel, before or after the server was involved. |

A failure the server itself reports includes its reason, such as a missing
publication or a class currently being refreshed by the frontend.

### In Insert Function, Select Datasets, and Load Reserving Classes

| Message | Cause and what to do |
| :--- | :--- |
| `This PC is not set up to read Arco data. Ask the Arco team to give you access, then restart Excel.` | The same missing credential, said without brackets because it is shown in a box rather than a cell. |
| `Unable to load dataset list:`, `Unable to load reserving classes:`, or `Lists unavailable:` followed by a reason | The lists could not be fetched. The reason is one of the cell messages above, or one of the two below. |
| `Ask the Arco team to update the Arco Server.` | The server does not yet answer the pickers' list request. |
| `This project defines no dataset types.` | The project was read and has no dataset types configured. |
| `Please connect and log in, then select a default project before using Select Datasets.` (or `Load Reserving Classes`) | Nothing is wrong with the server; the workbook has no default project selected yet. |

## What still comes from the share

Moving project data to the server did not remove the drive mapping. These are
still opened directly, so a PC that cannot reach the share loses them:

- the add-in itself, `Excel Add-ins\Arco.xlam` and the beta beside it;
- `apps\Arco Credential\Arco Credential.exe`, the first-run helper;
- `Excel Add-ins\Arco Release Notes.md`, opened by the About window and
  published from [`RELEASE_NOTES.md`](RELEASE_NOTES.md) by each release;
- `Team Profile\Actuarial_NJ.xlsm`, the default team profile in Settings.

## The recorded checks

Snapshot behavior is checked in isolated Excel sessions. The checks below
describe the expected results and retain earlier transport measurements:

Run `py -3.10 -B excel-addin/tools/verify_workbook_snapshots.py` on a Windows
PC with Excel, pywin32, and trusted VBA project access. The harness uses
synthetic Gateway responses and disposable workbooks under repository `test/`.
After building, `py -3.10 -B excel-addin/tools/verify_built_addin.py
excel-addin/beta/ARCRHO_BETA.xlam` checks the compiled add-in against its source.
`py -3.10 -B excel-addin/tools/verify_reference_repair.py` checks reference
rewrites in both directions, arrays, named formulas, protected sheets,
recalculation, saved links, target availability, and large-workbook progress and
cancellation using synthetic add-ins and disposable workbooks in the same test root.

| Check | What it proves |
| :--- | :--- |
| [check_dataset_cache.md](tools/check_dataset_cache.md) | Saved snapshots reopen without server access, entered formulas load missing requests, and explicit refresh fetches each distinct request once. |
| [check_gateway_signing.md](tools/check_gateway_signing.md) | The add-in signs a request the way the server verifies it, and this PC can reach the server. |
| [check_gateway_transport.md](tools/check_gateway_transport.md) | Every worksheet function returns the same figures from the server as it did from the share, and how long each takes. |
| [check_first_run_credential.md](tools/check_first_run_credential.md) | A PC with no credential gives itself one when a new formula or refresh needs data, an opt-out is left alone, and a dead share fails quickly. |

## Building and releasing

[`agent-instructions/excel-addin-build-and-release.md`](../agent-instructions/excel-addin-build-and-release.md)
owns the procedure. `tools/build_xlam.ps1` builds the beta add-in;
`tools/release_xlam.ps1` publishes `Arco.xlam` to the share, where every user
picks it up on the next Excel launch. The scripts require the existing beta
workbook and signature files. When invoking the required server-clone scripts
from another working clone, pass that clone's current `SourceDir` and
`CustomUIPath` explicitly so the build includes the changes being released.
