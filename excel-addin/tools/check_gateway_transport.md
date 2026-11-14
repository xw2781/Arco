# Check: formulas read the same figures from the server as from the share

A ten-minute manual check that every worksheet function returns the same value
whether it reads project data from the ArcRho Server or from the workspace
share, and how long a full recalculation takes each way. There is no automated
harness for the add-in's VBA, so this is the check.

Since add-in 2.6.0 the share path is gone, so the check compares two builds of
the add-in rather than two settings of one; see the section below.

## The setting that forced the share, and what replaced it

While both paths existed, `ArcRhoForceSharePath True` sent formulas back to the
share for one pass and `False` returned them to the server. That setting was
removed with the share path itself, so the two paths can no longer be compared
inside one add-in. From this point on the comparison is between two builds of
the add-in: build the older sources to a second `.xlam` with
`build_xlam.ps1 -SourceDir <sources> -TargetPath <second xlam>`, run the
workbook once against each, and compare the two dumps.

`build_xlam.ps1` updates an existing package rather than creating one, so copy
`ARCRHO_BETA.xlam` to the second target first.

## The workbook

One sheet covering every worksheet function, all against
`NJ_Annual_Prod_202605_Fake`, reserving class `HPPREF\HO+DF\NJ\Legacy\HOL`:

| Block | Formula |
| :--- | :--- |
| array triangle | `ArcoTri(class,"Net Loss--Incurred Adjusted***",TRUE,FALSE,FALSE,project,1,1)` |
| single cell | `ArcoTriCell(class,"Net Loss--Incurred Adjusted***",2,3,TRUE,project,1,1)` |
| diagonal | `ArcoTriDiag(class,"Net Loss--Incurred Adjusted***",0,TRUE,FALSE,project,1,1)` |
| origin row | `ArcoTriOrigin(class,"Net Loss--Incurred Adjusted***",2,TRUE,FALSE,project,1,1)` |
| vector | `ArcoVec(class,"C 81 - Prior Qtr Indicated",FALSE,project,12)` |
| vector cell | `ArcoVecCell(class,"C 81 - Prior Qtr Indicated",2,project,12)` |
| period headings | `ArcoHeaders(0,TRUE,12,project,-1,FALSE)` and the same with `1` |
| project settings | `ArcoProjectSettings(project)` |
| coarser view | `ArcoTri(class,"Net Loss--Incurred Adjusted***",TRUE,FALSE,FALSE,project,12,12)` |

Each array block is entered over a fixed range so that the two passes can be
compared cell by cell.

**No block may overlap another.** Writing a single-cell formula into a cell that
already belongs to an array block raises "You can't change part of an array",
and Excel shows that as a modal dialog on the desktop even when the instance is
invisible and alerts are off — the COM call then never returns. An extended
version of this workbook once put a single-cell block three rows inside a
twenty-row vector block and stalled for eighteen seconds on it.

## The passes

Put Excel in manual calculation. Then, alternating and starting with a warm-up
pass on each side: put the add-in on the path being measured, wait twelve
seconds so Windows drops the share's cached directory metadata, recalculate
everything, and read every block. Three measured passes each way; take the
median of the three times.

Without that wait the share is measured warmer than a user opening a workbook
ever meets it, because Windows answers a repeated look at the same folder from
its own cache for about ten seconds.

## What to expect

Every cell holds the same value on both paths. A failure is expected to read
differently: the server's own message is passed through, where the share path
could only say that a file was missing.

## First recorded run: one reserving class, every dataset already cached

2026-09-12 on the developer Client PC `L-H2MQ6280FVP`, Excel 16.0 driven over
COM, add-in version 2.5.0, against the Gateway on `NE7SASWPN02`, with the Engine
and Gateway redeployed the same day.

### Values

| Workbook | Cells compared | Cells that differ |
| :--- | :--- | :--- |
| The nine blocks above that both paths can serve | 566 | 0 |
| Twenty-three annual triangles in one class | 1,104 | 0 |

The coarser-view block, 400 more cells, could not be compared on this PC. The
server answered it correctly; the share path failed with "a dataset view must be
written to the reserving class's view cache" because a beta add-in loaded from
the repository works out the workspace root as a UNC path, which the server's
view handler will not accept as the same location as its own drive letter. An
add-in loaded from the share, as every user's is, does not have that problem.

### Times

| Workbook | Share | Server |
| :--- | :--- | :--- |
| Ten blocks, nine datasets | 0.46 s | 0.60 s |
| Twenty-three annual triangles | 1.03 s | 1.14 s |

Both are medians of three alternating passes. One dataset costs roughly 45 ms
over the share and 50 ms over the server on this network on this day, and a
second formula asking for the same dataset in the same pass costs 10 ms either
way, because the add-in already remembers it.

The share is therefore as fast as the server for a warm workbook of hand-entered
datasets in one reserving class, which is not what the plan's own measurement
predicted; see the open decision in
[docs/plans/completed/excel_addin_gateway_transport.md](../../docs/plans/completed/excel_addin_gateway_transport.md).
The server's advantage that this run does show is the coarser view, which it
builds in memory in about 90 ms and which the share path cannot serve at all
here.

### Two failures that are not about the transport

Both predate this change and appear identically on both paths:

- **A calendar-period view of a hand-entered triangle is unavailable.** The
  roll-up will only build a view from a stored triangle whose own calendar mode
  matches, so both paths refuse. `ArcoTriDiag` and `ArcoTriCell` ask for one
  without meaning to, because of the way they pass their arguments on.
- **`ArcoTriDiag` asks for the transposed calendar shape** rather than the one
  its caller asked for, so the diagonal of a hand-entered triangle fails on both
  paths.

## Second recorded run: many classes, and datasets the Engine has to calculate

Later the same day, 2026-09-12, on the same PC, the same Excel 16.0 driven over
COM, the same add-in package and the same Gateway on `NE7SASWPN02`. Nothing was
rebuilt or redeployed between the two runs.

The first run covered one reserving class and only datasets whose figures were
already sitting in the class's cache, which is the case the share path is best
at. It did not cover the two the plan expected the win to come from, so both
were measured here.

- **Case A, many classes.** Twelve reserving classes of
  `NJ_Annual_Prod_202605_Fake`, each contributing one annual triangle
  (`Net Loss--Paid`) and one vector (`Earned Premium`): twenty-four datasets,
  1,332 figures, every one of them already cached. The share path pays its
  dataset-type look, class-index look and directory check in twelve different
  folders rather than one.
- **Case B, the Engine actually calculates.** Three engine triangles
  (`Net Loss--Paid`, `Net Loss--Incurred`, `Gross Loss--Paid`) in
  `HPPREF\HO+DF\NJ\Legacy\HOL`, with the add-in's "always refresh" setting
  turned on so that neither path may serve a cached figure. Over the share that
  is a cache delete, a request file and the poll loop; over the server it is the
  same one call as any other read. The cache CSVs' timestamps after each pass
  confirm the Engine really recalculated on both paths rather than answering
  from the cache.

Passes were run exactly as described above: alternating, the force setting
written before every pass so the add-in's own per-pass memory is dropped, twelve
seconds of waiting so Windows lets go of the share's cached directory metadata,
and one unmeasured warm-up pass on each side first. Five measured passes each
way for case A, three each way for case B.

### Values

| Workbook | Cells compared | Cells that differ |
| :--- | :--- | :--- |
| Case A, twenty-four datasets in twelve classes | 1,332 | 0 |
| Case B, three recalculated triangles | 297 | 0 |

### Times

| Workbook | Share | Server | Faster |
| :--- | :--- | :--- | :--- |
| Case A, twenty-four cached datasets in twelve classes | 1.78 s | 1.46 s | the server, by about 18% |
| Case B, three datasets the Engine recalculates | 1.74 s | 0.86 s | the server, by about half |

Medians, and the passes behind them:

| Workbook | Share passes | Server passes |
| :--- | :--- | :--- |
| Case A | 1.84, 1.78, 1.50, 1.92, 1.35 | 1.27, 1.20, 1.46, 1.51, 1.78 |
| Case B | 1.81, 1.74, 1.72 | 0.88, 0.86, 0.86 |

**Case A: the server is faster, but not by more than the noise.** Its median is
0.32 s ahead over twenty-four datasets, about 13 ms a dataset, and the spread
between the slowest and fastest pass is wider than that on both sides. An
earlier three-pass set the same evening put the share at 1.31 s and the server
at 1.23 s. Read together, the honest reading is that the server is at least as
fast as the share for cached datasets spread across many classes, and probably a
little faster; it is not the two-to-one win the plan's original single-dataset
measurement suggested.

**Case B: the server is clearly and repeatably faster.** Roughly twice as fast,
0.29 s a dataset saved, and every pass on each side landed within 0.1 s of its
own median, so this one is not noise. This is the case the plan predicted: the
share pays a request file and a poll loop for a calculation the server answers
in the same call it answers a read with. The share path also gives up after five
seconds of polling, which the server path has no equivalent of.

Neither case covered the coarser view, so the UNC failure recorded in the first
run above was neither reproduced nor re-checked here, and nothing was written to
the share to work around it.

## Third recorded run: the share path is gone

2026-09-12 on the developer Client PC `L-H2MQ6280FVP`, Excel 16.0 driven over
COM. The check for the step that deleted the share path: the same workbook run
once against the previous add-in (2.5.0, both paths, reading from the server)
and once against the new one (2.6.0, server only), then the two dumps compared
cell by cell. The workbook carries the ten blocks above plus the second run's
case A and case B datasets: seventeen blocks, 2,224 cells.

### Values

| Comparison | Cells compared | Cells that differ |
| :--- | :--- | :--- |
| 2.5.0 against 2.6.0, both reading from the server | 2,224 | 21 |

Not one figure moved. All twenty-one are cells of the two blocks the previous
run already recorded as failing on both paths for a reason that is not about
transport — `ArcoTriCell` and `ArcoTriDiag` asking for a calendar-period
view of a hand-entered triangle. They used to come back as `0` and `#VALUE!`,
because the wrappers around `ArcoTri` assumed an array and quietly discarded a
message. They now read

> (Input triangle 'Net Loss--Incurred Adjusted***' exists as a local cache that
> cannot derive 1x1 periods: calendar mode differs.)

which is the same refusal the array block itself has always shown.

### Without a credential

The credential at `%APPDATA%\Arco\arcrho_gateway.json` was renamed aside and
the same workbook run again, then the credential was restored. All 2,224 cells
read

> (this PC is not set up to read ArcRho data. Ask the ArcRho team to give you
> access, then restart Excel.)

No cell showed a path, a blank, `0` or an Excel error.

### Times

One pass over the whole workbook took 1.63 s on 2.5.0 and 1.46 s on 2.6.0.
These are single passes, not medians, and the difference is well inside the
spread the second run recorded; nothing here was expected to move, since only
the share path was removed and neither build used it.
