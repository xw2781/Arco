import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  SCON_CORRELATION_OPTIONS,
  applyConsolidationSettings,
  availableCandidates,
  baseTypeChoices,
  commonSimulationCount,
  consolidationRunState,
  optionTargetMatrix,
  parseCorrelationInput,
  rankToLinear,
  readConsolidationSettings,
  reorderTargetMatrix,
  runInputSnapshot,
  segmentBreakdown,
  segmentInfoMap,
  segmentRows,
  segmentShortLabel,
  setTargetCorrelation,
  squareTargetMatrix,
  usedCorrelationMatrix,
} from "../ui/method_pages/stochastic_consolidation/stochastic_consolidation_page_model.js";
import { resultsClipboardText, resultsView, summaryTableColumns } from "../ui/shared/components/reserve_range/reserve_range_model.js";
import {
  STOCHASTIC_CONSOLIDATION_TAB_DEFS,
  appDefaultWindowTab,
  resolveWindowTab,
  windowTabKind,
} from "../ui/shared/tabs/window_tab_catalog.js";

const frontendRoot = new URL("../", import.meta.url);
const read = (path) => readFile(new URL(path, frontendRoot), "utf8");

const BASE = "PRNJ - PA\\PA\\All States\\Direct Group";

function sampleMethod() {
  return {
    json_format: "arcrho-stochastic-consolidation-v4",
    details_tab: {
      name: "F 72 A - Bootstrap Consolidation",
      method_type: "Stochastic Consolidation",
      output_type: "F 00 - Ultimate Net Loss",
      dataset_category: "F Net Loss",
      base_triangle_type: "Net Loss--Incurred",
      origin_length: 12,
      development_length: 12,
      simulation_count: 10,
      random_seed: 1514684455,
    },
    segments_tab: {
      segments: [
        { reserving_class: `${BASE}\\BI Total`, method_name: "F 72 A", factor: 1, bootstrap_revision: "sha256:a" },
        { reserving_class: `${BASE}\\CMPxCAT`, method_name: "F 72 A", factor: 1, bootstrap_revision: "sha256:b" },
        { reserving_class: `${BASE}\\PD+UMPD`, method_name: "F 72 A", factor: 0.5, bootstrap_revision: "sha256:c" },
      ],
    },
    correlation_tab: {
      correlation_option: "specified",
      dependency_type: "normal",
      degrees_of_freedom: 20,
      target_correlations: [[1, 0, 0.38], [0, 1, 0.1], [0.38, 0.1, 1]],
      adjusted_correlations: [[1, 0, 0.395315], [0, 1, 0.104665], [0.395315, 0.104665, 1]],
    },
    results_tab: {
      input_revision: "sha256:run",
      origin_labels: ["2025", "2026"],
      latest_values: [100, 200],
      simulation_summary: {
        simulation_count: 10,
        random_seed: 1514684455,
        scaled: {
          mean: [70, 20, 50],
          standard_error: [14, 4, 10],
          percentiles: { 50: [65, 18, 47] },
          ultimate_mean: [370, 120, 250],
          histogram: { lower: 30, upper: 300, counts: [1, 3, 4, 2] },
        },
        achieved_rank_correlations: [[1, 0, 0.38], [0, 1, 0.1], [0.38, 0.1, 1]],
        achieved_linear_correlations: [[1, 0, 0.4], [0, 1, 0.12], [0.4, 0.12, 1]],
        segments: [
          { factor: 1, mean: 40, standard_error: 10, cv: 0.25, share_of_mean: 0.5 },
          { factor: 1, mean: 20, standard_error: 5, cv: 0.25, share_of_mean: 0.25 },
          { factor: 0.5, mean: 20, standard_error: 5, cv: 0.25, share_of_mean: 0.25 },
        ],
        diversification: { total_standard_error: 14, sum_of_standalone_standard_errors: 20, benefit: 6 },
      },
      consolidation_ultimate: [120, 250],
    },
    method_metadata: { owned_revision: "sha256:o", derived_revision: "sha256:d" },
  };
}

test("the tab catalog lists the consolidation's tabs and opens it on Results", () => {
  assert.deepEqual(STOCHASTIC_CONSOLIDATION_TAB_DEFS.map((item) => item.id), [
    "details", "segments", "correlation", "results", "notes", "audit",
  ]);
  assert.equal(windowTabKind("stochastic_consolidation")?.hint, "SCON");
  assert.equal(appDefaultWindowTab("stochastic_consolidation"), "results");
  assert.equal(resolveWindowTab("stochastic_consolidation", "correlation", {}), "correlation");
  assert.equal(resolveWindowTab("stochastic_consolidation", "method", {}), "results");
});

test("Project Instance opens, adds and restores Stochastic Consolidation windows", async () => {
  const [windows, table, messages, html] = await Promise.all([
    read("ui/project_instance/project_instance_windows.js"),
    read("ui/project_instance/project_instance_dataset_table.js"),
    read("ui/project_instance/project_instance_messages.js"),
    read("ui/project_instance/project_instance.html"),
  ]);
  assert.match(windows, /kind: "stochastic_consolidation"/u);
  assert.match(windows, /\/ui\/method_pages\/stochastic_consolidation\/stochastic_consolidation\.html\?/u);
  assert.match(windows, /windowTab\("stochastic_consolidation", options\.initialTab \|\| options\.sconTab\)/u);
  assert.match(windows, /sconTab: kind === "stochastic_consolidation"/u);
  assert.match(table, /=== "stochastic consolidation";/u);
  assert.match(table, /normalized === "add-stochastic-consolidation"/u);
  assert.match(messages, /filename = `SCON@\$\{namePart\}\.json`;/u);
  assert.match(messages, /msg\.type === "arcrho:scon-tab-changed"/u);
  assert.match(html, /data-row-action="add-stochastic-consolidation">Stochastic Consolidation</u);
});

test("settings read from a method write back to the same method", () => {
  const method = sampleMethod();
  const settings = readConsolidationSettings(method);
  assert.equal(settings.segments.length, 3);
  assert.equal(settings.segments[2].factor, 0.5);
  assert.equal(settings.correlationOption, "specified");
  assert.equal(settings.degreesOfFreedom, 20);
  assert.deepEqual(applyConsolidationSettings(method, settings), method);
  const fresh = readConsolidationSettings({});
  assert.equal(fresh.correlationOption, "specified");
  assert.equal(fresh.dependencyType, "normal");
  assert.equal(fresh.originLength, 12);
  assert.deepEqual(fresh.segments, []);
});

test("a segment keeps its consumed bootstrap revision only while it names the same bootstrap", () => {
  const method = sampleMethod();
  const settings = readConsolidationSettings(method);
  settings.segments = [settings.segments[1], { ...settings.segments[0], methodName: "F 72B" }];
  const saved = applyConsolidationSettings(method, settings);
  assert.deepEqual(saved.segments_tab.segments.map((segment) => segment.bootstrap_revision), ["sha256:b", ""]);
  assert.equal(saved.correlation_tab.target_correlations.length, 2);
});

test("a segment from another project keeps its project and is a different segment", () => {
  const method = sampleMethod();
  method.segments_tab.segments[2].project_name = "NJ_Annual_Prod_2026 Q3-Aug Oil";
  const settings = readConsolidationSettings(method);
  assert.equal(settings.segments[2].projectName, "NJ_Annual_Prod_2026 Q3-Aug Oil");
  assert.equal(settings.segments[0].projectName, "");
  // Written back unchanged: only the other project's segment names a project.
  assert.deepEqual(applyConsolidationSettings(method, settings), method);

  const local = { reserving_class: `${BASE}\\PD+UMPD`, method_name: "F 72 A" };
  const elsewhere = { ...local, project_name: "NJ_Annual_Prod_2026 Q3-Aug Oil" };
  assert.deepEqual(availableCandidates([local, elsewhere], settings), [local]);
  const rows = segmentRows(settings, segmentInfoMap([{ ...elsewhere, simulation_count: 10, has_run: true }]));
  assert.equal(rows[2].projectName, "NJ_Annual_Prod_2026 Q3-Aug Oil");
  assert.equal(rows[2].simulationCount, 10);
  assert.equal(rows[0].simulationCount, null);
});

test("editing a cell above the diagonal mirrors it below, and the diagonal stays 1", () => {
  const matrix = squareTargetMatrix([[1, 0.2, 0.3], [9, 1, 0.4], [9, 9, 1]], 3);
  assert.deepEqual(matrix, [[1, 0.2, 0.3], [0.2, 1, 0.4], [0.3, 0.4, 1]], "the upper triangle is authoritative");
  const edited = setTargetCorrelation(matrix, 0, 2, -0.5);
  assert.equal(edited[0][2], -0.5);
  assert.equal(edited[2][0], -0.5);
  assert.equal(setTargetCorrelation(matrix, 1, 1, 0.5)[1][1], 1);
  assert.equal(matrix[0][2], 0.3, "the original is not changed");
  assert.deepEqual(squareTargetMatrix([], 2), [[1, 0], [0, 1]]);
});

test("values outside -1..1 are refused with the reason", () => {
  assert.deepEqual(parseCorrelationInput("0.38"), { ok: true, value: 0.38 });
  assert.deepEqual(parseCorrelationInput("-1"), { ok: true, value: -1 });
  assert.deepEqual(parseCorrelationInput("38%"), { ok: true, value: 0.38 });
  assert.deepEqual(parseCorrelationInput(""), { ok: true, value: 0 });
  assert.match(parseCorrelationInput("1.2").error, /outside -1 to 1/u);
  assert.match(parseCorrelationInput("-101%").error, /outside -1 to 1/u);
  assert.match(parseCorrelationInput("abc").error, /not a number/u);
});

test("the correlations follow their segments through a move, a removal and an addition", () => {
  const matrix = [[1, 0.1, 0.2], [0.1, 1, 0.3], [0.2, 0.3, 1]];
  assert.deepEqual(reorderTargetMatrix(matrix, [1, 0, 2]), [[1, 0.1, 0.3], [0.1, 1, 0.2], [0.3, 0.2, 1]]);
  assert.deepEqual(reorderTargetMatrix(matrix, [0, 2]), [[1, 0.2], [0.2, 1]]);
  assert.deepEqual(reorderTargetMatrix(matrix, [0, 1, 2, -1])[3], [0, 0, 0, 1]);
});

test("each correlation option stands for its own matrix, and Used converts it", () => {
  const settings = readConsolidationSettings(sampleMethod());
  const byOption = (option) => optionTargetMatrix({ ...settings, correlationOption: option });
  assert.deepEqual(byOption("independent"), [[1, 0, 0], [0, 1, 0], [0, 0, 1]]);
  assert.deepEqual(byOption("as_generated"), byOption("independent"));
  assert.deepEqual(byOption("fully_correlated")[0], [1, 1, 1]);
  assert.equal(byOption("specified")[0][2], 0.38);
  assert.equal(SCON_CORRELATION_OPTIONS.length, 4);

  const used = usedCorrelationMatrix(settings);
  assert.ok(Math.abs(used.matrix[0][2] - 0.395315) < 1e-6, "2·sin(π·ρ/6) of 0.38");
  assert.equal(used.matrix[1][1], 1);
  assert.equal(used.repairNeeded, false);
  assert.ok(Math.abs(rankToLinear(1) - 1) < 1e-12);
  const full = usedCorrelationMatrix({ ...settings, correlationOption: "fully_correlated" });
  assert.equal(full.repairNeeded, true, "an all-ones matrix cannot be factored as it stands");
  const bad = usedCorrelationMatrix({ ...settings, targetCorrelations: [[1, 0.9, -0.9], [0.9, 1, 0.9], [-0.9, 0.9, 1]] });
  assert.equal(bad.repairNeeded, true);
});

test("the run chip reports not run, running, changed inputs, a changed segment and up to date", () => {
  assert.equal(consolidationRunState({ hasRun: false }).key, "not-run");
  assert.equal(consolidationRunState({ hasRun: false, running: true }).label, "Consolidating");
  assert.equal(consolidationRunState({ hasRun: true, settingsMatchRun: false, segmentChanged: true }).label, "Inputs changed — run again");
  assert.equal(consolidationRunState({ hasRun: true, settingsMatchRun: true, segmentChanged: true }).label, "A segment changed");
  assert.equal(consolidationRunState({ hasRun: true, settingsMatchRun: true }).label, "Up to date");

  const settings = readConsolidationSettings(sampleMethod());
  const snapshot = runInputSnapshot(settings);
  assert.equal(runInputSnapshot({ ...settings, name: "Other", outputType: "Other" }), snapshot, "name and output do not change a run");
  assert.notEqual(runInputSnapshot({ ...settings, randomSeed: 1 }), snapshot);
  assert.notEqual(runInputSnapshot({ ...settings, targetCorrelations: setTargetCorrelation(settings.targetCorrelations, 0, 1, 0.2) }), snapshot);
  assert.notEqual(runInputSnapshot({ ...settings, segments: settings.segments.slice().reverse() }), snapshot);
});

test("segment rows show each bootstrap's figures and why it cannot be consolidated", () => {
  const settings = readConsolidationSettings(sampleMethod());
  const info = segmentInfoMap([
    { reserving_class: `${BASE}\\BI Total`, method_name: "F 72 A", status: "current", has_run: true,
      simulation_count: 10000, base_triangle_type: "Net Loss--Incurred", mean: 273917, standard_error: 56987, cv: 0.208 },
    { reserving_class: `${BASE}\\CMPxCAT`, method_name: "F 72 A", status: "changed", has_run: true,
      simulation_count: 5000, base_triangle_type: "Paid Loss", mean: 1, standard_error: 1, cv: 1 },
    { reserving_class: `${BASE}\\PD+UMPD`, method_name: "F 72 A", status: "missing", problems: ["missing"] },
  ]);
  const rows = segmentRows(settings, info, { hasRun: true });
  assert.equal(rows[0].shortLabel, "BI Total");
  assert.equal(rows[0].mean, 273917);
  assert.deepEqual(rows[0].issues, []);
  assert.deepEqual(rows[1].issues.map((issue) => issue.kind), ["simulation_count_mismatch", "base_type_mismatch"]);
  assert.match(rows[1].issues[0].text, /Runs 5,000 simulations; BI Total runs 10,000/u);
  assert.equal(rows[1].note, "Changed since the last run.");
  assert.deepEqual(rows[2].issues.map((issue) => issue.kind), ["missing"]);
  assert.equal(commonSimulationCount(rows).text, "Segments disagree");
  assert.equal(commonSimulationCount(rows.slice(0, 1)).text, (10000).toLocaleString());

  const duplicate = segmentRows({ ...settings, segments: [settings.segments[0], settings.segments[0]] }, info);
  assert.deepEqual(duplicate[1].issues.map((issue) => issue.kind), ["duplicate"]);
  assert.equal(segmentRows(settings, info, { hasRun: false })[1].note, "", "no stale note before any run");

  assert.deepEqual(baseTypeChoices(settings, info).map((item) => item.value), ["", "Net Loss--Incurred", "Paid Loss"]);
  const candidates = [
    { reserving_class: `${BASE}\\BI Total`, method_name: "f 72 a" },
    { reserving_class: `${BASE}\\COL`, method_name: "F 72 A" },
  ];
  assert.deepEqual(availableCandidates(candidates, settings).map(segmentShortLabel), ["COL"]);
});

test("the results reuse the reserve-range views without DFM columns", () => {
  const method = sampleMethod();
  const view = resultsView(method, { basis: "scaled", measure: "reserves" });
  assert.equal(view.hasDfm, false);
  assert.equal(view.total.latest, 300);
  assert.equal(view.rows[0].percentile(50), 18);
  assert.deepEqual(
    summaryTableColumns("reserves", [50], { dfm: view.hasDfm }).map((column) => column.label),
    ["Latest", "Mean Reserve", "Std. Deviation", "CV", "50%", "Mean Ultimate"],
  );
  assert.equal(
    resultsClipboardText(view, { percentiles: [50] }).split("\r\n")[0],
    "Origin\tLatest\tMean Reserve\tStd. Deviation\tCV\t50%\tMean Ultimate",
  );
  assert.equal(resultsView(method, { measure: "ultimates" }).rows[1].mean, 250);
});

test("the segment breakdown names each segment's share and the diversification", () => {
  const breakdown = segmentBreakdown(sampleMethod());
  assert.deepEqual(breakdown.rows.map((row) => row.shortLabel), ["BI Total", "CMPxCAT", "PD+UMPD"]);
  assert.equal(breakdown.rows[2].factor, 0.5);
  assert.equal(breakdown.total.mean, 70);
  assert.equal(breakdown.total.sd, 14);
  assert.equal(breakdown.total.share, 1);
  assert.equal(breakdown.standaloneSd, 20);
  assert.equal(breakdown.benefit, 6);
  assert.equal(breakdown.benefitRatio, 0.3);
  assert.equal(segmentBreakdown({}), null);
});

test("the page carries every tab and control the design names", async () => {
  const html = await read("ui/method_pages/stochastic_consolidation/stochastic_consolidation.html");
  for (const id of [
    "sconConsolidateBtn", "sconSaveBar", "sconBaseTypeButton", "sconSeedInput", "sconNewSeedBtn",
    "sconSimulationCountInput", "sconAddSegmentBtn", "sconMoveUpBtn", "sconMoveDownBtn", "sconRemoveSegmentBtn",
    "sconCorrelationControl", "sconDependencyButton", "sconDegreesInput", "sconMatrixViewControl",
    "sconMeasureControl", "sconPercentileInput", "sconFullLadderInput", "sconCopyResultsBtn",
    "sconDistributionChart", "sconFanChart", "sconBreakdownBody", "sconEmptyConsolidateBtn",
  ]) {
    assert.match(html, new RegExp(`id="${id}"`, "u"), `${id} is on the page`);
  }
  assert.doesNotMatch(html, /sconBasisControl/u, "a consolidation has no Scaled / Unscaled switch");
});
