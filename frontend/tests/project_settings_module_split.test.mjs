import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (name) => readFile(new URL(`../ui/project_settings/${name}`, import.meta.url), "utf8");

const coordinator = await read("project_settings.js");
const tableColumns = await read("project_settings_table_columns.js");
const generalSettings = await read("project_settings_general_settings.js");
const projectMap = await read("project_settings_project_map.js");
const treeView = await read("project_settings_tree_view.js");
const projectOps = await read("project_settings_project_ops.js");
const duplicateJob = await read("project_settings_duplicate_job.js");
const fieldMapping = await read("project_settings_field_mapping.js");
const fieldMappingCss = await read("project_settings.css");
const fieldMappingFeatureCss = await read("project_settings_field_mapping.css");
const datasetTypes = await read("project_settings_dataset_types.js");
const datasetTypesCss = await read("project_settings_dataset_types.css");
const html = await read("project_settings.html");

const SPLIT_MODULES = [
  ["project_settings_table_columns.js", tableColumns],
  ["project_settings_general_settings.js", generalSettings],
  ["project_settings_project_map.js", projectMap],
  ["project_settings_tree_view.js", treeView],
  ["project_settings_project_ops.js", projectOps],
];

test("the coordinator delegates every split domain instead of reimplementing it", () => {
  for (const [name] of SPLIT_MODULES) {
    assert.ok(
      coordinator.includes(`/ui/project_settings/${name}?v=`),
      `project_settings.js does not import ${name}`,
    );
  }
  // Domain internals must not leak back into the coordinator.
  const movedDeclarations = [
    /function initTableColumnResizing\(/,
    /function normalizeBoundaryYmCanonical\(/,
    /function buildTreeData\(/,
    /function createFolderNode\(/,
    /function createProjectNode\(/,
    /function saveProjectData\(/,
    /function duplicateProject\(/,
    /function deleteFolder\(/,
  ];
  for (const pattern of movedDeclarations) {
    assert.doesNotMatch(coordinator, pattern, `${pattern} still lives in project_settings.js`);
  }
});

test("the project map document has exactly one owner", () => {
  // Only the store reads or writes the project map / folder-structure endpoints.
  const mapWriters = [coordinator, treeView, projectOps, tableColumns, generalSettings];
  for (const source of mapWriters) {
    assert.doesNotMatch(source, /fetch\w*\(`\/project_settings\/\$\{sourceKey\}/);
  }
  assert.match(projectMap, /let projectData = null;/);
  assert.match(projectMap, /let currentRevision = 0;/);
  assert.match(projectMap, /let treeData = null;/);
  for (const [name, source] of SPLIT_MODULES) {
    if (name === "project_settings_project_map.js") continue;
    assert.doesNotMatch(source, /^let projectData/m, `${name} keeps its own project map copy`);
    assert.doesNotMatch(source, /^let currentRevision/m, `${name} keeps its own revision copy`);
  }
  // Project ops reaches the registry only through the store's guarded writers.
  assert.match(projectOps, /store\.saveFolderStructure\(/);
  assert.match(projectOps, /store\.save\(/);
  assert.doesNotMatch(projectOps, /file_mtime/);
});

test("conflict and lock handling stays in the single map writer", () => {
  assert.match(projectMap, /res\.status === 409/);
  assert.match(projectMap, /res\.status === 423/);
  for (const [name, source] of SPLIT_MODULES) {
    if (name === "project_settings_project_map.js") continue;
    assert.doesNotMatch(source, /status === 409|status === 423/, `${name} duplicates conflict handling`);
  }
  assert.doesNotMatch(coordinator, /status === 409|status === 423/);
});

test("multi-step project operations keep their intended recovery policies", () => {
  // Disk folder first, then one authoritative project registry save.
  assert.match(
    projectOps,
    /createProjectInFolder[\s\S]*create_project_folder[\s\S]*saveFolderStructure[\s\S]*rollbackProjectFolder\("delete_project_folder"/,
  );
  assert.match(
    projectOps,
    /renameProject[\s\S]*rename_project_folder[\s\S]*saveFolderStructure[\s\S]*rollbackProjectFolder\("rename_project_folder", \{ old_name: newName, new_name: oldName \}\)/,
  );
  const duplicateBlock = projectOps.slice(
    projectOps.indexOf("async function duplicateProject("),
    projectOps.indexOf("async function deleteProject("),
  );
  assert.match(duplicateBlock, /duplicate_project_folder[\s\S]*completePendingDuplicate/);
  assert.match(duplicateBlock, /saveFolderStructure/);
  assert.doesNotMatch(duplicateBlock, /rollbackProjectFolder|delete_project_folder/);
});

test("duplicate recovery is wired into page load and the standard close contract", () => {
  assert.match(projectOps, /project_settings_duplicate_job\.js\?v=20260927smb18/);
  assert.match(coordinator, /await loadProjectData\(DEFAULT_SOURCE\);[\s\S]*resumePendingDuplicateProject\(\)/);
  assert.match(coordinator, /window\.__arcrho_request_close = \(\) => projectOpsFeature\.requestClose\(\)/);
  assert.match(coordinator, /e\.origin !== window\.location\.origin \|\| e\.source !== window\.parent/);
  assert.match(duplicateJob, /cache: "no-store"/);
});

test("the Project Explorer owns only view state", () => {
  assert.match(treeView, /arcrho_project_settings_expanded_folders_v1/);
  assert.match(treeView, /arcrho_project_settings_selected_project_v1/);
  assert.match(treeView, /LOCAL_PROJECT_PREFS_ENDPOINT = "\/local-project\/preferences"/);
  assert.doesNotMatch(coordinator, /arcrho_project_settings_expanded_folders_v1/);
  assert.doesNotMatch(coordinator, /local-project\/preferences/);
  // Rendering reads the tree through the store rather than holding its own copy.
  assert.match(treeView, /const treeData = getTreeData\(\);/);
});

test("boundary-month parsing and General Settings I/O have one home", () => {
  assert.match(generalSettings, /export function normalizeBoundaryYmCanonical\(/);
  assert.match(generalSettings, /"\/general_settings"/);
  assert.match(generalSettings, /\/general_settings\?project_name=/);
  for (const [name, source] of SPLIT_MODULES) {
    if (name === "project_settings_general_settings.js") continue;
    assert.doesNotMatch(source, /general_settings/, `${name} talks to General Settings directly`);
  }
  assert.doesNotMatch(coordinator, /\/general_settings/);
  assert.match(coordinator, /generalSettingsFeature\.ensureLoaded\(/);
  assert.match(coordinator, /generalSettingsFeature\.bindEditor\(project\)/);
});

test("Field Mapping is a step of the Import Settings window, not a tab", () => {
  // The table lives in the import window; the tab and its Save button are gone.
  assert.match(html, /<div class="sd-import-body sd-import-mapping" id="sdImportMapping" data-step="mapping" hidden>[\s\S]*id="fieldMappingBody"/);
  assert.doesNotMatch(html, /data-ribbon="field-mapping"|id="ribbonFieldMapping"|id="saveFieldMappingBtn"/);
  assert.doesNotMatch(coordinator, /ribbonFieldMapping|saveFieldMappingBtn/);
  // The window saves only a changed mapping, and a saved column the source lost counts as a change.
  assert.match(fieldMapping, /const savedFieldMappingByProject = new Map\(\);/);
  assert.match(fieldMapping, /return getMissingMappedFields\(projectName\)\.length > 0 \|\| currentFieldNames\.some/);
  assert.match(fieldMapping, /if \(!hasUnsavedFieldMappingChanges\(project\.name\)\) return \{ ok: true, saved: false, error: "" \};/);
  assert.match(fieldMapping, /captureSavedFieldMapping\(project\.name, rows\);/);
  // Closing the window drops unsaved edits by re-reading the saved mapping.
  assert.match(coordinator, /onMappingDiscard: \(\) => fieldMappingFeature\?\.ensureFieldMappingLoaded\(selectedProject\?\.name, \{ force: true \}\)/);
});

test("Field Mapping Level uses the shared stepper without wheel edits", () => {
  assert.match(html, /shared\/components\/spreadsheet\/numeric_stepper\.css\?v=/);
  assert.match(fieldMapping, /field-mapping-level-stepper/);
  assert.match(fieldMapping, /levelUpButton\.addEventListener\("click", \(\) => adjustLevel\(1\)\)/);
  assert.match(fieldMapping, /levelDownButton\.addEventListener\("click", \(\) => adjustLevel\(-1\)\)/);
  assert.match(fieldMapping, /levelInput\.addEventListener\("wheel", \(e\) => e\.preventDefault\(\), \{ passive: false \}\)/);
  assert.doesNotMatch(fieldMapping, /adjustLevelByWheel|levelTd\.addEventListener\("wheel"/);
  assert.match(fieldMappingFeatureCss, /\.field-mapping-level-stepper > input\[type="number"\][\s\S]*border: 0;[\s\S]*border-radius: 0;/);
  assert.match(fieldMappingFeatureCss, /\.field-mapping-level-stepper \.decimalPlacesStepper[\s\S]*width: 22px;[\s\S]*border-radius: 0;/);
});

test("Field Mapping Significance cells indicate their dropdown behavior", () => {
  assert.match(
    fieldMappingFeatureCss,
    /td:has\(input\[data-role="significance"\]\)[\s\S]*cursor: pointer;/,
  );
});

test("Dataset Type Data Format is a closed Triangle or Vector choice", () => {
  const control = html.match(/<select id="dtEditDataFormat"[\s\S]*?<\/select>/u)?.[0] || "";
  assert.ok(control, "Data Format must use a select control");
  assert.match(control, /<option value="Triangle">Triangle<\/option>/u);
  assert.match(control, /<option value="Vector">Vector<\/option>/u);
  assert.doesNotMatch(control, /type="text"/u);
  assert.match(datasetTypes, /Array\.from\(dtEditDataFormat\?\.options \|\| \[\]\)[\s\S]*option\.value === dataFormatValue/u);
});

test("Dataset Type Data Format opens an app-styled list instead of the native popup", () => {
  // The select stays the value store; the shared sd-select primitives draw it.
  assert.match(html, /<div class="sd-select dt-format-select" id="dtFormatSelect">/u);
  assert.match(html, /<select id="dtEditDataFormat" required tabindex="-1" aria-hidden="true">/u);
  assert.match(html, /class="sd-select-trigger"[\s\S]*id="dtFormatTrigger"[\s\S]*aria-haspopup="listbox"/u);
  assert.match(html, /id="dtFormatList" role="listbox"/u);
  assert.match(datasetTypes, /formatSelect\.setValue\(mode === "add" \? "" : String\(row\?\.\[1\] \?\? ""\)\)/u);
  assert.doesNotMatch(datasetTypes, /dtEditDataFormat\.value =/u);
  // A native select popup cannot be themed, so no editor field may rely on one.
  assert.doesNotMatch(fieldMappingCss, /\.rct-row-editor-body select/u);
  assert.match(datasetTypesCss, /\.rct-row-editor-body \.dt-format-select \.sd-select-trigger \{[\s\S]*height: 30px;/u);
});

test("Dataset Type Category is an editable existing-value combobox with new-category feedback", () => {
  assert.match(html, /id="dtEditCategory"[\s\S]*role="combobox"[\s\S]*aria-autocomplete="list"/u);
  assert.match(html, /id="dtCategoryList" role="listbox"/u);
  assert.match(html, /id="dtCategoryNewTip" role="status" hidden/u);
  assert.match(datasetTypes, /categoryCombo\.setOptions\(state\.rows\.map\(\(item\) => item\?\.\[2\]\)\)/u);
  assert.match(datasetTypes, /const categoryValue = categoryCombo\.getValue\(\);/u);
  assert.match(datasetTypesCss, /\.dt-category-new-tip \{[\s\S]*position: fixed;[\s\S]*box-shadow:/u);
});

test("each split module remains bounded", () => {
  const lineCount = (source) => source.split("\n").length;
  assert.ok(lineCount(coordinator) < 1800, `coordinator is ${lineCount(coordinator)} lines`);
  for (const [name, source] of SPLIT_MODULES) {
    const limit = name === "project_settings_project_ops.js" ? 1050 : 700;
    assert.ok(lineCount(source) < limit, `${name} is ${lineCount(source)} lines`);
  }
  assert.ok(lineCount(duplicateJob) < 300, `project_settings_duplicate_job.js is ${lineCount(duplicateJob)} lines`);
});

test("the page loads the coordinator with a current cache version", () => {
  const scriptMatch = html.match(/project_settings\.js\?v=([^"]+)"/);
  assert.ok(scriptMatch, "project_settings.html does not load project_settings.js");
  const version = scriptMatch[1];
  // Split modules are reached through the coordinator, so their versions move together.
  for (const [name] of SPLIT_MODULES) {
    assert.match(
      coordinator,
      new RegExp(`${name.replace(/\./g, "\\.")}\\?v=${version}`),
      `${name} is not pinned to the coordinator's ${version} version`,
    );
  }
});
