import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const frontendRoot = new URL("../", import.meta.url);

async function source(relativePath) {
  return readFile(new URL(relativePath, frontendRoot), "utf8");
}

test("Result Selection stops offering a Ratio Basis Add box at three datasets", async () => {
  const [html, ui] = await Promise.all([
    source("ui/method_pages/result_selection/result_selection.html"),
    source("ui/method_pages/result_selection/result_selection_ui.js"),
  ]);

  // Ratio Basis is chosen on the Data Flow map, which drops the Add box at
  // the slot's maximum.
  assert.doesNotMatch(html, /rsRatioBasisAddBtn|rsRatioBasisList/u);
  assert.match(ui, /label: "Ratio Basis",\s*multiple: true,\s*max: MAX_RATIO_BASIS_COUNT,/u);
});
