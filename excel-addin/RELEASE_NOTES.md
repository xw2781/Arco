# Arco Excel Add-in Release Notes

Newest first. The About window opens this file from beside the add-in on the
Arco Server share.

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
