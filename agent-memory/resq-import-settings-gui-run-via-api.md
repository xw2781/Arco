---
name: resq-import-settings-gui-run-via-api
description: Set up or change a ResQ saved import in the GUI Import Wizard; COM may only run an existing import (and repoint its table/file); the Fake project's five imports and how they are fed
metadata:
  type: feedback
---

Create or change a ResQ saved import (source, transforms, import settings, significances,
mappings) in the ResQ GUI Import Wizard. COM (`project.Imports()` items, 1-based) is fine for
reading an import's settings and for running one with its stored settings (`Execute`), and at
most repointing `Location` / `Tablename`.

**Why:** user's experience (2026-11-09), and the manual agrees: `xResQImport` exposes only the
location, table, login and the import-settings flags plus `Execute` / `Save`; transforms,
significances and mappings are wizard-only, so an import built or reshaped over COM is incomplete.

**How to apply:** GUI path is Home > Imports > right-click an import > Edit/View, then Next
through Connection > table list > Transforms > Import Settings > Import Definition >
Confirmation > Finish (Finish runs it; Save stores without running). An import of ~190k SQL rows
takes about 35 minutes. Use the computer-use skill; the `Importing data...` window closes itself
when done.

The Fake project (`NJ_Annual_Prod_202605_Fake`) has five saved imports, all "Clear Existing Data",
incremental, 1-month origin/development: `EP EEX` and `Budget` (delimited text in
`E:\ResQ\IBNR_SQL_Codes\202605\`), and `Loss`, `Reported Counts`, `Closed Counts` (SQL Server
`CO1ADBWPV01` / `Actuarial_NJ`, tables `ResQ_Channel_<kind>_202605_<suffix>`). All five are cut
from one source CSV by `tools/split_fake_source_for_resq.py`. Related: [[resq-com-probe]],
[[fake-project-refresh]].
