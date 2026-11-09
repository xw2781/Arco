---
name: fake-ma-bi-total-f63-test-class
description: "The Fake project's MA BI Total reproduces the live F 63 chain (quarterly P 06, annual Engine premiums); Fake NY BI Total does not"
metadata:
  node_type: memory
  type: reference
  originSessionId: a67cea08-d868-4db6-946c-c248084098c5
  modified: 2026-09-29T16:28:24.200Z
---

For GUI or offline tests of F 63 (`P 06 * (Earned Premium + Remaining Budget Premium)`), use
`NJ_Annual_Prod_202605_Fake` class `PRNJ - PA\PA\MA\Direct Group\BI Total`: P 06 is a quarterly
input (sidecar names `@3`), both premiums are annual Engine vectors (`@12`, stored 1), F 63 is
quarterly. NY MP+PIP and Penn+CT BI Total look the same. Fake **NY BI Total** does not: it has
no F 63 at all (its CSV-less F 63 sidecar was deleted in the 2026-11 refresh; its P 06 is now
stored quarterly), so F 63 cannot be tested there.

**How to apply:** in Arco, change the path bar's state to MA and the last segment to BI Total
(the list scrolls; drag its scrollbar). Saving P 06 with no edit forces the walk. Before the
2026-11 data refresh every save there showed a "Dependent updates" box for G 41 / G 91 / G 92;
since the refresh every class walk is clean ([[fake-project-refresh]] plan, step 13). Used 2026-09-29 for the
[[calculated-walk-reads-stale-sibling-views]] fix; the evidence script pattern (recompute F 63
from the `@3` files) is in that session's temp/f63_gui_test/snapshot.py.
