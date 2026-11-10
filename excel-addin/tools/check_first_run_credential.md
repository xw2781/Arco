# Check: a PC with no access enrolls when data is needed

A five-minute manual check that the add-in installs this PC's own ArcRho
Server credential when a new formula or explicit refresh first needs it, that a
credential deliberately turned off is left alone, and that a PC away from the office pays one short
failure rather than a hang. The snapshot harness substitutes the credential
helper; these checks exercise real enrollment.

## What it needs

- The beta add-in built from this clone:
  `powershell -NoProfile -ExecutionPolicy Bypass -File excel-addin\tools\build_xlam.ps1`
- The helper deployed on the share at
  `<workspace>\apps\Arco Credential\Arco Credential.exe`
- A credential of your own at `%APPDATA%\ArcRho\arcrho_gateway.json` to copy
  aside and put back at the end, so the check leaves the PC as it found it.

Excel is driven over COM. Set `DisplayAlerts`, `EnableEvents` and
`ScreenUpdating` to `False` the moment the application object exists — a modal
alert from an invisible instance lands on the desktop and blocks the call for
ever — keep events disabled while opening the add-in. Opening and recalculating a
saved snapshot must not provision a credential. Enable events for the formula-entry
check, or run the explicit ribbon refresh for the refresh check. Never overwrite
part of an array formula.

## The four checks

1. **The helper runs from the share.** Move the credential aside and start
   `Arco Credential.exe` the way the add-in does — through `WScript.Shell`,
   hidden, waiting for it — handing it the workspace root as its one argument.
   It must exit 0 with no warning dialog and the credential must be back.
2. **Excel sets the PC up on its own.** Move the credential aside again, open
   the beta `.xlam`, and confirm no credential is created while reading saved
   values. Enter a formula for an already saved request and confirm no credential
   is created. Then enter a formula whose request is missing and confirm the
   credential is installed and figures are returned. Repeat in a fresh session
   with Refresh Workbook as the first request instead.
3. **An opt-out is honoured.** Put `{"enabled": false}` in the credential file,
   enter a formula for a missing request or run an explicit refresh, and confirm
   the file is untouched, the operation reports that this PC is not configured,
   and saved figures remain available.
4. **A dead share fails quickly.** Time the add-in's own guard — `Dir$` against
   a path on a host that does not exist — and confirm it comes back with an
   error in about a second and raises no dialog.

## Historical result before enrollment moved out of workbook open, 2026-09-12, `L-H2MQ6280FVP`, add-in 2.6.0

Against `NJ_Annual_Prod_202605_Fake`, reserving class
`HPPREF\HO+DF\NJ\Legacy\HOL`, dataset `Net Loss--Incurred Adjusted***` asked
for at one month by one month.

| Check | Result |
| :--- | :--- |
| Helper from the share | exit 0 in 14.05 s, no dialog, credential back and byte-identical to the one moved aside |
| Excel opens with no credential | credential installed during `Workbook_Open` in 11.78 s; `ArcoTri` then returned a 120 x 113 array in 0.47 s |
| `enabled: false` left alone | file unchanged; the formula answered "(this PC is not set up to read ArcRho data. Ask the ArcRho team to give you access, then restart Excel.)" |
| Host that does not exist | VBA error 52 after 1.34 s, nothing shown, nothing left running |

The same secret came back in check 1 because this user was already in the
shared registry: enrollment reuses an entry rather than replacing it, so a
second run cannot lock the first one out.

The eleven to fourteen seconds is the whole enrollment — reading the shared
registry over the share, asking the Gateway whether it is there, writing both
files — and is paid once on a PC that has never had a credential. The loading
window says what is happening while it runs.
