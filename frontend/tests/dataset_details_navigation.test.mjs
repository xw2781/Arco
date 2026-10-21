import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";

const dependenciesSource = await readFile(
  new URL("../ui/shared/tabs/details/details_dependencies.js", import.meta.url),
  "utf8",
);
const dependenciesCss = await readFile(
  new URL("../ui/shared/tabs/details/details_dependencies.css", import.meta.url),
  "utf8",
);

test("a Details map box requests method-aware routing", () => {
  assert.match(dependenciesSource, /onOpenEntry: \(entry\) => openRelated\(entry, \{ openMethod: true \}\)/u);
  assert.match(dependenciesSource, /"cape cod": "Cape Cod"/u);
  assert.match(dependenciesSource, /getBerquistShermanContract\(text\)\?\.methodType/u);
});

test("the formula names its sources as quoted text and leaves opening them to the map", () => {
  const formulaComponent = dependenciesSource.match(
    /function appendFormulaComponent[\s\S]*?\r?\n  \}\r?\n/u,
  )?.[0] || "";

  // Plain text, not a control: nothing the user can activate, and the quotes are
  // always drawn so a name containing spaces reads as one operand.
  assert.match(formulaComponent, /doc\.createElement\("span"\)/u);
  assert.match(formulaComponent, /`"\$\{String\(label \?\? ""\)\.trim\(\)\}"`/u);
  assert.doesNotMatch(formulaComponent, /addEventListener|createElement\("button"\)|openRelated/u);

  const component = dependenciesCss.match(/\.arDetailsFormulaComponent \{[^}]*\}/u)?.[0] || "";
  // Read-only colour: the field is display-only, its formula belonging to the
  // dataset type in Project Settings.
  assert.match(component, /color:\s*var\(--ar-details-readonly-color/u);
  assert.doesNotMatch(component, /cursor:\s*pointer|text-decoration/u);
});

test("Project Instance falls back to Dataset Viewer when method-aware routing finds no method", async () => {
  const messagesSource = await readFile(
    new URL("../ui/project_instance/project_instance_messages.js", import.meta.url),
    "utf8",
  );
  const handler = messagesSource.match(
    /function handleOpenDependentDataset[\s\S]*?function handleAutomationWindowCommand/u,
  )?.[0] || "";

  assert.match(handler, /const openMethod = !!message\?\.openMethod/u);
  assert.match(handler, /else \{\s*frame = openDatasetWindow\(datasetName,/u);
});

// Every Details tab: [page script, markup, element-id prefix, method type the
// middle box is labelled with]. The Dataset Viewer's middle box is a dataset.
const DETAILS_HOSTS = [
  ["../ui/shared/tabs/data/data_tab_details_controller.js", "../ui/dataset_viewer/dataset_viewer_view.js", "ds", null],
  ["../ui/method_pages/dfm/dfm_details_dependencies.js", "../ui/method_pages/dfm/dfm.html", "dfm", '"DFM"'],
  ["../ui/method_pages/bornhuetter_ferguson/bornhuetter_ferguson_main.js", "../ui/method_pages/bornhuetter_ferguson/bornhuetter_ferguson.html", "bf", '"Bornhuetter Ferguson"'],
  ["../ui/method_pages/cape_cod/cape_cod_main.js", "../ui/method_pages/cape_cod/cape_cod.html", "cc", '"Cape Cod"'],
  ["../ui/method_pages/result_selection/result_selection_main.js", "../ui/method_pages/result_selection/result_selection.html", "rs", '"Result Selection"'],
  ["../ui/method_pages/berquist_sherman/berquist_sherman_main.js", "../ui/method_pages/berquist_sherman/berquist_sherman.html", "bs", "contract?.methodType"],
  ["../ui/method_pages/bootstrap/bootstrap_main.js", "../ui/method_pages/bootstrap/bootstrap.html", "bst", '"Bootstrap"'],
  ["../ui/method_pages/stochastic_consolidation/stochastic_consolidation_main.js", "../ui/method_pages/stochastic_consolidation/stochastic_consolidation.html", "scon", '"Stochastic Consolidation"'],
];
const escapeRe = (text) => text.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");

test("every Details tab draws one Dependencies map through the shared owner", async () => {
  for (const [scriptPath, markupPath, prefix, methodType] of DETAILS_HOSTS) {
    const source = await readFile(new URL(scriptPath, import.meta.url), "utf8");
    assert.match(source, /shared\/tabs\/details\/details_dependencies\.js\?v=20261020b/u, scriptPath);
    assert.match(source, new RegExp(`dependencyMap: "${prefix}DependencyMap"`, "u"), scriptPath);
    if (methodType) {
      assert.match(source, new RegExp(`getSelfMethodType: \\(\\) => ${escapeRe(methodType)}`, "u"), scriptPath);
    }
    // Only the owner reads the sidecar graph: no page picks the v4 lower-case
    // `precedents` / `dependents` off a payload itself, and none still reads
    // the retired Title Case keys or names a chip list.
    assert.doesNotMatch(source, /\.(?:Precedents|Dependents|precedents|dependents)\b|precedentsList|dependentsList/u, scriptPath);

    const markup = await readFile(new URL(markupPath, import.meta.url), "utf8");
    assert.match(markup, new RegExp(`id="${prefix}DependencyMap" class="arDetailsDepMap"`, "u"), markupPath);
    assert.doesNotMatch(markup, /arDetailsChipBox|arDetailsChipList|PrecedentsList|DependentsList/u, markupPath);
    if (markupPath.endsWith(".html")) {
      assert.match(markup, /\/ui\/shared\/styles\/dependency_families\.css\?v=\d{8}[a-z]/u, markupPath);
      assert.match(markup, /\/ui\/shared\/tabs\/details\/details_dependencies\.css\?v=20261020c/u, markupPath);
    }
  }
  // The shared module owns the map and the open-graph request; no chip code is left.
  assert.match(dependenciesSource, /from "\.\/details_dependency_map\.js\?v=20261020b"/u);
  assert.doesNotMatch(dependenciesSource, /buildChip|renderChipList|arDetailsChipBox/u);
  assert.doesNotMatch(dependenciesCss, /\.arDetailsChip\b|\.arDetailsChipBox|\.arDetailsChipList|\.arDetailsCalculatedIcon/u);
});

test("a method page reads its graph for the dataset it publishes, not for the method", async () => {
  // The sidecar graph is keyed by dataset name. A method page that asked for
  // its own method name would silently render an empty pair of rows.
  assert.match(dependenciesSource, /export async function loadDetailsDependencies/u);
  assert.match(dependenciesSource, /"\/dataset\/sidecar\/load"/u);
  assert.match(dependenciesSource, /precedents: normalizeDependencyEntries\(payload\.precedents\)/u);
  assert.match(dependenciesSource, /dependents: normalizeDependencyEntries\(payload\.dependents\)/u);

  const dfmSource = await readFile(
    new URL("../ui/method_pages/dfm/dfm_details_dependencies.js", import.meta.url),
    "utf8",
  );
  assert.match(dfmSource, /datasetName: outputDatasetName/u);

  const persistence = await readFile(
    new URL("../ui/method_pages/dfm/dfm_persistence.js", import.meta.url),
    "utf8",
  );
  // Both the load and the save resolve the output identity, and both repaint.
  const refreshes = persistence.split("refreshDfmDetailsDependencies(currentDfmOutputDataset)").length - 1;
  assert.equal(refreshes, 2);
});

test("no page keeps its own copy of the dependency map or formula rendering", async () => {
  const featureDirs = [
    "../ui/dataset_viewer/",
    "../ui/method_pages/dfm/",
    "../ui/method_pages/bornhuetter_ferguson/",
    "../ui/method_pages/cape_cod/",
    "../ui/method_pages/result_selection/",
    "../ui/method_pages/berquist_sherman/",
    "../ui/method_pages/bootstrap/",
    "../ui/method_pages/stochastic_consolidation/",
  ];
  for (const dir of featureDirs) {
    const dirUrl = new URL(dir, import.meta.url);
    for (const entry of await readdir(dirUrl, { withFileTypes: true })) {
      if (!entry.isFile() || !entry.name.endsWith(".css")) continue;
      const css = await readFile(new URL(entry.name, dirUrl), "utf8");
      assert.doesNotMatch(
        css,
        /\.arDetailsDepMap|\.arDetailsDepNode|\.arDetailsFormulaBox|\.arDetailsFormulaComponent/u,
        `${dir}${entry.name} must not restate the shared dependency look`,
      );
    }
  }
});

test("a Details map opens the full Dependency Graph through the Project Instance page", async () => {
  const { requestDependencyGraph } = await import("../ui/shared/tabs/details/details_dependency_map.js");
  const posted = [];
  requestDependencyGraph({
    windowRef: { parent: { postMessage: (message, origin) => posted.push([message, origin]) } },
    instanceId: "pi_ds_1",
    reservingClass: " Fake\\NJ ",
    datasetName: " Paid Loss ",
  });
  assert.deepEqual(posted, [[{
    type: "arcrho:project-instance-open-dependency-graph",
    inst: "pi_ds_1",
    reservingClass: "Fake\\NJ",
    focusDatasetName: "Paid Loss",
  }, "*"]]);

  const host = await readFile(
    new URL("../ui/project_instance/project_instance_dependency_graph.js", import.meta.url),
    "utf8",
  );
  assert.match(host, /openDependencyGraph\(\{ path: event\.data\.reservingClass, focus: event\.data\.focusDatasetName \}\)/u);
  assert.match(host, /if \(focus\) params\.set\("focus", focus\)/u);

  const graph = await readFile(new URL("../ui/project_instance/dependency_graph_window.js", import.meta.url), "utf8");
  assert.match(graph, /let pendingFocus = dependencyGraphKey\(params\.get\("focus"\)\)/u);
  assert.match(graph, /applyGraph\(\{ keepViewport \}\);\s*applyPendingFocus\(\);/u);
});

test("the dependency map labels a box the way the full graph labels its node", async () => {
  const { dependencyMapNodeKind, dependencyMapEdgePath } = await import("../ui/shared/tabs/details/details_dependency_map.js");
  assert.deepEqual(dependencyMapNodeKind({}), { family: "dataset", label: "Dataset" });
  assert.deepEqual(dependencyMapNodeKind({ formula: "\"A\" + \"B\"" }), { family: "calculated", label: "Calculated" });
  assert.deepEqual(dependencyMapNodeKind({ methodType: "DFM" }), { family: "method", label: "DFM" });
  assert.equal(
    dependencyMapEdgePath({ right: 10, top: 0, height: 20 }, { left: 50, top: 40, height: 20 }),
    "M10 10C30 10,30 50,50 50",
  );
});
