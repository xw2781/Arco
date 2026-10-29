# ResQ instance formulas Arco cannot reproduce

Status: Investigated 2026-10-28. Read-only; nothing was imported, changed or fixed.
Last updated: 2026-10-28

## The issue

In ResQ a dataset can carry its own formula, kept on that one reserving class and not on the dataset type. The request from the Arco Excel add-in for such a dataset returns 0, because Arco has no data processing rule that reads a value from another reserving class.

The case that raised it is `NJ_Annual_Prod_2026 Sep`, class `HPPREF\PCAT\NJ\Legacy\UMBR`, vector `Remaining Budget Premium`. Its ResQ formula is `"PRNJ - UMBR\PCAT\NJ\Legacy\UMBR\Remaining Budget Premium"`. The type itself has no formula in ResQ, and in Arco it is a generated type read from one source column. The source has no value for this class, so Arco generates zeros.

## How it was checked

- **Connection:** ResQ's COM interface on the Server PC, using the service account in the server config. A direct SQL Server connection was refused, so the database was not queried directly.
- **Scan:** every vector and triangle in every reserving class that ResQ does not itself mark as a roll-up, keeping those with their own formula on a dataset type that is not calculated. Values were read to tell a dataset that holds data from an empty stub.
- **Cross-class formula:** one whose text names a path with a backslash, meaning it reads another reserving class. This is the issue above.
- **Coverage:** 829 of 1,294 projects, all 135 with `2026` in the name but one, 277 with `2025` or `2026`. The rest are older backups. The scan was stopped before the remaining projects finished, so totals for older years are a floor.

## What was found

| Scope | Projects scanned | Projects affected | Datasets | Of which hold data |
| :--- | :--- | :--- | :--- | :--- |
| All scanned | 829 | 508 | 20,544 | 18,123 |
| 2025 and 2026 | 277 | 209 | 16,652 | 14,908 |
| 2026 only | 134 | 102 | 6,936 | 6,148 |

Affected projects by family: NE 195, NJ 144, IA 104, HG 54, a few others.

Three shapes make up the cross-class datasets:

- **Arithmetic or function** (14,687): a formula such as `"P F55 - Selected UMBR Allocation" * "Enterprise_Umbrella\UMBR\...\F 55 - Net Loss IBNR"`.
- **Single link** (5,175): a copy of the same dataset from another class, such as the case above.
- **Sum of classes** (682): the same dataset added up from several classes.

### By project family

- **NJ** (every 2026 project, and the fake project `NJ_Annual_Prod_202605_Fake`): 27 datasets in 16 classes, all vectors. `Earned Exposure` 15, `Earned Premium` 10, `Remaining Budget Exposure` 1, `Remaining Budget Premium` 1. All 27 hold data in `NJ_Annual_Prod_2026 Sep`.
  - Typical case: the `OIL` class reads `HOL` in the same state and channel.
  - Typical case: the `HOP_CAT` classes read `HOP`.
  - Typical case: the `UMBR` class reads `PRNJ - UMBR`.
- **HG:** the same 27 in every 2026 project, 541 in `HG_Annual_Prod_2026 Aug- ALAE Reserves`.
- **IA quarterly:** 29 to 141 per project, mostly `F 55`, `G 55`, `F 55p`, `G 55p` and `P F55b - UMBR EP Distribution`, which are umbrella allocations that read `Enterprise_Umbrella\UMBR\All_States\All_Companies\UMBR`. Older projects also have `Expense` and `Incurred Claims`.
- **Older NE projects:** the same pattern with `Earned Exposure`, `Earned Premium` and bootstrap copies.

### Roll-up classes

In `NJ_Annual_Prod_2026 Sep`, 84,977 more datasets carry a cross-class formula inside classes ResQ marks as roll-ups (`PRNJ - PA`, `PIC2`, `Rider` and so on). Those are ResQ's own aggregation and Arco builds them from its reserving-class types, so they are not part of the counts above. This is the same reasoning as the existing `resq-formula-belongs-to-type` finding. They were not checked against Arco's output here.

### A second, smaller pattern

Datasets whose formula names other datasets in the same class, on a type ResQ does not mark calculated, are already known and handled by the instance-formula import design: `C 61 Reported - CWOP`, `F 31`, `D 31`, `F 42`, `G 42` and the prior and current quarter `82` and `92` types. `NJ_Annual_Prod_2026 Sep` has 3 of them. Across the scan there are 3,819 in 206 projects. They are listed for completeness and are not the issue in this document.

## What is not known

- Whether Arco's stored value for each of the 27 NJ datasets is zero. Only `NJ_Annual_Prod_202605_Fake` is readable by agents, and that is a perturbed copy. The add-in request for `UMBR` was reported as 0 by the user and was not re-run.
- Whether the datasets with only zero values (2,421 of the 20,544) are abandoned stubs or real zeros, as with the `UMBR` case above.
- The roll-up classes above, and the 465 projects not scanned.

## Options for the owner to decide

- **Import the link:** a cross-class single link or sum becomes an in-cell formula link to the other class's dataset, extending the instance-formula import design to a class path. Needs the link grammar to accept a class path.
- **Add a processing rule:** a data processing rule that sums or copies a source slice from another class, so the Engine can generate it. This reproduces the NJ cases (copy `HOL` into `OIL`) without a link grammar change.
- **Leave as is** for the quarterly umbrella allocations, which depend on a class from a different project layout.

No option has been chosen.
