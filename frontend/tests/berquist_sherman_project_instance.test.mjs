import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const contractSource = await readFile(
  new URL("../ui/shared/dataset/berquist_sherman_contract.js", import.meta.url),
  "utf8"
);
const {
  BERQUIST_SHERMAN_VARIANTS,
  berquistShermanDisplayLabel,
  getBerquistShermanContract,
  normalizeBerquistShermanVariant,
} = await import(`data:text/javascript;base64,${Buffer.from(contractSource).toString("base64")}`);
const { dependencyMapNodeKind } = await import("../ui/shared/tabs/details/details_dependency_map.js");

const [
  htmlSource,
  cacheSource,
  tableSource,
  windowsSource,
  messagesSource,
  detailsDependenciesSource,
  indexServiceSource,
  sidecarStatusSource,
  migrationCoreSource,
  methodPageSource,
] = await Promise.all([
  readFile(new URL("../ui/project_instance/project_instance.html", import.meta.url), "utf8"),
  readFile(new URL("../ui/project_instance/project_instance_dataset_cache.js", import.meta.url), "utf8"),
  readFile(new URL("../ui/project_instance/project_instance_dataset_table.js", import.meta.url), "utf8"),
  readFile(new URL("../ui/project_instance/project_instance_windows.js", import.meta.url), "utf8"),
  readFile(new URL("../ui/project_instance/project_instance_messages.js", import.meta.url), "utf8"),
  readFile(new URL("../ui/shared/tabs/details/details_dependencies.js", import.meta.url), "utf8"),
  readFile(new URL("../app_server/services/dataset_instance_index_service.py", import.meta.url), "utf8"),
  readFile(new URL("../app_server/services/dataset_sidecar_status_service.py", import.meta.url), "utf8"),
  readFile(new URL("../../python-api/migration/resq_migration/core.py", import.meta.url), "utf8"),
  readFile(new URL("../ui/method_pages/berquist_sherman/berquist_sherman_main.js", import.meta.url), "utf8"),
]);

test("Berquist Sherman variants share one canonical frontend contract", () => {
  assert.deepEqual(BERQUIST_SHERMAN_VARIANTS, ["sr", "cra"]);
  assert.deepEqual(getBerquistShermanContract("sr"), {
    variant: "sr",
    methodType: "B&S Settlement Rate Adjustment",
    displayLabel: "Berquist Sherman SR",
    sourceKind: "berquist_sherman_sr",
    filenamePrefix: "BSSR@",
    jsonFormat: "arcrho-berquist-sherman-sr-v4",
  });
  assert.deepEqual(getBerquistShermanContract("cra"), {
    variant: "cra",
    methodType: "B&S Case Reserve Adequacy Adjustment",
    displayLabel: "Berquist Sherman CRA",
    sourceKind: "berquist_sherman_cra",
    filenamePrefix: "BSCRA@",
    jsonFormat: "arcrho-berquist-sherman-cra-v4",
  });
  assert.equal(normalizeBerquistShermanVariant("B&S Settlement Rate Adjustment"), "sr");
  assert.equal(normalizeBerquistShermanVariant("berquist_sherman_cra"), "cra");
  // The label a user sees resolves back to the same variant, so a display
  // string can never break window routing or an Add command.
  assert.equal(normalizeBerquistShermanVariant("Berquist Sherman CRA"), "cra");
  assert.equal(berquistShermanDisplayLabel("B&S Settlement Rate Adjustment"), "Berquist Sherman SR");
  assert.equal(berquistShermanDisplayLabel("DFM"), "DFM");
});

test("every B&S surface shows the ResQ label and persists the canonical identity", () => {
  // The Project Instance table, the Add menu, the floating window title, and
  // the method page all read the display label...
  assert.match(tableSource, /case "methodType":\s*\n\s*return berquistShermanDisplayLabel\(getMethodType\(row\)\)/u);
  assert.match(windowsSource, /const title = `\$\{targetPath\}\\\\\$\{contract\.displayLabel\}\\\\\$\{name\}`/u);
  assert.match(methodPageSource, /els\.methodTypeInput\.value = contract\.displayLabel/u);
  assert.match(methodPageSource, /document\.title = name \? `\$\{name\} - \$\{contract\.displayLabel\}`/u);
  // ...while every persisted field keeps the canonical method type.
  assert.match(windowsSource, /frame\.dataset\.windowMethodType = contract\.methodType/u);
  assert.match(methodPageSource, /method_type: contract\.methodType/u);
  assert.doesNotMatch(methodPageSource, /method_type: contract\.displayLabel/u);
});

test("Project Instance filter menus use the index-backed render context", () => {
  assert.match(
    tableSource,
    /function openDatasetTableFilterPopover\([\s\S]*?const context = buildDatasetTableRenderContext\(\);[\s\S]*?getDatasetColumnOptions\(key, context\)/u,
  );
});

test("Project Instance exposes two direct annual-triangle Add commands", () => {
  assert.match(htmlSource, /data-row-action="add-berquist-sherman-sr">Berquist Sherman SR</u);
  assert.match(htmlSource, /data-row-action="add-berquist-sherman-cra">Berquist Sherman CRA</u);
  assert.doesNotMatch(htmlSource, /data-row-action="add-bsm"/u);
  assert.match(tableSource, /getDatasetRecordValue\(record, "dataFormat"\)\) === "triangle"/u);
  assert.match(tableSource, /\["", "none"\]\.includes\(normalizeLookupKey\(getDatasetRecordValue\(record, "methodType"\)\)\)/u);
  assert.match(tableSource, /originLength === 12/u);
  assert.match(tableSource, /developmentLength === 12/u);
  assert.match(cacheSource, /meta\.developmentLength = Math\.trunc\(developmentLength\)/u);
  assert.match(tableSource, /fresh:\s*true[\s\S]*?inputTriangle:\s*datasetName[\s\S]*?variant:\s*contract\.variant/u);
});

test("Project Instance routes and restores shared Berquist Sherman windows", () => {
  assert.match(windowsSource, /kind:\s*"berquist_sherman"/u);
  assert.match(windowsSource, /\/ui\/method_pages\/berquist_sherman\/berquist_sherman\.html/u);
  assert.match(windowsSource, /params\.set\("variant", variant\)/u);
  assert.match(windowsSource, /params\.set\("fresh", "1"\)/u);
  assert.match(windowsSource, /params\.set\("input_triangle", toText\(options\.inputTriangle\)\)/u);
  assert.match(windowsSource, /bsTab:\s*kind === "berquist_sherman"/u);
  assert.match(windowsSource, /bsVariant:\s*kind === "berquist_sherman"/u);
  assert.match(messagesSource, /msg\.type === "arcrho:berquist-sherman-tab-changed"/u);
  assert.match(messagesSource, /frame\.dataset\.bsTab = toText\(msg\.tab \|\| ""\)/u);
  assert.match(messagesSource, /openMethod && bsVariant/u);
  assert.match(
    windowsSource,
    /kind === "berquist_sherman"[\s\S]*?openBerquistShermanWindow\(name,\s*\{\s*path:\s*item\?\.path/u,
  );
});

test("a successful B&S draft save rekeys the same Project Instance window to its output name", () => {
  assert.match(
    methodPageSource,
    /type:\s*"arcrho:project-instance-refresh-datasets"[\s\S]*?inst,[\s\S]*?savedDatasetName:\s*details\.name,[\s\S]*?variant/u,
  );
  assert.match(
    messagesSource,
    /msg\.type === "arcrho:project-instance-refresh-datasets"[\s\S]*?syncBerquistShermanWindowIdentity\([\s\S]*?savedDatasetName/u,
  );
  assert.match(windowsSource, /function syncBerquistShermanWindowIdentity\(frame, datasetName, variant = ""\)/u);
  assert.match(windowsSource, /datasetWindows\.delete\(previousKey\)/u);
  assert.match(windowsSource, /frame\.dataset\.windowKey = nextKey/u);
  assert.match(windowsSource, /frame\.dataset\.windowDatasetName = name/u);
  assert.match(windowsSource, /frame\.dataset\.windowItemName = name/u);
  assert.match(windowsSource, /datasetWindows\.set\(nextKey, frame\)/u);
});

test("the shared method page uses the routed tab and generic lifecycle messages", () => {
  assert.match(methodPageSource, /from "\/ui\/shared\/dataset\/berquist_sherman_contract\.js"/u);
  assert.match(methodPageSource, /type:\s*"arcrho:berquist-sherman-tab-changed"/u);
  assert.match(methodPageSource, /type:\s*"arcrho:dataset-dirty"/u);
  assert.match(methodPageSource, /message\.type === "arcrho:dataset-save"/u);
  assert.match(methodPageSource, /messageType:\s*"arcrho:dataset-close-confirmed"/u);
});

test("method JSON and shared Data-tab links retain the canonical B&S method identity", () => {
  assert.match(messagesSource, /filename = `\$\{contract\.filenamePrefix\}\$\{namePart\}\.json`/u);
  // The routing that turns a persisted method_type into a B&S contract now lives
  // in the shared Details dependency surface, which every method page uses too.
  assert.match(detailsDependenciesSource, /getBerquistShermanContract\(text\)\?\.methodType/u);
  // A Dependencies map box is labelled the way the full graph labels its node,
  // which reads the B&S display label from the contract.
  assert.match(detailsDependenciesSource, /from "\.\/details_dependency_map\.js\?v=\d{8}[a-z]"/u);
  assert.equal(dependencyMapNodeKind({ methodType: "B&S Settlement Rate Adjustment" }).label, "Berquist Sherman SR");
});

test("app-server and migration adapters retain every canonical frontend contract value", () => {
  for (const variant of BERQUIST_SHERMAN_VARIANTS) {
    const contract = getBerquistShermanContract(variant);
    assert.ok(indexServiceSource.includes(contract.jsonFormat));
    assert.ok(indexServiceSource.includes(contract.filenamePrefix));
    assert.ok(sidecarStatusSource.includes(contract.methodType));
    assert.ok(sidecarStatusSource.includes(contract.sourceKind));
    assert.ok(migrationCoreSource.includes(contract.jsonFormat));
    assert.ok(migrationCoreSource.includes(contract.filenamePrefix));
    assert.ok(migrationCoreSource.includes(contract.methodType));
    assert.ok(migrationCoreSource.includes(contract.sourceKind));
  }
});
