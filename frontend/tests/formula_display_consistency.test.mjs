import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const moduleUrl = new URL("../ui/shared/tabs/details/details_dependencies.js", import.meta.url);
const moduleSource = await readFile(moduleUrl, "utf8");
// Loaded from disk so its relative import of the dependency map resolves.
const { formatDetailsFormulaText, formulaComponentNames, tokenizeDetailsFormula } = await import(moduleUrl.href);

const NAMES = [
  "C 32 - Reported DFM w/ Selected LDFs",
  "C 22 - CWOP DFM w/ Selected LDFs",
  "Paid Loss",
  "Paid Loss Ratio",
  "Earned Premium",
];

test("a stored formula reads the same whether or not it was written with quotes", () => {
  const quoted = '"C 32 - Reported DFM w/ Selected LDFs" - "C 22 - CWOP DFM w/ Selected LDFs"';
  const bare = "C 32 - Reported DFM w/ Selected LDFs - C 22 - CWOP DFM w/ Selected LDFs";
  const expected = '"C 32 - Reported DFM w/ Selected LDFs" - "C 22 - CWOP DFM w/ Selected LDFs"';

  assert.equal(formatDetailsFormulaText(quoted, NAMES), expected);
  assert.equal(formatDetailsFormulaText(bare, NAMES), expected);
});

test("a name is never split on the operators it contains", () => {
  // "C 22 - CWOP DFM w/ Selected LDFs" holds both `-` and `/`. Splitting the
  // text on operators without knowing the names turns one dataset into an
  // expression, and the Details tab then shows a formula that is not on disk.
  const bare = "C 32 - Reported DFM w/ Selected LDFs - C 22 - CWOP DFM w/ Selected LDFs";

  const tokens = tokenizeDetailsFormula(bare, NAMES);
  assert.deepEqual(
    tokens.filter((token) => token.type === "component").map((token) => token.value),
    ["C 32 - Reported DFM w/ Selected LDFs", "C 22 - CWOP DFM w/ Selected LDFs"],
  );

  // With no names to match, the formula is returned untouched rather than
  // guessed at - a wrong split is worse than an unstyled string.
  assert.equal(formatDetailsFormulaText(bare, []), bare);
  assert.deepEqual(tokenizeDetailsFormula(bare, []), [{ type: "text", value: bare }]);
});

test("the longest matching name wins, so a prefix name cannot shadow it", () => {
  assert.equal(
    formatDetailsFormulaText("Paid Loss Ratio + Paid Loss", NAMES),
    '"Paid Loss Ratio" + "Paid Loss"',
  );
});

test("operators and spacing are normalised, and an empty formula stays empty", () => {
  assert.equal(
    formatDetailsFormulaText("Paid Loss+Earned Premium", NAMES),
    '"Paid Loss" + "Earned Premium"',
  );
  assert.equal(formatDetailsFormulaText("", NAMES), "");
  assert.equal(formatDetailsFormulaText(null, NAMES), "");
});

test("precedent entries and extra names both feed the matcher", () => {
  const names = formulaComponentNames(
    [{ dataset_name: "Paid Loss", dataset_type_name: "Paid Loss" }],
    ["Earned Premium"],
  );
  assert.ok(names.includes("Paid Loss"));
  assert.ok(names.includes("Earned Premium"));
  // Longest first, or "Paid Loss" would match inside "Paid Loss Ratio".
  assert.deepEqual([...names].sort((a, b) => b.length - a.length), names);
});

test("all three surfaces render a formula through the one shared formatter", async () => {
  const [datasetTypesSource, datasetTableSource, detailsControllerSource] = await Promise.all([
    readFile(new URL("../ui/project_settings/project_settings_dataset_types.js", import.meta.url), "utf8"),
    readFile(new URL("../ui/project_instance/project_instance_dataset_table.js", import.meta.url), "utf8"),
    readFile(new URL("../ui/shared/tabs/data/data_tab_details_controller.js", import.meta.url), "utf8"),
  ]);

  // Project Settings Dataset Types and the Project Instance dataset table print
  // the formatted string; the Dataset Viewer paints the same tokens.
  for (const source of [datasetTypesSource, datasetTableSource]) {
    assert.match(source, /formatDetailsFormulaText/u);
    assert.match(source, /shared\/tabs\/details\/details_dependencies\.js/u);
  }
  assert.match(detailsControllerSource, /shared\/tabs\/details\/details_dependencies\.js/u);
  assert.match(moduleSource, /function renderFormulaTokens[\s\S]*?tokenizeDetailsFormula\(formula, names\)/u);

  // Both tables have to hand the matcher their dataset-type names, or an
  // unquoted name containing an operator cannot be recognised.
  assert.match(datasetTypesSource, /knownNames = \(rows \|\| \[\]\)/u);
  assert.match(datasetTableSource, /knownNames = state\.datasetRows\.map\(getDatasetName\)/u);
});

test("Project Settings keeps the stored formula for copy and for the row editor", async () => {
  const source = await readFile(
    new URL("../ui/project_settings/project_settings_dataset_types.js", import.meta.url),
    "utf8",
  );
  // Formatting is presentation only: the cell carries the raw text so a copy or
  // an edit round-trips what is actually stored.
  assert.match(source, /td\.dataset\.rawValue = raw/u);
  assert.match(source, /cell\.dataset\?\.rawValue \?\? cell\.textContent/u);
  assert.match(source, /dtEditFormula\.value = mode === "add" \? "" : String\(row\?\.\[4\] \?\? ""\)/u);
});

test("the Formula field is presented as read-only, because its formula lives in Dataset Types", async () => {
  const css = await readFile(
    new URL("../ui/shared/tabs/details/details_dependencies.css", import.meta.url),
    "utf8",
  );
  const box = css.match(/\.arDetailsFormulaBox \{[^}]*\}/u)?.[0] || "";
  assert.match(box, /background:\s*var\(--ar-details-readonly-background/u);
  assert.match(box, /cursor:\s*default/u);
});
