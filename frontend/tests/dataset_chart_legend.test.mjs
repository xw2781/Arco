import assert from "node:assert/strict";
import test from "node:test";

import {
  canHideChartLegendSeries,
  hiddenChartSeriesIdsAfterContextToggle,
} from "../ui/shared/components/chart_legend/chart_legend.js";

test("shared chart legend keeps one series visible and toggles isolation", () => {
  const series = [{ id: 0 }, { id: 1 }, { id: 2 }];
  assert.equal(canHideChartLegendSeries(series, 2, [0, 1]), false);
  assert.deepEqual([...hiddenChartSeriesIdsAfterContextToggle(series, 1)], [0, 2]);
  assert.deepEqual([...hiddenChartSeriesIdsAfterContextToggle(series, 1, [0, 2])], []);
});
