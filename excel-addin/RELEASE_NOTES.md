# Arco Excel Add-in Release Notes

Newest first. The About window opens this file from beside the add-in on the
Arco Server share.

## 4.4.1 - 2026-11-10

- Insert Arco Function: typing in a path, dataset, project, or folder box now
  shows the matches in a list under the box, without the blank block the
  dropdown used to draw. The arrow keys move through the matches, Enter or a
  click takes one, and Esc puts the list away.
- Typing several words finds the names that contain all of them, such as
  `2026 jul`, and the count of matches shows beside the box.
- A half-typed project name no longer raises the "not on the project list"
  message; the name is checked once it is picked.

## 4.4.0 - 2026-11-10

- Insert Arco Function has a new, narrower layout: the function is a dropdown
  at the top, each argument shows beside it what goes into the formula or the
  default it falls back to, and one help box describes the argument you are in.
- The window is only as tall as the chosen function's arguments need.
- `ArcoProjectNames` is in the Insert Arco Function list, with the project
  folders offered for its `Folder` argument.

## 4.3.4 - 2026-11-10

- Reset Add-in References shows Arco and ResQ as two rows to pick from, each
  with its add-in path, instead of a dropdown. It also has a Close button.

## 4.3.3 - 2026-11-10

- The Reset Add-in References window is smaller.

## 4.3.2 - 2026-11-10

- Connect and Login no longer writes the project names into column B of the
  `Arco Settings` sheet. The Default Project Name dropdown reads the
  `ArcoProjectNames` list in A11 instead.

## 4.3.1 - 2026-11-10

- `ArcoProjectNames` takes an optional `Folder` and lists only the projects in
  that folder of the Arco project list, such as `=ArcoProjectNames("Legacy")`.
- Its optional `ShowFullPath`, when TRUE or 1, puts each project's folder in front
  of its name, such as `Legacy\My Project`.

## 4.3.0 - 2026-11-10

- New function `ArcoProjectNames()` lists every project on the Arco Server,
  one name per row.
- Connect and Login puts that formula in cell A11 of the `Arco Settings`
  sheet, clearing column A from row 11 down to make room.

## 4.2.7 - 2026-11-10

- Connect and Login renames a workbook's `ResQ Settings` sheet to
  `Arco Settings`.
- Reset Add-in References does the same when it points a workbook at Arco, and
  renames the sheet back to `ResQ Settings` when it points a workbook at ResQ.
- `ArcoProjectSettings` shows the folder as `Arco Virtual Project`.

## 4.2.6 - 2026-11-09

- First-time sign-in starts the helper under its new name, `Arco Credential`,
  after the server components were renamed from `ArcRho` to `Arco`.

## 4.2.5 - 2026-11-09

- The add-in is now `Arco.xlam` in `E:\Arco Server\Excel Add-ins`, after the
  server folder was renamed from `ArcRho Server`. Updating Arco Workspace
  registers it in Excel and turns off the old `ArcRho.xlam` entry.
- Reset Add-in References points workbooks that still name `ArcRho.xlam` at
  the new add-in.

## 4.2.4 - 2026-10-28

- Cells skipped by Refresh Workbook because their dataset is not in Arco keep
  showing "(dataset not found)" after the refresh finishes.

## 4.2.3 - 2026-10-28

- Refresh Workbook skips formulas that point to a dataset Arco does not have,
  refreshes the rest, and reports how many were skipped.

## 4.2.2 - 2026-09-30

- Entering an Arco formula keeps the cache data sheet out of view while saving its results.

## 4.2.1 - 2026-09-28

- Refresh Workbook shows why a refresh failed instead of stopping with a
  "Method 'StatusBar' of object '_Application' failed" error.
- Insert Function leaves an optional argument empty when you leave it blank,
  rather than writing its default, such as `=ArcoVec(D2, N18, , , 3)`.
- The About window opens these release notes.

## 4.2.0 - 2026-09-23

- Insert Function panel, with reserving classes, datasets, and projects listed
  from the Arco Server.

## 4.1.1 - 2026-09-22

- Repair a workbook's add-in references from a target selector.

## 4.0.2 - 2026-09-21

- Refresh ends with a full-workbook recalculation, so formulas that depend on
  Arco results are current.

## 4.0.0 - 2026-09-18

- The product is renamed Arco; the worksheet functions are now the Arco
  functions.

## 3.0.1 - 2026-09-18

- Entering or editing a formula loads its data.

## 3.0.0 - 2026-09-17

- Workbooks save the results of their Arco formulas and show them without
  reaching the server.

## 2.6.0 - 2026-09-12

- Project data is no longer read from the workspace share.

## 2.5.0 - 2026-09-12

- Project data is read through the Arco Gateway.

## 2.4.0 - 2026-09-12

- A dataset is fetched once per recalculation, however many formulas use it.

## 2.3.0 - 2026-09-12

- A hand-entered dataset can be read at a coarser period.

## 2.2.0 - 2026-06-23

- Fixed when the dataset cache is rebuilt.

## 2.1.0 - 2026-05-25

- Reversible escaping of dataset file names.
