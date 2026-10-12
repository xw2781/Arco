import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const moduleUrl = new URL(
  "../ui/project_settings/project_settings_data_processing_rules.js",
  import.meta.url,
);
const moduleSource = await readFile(moduleUrl, "utf8");
const projectSettingsHtml = await readFile(
  new URL("../ui/project_settings/project_settings.html", import.meta.url),
  "utf8",
);
const projectSettingsStylesheetNames = [
  "project_settings.css",
  "project_settings_skeleton.css",
  "project_settings_summary.css",
  "project_settings_combined_source.css",
  "project_settings_field_mapping.css",
  "project_settings_dataset_types.css",
  "project_settings_reserving_class_types.css",
  "project_settings_data_processing_rules.css",
  "project_settings_scrollbars.css",
];
const projectSettingsStylesheets = new Map(await Promise.all(
  projectSettingsStylesheetNames.map(async (name) => [
    name,
    await readFile(new URL(`../ui/project_settings/${name}`, import.meta.url), "utf8"),
  ]),
));
const projectSettingsCoreCss = projectSettingsStylesheets.get("project_settings.css");
const reservingClassTypesCss = projectSettingsStylesheets.get(
  "project_settings_reserving_class_types.css",
);
const dataProcessingRulesCss = projectSettingsStylesheets.get(
  "project_settings_data_processing_rules.css",
);
const projectSettingsCss = projectSettingsStylesheetNames
  .map((name) => projectSettingsStylesheets.get(name))
  .join("\n");
const projectSettingsJs = await readFile(
  new URL("../ui/project_settings/project_settings.js", import.meta.url),
  "utf8",
);
const reservingClassTypesJs = await readFile(
  new URL("../ui/project_settings/project_settings_reserving_class_types.js", import.meta.url),
  "utf8",
);
const tableColumnsJs = await readFile(
  new URL("../ui/project_settings/project_settings_table_columns.js", import.meta.url),
  "utf8",
);
const projectSettingsDefaultPreferences = JSON.parse(await readFile(
  new URL("../app_server/default_preferences/project_settings_preferences.json", import.meta.url),
  "utf8",
));
const rulesUi = await import(`${moduleUrl.href}?test=${Date.now()}`);

test("Project Settings loads its external stylesheets in cascade order", () => {
  const projectStylesheetLinks = [...projectSettingsHtml.matchAll(
    /<link rel="stylesheet" href="(\/ui\/project_settings\/[^"?]+\.css)\?v=([^"]+)"\/>/g,
  )];
  assert.deepEqual(
    projectStylesheetLinks.map((match) => match[1]),
    projectSettingsStylesheetNames.map((name) => `/ui/project_settings/${name}`),
  );
  assert.equal(new Set(projectStylesheetLinks.map((match) => match[2])).size, 1);
  assert.ok(
    projectSettingsHtml.indexOf("/ui/shared/styles/scrollbars.css")
      < projectSettingsHtml.indexOf(projectStylesheetLinks[0][0]),
  );
  assert.doesNotMatch(projectSettingsHtml, /<style(?:\s|>)/);
});

test("Project Settings stylesheet split keeps feature rules with their owners", () => {
  const ownershipMarkers = new Map([
    ["project_settings.css", /\/\* Shared data-grid frames and tables \*\//],
    ["project_settings_skeleton.css", /@keyframes ps-skeleton-sweep\s*\{/],
    ["project_settings_summary.css", /\.sd-columns\s*\{/],
    ["project_settings_combined_source.css", /\.cs-row\s*\{/],
    ["project_settings_field_mapping.css", /\.fm-dataset-type-dropdown\s*\{/],
    ["project_settings_dataset_types.css", /#datasetTypesTable \.dt-filter-btn\s*\{/],
    ["project_settings_reserving_class_types.css", /\.rct-formula-frame\s*\{/],
    ["project_settings_data_processing_rules.css", /\.dpr-editor\s*\{/],
    ["project_settings_scrollbars.css", /\/\* Project Settings owns one PI-aligned scrollbar treatment/],
  ]);
  for (const [name, marker] of ownershipMarkers) {
    assert.match(projectSettingsStylesheets.get(name), marker, name);
  }
  assert.doesNotMatch(
    projectSettingsCss,
    /--muted|--folder-bg|--table-border-width|detail-actions|detail-label|detail-value|dpr-section-title|dpr-section-hint/,
  );
});

test("normalizes list operators without losing raw-row scope", () => {
  const document = rulesUi.normalizeDataProcessingRulesDocument({
    revision: 4,
    rules: [
      {
        id: "nj-earned-premium",
        name: "NJ earned premium",
        target: { source_measure: "Earned_Premium" },
        request_conditions: {
          all: [{ field: "IBNRCAT", level: "5", operator: "in", value: ["TOTAL PA", "TOTAL CMP"] }],
        },
        row_conditions: {
          all: [{ field: "STATE_CD", operator: "equals", value: "NJ" }],
        },
        action: {
          type: "exclude_members",
          field: "IBNRCAT",
          level: "5",
          members: ["BI", "UMBI"],
        },
      },
    ],
  });

  assert.equal(document.json_format, "arcrho-data-processing-rules-v1");
  assert.equal(document.revision, 4);
  assert.deepEqual(document.rules[0].request_conditions.all[0].value, ["TOTAL PA", "TOTAL CMP"]);
  assert.deepEqual(document.rules[0].row_conditions.all[0], {
    field: "STATE_CD",
    operator: "equals",
    value: "NJ",
  });
  assert.equal(document.rules[0].action.level, 5);
});

test("summarizes request conditions separately from raw-row conditions", () => {
  const summary = rulesUi.summarizeDataProcessingRule({
    id: "nj-earned-premium",
    name: "NJ earned premium",
    target: { source_measure: "Earned_Premium" },
    request_conditions: {
      all: [{ field: "IBNRCAT", level: 5, operator: "equals", value: "TOTAL PA" }],
    },
    row_conditions: {
      all: [{ field: "STATE_CD", operator: "equals", value: "NJ" }],
    },
    action: {
      type: "exclude_members",
      field: "IBNRCAT",
      level: 5,
      members: ["BI", "UMBI"],
    },
  });

  assert.match(summary, /when IBNRCAT is TOTAL PA/);
  assert.match(summary, /exclude rows where STATE_CD is NJ and IBNRCAT is any of BI, UMBI/);
});

test("multi-value request conditions read as 'is any of'", () => {
  const summary = rulesUi.summarizeDataProcessingRule({
    id: "eex-bi",
    name: "EEX BI",
    target: { source_measure: "Earned_Exposure" },
    request_conditions: {
      all: [{ field: "IBNRCAT", level: 5, operator: "in", value: ["BI Total", "BI+PIP"] }],
    },
    row_conditions: { all: [] },
    action: { type: "keep_members", field: "IBNRCAT", level: 5, members: ["BI"] },
  });

  assert.match(summary, /when IBNRCAT is any of BI Total, BI\+PIP/);
  assert.match(summary, /keep only rows where IBNRCAT is BI/);
});

test("request conditions round-trip is-not operators", () => {
  const document = rulesUi.normalizeDataProcessingRulesDocument({
    rules: [{
      id: "outside-nj",
      name: "Outside NJ",
      target: { source_measure: "Earned_Premium" },
      request_conditions: {
        all: [{ field: "STATE_CD", level: 3, operator: "not_in", value: ["NJ", "NY"] }],
      },
      row_conditions: { all: [] },
      action: { type: "exclude_members", field: "IBNRCAT", level: 5, members: ["BI"] },
    }],
  });

  const uiCondition = rulesUi.uiConditionFromJson(
    document.rules[0].request_conditions.all[0],
  );
  assert.deepEqual(uiCondition, {
    field: "STATE_CD",
    level: 3,
    operator: "is_not",
    values: ["NJ", "NY"],
  });
  assert.deepEqual(rulesUi.jsonConditionFromUi(uiCondition), {
    field: "STATE_CD",
    level: 3,
    operator: "not_in",
    value: ["NJ", "NY"],
  });
});

test("editor validation separates current-rule errors from other saved-rule errors", () => {
  const grouped = rulesUi.groupEditorValidationErrors([
    "Rule 1 (Current): action member is invalid.",
    "Rule 8 (Saved): keep_members cannot add a base-excluded member.",
    "Source table could not be refreshed.",
  ], 1);

  assert.deepEqual(grouped.currentRule, ["Rule 1 (Current): action member is invalid."]);
  assert.deepEqual(grouped.otherRules, [
    "Rule 8 (Saved): keep_members cannot add a base-excluded member.",
  ]);
  assert.deepEqual(grouped.project, ["Source table could not be refreshed."]);
  assert.match(grouped.message, /This rule needs attention:/);
  assert.match(grouped.message, /Other saved rules must be fixed/);
  assert.match(grouped.message, /Project configuration errors must be fixed/);
});

test("editor validation does not blame the open rule for errors elsewhere", () => {
  const grouped = rulesUi.groupEditorValidationErrors([
    "Rule 8 (Saved): keep_members cannot add a base-excluded member.",
  ], 1);

  assert.deepEqual(grouped.currentRule, []);
  assert.equal(grouped.message.startsWith("Other saved rules must be fixed"), true);
});

test("keep-only with a row filter states that unfiltered rows are untouched", () => {
  const summary = rulesUi.summarizeDataProcessingRule({
    id: "nj-keep",
    name: "NJ keep",
    target: { source_measure: "Earned_Premium" },
    request_conditions: { all: [] },
    row_conditions: {
      all: [{ field: "STATE_CD", operator: "equals", value: "NJ" }],
    },
    action: { type: "keep_members", field: "IBNRCAT", level: 5, members: ["BI"] },
  });

  assert.match(summary, /keep only rows where IBNRCAT is BI among rows where STATE_CD is NJ/);
  assert.match(summary, /other rows are untouched/);
});

test("UI conditions merge equals/in and split back by committed value count", () => {
  assert.deepEqual(
    rulesUi.uiConditionFromJson({ field: "IBNRCAT", operator: "in", value: ["A", "B"], level: 5 }),
    { field: "IBNRCAT", operator: "is", values: ["A", "B"], level: 5 },
  );
  assert.deepEqual(
    rulesUi.uiConditionFromJson({ field: "STATE_CD", operator: "not_equals", value: "NJ" }),
    { field: "STATE_CD", operator: "is_not", values: ["NJ"] },
  );
  assert.deepEqual(
    rulesUi.jsonConditionFromUi({ field: "IBNRCAT", operator: "is", values: ["A", "B"], level: 5 }),
    { field: "IBNRCAT", operator: "in", value: ["A", "B"], level: 5 },
  );
  assert.deepEqual(
    rulesUi.jsonConditionFromUi({ field: "IBNRCAT", operator: "is", values: ["A"] }),
    { field: "IBNRCAT", operator: "equals", value: "A" },
  );
  assert.deepEqual(
    rulesUi.jsonConditionFromUi({ field: "STATE_CD", operator: "is_not", values: ["NJ", "NY"] }),
    { field: "STATE_CD", operator: "not_in", value: ["NJ", "NY"] },
  );
  assert.deepEqual(
    rulesUi.jsonConditionFromUi({ field: "STATE_CD", operator: "is_blank", values: ["ignored"] }),
    { field: "STATE_CD", operator: "is_blank" },
  );
});

test("unified Then conditions split into action members and row filters", () => {
  const isReservingField = (field) => field === "IBNRCAT";
  const split = rulesUi.splitThenConditions(
    [
      { field: "IBNRCAT", operator: "is", values: ["BIR51", "UMBIR51"] },
      { field: "STATE_CD", operator: "is", values: ["NJ"] },
    ],
    { actionType: "exclude_members", isReservingField },
  );

  assert.equal(split.error, "");
  assert.deepEqual(split.action, { field: "IBNRCAT", members: ["BIR51", "UMBIR51"] });
  assert.deepEqual(split.rowConditions, [
    { field: "STATE_CD", operator: "equals", value: "NJ" },
  ]);
});

test("keep-only rejects ambiguous member conditions and missing value lists", () => {
  const isReservingField = (field) => field === "IBNRCAT" || field === "STATE_GROUP";
  const ambiguous = rulesUi.splitThenConditions(
    [
      { field: "IBNRCAT", operator: "is", values: ["BI"] },
      { field: "STATE_GROUP", operator: "is", values: ["NJ Group"] },
    ],
    { actionType: "keep_members", isReservingField },
  );
  assert.match(ambiguous.error, /single values-list condition/);

  const empty = rulesUi.splitThenConditions(
    [{ field: "STATE_CD", operator: "is_blank", values: [] }],
    { actionType: "keep_members", isReservingField },
  );
  assert.match(empty.error, /at least one "is" condition/);
});

test("auto rule names freeze the dataset, verb, members, and scope", () => {
  const name = rulesUi.composeAutoRuleName(
    {
      target: { source_measure: "Earned_Premium" },
      request_conditions: {
        all: [{ field: "IBNRCAT", level: 5, operator: "equals", value: "TOTAL PA" }],
      },
      row_conditions: { all: [] },
      action: { type: "exclude_members", field: "IBNRCAT", members: ["BIR51", "UMBIR51"] },
    },
    { datasetLabel: "Earned premium" },
  );

  assert.equal(name, "Earned premium - exclude BIR51, UMBIR51 for TOTAL PA");
});

test("auto rule names preserve negative request scope meaning", () => {
  const name = rulesUi.composeAutoRuleName({
    target: { source_measure: "Earned_Premium" },
    request_conditions: {
      all: [{ field: "STATE_CD", level: 3, operator: "not_equals", value: "NJ" }],
    },
    row_conditions: { all: [] },
    action: { type: "exclude_members", field: "IBNRCAT", level: 5, members: ["BI"] },
  }, { datasetLabel: "Earned premium" });

  assert.equal(name, "Earned premium - exclude BI for STATE_CD is not NJ");
});

test("blank operators remain value-free in the normalized semantic view", () => {
  const document = rulesUi.normalizeDataProcessingRulesDocument({
    rules: [
      {
        id: "blank-state",
        name: "Blank state",
        target: { source_measure: "Paid_Loss" },
        row_conditions: {
          all: [{ field: "STATE_CD", operator: "is_blank", value: "ignored" }],
        },
        action: {
          type: "exclude_members",
          field: "IBNRCAT",
          members: ["BI"],
        },
      },
    ],
  });

  assert.equal(document.rules[0].row_conditions.all[0].operator, "is_blank");
  assert.equal(Object.hasOwn(document.rules[0].row_conditions.all[0], "value"), false);
});

test("condition round-trips preserve scalar types and literal commas", () => {
  const document = rulesUi.normalizeDataProcessingRulesDocument({
    rules: [{
      id: "typed-values",
      target: { source_measure: "Paid_Loss" },
      row_conditions: {
        all: [
          { field: "LOSS_YEAR", operator: "equals", value: 2025 },
          { field: "IS_DIRECT", operator: "equals", value: false },
          { field: "RAW_LABEL", operator: "equals", value: "A,B" },
        ],
      },
      action: { type: "exclude_members", field: "IBNRCAT", members: ["BI"] },
    }],
  });
  assert.equal(document.rules[0].row_conditions.all[0].value, 2025);
  assert.equal(document.rules[0].row_conditions.all[1].value, false);
  assert.equal(document.rules[0].row_conditions.all[2].value, "A,B");

  for (const condition of document.rules[0].row_conditions.all) {
    const ui = rulesUi.uiConditionFromJson(condition);
    const roundTrip = rulesUi.jsonConditionFromUi(ui);
    assert.deepEqual(roundTrip, condition);
  }
});

test("action members preserve case-sensitive raw values", () => {
  const document = rulesUi.normalizeDataProcessingRulesDocument({
    rules: [
      {
        id: "case-sensitive-members",
        name: "Case-sensitive members",
        target: { source_measure: "Paid_Loss" },
        action: {
          type: "keep_members",
          field: "RAW_CODE",
          members: ["A", "a", "A"],
        },
      },
    ],
  });

  assert.deepEqual(document.rules[0].action.members, ["A", "a"]);
});

test("preserves case-sensitive Dataset Types table names", () => {
  const options = rulesUi.buildSourceMeasureDisplayOptions(
    ["Earned_Exposure", "Paid_Loss"],
    [
      {
        field_name: "Earned_Exposure",
        significance: "Dataset",
        dataset_type: "Earned Exposure - BI",
      },
      {
        field_name: "Paid_Loss",
        significance: "Dataset",
        dataset_type: "PAID Loss",
      },
    ],
  );

  assert.deepEqual(options, [
    { value: "Earned_Exposure", label: "Earned Exposure - BI" },
    { value: "Paid_Loss", label: "PAID Loss" },
  ]);
  assert.equal(
    rulesUi.datasetTypeLabelForSourceMeasure("Earned_Exposure", options),
    "Earned Exposure - BI",
  );
  assert.equal(
    rulesUi.datasetTypeLabelForSourceMeasure("Unknown_Measure", options),
    "Unknown_Measure",
  );
});

test("keeps field labels identical to Field Mapping names", () => {
  assert.equal(rulesUi.sentenceCaseUiLabel("Earned_Premium"), "Earned premium");
  assert.deepEqual(rulesUi.buildFieldDisplayOptions([
    { field: "CHANNEL" },
    { field: "CO_CD" },
    { field: "acc_yrmo" },
  ]), [
    { value: "CHANNEL", label: "CHANNEL" },
    { value: "CO_CD", label: "CO_CD" },
    { value: "acc_yrmo", label: "acc_yrmo" },
  ]);
});

test("action level prefers the reserving-class mapping for duplicate field names", () => {
  const options = {
    sourceFields: [{ field: "IBNRCAT", significance: "Reserving Class" }],
    reservingClassFields: [{ field: "IBNRCAT", level: 5 }],
  };

  assert.equal(rulesUi.resolveActionLevelForField(options, "IBNRCAT"), 5);
  assert.equal(rulesUi.resolveActionLevelForField(options, "ibnrcat"), 5);
  assert.equal(rulesUi.resolveActionLevelForField(options, "STATE_CD"), null);
});

function phaseTwoOptions() {
  return rulesUi.normalizeDataProcessingRulesOptions({
    source_measures: ["Earned_Premium", "Remaining_Budget_Premium"],
    source_fields: [
      {
        field: "STATE_CD",
        values: ["NJ", "NY"],
        values_by_measure: {
          Earned_Premium: ["NJ", "NY"],
          Remaining_Budget_Premium: ["NJ"],
        },
      },
      {
        field: "IBNRCAT",
        significance: "Reserving Class",
        level: 5,
        values: ["BI", "PD", "BI Total"],
        values_by_measure: {
          Earned_Premium: ["BI", "PD"],
          Remaining_Budget_Premium: ["BI Total"],
        },
      },
      {
        field: "CHANNEL",
        values_by_measure: {
          Earned_Premium: ["Direct", "Independent"],
          Remaining_Budget_Premium: ["Direct"],
        },
      },
    ],
    reserving_class_fields: [
      { field: "STATE_CD", level: 3, types: ["All States", "NJ"] },
      { field: "IBNRCAT", level: 5, types: ["TOTAL PA", "BI Total"] },
    ],
    source_vocabulary: {
      json_format: "arcrho-source-vocab-v1",
      key_fields: [
        { field: "STATE_CD", level: 3 },
        { field: "IBNRCAT", level: 5 },
      ],
      datasets: {
        Earned_Premium: {
          dataset_type: "Earned premium",
          row_count: 40,
          combination_count: 3,
          combinations: [
            ["NJ", "BI"],
            ["NJ", "PD"],
            ["NY", "PD"],
          ],
        },
        Remaining_Budget_Premium: {
          dataset_type: "Remaining budget premium",
          row_count: 10,
          combination_count: 1,
          combinations: [["NJ", "BI Total"]],
        },
      },
      missing_columns: [],
    },
  });
}

test("normalizes dataset-specific values and exact source-combination inventory", () => {
  const options = phaseTwoOptions();

  assert.deepEqual(options.sourceVocabulary.keyFields, [
    { field: "STATE_CD", level: 3 },
    { field: "IBNRCAT", level: 5 },
  ]);
  assert.deepEqual(
    options.sourceVocabulary.datasets.Earned_Premium.combinations,
    [["NJ", "BI"], ["NJ", "PD"], ["NY", "PD"]],
  );
  assert.deepEqual(options.sourceFields[1].valuesByMeasure.Earned_Premium, ["BI", "PD"]);
  assert.deepEqual(options.sourceMeasureOptions, [
    { value: "Earned_Premium", label: "Earned premium" },
    { value: "Remaining_Budget_Premium", label: "Remaining budget premium" },
  ]);
});

test("refreshed option contracts replace removed values and intentional empty vocabularies", () => {
  const previous = phaseTwoOptions();
  const refreshed = rulesUi.normalizeDataProcessingRulesOptions({
    source_measures: ["Earned_Premium"],
    source_fields: [{
      field: "IBNRCAT",
      significance: "Reserving Class",
      level: 5,
      values: [],
      values_by_measure: { Earned_Premium: [] },
    }],
    reserving_class_fields: [{ field: "IBNRCAT", level: 5, types: [], members: [] }],
    source_vocabulary: {
      key_fields: [{ field: "IBNRCAT", level: 5 }],
      datasets: {
        Earned_Premium: {
          dataset_type: "Earned premium",
          row_count: 0,
          combination_count: 0,
          combinations: [],
        },
      },
      missing_columns: ["IBNRCAT"],
    },
  });

  const merged = rulesUi.mergeDataProcessingRulesOptions(refreshed, previous);
  assert.deepEqual(merged.sourceMeasures, ["Earned_Premium"]);
  assert.deepEqual(merged.sourceFields[0].values, []);
  assert.deepEqual(merged.sourceFields[0].valuesByMeasure, { Earned_Premium: [] });
  assert.deepEqual(merged.sourceVocabulary.datasets.Earned_Premium.combinations, []);
  assert.deepEqual(merged.sourceVocabulary.missingColumns, ["IBNRCAT"]);
  assert.equal(Object.hasOwn(merged.sourceVocabulary.datasets, "Remaining_Budget_Premium"), false);
  assert.equal(
    rulesUi.hasAuthoritativeDatasetFieldVocabulary(merged, "Earned_Premium", "IBNRCAT"),
    true,
  );
  assert.deepEqual(
    rulesUi.buildDatasetFieldSuggestions(merged, "Earned_Premium", "IBNRCAT"),
    [],
  );
});

test("Then suggestions cascade by dataset and compatible source combinations", () => {
  const options = phaseTwoOptions();
  const conditions = [
    { field: "STATE_CD", operator: "is", values: ["NY"] },
    { field: "IBNRCAT", operator: "is", values: ["BI"] },
  ];

  assert.deepEqual(
    rulesUi.buildDatasetFieldSuggestions(
      options,
      "Earned_Premium",
      "IBNRCAT",
      conditions,
      { ignoreConditionIndex: 1 },
    ),
    ["PD"],
  );
  assert.deepEqual(
    rulesUi.buildDatasetFieldSuggestions(options, "Remaining_Budget_Premium", "IBNRCAT"),
    ["BI Total"],
  );
  assert.deepEqual(
    rulesUi.buildDatasetFieldSuggestions(options, "Earned_Premium", "CHANNEL"),
    ["Direct", "Independent"],
  );
});

test("source-combination analysis distinguishes missing and incompatible tokens", () => {
  const options = phaseTwoOptions();
  const compatible = rulesUi.analyzeDatasetConditionCombos(options, "Earned_Premium", [
    { field: "STATE_CD", operator: "is", values: ["NJ"] },
    { field: "IBNRCAT", operator: "is", values: ["BI"] },
  ]);
  assert.equal(compatible.status, "ok");
  assert.equal(compatible.possible, true);
  assert.equal(compatible.matchCount, 1);

  const missing = rulesUi.analyzeDatasetConditionCombos(options, "Earned_Premium", [
    { field: "IBNRCAT", operator: "is", values: ["HOP"] },
  ]);
  assert.equal(missing.status, "bad");
  assert.equal(missing.tokens[0].status, "bad");
  assert.match(missing.tokens[0].message, /does not appear in current source rows/);

  const incompatible = rulesUi.analyzeDatasetConditionCombos(options, "Earned_Premium", [
    { field: "STATE_CD", operator: "is", values: ["NY"] },
    { field: "IBNRCAT", operator: "is", values: ["BI"] },
  ]);
  assert.equal(incompatible.status, "warn");
  assert.equal(incompatible.possible, false);
  assert.equal(incompatible.matchCount, 0);
  assert.ok(incompatible.tokens.every((token) => token.status === "warn"));
});

test("source combo matching supports positive, negative, blank, and numeric operators", () => {
  const inventory = rulesUi.normalizeSourceComboInventory({
    key_fields: ["STATE_CD", "LOSS_YEAR", "CHANNEL"],
    datasets: {
      Paid_Loss: { combinations: [["NJ", "2025", ""]] },
    },
  });
  const combo = inventory.datasets.Paid_Loss.combinations[0];
  assert.equal(rulesUi.sourceComboMatchesConditions(inventory, "Paid_Loss", combo, [
    { field: "STATE_CD", operator: "is_not", values: ["NY"] },
    { field: "LOSS_YEAR", operator: "greater_than_or_equal", values: ["2024"] },
    { field: "CHANNEL", operator: "is_blank", values: [] },
  ]), true);
  assert.equal(rulesUi.sourceComboMatchesConditions(inventory, "Paid_Loss", combo, [
    { field: "STATE_CD", operator: "is", values: ["nj"] },
  ]), false);
});

test("rules render in the standard resizable Project Settings table", () => {
  const listStart = projectSettingsHtml.indexOf('<table class="dataset-types-table dpr-rules-table"');
  const listEnd = projectSettingsHtml.indexOf('id="dataProcessingRulesRowContextMenu"', listStart);
  const listSource = projectSettingsHtml.slice(listStart, listEnd);
  const menuStart = projectSettingsHtml.indexOf('id="dataProcessingRulesRowContextMenu"');
  const menuEnd = projectSettingsHtml.indexOf('<div class="dpr-editor"', menuStart);
  const menuSource = projectSettingsHtml.slice(menuStart, menuEnd);

  assert.match(listSource, /class="dataset-types-table dpr-rules-table"/);
  assert.match(listSource, /<tbody id="dataProcessingRulesBody">/);
  assert.doesNotMatch(listSource, /dpr-order-header|>Order<\/span>/);
  assert.match(listSource, /<th>Enabled<\/th>/);
  assert.match(listSource, /<th>Applies when<\/th>/);
  assert.match(listSource, /<th>Effect<\/th>/);
  assert.match(moduleSource, /function renderRulesTable\(state, rules\)/);
  assert.match(moduleSource, /className = "dpr-row-drag-handle"/);
  assert.match(moduleSource, /dragHandle\.draggable = true/);
  assert.match(moduleSource, /const handle = event\.target\?\.closest\?\.\("\.dpr-row-drag-handle"\)/);
  assert.match(moduleSource, /if \(ruleOrderSaving \|\| !handle \|\| !row \|\| !rulesBody\?\.contains\(row\)\)/);
  assert.doesNotMatch(moduleSource, /row\.draggable = true/);
  assert.match(moduleSource, /addEventListener\("dragstart", handleRuleDragStart\)/);
  assert.match(moduleSource, /addEventListener\("drop", handleRuleDrop\)/);
  assert.match(moduleSource, /className = "dpr-table-switch"/);
  assert.match(moduleSource, /enabledCheckbox\.type = "checkbox"/);
  assert.match(moduleSource, /enabledCheckbox\.checked = rule\.enabled/);
  assert.match(moduleSource, /enabledCell\.appendChild\(dragHandle\)/);
  assert.match(moduleSource, /initTableColumnResizing\("dataProcessingRulesTable", \[72, 220, 190, 300, 420\]\)/);
  assert.match(menuSource, /data-action="edit"/);
  assert.match(menuSource, /data-action="duplicate"/);
  assert.match(menuSource, /data-action="toggle"/);
  assert.match(menuSource, /data-action="delete"/);
});

test("rule reordering moves one row without mutating the source array", () => {
  const rules = [{ id: "one" }, { id: "two" }, { id: "three" }];
  const reordered = rulesUi.reorderRules(rules, 0, 2);
  assert.deepEqual(reordered.map((rule) => rule.id), ["two", "three", "one"]);
  assert.deepEqual(rules.map((rule) => rule.id), ["one", "two", "three"]);
});

test("rules toolbar actions use the compact ArcRho button type scale", () => {
  assert.match(
    dataProcessingRulesCss,
    /\.dpr-toolbar button\s*\{[^}]*font-size:\s*12px;[^}]*line-height:\s*1\.2;/s,
  );
});

test("table and editor enabled switches share the compact DPR track style", () => {
  assert.match(dataProcessingRulesCss, /:root\s*\{[^}]*--dpr-blue:\s*#1a73e8;/s);
  assert.match(
    dataProcessingRulesCss,
    /\.dpr-rules-table td\.dpr-enabled-cell\s*\{[^}]*text-align:\s*center;/s,
  );
  assert.match(
    dataProcessingRulesCss,
    /\.dpr-table-switch-track,\s*\.dpr-enabled-track\s*\{[^}]*width:\s*32px;[^}]*height:\s*18px;[^}]*background:\s*#c9d1d9;/s,
  );
  assert.match(
    dataProcessingRulesCss,
    /\.dpr-table-switch-track::after,\s*\.dpr-enabled-track::after\s*\{[^}]*width:\s*14px;[^}]*height:\s*14px;/s,
  );
  assert.match(
    dataProcessingRulesCss,
    /\.dpr-table-switch \.dpr-enabled-checkbox:checked \+ \.dpr-table-switch-track,\s*\.dpr-enabled-switch input:checked \+ \.dpr-enabled-track\s*\{[^}]*background:\s*var\(--dpr-blue\);/s,
  );
});

test("dragged rule rows show clear insertion feedback", () => {
  assert.match(dataProcessingRulesCss, /\.dpr-row-drag-handle\s*\{[^}]*position:\s*absolute;[^}]*left:\s*2px;[^}]*width:\s*14px;[^}]*cursor:\s*grab;[^}]*opacity:\s*0;[^}]*pointer-events:\s*none;/s);
  assert.match(dataProcessingRulesCss, /\.dpr-rule-row:hover \.dpr-row-drag-handle,[\s\S]*\.dpr-row-dragging \.dpr-row-drag-handle\s*\{[^}]*opacity:\s*1;[^}]*pointer-events:\s*auto;/s);
  assert.match(dataProcessingRulesCss, /\.dpr-rule-row\.dpr-row-dragging\s*\{[^}]*opacity:\s*0\.55;/s);
  assert.match(dataProcessingRulesCss, /\.dpr-rule-row\.dpr-drop-before td\s*\{[^}]*box-shadow:\s*inset 0 2px 0 var\(--dpr-blue\);/s);
  assert.match(dataProcessingRulesCss, /\.dpr-rule-row\.dpr-drop-after td\s*\{[^}]*box-shadow:\s*inset 0 -2px 0 var\(--dpr-blue\);/s);
});

test("floating editor positions stay inside the Project Settings viewport", () => {
  assert.deepEqual(rulesUi.clampFloatingEditorPosition({
    left: -40,
    top: 900,
    width: 420,
    height: 300,
    viewportWidth: 1000,
    viewportHeight: 700,
  }), { left: 8, top: 392 });

  assert.deepEqual(rulesUi.clampFloatingEditorPosition({
    left: 200,
    top: 120,
    width: 900,
    height: 760,
    viewportWidth: 700,
    viewportHeight: 600,
  }), { left: 8, top: 8 });
});

test("data processing editor is a non-modal floating page window", () => {
  const editorStart = projectSettingsHtml.indexOf('id="dataProcessingRuleEditor"');
  const editorEnd = projectSettingsHtml.indexOf('id="dataProcessingRulesJsonOverlay"', editorStart);
  const editorSource = projectSettingsHtml.slice(editorStart, editorEnd);
  const headerEnd = editorSource.indexOf('<div class="dpr-editor-body">');
  const headerSource = editorSource.slice(0, headerEnd);
  const bodySource = editorSource.slice(headerEnd);
  assert.match(editorSource, /aria-modal="false"/);
  assert.match(editorSource, /class="dpr-editor-header"/);
  assert.match(editorSource, /class="dpr-editor-close"/);
  assert.match(editorSource, />Add rule<\/div>/);
  assert.match(editorSource, /class="dpr-step-chip">When</);
  assert.match(editorSource, /class="dpr-step-chip then">Then</);
  assert.doesNotMatch(editorSource, /class="dpr-step-hint"|>scope<|>action</);
  assert.match(editorSource, /id="dprActionVerbGroup"/);
  assert.match(editorSource, /<option value="keep_members" selected>Keep only<\/option>/);
  assert.match(editorSource, /<option value="exclude_members">Exclude<\/option>/);
  assert.match(editorSource, /id="dprThenConditions"/);
  assert.match(editorSource, /id="dprKeepHint"/);
  assert.match(editorSource, /id="dprVocabWarning"/);
  assert.match(editorSource, /id="dprEditError" role="alert" aria-live="polite"/);
  assert.match(editorSource, /class="dpr-enabled-switch"/);
  assert.doesNotMatch(headerSource, /id="dprEditName"/);
  assert.match(bodySource, /class="dpr-rule-settings"/);
  assert.match(bodySource, /for="dprEditName">Name<\/label>/);
  assert.match(bodySource, /id="dprEditName"[^>]*aria-describedby="dprRuleNameHint"/);
  assert.match(dataProcessingRulesCss, /\.dpr-editor \*,\s*\.dpr-editor \*::before,\s*\.dpr-editor \*::after\s*\{\s*box-sizing:\s*border-box;/s);
  assert.match(dataProcessingRulesCss, /\.dpr-editor-body\s*\{[^}]*min-height:\s*0;[^}]*overflow-x:\s*hidden;/s);
  assert.match(dataProcessingRulesCss, /@media \(max-width: 760px\)[\s\S]*\.dpr-section\.dpr-step\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/);
  assert.match(moduleSource, /window\.addEventListener\("resize", \(\) => \{/);
});

test("editor selects use the styled ArcRho listbox instead of native opened menus", () => {
  assert.match(moduleSource, /function enhanceEditorSelect\(select\)/);
  assert.match(moduleSource, /trigger\.setAttribute\("aria-haspopup", "listbox"\)/);
  assert.match(moduleSource, /editorSelectPopup\.setAttribute\("role", "listbox"\)/);
  assert.match(moduleSource, /item\.setAttribute\("role", "option"\)/);
  assert.match(moduleSource, /\["ArrowDown", "ArrowUp", "Home", "End", "Enter", " "\]/);
  assert.match(moduleSource, /fieldWrap\.append\(enhanceEditorSelect\(fieldSelect\), badge\)/);
  assert.match(moduleSource, /operatorControl = enhanceEditorSelect\(operatorSelect\)/);
  assert.match(moduleSource, /enhanceEditorSelect\(actionVerbGroup\)\?\.classList\.add\("dpr-verb-group"\)/);
  assert.match(moduleSource, /actionVerbGroup\?\.addEventListener\("change"/);
  assert.doesNotMatch(projectSettingsHtml, /button[^>]+data-verb=/);
  assert.match(moduleSource, /const operatorOptions = request \? REQUEST_UI_OPERATORS : UI_OPERATORS/);
  assert.doesNotMatch(moduleSource, /condition\.operator = "is";/);
  assert.match(dataProcessingRulesCss, /\.dpr-select-popup\s*\{[^}]*position:\s*fixed;[^}]*z-index:\s*4200;/s);
  assert.match(dataProcessingRulesCss, /\.dpr-select-option\.selected\s*\{[^}]*background:\s*#e3edfc;/s);
  assert.match(dataProcessingRulesCss, /\.dpr-select-caret\s*\{[^}]*border-top:\s*5px solid #7b8794;/s);
});

test("token suggestion menus escape the editor scroll frame and stay viewport-safe", () => {
  assert.match(moduleSource, /function positionTokenMenu\(menu, anchor\)/);
  assert.match(moduleSource, /document\.body\.appendChild\(menu\)/);
  assert.match(moduleSource, /menu\.remove\(\)/);
  assert.doesNotMatch(moduleSource, /box\.appendChild\(menu\)/);
  assert.match(dataProcessingRulesCss, /\.dpr-token-menu\s*\{[^}]*position:\s*fixed;[^}]*z-index:\s*4210;/s);
});

test("rule tracing panel and result are removed", () => {
  assert.doesNotMatch(projectSettingsHtml, /dpr-trace-panel|dpr-trace-result|dprTrace/);
  assert.doesNotMatch(projectSettingsCss, /dpr-trace-panel|dpr-trace-result|dprTrace/);
  assert.doesNotMatch(moduleSource, /renderTrace|traceDataProcessingRules|buildTraceRequestFieldOptions|dprTrace/);
  assert.doesNotMatch(projectSettingsJs, /dprTrace/);
  assert.match(projectSettingsJs, /dprVocabWarning,/);
});

test("vocabulary warning tokens use the shared ArcRho tooltip", () => {
  assert.match(moduleSource, /import \{ attachArcrhoTooltip \} from "\.\.\/shared\/components\/tooltip\/tooltip\.js"/);
  assert.match(moduleSource, /attachArcrhoTooltip\(chip, tokenState\.message\)/);
  assert.doesNotMatch(moduleSource, /chip\.title\s*=/);
});

test("mockup summary and condition details render as safe structured DOM", () => {
  assert.match(moduleSource, /badge\.textContent = level \? `Level \$\{level\}` : "Raw field"/);
  assert.match(moduleSource, /editSummary\.replaceChildren\(\)/);
  assert.match(moduleSource, /className = `dpr-summary-verb \$\{kind\}`/);
  assert.match(moduleSource, /appendRichConditionSummary\(editSummary, condition\)/);
  assert.doesNotMatch(moduleSource, /editSummary\.innerHTML\s*=/);
});

test("Validate all replaces live vocabulary and rerenders open surfaces", () => {
  assert.match(
    moduleSource,
    /if \(payload\?\.options[\s\S]*state\.options = mergeOptions\([\s\S]*normalizeDataProcessingRulesOptions\(payload\.options\)[\s\S]*renderRules\(name\)[\s\S]*renderEditorConditions\(\)/,
  );
  assert.match(moduleSource, /if \(hasAuthoritativeDatasetFieldVocabulary\([\s\S]*return \[\]/);
  assert.match(moduleSource, /refreshEditorComboAnalysis\(\{ refreshTokens: true \}\)/);
});

test("failed editor validation still refreshes live vocabulary", () => {
  assert.match(
    moduleSource,
    /async function applyEditor\(\)[\s\S]*allowInvalid: true[\s\S]*validation\?\.options[\s\S]*state\.options = mergeOptions\([\s\S]*renderEditorConditions\(\)[\s\S]*validation\?\.valid === false/,
  );
});

test("all Project Settings table wrappers use the refined frame and scroll activity", () => {
  assert.match(projectSettingsCoreCss, /\.field-mapping-grid,\s*\.dataset-types-grid\s*\{[^}]*border:\s*1px solid #cbd5e1;[^}]*scrollbar-gutter:\s*stable;/s);
  assert.match(projectSettingsCoreCss, /\.field-mapping-table,\s*\.dataset-types-table\s*\{[^}]*border-collapse:\s*separate;[^}]*border-spacing:\s*0;/s);
  assert.match(projectSettingsCoreCss, /:is\(\.field-mapping-table, \.dataset-types-table\) tbody tr\s*\{[^}]*height:\s*31px;/s);
  assert.match(projectSettingsJs, /querySelectorAll\("\.tree-content, \.sd-list, \.field-mapping-grid, \.dataset-types-grid"\)[\s\S]*forEach\(wireProjectSettingsTableScrollbarActivity\)/);
});

test("Project Settings uses one PI-aligned themed scrollbar treatment on every scroll surface", () => {
  const scrollbarCss = projectSettingsStylesheets.get("project_settings_scrollbars.css");
  assert.match(projectSettingsHtml, /<body class="project-settings-page">/);
  assert.ok(
    projectSettingsHtml.indexOf("/ui/shared/styles/themes/dark.css")
      < projectSettingsHtml.indexOf("/ui/project_settings/project_settings_scrollbars.css"),
  );
  assert.match(scrollbarCss, /--ps-scrollbar-size:\s*20px;/);
  assert.match(scrollbarCss, /--ps-scrollbar-button-size:\s*16px;/);
  assert.match(scrollbarCss, /--ps-scrollbar-arrow-size:\s*12px;/);
  assert.match(scrollbarCss, /\.project-settings-page \*::\-webkit-scrollbar\s*\{[^}]*width:\s*var\(--ps-scrollbar-size\);[^}]*height:\s*var\(--ps-scrollbar-size\);/s);
  assert.match(scrollbarCss, /::\-webkit-scrollbar-button\s*\{[^}]*width:\s*var\(--ps-scrollbar-button-size\);[^}]*height:\s*var\(--ps-scrollbar-button-size\);/s);
  assert.match(scrollbarCss, /::\-webkit-scrollbar-track,[\s\S]*::\-webkit-scrollbar-corner,[\s\S]*::\-webkit-resizer\s*\{[^}]*--ar-color-scrollbar-track/s);
  assert.match(scrollbarCss, /::\-webkit-scrollbar-thumb\s*\{[^}]*border:\s*3px solid[^}]*border-radius:\s*5px;[^}]*background-clip:\s*content-box;/s);
  assert.match(scrollbarCss, /\.isScrolling::\-webkit-scrollbar-thumb,[\s\S]*\.isScrollbarHover::\-webkit-scrollbar-thumb,[\s\S]*::\-webkit-scrollbar-thumb:hover/);
  assert.match(scrollbarCss, /::\-webkit-scrollbar-button:horizontal:start:increment,[\s\S]*display:\s*none;/);
  assert.match(scrollbarCss, /::\-webkit-scrollbar-button:horizontal:start:decrement\s*\{[^}]*background-image:/s);
  assert.match(scrollbarCss, /::\-webkit-scrollbar-button:vertical:end:increment\s*\{[^}]*background-image:/s);
  assert.doesNotMatch(scrollbarCss, /scrollbar-color:/);
  assert.match(scrollbarCss, /\.tree-content::\-webkit-scrollbar-track,[\s\S]*\.tree-content::\-webkit-scrollbar-corner\s*\{[^}]*background-color:\s*transparent !important;/s);
  assert.match(scrollbarCss, /\.tree-content::\-webkit-scrollbar-button\s*\{[^}]*display:\s*none;[^}]*width:\s*0;[^}]*height:\s*0;[^}]*background-image:\s*none !important;/s);
  assert.match(scrollbarCss, /\.tree-content::\-webkit-scrollbar-thumb\s*\{[^}]*border-color:\s*transparent !important;/s);

  for (const [name, stylesheet] of projectSettingsStylesheets) {
    if (name === "project_settings_scrollbars.css") continue;
    assert.doesNotMatch(stylesheet, /::\-webkit-scrollbar/, `${name} duplicates scrollbar paint`);
  }
});

test("reserving-class editor resizes from an invisible bottom-right corner", () => {
  assert.match(projectSettingsHtml, /id="reservingClassTypeEditorResizer"/);
  assert.match(
    reservingClassTypesCss,
    /#reservingClassTypeEditor\s*\{[\s\S]*?box-sizing:\s*border-box;[\s\S]*?resize:\s*none;[\s\S]*?overflow:\s*hidden;/s,
  );
  assert.match(
    reservingClassTypesCss,
    /#reservingClassTypeEditor\.show\s*\{[\s\S]*?display:\s*flex;[\s\S]*?flex-direction:\s*column;/s,
  );
  assert.match(
    reservingClassTypesCss,
    /#reservingClassTypeEditor \.rct-row-editor-body\s*\{[\s\S]*?flex:\s*1 1 auto;[\s\S]*?min-height:\s*0;[\s\S]*?overflow:\s*auto;/s,
  );
  assert.match(
    reservingClassTypesCss,
    /\.rct-row-editor-resizer\s*\{[\s\S]*?position:\s*absolute;[\s\S]*?cursor:\s*nwse-resize;/s,
  );
  assert.match(reservingClassTypesJs, /function onEditorResizerMouseDown\(e\)/);
  const resizeStart = reservingClassTypesJs.match(
    /function onEditorResizerMouseDown\(e\)\s*\{[\s\S]*?\n  \}/,
  )?.[0] || "";
  assert.ok(
    resizeStart.indexOf("pinReservingClassTypeEditorPosition")
      < resizeStart.indexOf("rctEditorResizeState ="),
    "the resize drag must pin the top-left corner before sizing",
  );
  assert.match(reservingClassTypesJs, /if \(rctEditorResizeState\) \{/);
  assert.match(reservingClassTypesJs, /style\.width = `\$\{Math\.max\(state\.minWidth/);
  assert.match(reservingClassTypesJs, /style\.height = `\$\{Math\.max\(state\.minHeight/);
  assert.match(projectSettingsJs, /reservingClassTypeEditorResizer\?\.addEventListener\("mousedown",/);
});

test("Project Settings column resizing follows the PI explicit-width model", () => {
  assert.match(tableColumnsJs, /table\.style\.width = `\$\{width\}px`/);
  assert.match(tableColumnsJs, /table\.style\.minWidth = `\$\{width\}px`/);
  assert.match(tableColumnsJs, /cols\[idx\]\.style\.width = `\$\{Math\.round\(newW\)\}px`/);
  assert.match(tableColumnsJs, /tableColumnWidthsById\.set\(tableId, captureTableColumnWidths/);
  assert.doesNotMatch(tableColumnsJs, /getColResizePreviewEl|colResizePreviewEl/);
  // The sizing model is owned by one module, not re-implemented by the coordinator.
  assert.doesNotMatch(projectSettingsJs, /function initTableColumnResizing\(/);
});

test("Source Data column widths still come from the shared table preference JSON", () => {
  // The Source Data list is no longer a <table>; it reads the same configured widths.
  assert.match(tableColumnsJs, /configuredTableColumnWidthsById\.get\(tableId\)/);
  assert.match(projectSettingsJs, /getConfiguredTableColumnWidthMap\("summaryColumnsTable"\)/);
  assert.match(projectSettingsJs, /sourceDataFeature\.applyConfiguredColumnWidths\(\)/);
});

test("column resize handles do not bubble clicks into sortable headers", () => {
  assert.match(
    tableColumnsJs,
    /resizer\.addEventListener\("click", \(e\) => \{\s*e\.preventDefault\(\);\s*e\.stopPropagation\(\);\s*\}\);/,
  );
  assert.match(
    reservingClassTypesJs,
    /th\.addEventListener\("click", \(event\) => \{\s*if \(!event\.target\.closest\("\.table-col-label"\)\) return;/,
  );
});

test("Project Settings table defaults come from the editable server preference JSON", () => {
  const tables = projectSettingsDefaultPreferences?.projectSettings?.tables;
  assert.deepEqual(Object.keys(tables).sort(), [
    "auditLogTable",
    "dataProcessingRulesTable",
    "datasetTypesTable",
    "fieldMappingTable",
    "reservingClassTypesTable",
    "summaryColumnsTable",
  ]);
  assert.deepEqual(tables.dataProcessingRulesTable.widths, {
    Enabled: 72,
    Name: 220,
    "Dataset type": 190,
    "Applies when": 300,
    Effect: 420,
  });
  assert.match(projectSettingsJs, /loadProjectUserPreferences\(project\?\.name, \{ forceReload: true \}\)/);
  assert.match(tableColumnsJs, /preferences\?\.projectSettings\?\.tables/);
  assert.match(tableColumnsJs, /else if \(configuredWidths\) \{\s*applyTableColumnWidths/);
});
