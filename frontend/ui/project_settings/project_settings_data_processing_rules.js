import { attachArcrhoTooltip } from "../shared/components/tooltip/tooltip.js";
import {
  clearTableSkeletonRows,
  renderTableSkeletonRows,
} from "./project_settings_skeleton.js?v=20260821pstree1";
import {
  createDataProcessingRulesRequestId,
  describeDataProcessingRulesSaveResult,
  waitForDataProcessingRulesJob,
} from "./project_settings_data_processing_rules_job.js?v=20260927smb18";

const RULES_FORMAT = "arcrho-data-processing-rules-v1";

function cleanText(value) {
  return String(value ?? "").trim();
}

export function sentenceCaseUiLabel(value) {
  const text = cleanText(value)
    .replaceAll("_", " ")
    .replace(/\s+/g, " ")
    .toLowerCase();
  return text ? `${text.charAt(0).toUpperCase()}${text.slice(1)}` : "";
}

function projectKey(value) {
  return cleanText(value).toLowerCase();
}

function cloneJson(value) {
  return JSON.parse(JSON.stringify(value));
}

export function reorderRules(rules, fromIndex, toIndex) {
  const next = Array.isArray(rules) ? rules.slice() : [];
  const from = Number(fromIndex);
  const to = Number(toIndex);
  if (!Number.isInteger(from) || !Number.isInteger(to)
      || from < 0 || from >= next.length || to < 0 || to >= next.length
      || from === to) {
    return next;
  }
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
}

function validationErrorRuleNumber(message) {
  const match = cleanText(message).match(/^Rule\s+(\d+)(?:\s|\()/i);
  if (!match) return null;
  const ruleNumber = Number(match[1]);
  return Number.isInteger(ruleNumber) && ruleNumber > 0 ? ruleNumber : null;
}

export function groupEditorValidationErrors(errors, currentRuleNumber) {
  const normalized = (Array.isArray(errors) ? errors : [])
    .map(cleanText)
    .filter(Boolean);
  const activeRuleNumber = Number(currentRuleNumber);
  const hasActiveRule = Number.isInteger(activeRuleNumber) && activeRuleNumber > 0;
  const currentRule = [];
  const otherRules = [];
  const project = [];

  for (const message of normalized) {
    const ruleNumber = validationErrorRuleNumber(message);
    if (ruleNumber === null) {
      project.push(message);
    } else if (hasActiveRule && ruleNumber === activeRuleNumber) {
      currentRule.push(message);
    } else {
      otherRules.push(message);
    }
  }

  const blocks = [];
  if (currentRule.length) {
    blocks.push(`This rule needs attention:\n${currentRule.map((message) => `- ${message}`).join("\n")}`);
  }
  if (otherRules.length) {
    blocks.push(
      `Other saved rules must be fixed before this change can be saved:\n`
      + otherRules.map((message) => `- ${message}`).join("\n"),
    );
  }
  if (project.length) {
    blocks.push(
      `Project configuration errors must be fixed before this change can be saved:\n`
      + project.map((message) => `- ${message}`).join("\n"),
    );
  }

  return {
    currentRule,
    otherRules,
    project,
    message: blocks.join("\n\n"),
  };
}

export function clampFloatingEditorPosition({
  left,
  top,
  width,
  height,
  viewportWidth,
  viewportHeight,
  padding = 8,
} = {}) {
  const safePadding = Math.max(0, Number(padding) || 0);
  const maxLeft = Math.max(safePadding, (Number(viewportWidth) || 0) - (Number(width) || 0) - safePadding);
  const maxTop = Math.max(safePadding, (Number(viewportHeight) || 0) - (Number(height) || 0) - safePadding);
  return {
    left: Math.max(safePadding, Math.min(maxLeft, Number(left) || 0)),
    top: Math.max(safePadding, Math.min(maxTop, Number(top) || 0)),
  };
}

function normalizeExactValueList(raw) {
  if (!Array.isArray(raw)) return [];
  const out = [];
  const seen = new Set();
  for (const item of raw) {
    const value = cleanText(item);
    if (!value || seen.has(value)) continue;
    seen.add(value);
    out.push(value);
  }
  return out;
}

function createRuleId() {
  const randomUuid = globalThis.crypto?.randomUUID?.();
  if (randomUuid) return `rule-${randomUuid}`;
  const randomPart = Math.random().toString(36).slice(2, 10);
  return `rule-${Date.now().toString(36)}-${randomPart}`;
}

function normalizeConditionScalar(value) {
  if (typeof value === "string") return cleanText(value);
  if (typeof value === "number" || typeof value === "boolean" || value === null) return value;
  return cleanText(value);
}

function rawValuesFromCondition(condition) {
  const raw = condition?.value;
  const values = Array.isArray(raw) ? raw : [raw];
  const out = [];
  const seen = new Set();
  for (const item of values) {
    if (item === undefined) continue;
    const value = normalizeConditionScalar(item);
    const signature = `${value === null ? "null" : typeof value}:${JSON.stringify(value)}`;
    if (seen.has(signature)) continue;
    seen.add(signature);
    out.push(value);
  }
  return out;
}

function displayConditionValue(value) {
  return value === null ? "null" : cleanText(value);
}

function valuesFromCondition(condition) {
  return rawValuesFromCondition(condition).map(displayConditionValue).filter(Boolean);
}

function normalizeCondition(raw, { request = false } = {}) {
  const operator = cleanText(raw?.operator || "equals").toLowerCase();
  const values = rawValuesFromCondition(raw);
  const condition = {
    field: cleanText(raw?.field),
    operator,
  };
  if (operator === "in" || operator === "not_in") {
    condition.value = values;
  } else if (operator !== "is_blank" && operator !== "is_not_blank") {
    condition.value = normalizeConditionScalar(Array.isArray(raw?.value) ? raw.value[0] : raw?.value);
  }
  if (request || raw?.level !== undefined) {
    const level = Number(raw?.level);
    if (Number.isFinite(level) && level > 0) condition.level = level;
  }
  return condition;
}

function normalizeRule(raw) {
  const actionType = cleanText(raw?.action?.type) === "exclude_members"
    ? "exclude_members"
    : "keep_members";
  const actionLevel = Number(raw?.action?.level);
  const rule = {
    id: cleanText(raw?.id),
    name: cleanText(raw?.name),
    enabled: raw?.enabled !== false,
    target: {
      source_measure: cleanText(raw?.target?.source_measure),
    },
    request_conditions: {
      all: (Array.isArray(raw?.request_conditions?.all) ? raw.request_conditions.all : [])
        .map((condition) => normalizeCondition(condition, { request: true }))
        .filter((condition) => condition.field),
    },
    row_conditions: {
      all: (Array.isArray(raw?.row_conditions?.all) ? raw.row_conditions.all : [])
        .map((condition) => normalizeCondition(condition))
        .filter((condition) => condition.field),
    },
    action: {
      type: actionType,
      field: cleanText(raw?.action?.field),
      members: normalizeExactValueList(raw?.action?.members),
    },
  };
  if (Number.isFinite(actionLevel) && actionLevel > 0) rule.action.level = actionLevel;
  return rule;
}

function normalizeDocument(raw) {
  const revision = Number(raw?.revision);
  return {
    json_format: cleanText(raw?.json_format) || RULES_FORMAT,
    revision: Number.isFinite(revision) && revision >= 0 ? revision : 0,
    updated_at: cleanText(raw?.updated_at),
    updated_by: cleanText(raw?.updated_by),
    rules: (Array.isArray(raw?.rules) ? raw.rules : []).map(normalizeRule),
  };
}

export function normalizeDataProcessingRulesDocument(raw) {
  return normalizeDocument(raw);
}

const OPERATOR_LABELS = {
  equals: "is",
  in: "is any of",
  not_equals: "is not",
  not_in: "is none of",
  is_blank: "is blank",
  is_not_blank: "is not blank",
  greater_than: "greater than",
  greater_than_or_equal: "at least",
  less_than: "less than",
  less_than_or_equal: "at most",
};

// UI operators merge equals/in ("is") and not_equals/not_in ("is not"); the
// saved JSON operator is picked from the committed value count.
const REQUEST_UI_OPERATORS = [
  { id: "is", label: "is", multi: true },
  { id: "is_not", label: "is not", multi: true },
];

const UI_OPERATORS = [
  ...REQUEST_UI_OPERATORS,
  { id: "is_blank", label: "is blank", noValue: true },
  { id: "is_not_blank", label: "is not blank", noValue: true },
  { id: "greater_than", label: "greater than", single: true },
  { id: "greater_than_or_equal", label: "at least", single: true },
  { id: "less_than", label: "less than", single: true },
  { id: "less_than_or_equal", label: "at most", single: true },
];

function uiOperatorDefinition(id) {
  return UI_OPERATORS.find((item) => item.id === id) || UI_OPERATORS[0];
}

export function uiConditionFromJson(raw) {
  const condition = normalizeCondition(raw || {});
  const rawValues = rawValuesFromCondition(condition);
  const values = rawValues.map(displayConditionValue).filter(Boolean);
  let operator = condition.operator;
  if (operator === "equals" || operator === "in") operator = "is";
  else if (operator === "not_equals" || operator === "not_in") operator = "is_not";
  const ui = { field: condition.field, operator, values };
  if (condition.level !== undefined) ui.level = condition.level;
  Object.defineProperty(ui, "_rawValues", {
    value: rawValues,
    writable: true,
    enumerable: false,
  });
  return ui;
}

export function jsonConditionFromUi(ui) {
  const field = cleanText(ui?.field);
  const operator = cleanText(ui?.operator || "is");
  const values = (Array.isArray(ui?.values) ? ui.values : [])
    .map(displayConditionValue)
    .filter(Boolean);
  const unusedRawValues = Array.isArray(ui?._rawValues) ? [...ui._rawValues] : [];
  const semanticValues = values.map((value) => {
    const index = unusedRawValues.findIndex((rawValue) => displayConditionValue(rawValue) === value);
    if (index < 0) return value;
    return unusedRawValues.splice(index, 1)[0];
  });
  const uniqueSemanticValues = [];
  const seenSemanticValues = new Set();
  for (const value of semanticValues) {
    const signature = `${value === null ? "null" : typeof value}:${JSON.stringify(value)}`;
    if (seenSemanticValues.has(signature)) continue;
    seenSemanticValues.add(signature);
    uniqueSemanticValues.push(value);
  }
  const condition = {
    field,
    operator,
    value: uniqueSemanticValues.length === 1 ? uniqueSemanticValues[0] : uniqueSemanticValues,
  };
  if (operator === "is") {
    condition.operator = uniqueSemanticValues.length > 1 ? "in" : "equals";
  } else if (operator === "is_not") {
    condition.operator = uniqueSemanticValues.length > 1 ? "not_in" : "not_equals";
  } else if (operator === "is_blank" || operator === "is_not_blank") {
    delete condition.value;
  } else {
    condition.value = uniqueSemanticValues[0] ?? "";
  }
  const level = Number(ui?.level);
  if (Number.isFinite(level) && level > 0) condition.level = level;
  return condition;
}

// Splits the unified "Then" condition list back into the persisted shape:
// one positive values-list condition becomes action.field/members, the rest
// stay row_conditions. For "keep only" the member condition must be
// unambiguous because the engine leaves rows outside the row filter
// untouched; for "exclude" any split is behavior-identical.
export function splitThenConditions(uiConditions, { actionType = "keep_members", isReservingField = () => false } = {}) {
  const conditions = (Array.isArray(uiConditions) ? uiConditions : [])
    .filter((item) => cleanText(item?.field));
  const positive = conditions.filter(
    (item) => cleanText(item.operator || "is") === "is" && normalizeExactValueList(item.values).length > 0,
  );
  const reservingPositive = positive.filter((item) => isReservingField(item.field));
  const candidates = reservingPositive.length ? reservingPositive : positive;

  let error = "";
  if (!candidates.length) {
    error = "Add at least one \"is\" condition listing the values to keep or exclude.";
  } else if (actionType === "keep_members" && reservingPositive.length > 1) {
    error = "\"Keep only\" needs a single values-list condition on a reserving-class field. "
      + "Combine the lists into one condition or split the rule.";
  }

  const actionCondition = candidates[0] || null;
  const rowConditions = conditions
    .filter((item) => item !== actionCondition)
    .map((item) => jsonConditionFromUi(item))
    .map((item) => {
      const condition = { ...item };
      delete condition.level;
      return condition;
    });
  return {
    action: actionCondition
      ? { field: cleanText(actionCondition.field), members: normalizeExactValueList(actionCondition.values) }
      : { field: "", members: [] },
    rowConditions,
    error,
  };
}

export function composeAutoRuleName(rule, { datasetLabel = "" } = {}) {
  const normalized = normalizeRule(rule || {});
  const dataset = cleanText(datasetLabel) || sentenceCaseUiLabel(normalized.target.source_measure) || "Rule";
  const verb = normalized.action.type === "exclude_members" ? "exclude" : "keep";
  const members = normalized.action.members.join(", ") || "…";
  const requestConditions = normalized.request_conditions.all;
  const scopeValues = requestConditions.flatMap((condition) => valuesFromCondition(condition));
  const hasNegativeScope = requestConditions.some(
    (condition) => ["not_equals", "not_in"].includes(cleanText(condition.operator)),
  );
  const scope = scopeValues.length
    ? ` for ${hasNegativeScope
      ? requestConditions.map((condition) => conditionSummary(condition)).join(" and ")
      : scopeValues.join(", ")}`
    : "";
  const name = `${dataset} - ${verb} ${members}${scope}`;
  return name.length > 90 ? `${name.slice(0, 87)}...` : name;
}

function operatorLabel(operator, valueCount = 1) {
  const key = cleanText(operator || "equals");
  if (key === "equals" || key === "is") return valueCount > 1 ? "is any of" : "is";
  if (key === "not_equals" || key === "is_not") return valueCount > 1 ? "is none of" : "is not";
  return OPERATOR_LABELS[key] || key.replaceAll("_", " ");
}

function conditionSummary(condition) {
  const field = cleanText(condition?.field) || "(field)";
  const operator = cleanText(condition?.operator || "equals");
  if (operator === "is_blank" || operator === "is_not_blank") {
    return `${field} ${operatorLabel(operator)}`;
  }
  const values = valuesFromCondition(condition);
  return `${field} ${operatorLabel(operator, values.length)} ${values.join(", ") || "(value)"}`;
}

// Wording mirrors the engine mask `NOT(row filter) OR action`: exclude is an
// exact AND filter, keep-with-filter leaves unfiltered rows untouched.
export function describeRuleEffect(rule) {
  const normalized = normalizeRule(rule || {});
  const filters = normalized.row_conditions.all.map((condition) => conditionSummary(condition));
  const field = cleanText(normalized.action.field) || "(field)";
  const members = normalized.action.members.join(", ") || "(no members)";
  const memberPhrase = `${field} ${operatorLabel("is", normalized.action.members.length)} ${members}`;
  if (normalized.action.type === "exclude_members") {
    return `Exclude rows where ${[...filters, memberPhrase].join(" and ")}`;
  }
  if (filters.length) {
    return `Keep only rows where ${memberPhrase} among rows where ${filters.join(" and ")} (other rows are untouched)`;
  }
  return `Keep only rows where ${memberPhrase}`;
}

function ruleSummary(rule) {
  const request = rule.request_conditions.all.map((condition) => conditionSummary(condition)).join(" and ");
  const requestText = request || "any requested coverage";
  const sourceMeasure = sentenceCaseUiLabel(rule.target.source_measure) || "(source measure)";
  const effect = describeRuleEffect(rule);
  return `For ${sourceMeasure}, when ${requestText}, ${effect.charAt(0).toLowerCase()}${effect.slice(1)}.`;
}

export function summarizeDataProcessingRule(raw) {
  return ruleSummary(normalizeRule(raw));
}

function normalizeOptionList(raw) {
  if (!Array.isArray(raw)) return [];
  const out = [];
  const seen = new Set();
  for (const item of raw) {
    const value = cleanText(
      typeof item === "string"
        ? item
        : item?.field ?? item?.field_name ?? item?.name ?? item?.value,
    );
    const key = value.toLowerCase();
    if (!value || seen.has(key)) continue;
    seen.add(key);
    out.push(value);
  }
  return out;
}

function normalizeValuesByMeasure(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const out = {};
  for (const [measure, values] of Object.entries(raw)) {
    const key = cleanText(measure);
    if (!key) continue;
    out[key] = normalizeExactValueList(Array.isArray(values) ? values : [values]);
  }
  return out;
}

function valueListForMeasure(valuesByMeasure, sourceMeasure) {
  const key = projectKey(sourceMeasure);
  if (!key) return [];
  for (const [measure, values] of Object.entries(valuesByMeasure || {})) {
    if (projectKey(measure) === key) return Array.isArray(values) ? values : [];
  }
  return [];
}

function hasMeasureVocabularyEntry(valuesByMeasure, sourceMeasure) {
  const key = projectKey(sourceMeasure);
  return !!key && Object.keys(valuesByMeasure || {}).some((measure) => projectKey(measure) === key);
}

function normalizeSourceKeyFields(raw) {
  const out = [];
  const seen = new Set();
  for (const item of Array.isArray(raw) ? raw : []) {
    const field = cleanText(typeof item === "string" ? item : item?.field ?? item?.field_name ?? item?.name);
    const key = projectKey(field);
    if (!field || seen.has(key)) continue;
    seen.add(key);
    const level = Number(typeof item === "string" ? null : item?.level);
    out.push({
      field,
      level: Number.isFinite(level) && level > 0 ? level : null,
    });
  }
  return out;
}

function normalizeSourceCombinations(raw, keyFields) {
  const out = [];
  const seen = new Set();
  for (const item of Array.isArray(raw) ? raw : []) {
    let values;
    if (Array.isArray(item)) {
      values = keyFields.map((_field, index) => cleanText(item[index]));
    } else if (item && typeof item === "object") {
      values = keyFields.map(({ field }) => {
        const match = Object.entries(item).find(([key]) => projectKey(key) === projectKey(field));
        return cleanText(match?.[1]);
      });
    } else {
      continue;
    }
    const signature = JSON.stringify(values);
    if (seen.has(signature)) continue;
    seen.add(signature);
    out.push(values);
  }
  return out;
}

export function normalizeSourceComboInventory(raw) {
  const keyFields = normalizeSourceKeyFields(raw?.key_fields ?? raw?.keyFields);
  const datasets = {};
  const rawDatasets = raw?.datasets && typeof raw.datasets === "object" && !Array.isArray(raw.datasets)
    ? raw.datasets
    : {};
  for (const [rawMeasure, rawDataset] of Object.entries(rawDatasets)) {
    const sourceMeasure = cleanText(rawMeasure || rawDataset?.source_measure || rawDataset?.sourceMeasure);
    if (!sourceMeasure) continue;
    const combinations = normalizeSourceCombinations(
      rawDataset?.combinations ?? rawDataset?.combos,
      keyFields,
    );
    const rowCount = Number(rawDataset?.row_count ?? rawDataset?.rowCount);
    const declaredCombinationCount = Number(
      rawDataset?.combination_count ?? rawDataset?.combinationCount,
    );
    datasets[sourceMeasure] = {
      datasetType: cleanText(rawDataset?.dataset_type ?? rawDataset?.datasetType),
      rowCount: Number.isFinite(rowCount) && rowCount >= 0 ? rowCount : 0,
      combinationCount: Number.isFinite(declaredCombinationCount) && declaredCombinationCount >= 0
        ? declaredCombinationCount
        : combinations.length,
      combinations,
    };
  }
  return {
    jsonFormat: cleanText(raw?.json_format ?? raw?.jsonFormat) || "arcrho-source-vocab-v1",
    keyFields,
    datasets,
    missingColumns: normalizeOptionList(raw?.missing_columns ?? raw?.missingColumns),
  };
}

function sourceDataset(inventory, sourceMeasure) {
  const key = projectKey(sourceMeasure);
  if (!key) return null;
  for (const [measure, dataset] of Object.entries(inventory?.datasets || {})) {
    if (projectKey(measure) === key) return { sourceMeasure: measure, ...dataset };
  }
  return null;
}

function sourceFieldIndex(inventory, fieldName) {
  const key = projectKey(fieldName);
  return (inventory?.keyFields || []).findIndex((item) => projectKey(item?.field) === key);
}

function uiConditionValues(condition) {
  if (Array.isArray(condition?.values)) return normalizeExactValueList(condition.values);
  return valuesFromCondition(condition);
}

function canonicalUiOperator(condition) {
  const operator = cleanText(condition?.operator || condition?.op || "is").toLowerCase();
  if (operator === "equals" || operator === "in") return "is";
  if (operator === "not_equals" || operator === "not_in") return "is_not";
  if (operator === "gte") return "greater_than_or_equal";
  if (operator === "lte") return "less_than_or_equal";
  return operator;
}

function compareSourceValues(left, right) {
  const leftText = cleanText(left);
  const rightText = cleanText(right);
  const leftNumber = Number(leftText);
  const rightNumber = Number(rightText);
  if (leftText && rightText && Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) {
    return leftNumber - rightNumber;
  }
  return leftText.localeCompare(rightText, undefined, { sensitivity: "case", numeric: true });
}

function sourceValueMatchesCondition(value, condition) {
  const candidate = cleanText(value);
  const values = uiConditionValues(condition);
  const operator = canonicalUiOperator(condition);
  if (operator === "is_blank") return !candidate;
  if (operator === "is_not_blank") return !!candidate;
  if (!values.length) return true;
  if (operator === "is") return values.includes(candidate);
  if (operator === "is_not") return !values.includes(candidate);
  const comparison = compareSourceValues(candidate, values[0]);
  if (operator === "greater_than") return comparison > 0;
  if (operator === "greater_than_or_equal") return comparison >= 0;
  if (operator === "less_than") return comparison < 0;
  if (operator === "less_than_or_equal") return comparison <= 0;
  return true;
}

export function sourceComboMatchesConditions(
  inventory,
  sourceMeasure,
  combination,
  conditions = [],
  { ignoreConditionIndex = -1, ignoreField = "", ignoreBlankConditions = false } = {},
) {
  const dataset = sourceDataset(inventory, sourceMeasure);
  if (!dataset || !Array.isArray(combination)) return false;
  const ignoredFieldKey = projectKey(ignoreField);
  return (Array.isArray(conditions) ? conditions : []).every((condition, index) => {
    if (index === ignoreConditionIndex) return true;
    if (ignoredFieldKey && projectKey(condition?.field) === ignoredFieldKey) return true;
    if (ignoreBlankConditions && canonicalUiOperator(condition) === "is_blank") return true;
    const fieldIndex = sourceFieldIndex(inventory, condition?.field);
    if (fieldIndex < 0) return true;
    return sourceValueMatchesCondition(combination[fieldIndex], condition);
  });
}

function sortSourceValues(values) {
  return normalizeExactValueList(values).sort((a, b) => (
    a.localeCompare(b, undefined, { sensitivity: "base", numeric: true })
  ));
}

export function buildDatasetFieldSuggestions(
  options,
  sourceMeasure,
  fieldName,
  conditions = [],
  { ignoreConditionIndex = -1 } = {},
) {
  const inventory = options?.sourceVocabulary || normalizeSourceComboInventory({});
  const dataset = sourceDataset(inventory, sourceMeasure);
  const fieldIndex = sourceFieldIndex(inventory, fieldName);
  if (dataset && fieldIndex >= 0 && dataset.combinations.length) {
    const compatible = dataset.combinations.filter((combination) => sourceComboMatchesConditions(
      inventory,
      sourceMeasure,
      combination,
      conditions,
      { ignoreConditionIndex, ignoreBlankConditions: true },
    ));
    return sortSourceValues(compatible.map((combination) => combination[fieldIndex]).filter(Boolean));
  }

  const key = projectKey(fieldName);
  const sourceField = (options?.sourceFields || []).find((item) => projectKey(item?.field) === key);
  const datasetValues = valueListForMeasure(sourceField?.valuesByMeasure, sourceMeasure);
  if (hasMeasureVocabularyEntry(sourceField?.valuesByMeasure, sourceMeasure)) {
    return sortSourceValues(datasetValues);
  }
  return sortSourceValues(sourceField?.values || []);
}

export function hasAuthoritativeDatasetFieldVocabulary(options, sourceMeasure, fieldName) {
  const inventory = options?.sourceVocabulary || normalizeSourceComboInventory({});
  if (sourceDataset(inventory, sourceMeasure) && sourceFieldIndex(inventory, fieldName) >= 0) {
    return true;
  }
  const sourceField = (options?.sourceFields || [])
    .find((item) => projectKey(item?.field) === projectKey(fieldName));
  return hasMeasureVocabularyEntry(sourceField?.valuesByMeasure, sourceMeasure);
}

export function analyzeDatasetConditionCombos(options, sourceMeasure, conditions = []) {
  const safeConditions = Array.isArray(conditions) ? conditions : [];
  const inventory = options?.sourceVocabulary || normalizeSourceComboInventory({});
  const dataset = sourceDataset(inventory, sourceMeasure);
  const hasUnsupportedBlank = safeConditions.some((condition) => (
    canonicalUiOperator(condition) === "is_blank"
    && sourceFieldIndex(inventory, condition?.field) >= 0
  ));
  const tokens = [];
  const issues = [];

  safeConditions.forEach((condition, conditionIndex) => {
    if (canonicalUiOperator(condition) !== "is") return;
    const field = cleanText(condition?.field);
    const fieldValues = buildDatasetFieldSuggestions(options, sourceMeasure, field);
    const sourceField = (options?.sourceFields || [])
      .find((item) => projectKey(item?.field) === projectKey(field));
    const fieldIndex = sourceFieldIndex(inventory, field);
    const inventoryHasField = !!dataset
      && fieldIndex >= 0
      && !(inventory.missingColumns || []).some((item) => projectKey(item) === projectKey(field));
    const hasFieldVocabulary = inventoryHasField
      || hasMeasureVocabularyEntry(sourceField?.valuesByMeasure, sourceMeasure)
      || (sourceField?.values || []).length > 0;
    uiConditionValues(condition).forEach((value, valueIndex) => {
      let status = "ok";
      let message = "";
      if (hasFieldVocabulary && !fieldValues.includes(value)) {
        status = "bad";
        message = `\"${value}\" does not appear in current source rows for ${cleanText(field)} in ${datasetTypeLabelForSourceMeasure(sourceMeasure, options?.sourceMeasureOptions)}; this condition currently cannot match.`;
      } else if (!hasUnsupportedBlank && dataset && fieldIndex >= 0 && dataset.combinations.length) {
        const probe = { field, operator: "is", values: [value] };
        const compatible = dataset.combinations.some((combination) => (
          sourceComboMatchesConditions(
            inventory,
            sourceMeasure,
            combination,
            safeConditions,
            { ignoreConditionIndex: conditionIndex, ignoreBlankConditions: true },
          ) && sourceValueMatchesCondition(combination[fieldIndex], probe)
        ));
        if (!compatible) {
          status = "warn";
          message = `\"${value}\" exists in ${cleanText(field)} for ${datasetTypeLabelForSourceMeasure(sourceMeasure, options?.sourceMeasureOptions)}, but does not currently occur with the other selected source values.`;
        }
      }
      const token = { conditionIndex, valueIndex, field, value, status, message };
      tokens.push(token);
      if (message) issues.push(token);
    });
  });

  const analyzableConditions = safeConditions.filter(
    (condition) => sourceFieldIndex(inventory, condition?.field) >= 0,
  );
  const matchingCombinations = dataset?.combinations?.filter((combination) => (
    sourceComboMatchesConditions(
      inventory,
      sourceMeasure,
      combination,
      analyzableConditions,
      { ignoreBlankConditions: true },
    )
  )) || [];
  const available = !hasUnsupportedBlank && !!dataset && dataset.combinations.length > 0;
  const possible = !available || !analyzableConditions.length || matchingCombinations.length > 0;
  if (!possible && !issues.length) {
    issues.push({
      conditionIndex: -1,
      valueIndex: -1,
      field: "",
      value: "",
      status: "warn",
      message: "The selected source-field conditions do not currently occur together in this dataset type.",
    });
  }
  return {
    available,
    possible,
    status: issues.some((item) => item.status === "bad")
      ? "bad"
      : (issues.length || !possible ? "warn" : "ok"),
    combinationCount: dataset?.combinations?.length || 0,
    matchCount: matchingCombinations.length,
    tokens,
    issues,
  };
}

export function buildSourceMeasureDisplayOptions(sourceMeasures = [], fieldMappingRows = []) {
  const optionsByValue = new Map();
  for (const value of normalizeOptionList(sourceMeasures)) {
    optionsByValue.set(projectKey(value), { value, label: value });
  }
  for (const row of Array.isArray(fieldMappingRows) ? fieldMappingRows : []) {
    if (cleanText(row?.significance) !== "Dataset") continue;
    const value = cleanText(row?.field_name);
    if (!value) continue;
    const label = cleanText(row?.dataset_type) || value;
    optionsByValue.set(projectKey(value), { value, label });
  }
  return Array.from(optionsByValue.values()).sort((a, b) => (
    a.label.localeCompare(b.label, undefined, { sensitivity: "base", numeric: true })
  ));
}

export function buildFieldDisplayOptions(fields = []) {
  return normalizeOptionList(fields).map((value) => ({
    value,
    label: value,
  }));
}

export function resolveActionLevelForField(options = {}, fieldName = "") {
  const key = projectKey(fieldName);
  if (!key) return null;
  for (const fields of [options.reservingClassFields, options.sourceFields]) {
    for (const item of Array.isArray(fields) ? fields : []) {
      if (projectKey(item?.field) !== key) continue;
      const level = Number(item?.level);
      if (Number.isFinite(level) && level > 0) return level;
    }
  }
  return null;
}

export function datasetTypeLabelForSourceMeasure(sourceMeasure, sourceMeasureOptions = []) {
  const rawValue = cleanText(sourceMeasure);
  const key = projectKey(rawValue);
  const match = (Array.isArray(sourceMeasureOptions) ? sourceMeasureOptions : [])
    .find((item) => projectKey(item?.value) === key);
  return cleanText(match?.label) || rawValue;
}

export function normalizeDataProcessingRulesOptions(raw) {
  const hasOwn = (key) => !!raw && Object.prototype.hasOwnProperty.call(raw, key);
  const hasSourceVocabulary = hasOwn("source_vocabulary") || hasOwn("sourceVocabulary");
  const sourceVocabulary = normalizeSourceComboInventory(raw?.source_vocabulary ?? raw?.sourceVocabulary);
  const sourceMeasureMap = new Map(
    buildSourceMeasureDisplayOptions([
      ...(Array.isArray(raw?.source_measures) ? raw.source_measures : []),
      ...Object.keys(sourceVocabulary.datasets),
    ]).map((item) => [projectKey(item.value), item]),
  );
  for (const [sourceMeasure, dataset] of Object.entries(sourceVocabulary.datasets)) {
    const key = projectKey(sourceMeasure);
    sourceMeasureMap.set(key, {
      value: sourceMeasure,
      label: cleanText(dataset.datasetType) || sourceMeasure,
    });
  }
  const sourceMeasureOptions = Array.from(sourceMeasureMap.values()).sort((a, b) => (
    a.label.localeCompare(b.label, undefined, { sensitivity: "base", numeric: true })
  ));
  const options = {
    sourceMeasures: sourceMeasureOptions.map((item) => item.value),
    sourceMeasureOptions,
    sourceFields: [],
    reservingClassFields: [],
    sourceVocabulary,
    contracts: {
      sourceMeasures: hasOwn("source_measures") || hasOwn("sourceMeasures") || hasSourceVocabulary,
      sourceFields: hasOwn("source_fields") || hasOwn("sourceFields"),
      reservingClassFields: hasOwn("reserving_class_fields") || hasOwn("reservingClassFields"),
      sourceVocabulary: hasSourceVocabulary,
    },
  };

  for (const item of Array.isArray(raw?.source_fields) ? raw.source_fields : []) {
    const field = cleanText(
      typeof item === "string"
        ? item
        : item?.field ?? item?.field_name ?? item?.name,
    );
    if (!field) continue;
    options.sourceFields.push({
      field,
      significance: cleanText(item?.significance),
      level: Number(item?.level) || null,
      values: normalizeExactValueList(item?.values),
      valuesByMeasure: normalizeValuesByMeasure(item?.values_by_measure ?? item?.valuesByMeasure),
    });
  }

  for (const item of Array.isArray(raw?.reserving_class_fields) ? raw.reserving_class_fields : []) {
    const field = cleanText(item?.field ?? item?.field_name ?? item?.name);
    if (!field) continue;
    options.reservingClassFields.push({
      field,
      level: Number(item?.level) || null,
      types: normalizeExactValueList(item?.types ?? item?.values),
      members: normalizeExactValueList(item?.members),
    });
  }
  return options;
}

function optionContracts(options) {
  return {
    sourceMeasures: !!options?.contracts?.sourceMeasures,
    sourceFields: !!options?.contracts?.sourceFields,
    reservingClassFields: !!options?.contracts?.reservingClassFields,
    sourceVocabulary: !!options?.contracts?.sourceVocabulary,
  };
}

export function mergeDataProcessingRulesOptions(primary, fallback) {
  const primaryOptions = primary || normalizeDataProcessingRulesOptions({});
  const fallbackOptions = fallback || normalizeDataProcessingRulesOptions({});
  const primaryContracts = optionContracts(primaryOptions);
  const fallbackContracts = optionContracts(fallbackOptions);
  const primaryOwnsMeasures = primaryContracts.sourceMeasures || primaryContracts.sourceVocabulary;

  let sourceMeasureOptions = cloneJson(
    primaryOwnsMeasures
      ? (primaryOptions.sourceMeasureOptions || [])
      : (fallbackOptions.sourceMeasureOptions || []),
  );
  if (primaryOwnsMeasures && !primaryContracts.sourceVocabulary) {
    sourceMeasureOptions = sourceMeasureOptions.map((item) => {
      const fallbackMatch = (fallbackOptions.sourceMeasureOptions || [])
        .find((candidate) => projectKey(candidate?.value) === projectKey(item?.value));
      return {
        ...item,
        label: cleanText(fallbackMatch?.label) || cleanText(item?.label) || cleanText(item?.value),
      };
    });
  }
  const sourceMeasures = sourceMeasureOptions.map((item) => cleanText(item?.value)).filter(Boolean);
  const sourceFields = cloneJson(
    primaryContracts.sourceFields
      ? (primaryOptions.sourceFields || [])
      : (fallbackOptions.sourceFields || []),
  );
  const reservingClassFields = cloneJson(
    primaryContracts.reservingClassFields
      ? (primaryOptions.reservingClassFields || [])
      : (fallbackOptions.reservingClassFields || []),
  );
  const selectedVocabulary = primaryContracts.sourceVocabulary
    ? primaryOptions.sourceVocabulary
    : fallbackOptions.sourceVocabulary;
  const sourceVocabulary = selectedVocabulary
    ? cloneJson(selectedVocabulary)
    : normalizeSourceComboInventory({});

  return {
    sourceMeasures,
    sourceMeasureOptions,
    sourceFields,
    reservingClassFields,
    sourceVocabulary,
    contracts: {
      sourceMeasures: primaryOwnsMeasures || fallbackContracts.sourceMeasures,
      sourceFields: primaryContracts.sourceFields || fallbackContracts.sourceFields,
      reservingClassFields: primaryContracts.reservingClassFields || fallbackContracts.reservingClassFields,
      sourceVocabulary: primaryContracts.sourceVocabulary || fallbackContracts.sourceVocabulary,
    },
  };
}

async function readJsonResponse(response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body?.detail;
    if (Array.isArray(detail)) {
      throw new Error(detail.map((item) => cleanText(item?.msg || item)).filter(Boolean).join("; "));
    }
    if (detail && typeof detail === "object") {
      const errors = Array.isArray(detail.errors) ? detail.errors.map(cleanText).filter(Boolean) : [];
      throw new Error(errors.join("; ") || cleanText(detail.message) || `HTTP ${response.status}`);
    }
    throw new Error(cleanText(detail || body?.message) || `HTTP ${response.status}`);
  }
  return body;
}

export function createDataProcessingRulesFeature(deps = {}) {
  const {
    rulesBody = null,
    rulesStatus = null,
    rowContextMenu = null,
    addButton = null,
    validateButton = null,
    jsonButton = null,
    editor = null,
    editorTitle = null,
    editorClose = null,
    editName = null,
    editEnabled = null,
    editSourceMeasure = null,
    requestConditions = null,
    addRequestConditionButton = null,
    thenConditions = null,
    addThenConditionButton = null,
    actionVerbGroup = null,
    keepHint = null,
    dprVocabWarning = null,
    vocabWarning = null,
    editSummary = null,
    editError = null,
    autoNamePill = null,
    editEnabledLabel = null,
    editorCancelButton = null,
    editorSaveButton = null,
    jsonOverlay = null,
    jsonBody = null,
    jsonClose = null,
    fetchImpl = fetch,
    setStatus = () => {},
    // Posts one shell progress message; the Engine-hosted save is followed in
    // the shell's progress window, like the Source Data import.
    publishShellProgress = null,
    loadAuditLog = async () => {},
    showConfirm = async (message) => window.confirm(message),
    initTableColumnResizing = () => {},
    positionContextMenu = (menu, x, y) => {
      menu.style.left = `${x}px`;
      menu.style.top = `${y}px`;
      menu.classList.add("show");
    },
    hideContextMenu = () => {},
    hideFolderContextMenu = () => {},
    hideTreeContextMenu = () => {},
    hideDatasetTypesRowContextMenu = () => {},
    hideReservingClassTypesRowContextMenu = () => {},
  } = deps;

  const vocabWarningHost = dprVocabWarning || vocabWarning;
  const stateByProject = new Map();
  let selectedProjectName = "";
  let loadSequence = 0;
  let editorProjectName = "";
  let editorRuleIndex = -1;
  let editorMode = "add";
  let editorDraft = null;
  let editorUi = null;
  let editorComboAnalysis = null;
  let contextRuleIndex = -1;
  let editorDragState = null;
  let openTokenMenu = null;
  let activeEditorSelect = null;
  let editorSelectPopup = null;
  let editorSelectList = null;
  let draggedRuleIndex = -1;
  let dragTargetRuleIndex = -1;
  let dragTargetAfter = false;
  let ruleOrderSaving = false;

  function setRulesStatus(message, isError = false) {
    if (!rulesStatus) return;
    rulesStatus.textContent = cleanText(message);
    rulesStatus.classList.toggle("error", !!isError);
  }

  function stateForProject(projectName) {
    const key = projectKey(projectName);
    if (!stateByProject.has(key)) {
      stateByProject.set(key, {
        document: normalizeDocument({}),
        options: normalizeDataProcessingRulesOptions({}),
        semanticHash: "",
        loaded: false,
      });
    }
    return stateByProject.get(key);
  }

  function optionForField(options, fieldName) {
    const key = projectKey(fieldName);
    return options.sourceFields.find((item) => projectKey(item.field) === key)
      || options.reservingClassFields.find((item) => projectKey(item.field) === key)
      || null;
  }

  function reservingFieldOption(options, fieldName) {
    const key = projectKey(fieldName);
    return options.reservingClassFields.find((item) => projectKey(item.field) === key) || null;
  }

  function mergeOptions(primary, fallback) {
    return mergeDataProcessingRulesOptions(primary, fallback);
  }

  async function loadFallbackOptions(projectName) {
    const encoded = encodeURIComponent(projectName);
    const requests = await Promise.allSettled([
      fetchImpl(`/field_mapping?project_name=${encoded}`).then(readJsonResponse),
      fetchImpl(`/reserving_class_types?project_name=${encoded}`).then(readJsonResponse),
    ]);

    const fieldPayload = requests[0]?.status === "fulfilled" ? requests[0].value : {};
    const reservingPayload = requests[1]?.status === "fulfilled" ? requests[1].value : {};
    const fieldRows = Array.isArray(fieldPayload?.data?.rows) ? fieldPayload.data.rows : [];
    const sourceFields = [];
    const sourceMeasureOptions = buildSourceMeasureDisplayOptions([], fieldRows);
    const sourceMeasures = sourceMeasureOptions.map((item) => item.value);
    const reservingClassFields = [];
    const reservingByLevel = new Map();

    for (const row of fieldRows) {
      const field = cleanText(row?.field_name);
      if (!field) continue;
      const significance = cleanText(row?.significance);
      const level = Number(row?.level) || null;
      sourceFields.push({ field, significance, level, values: [], valuesByMeasure: {} });
      if (significance === "Reserving Class" && level) {
        const entry = { field, level, types: [], members: [] };
        reservingClassFields.push(entry);
        reservingByLevel.set(String(level), entry);
      }
    }

    const data = reservingPayload?.data || {};
    const columns = Array.isArray(data?.columns) ? data.columns.map(cleanText) : [];
    const rows = Array.isArray(data?.rows) ? data.rows : [];
    const sourceNames = new Set(
      (Array.isArray(reservingPayload?.source_derived_names) ? reservingPayload.source_derived_names : [])
        .map(projectKey)
        .filter(Boolean),
    );
    const nameIndex = Math.max(0, columns.indexOf("Name"));
    const levelIndex = columns.indexOf("Level") >= 0 ? columns.indexOf("Level") : 1;
    const formulaIndex = columns.indexOf("Formula") >= 0 ? columns.indexOf("Formula") : 2;
    for (const row of rows) {
      if (!Array.isArray(row)) continue;
      const name = cleanText(row[nameIndex]);
      const level = cleanText(row[levelIndex]);
      const formula = cleanText(row[formulaIndex]);
      const entry = reservingByLevel.get(level);
      if (!entry || !name) continue;
      entry.types.push(name);
      if (sourceNames.has(projectKey(name)) || !formula) entry.members.push(name);
    }

    for (const item of reservingClassFields) {
      item.types = normalizeExactValueList(item.types);
      item.members = normalizeExactValueList(item.members);
    }
    return {
      sourceMeasures,
      sourceMeasureOptions,
      sourceFields,
      reservingClassFields,
      sourceVocabulary: normalizeSourceComboInventory({}),
      contracts: {
        sourceMeasures: true,
        sourceFields: true,
        reservingClassFields: true,
        sourceVocabulary: false,
      },
    };
  }

  async function loadRules(projectName, { force = false } = {}) {
    const name = cleanText(projectName);
    hideRowContextMenu();
    selectedProjectName = name;
    if (!name) {
      renderEmpty("Select a project to load data processing rules.");
      setRulesStatus("");
      return false;
    }
    const state = stateForProject(name);
    if (state.loaded && !force) {
      renderRules(name);
      return true;
    }

    const sequence = ++loadSequence;
    setRulesStatus("Loading data processing rules...");
    // Every path from here reaches the project folder, so the frame always earns itself.
    renderLoading();
    try {
      const response = await fetchImpl(`/data_processing_rules?project_name=${encodeURIComponent(name)}`);
      const payload = await readJsonResponse(response);
      const fallbackOptions = await loadFallbackOptions(name);
      if (sequence !== loadSequence || selectedProjectName !== name) return false;
      state.document = normalizeDocument(payload?.data || {});
      state.options = mergeOptions(normalizeDataProcessingRulesOptions(payload?.options || {}), fallbackOptions);
      state.semanticHash = cleanText(payload?.semantic_hash);
      state.loaded = true;
      renderRules(name);
      setRulesStatus("");
      return true;
    } catch (error) {
      if (sequence !== loadSequence) return false;
      state.document = normalizeDocument({});
      state.options = normalizeDataProcessingRulesOptions({});
      state.loaded = false;
      renderEmpty("Unable to load data processing rules.");
      setRulesStatus(`Load error: ${error.message}`, true);
      return false;
    }
  }

  /** Flowing placeholder rows while the rules are read from the project folder. */
  function renderLoading() {
    if (!rulesBody) return;
    hideRowContextMenu();
    renderTableSkeletonRows(rulesBody, { columns: 5 });
  }

  function renderEmpty(message) {
    if (!rulesBody) return;
    clearTableSkeletonRows(rulesBody);
    rulesBody.innerHTML = "";
    const text = cleanText(message) || "No custom processing rules.";
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 5;
    cell.className = "dataset-types-empty";
    cell.textContent = text;
    row.appendChild(cell);
    rulesBody.appendChild(row);
  }

  function renderRulesTable(state, rules) {
    rules.forEach((rule, index) => {
      const row = document.createElement("tr");
      row.className = "dpr-rule-row";
      row.dataset.index = String(index);

      const enabledCell = document.createElement("td");
      enabledCell.className = "dpr-enabled-cell";
      const dragHandle = document.createElement("button");
      dragHandle.type = "button";
      dragHandle.className = "dpr-row-drag-handle";
      dragHandle.draggable = true;
      dragHandle.setAttribute("aria-label", `Reorder ${rule.name || rule.id || "data processing rule"}`);
      dragHandle.setAttribute("aria-grabbed", "false");
      dragHandle.innerHTML = `
        <svg viewBox="0 0 10 14" aria-hidden="true">
          <circle cx="3" cy="3" r="1"></circle><circle cx="7" cy="3" r="1"></circle>
          <circle cx="3" cy="7" r="1"></circle><circle cx="7" cy="7" r="1"></circle>
          <circle cx="3" cy="11" r="1"></circle><circle cx="7" cy="11" r="1"></circle>
        </svg>`;
      attachArcrhoTooltip(dragHandle, "Drag to reorder rule");
      enabledCell.appendChild(dragHandle);
      const enabledCheckbox = document.createElement("input");
      enabledCheckbox.type = "checkbox";
      enabledCheckbox.className = "dpr-enabled-checkbox";
      enabledCheckbox.dataset.action = "toggle";
      enabledCheckbox.dataset.index = String(index);
      enabledCheckbox.checked = rule.enabled;
      enabledCheckbox.setAttribute(
        "aria-label",
        `${rule.enabled ? "Disable" : "Enable"} ${rule.name || rule.id || "data processing rule"}`,
      );
      const switchLabel = document.createElement("label");
      switchLabel.className = "dpr-table-switch";
      const switchTrack = document.createElement("span");
      switchTrack.className = "dpr-table-switch-track";
      switchTrack.setAttribute("aria-hidden", "true");
      switchLabel.append(enabledCheckbox, switchTrack);
      enabledCell.appendChild(switchLabel);

      const nameCell = document.createElement("td");
      nameCell.textContent = rule.name || rule.id || "(unnamed rule)";

      const measureCell = document.createElement("td");
      measureCell.textContent = datasetTypeLabelForSourceMeasure(
        rule.target.source_measure,
        state.options.sourceMeasureOptions,
      );

      const requestCell = document.createElement("td");
      requestCell.textContent = rule.request_conditions.all.length
        ? rule.request_conditions.all.map((condition) => conditionSummary(condition)).join(" and ")
        : "Any requested coverage";

      const effectCell = document.createElement("td");
      effectCell.textContent = describeRuleEffect(rule);
      for (const cell of [enabledCell, nameCell, measureCell, requestCell, effectCell]) {
        row.appendChild(cell);
      }
      rulesBody.appendChild(row);
    });
    initTableColumnResizing("dataProcessingRulesTable", [72, 220, 190, 300, 420]);
  }

  function renderRules(projectName) {
    if (!rulesBody) return;
    const name = cleanText(projectName);
    if (!name) {
      renderEmpty("Select a project to load data processing rules.");
      return;
    }
    const state = stateForProject(name);
    const rules = state.document.rules;
    if (!rules.length) {
      renderEmpty("No custom processing rules. Standard reserving-class formulas apply.");
      return;
    }

    clearTableSkeletonRows(rulesBody);
    rulesBody.innerHTML = "";
    renderRulesTable(state, rules);
  }

  function clearRuleDropMarkers() {
    rulesBody?.querySelectorAll?.(".dpr-drop-before, .dpr-drop-after").forEach((row) => {
      row.classList.remove("dpr-drop-before", "dpr-drop-after");
    });
  }

  function clearRuleDragState() {
    clearRuleDropMarkers();
    rulesBody?.querySelectorAll?.(".dpr-row-dragging").forEach((row) => {
      row.classList.remove("dpr-row-dragging");
    });
    rulesBody?.querySelectorAll?.(".dpr-row-drag-handle[aria-grabbed='true']").forEach((handle) => {
      handle.setAttribute("aria-grabbed", "false");
    });
    draggedRuleIndex = -1;
    dragTargetRuleIndex = -1;
    dragTargetAfter = false;
  }

  function handleRuleDragStart(event) {
    const handle = event.target?.closest?.(".dpr-row-drag-handle");
    const row = event.target?.closest?.("tr[data-index]");
    if (ruleOrderSaving || !handle || !row || !rulesBody?.contains(row)) {
      event.preventDefault();
      return;
    }
    const index = Number(row.dataset.index);
    const state = stateForProject(selectedProjectName);
    if (!Number.isInteger(index) || index < 0 || index >= state.document.rules.length) {
      event.preventDefault();
      return;
    }
    hideRowContextMenu();
    draggedRuleIndex = index;
    row.classList.add("dpr-row-dragging");
    handle.setAttribute("aria-grabbed", "true");
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", String(index));
    }
  }

  function handleRuleDragOver(event) {
    if (draggedRuleIndex < 0 || ruleOrderSaving) return;
    const row = event.target?.closest?.("tr[data-index]");
    if (!row || !rulesBody?.contains(row)) return;
    const index = Number(row.dataset.index);
    if (!Number.isInteger(index)) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    const bounds = row.getBoundingClientRect();
    dragTargetRuleIndex = index;
    dragTargetAfter = event.clientY >= bounds.top + (bounds.height / 2);
    clearRuleDropMarkers();
    if (index !== draggedRuleIndex) {
      row.classList.add(dragTargetAfter ? "dpr-drop-after" : "dpr-drop-before");
    }
  }

  async function handleRuleDrop(event) {
    if (draggedRuleIndex < 0 || dragTargetRuleIndex < 0 || ruleOrderSaving) {
      clearRuleDragState();
      return;
    }
    event.preventDefault();
    const fromIndex = draggedRuleIndex;
    let toIndex = dragTargetRuleIndex + (dragTargetAfter ? 1 : 0);
    if (fromIndex < toIndex) toIndex -= 1;
    const state = stateForProject(selectedProjectName);
    toIndex = Math.max(0, Math.min(state.document.rules.length - 1, toIndex));
    clearRuleDragState();
    if (fromIndex === toIndex) return;

    const reordered = reorderRules(state.document.rules, fromIndex, toIndex)
      .map((rule) => cloneJson(rule));
    ruleOrderSaving = true;
    try {
      await saveRules(selectedProjectName, reordered, {
        statusMessage: "Saving rule order...",
      });
    } finally {
      ruleOrderSaving = false;
    }
  }

  function setSelectOptions(select, values, selectedValue = "", placeholder = "") {
    if (!select) return;
    const selected = cleanText(selectedValue);
    select.innerHTML = "";
    if (placeholder) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = placeholder;
      select.appendChild(option);
    }
    for (const item of values) {
      const value = cleanText(typeof item === "string" ? item : item?.value);
      if (!value) continue;
      const label = cleanText(typeof item === "string" ? item : item?.label) || value;
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      select.appendChild(option);
    }
    select.value = selected;
    if (select.value !== selected && selected) {
      const option = document.createElement("option");
      option.value = selected;
      option.textContent = selected;
      select.appendChild(option);
      select.value = selected;
    }
    syncEditorSelect(select);
  }

  function ensureEditorSelectPopup() {
    if (editorSelectPopup) return editorSelectPopup;
    editorSelectPopup = document.createElement("div");
    editorSelectPopup.className = "dpr-select-popup";
    editorSelectPopup.setAttribute("role", "listbox");
    editorSelectPopup.id = "dprEditorSelectPopup";
    editorSelectList = document.createElement("div");
    editorSelectList.className = "dpr-select-list";
    editorSelectPopup.appendChild(editorSelectList);
    editorSelectPopup.addEventListener("keydown", (event) => {
      const options = Array.from(editorSelectList?.querySelectorAll?.(".dpr-select-option") || []);
      const current = event.target?.closest?.(".dpr-select-option");
      const currentIndex = options.indexOf(current);
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        closeEditorSelectPopup({ restoreFocus: true });
        return;
      }
      if (event.key === "Tab") {
        closeEditorSelectPopup();
        return;
      }
      if (event.key === "Enter" || event.key === " ") {
        if (!current || !activeEditorSelect) return;
        event.preventDefault();
        chooseEditorSelectOption(activeEditorSelect, Number(current.dataset.index));
        return;
      }
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      if (event.key === "Home") focusEditorSelectOption(0);
      else if (event.key === "End") focusEditorSelectOption(options.length - 1);
      else focusEditorSelectOption(currentIndex + (event.key === "ArrowDown" ? 1 : -1));
    });
    document.body.appendChild(editorSelectPopup);
    return editorSelectPopup;
  }

  function editorSelectTrigger(select) {
    return select?.closest?.(".dpr-select-control")?.querySelector?.(".dpr-select-trigger") || null;
  }

  function syncEditorSelect(select) {
    const trigger = editorSelectTrigger(select);
    if (!trigger) return;
    const selectedOption = select.options?.[select.selectedIndex] || null;
    const valueHost = trigger.querySelector(".dpr-select-value");
    if (valueHost) valueHost.textContent = cleanText(selectedOption?.textContent) || "Select";
    trigger.disabled = !!select.disabled;
    trigger.classList.toggle("placeholder", !cleanText(select.value));
    if (activeEditorSelect === select) {
      renderEditorSelectPopup(select);
      positionEditorSelectPopup(select);
    }
  }

  function closeEditorSelectPopup({ restoreFocus = false } = {}) {
    const previousSelect = activeEditorSelect;
    activeEditorSelect = null;
    editorSelectPopup?.classList.remove("open");
    const trigger = editorSelectTrigger(previousSelect);
    trigger?.setAttribute("aria-expanded", "false");
    if (restoreFocus) trigger?.focus?.();
  }

  function positionEditorSelectPopup(select) {
    const popup = ensureEditorSelectPopup();
    const trigger = editorSelectTrigger(select);
    if (!trigger || !popup.classList.contains("open")) return;
    const rect = trigger.getBoundingClientRect();
    const viewportPadding = 8;
    const gap = 4;
    const width = Math.max(120, Math.round(rect.width));
    const spaceBelow = Math.max(0, window.innerHeight - rect.bottom - gap - viewportPadding);
    const spaceAbove = Math.max(0, rect.top - gap - viewportPadding);
    const availableHeight = Math.max(72, Math.min(240, Math.max(spaceBelow, spaceAbove)));
    popup.style.width = `${width}px`;
    popup.style.maxHeight = `${availableHeight}px`;
    if (editorSelectList) editorSelectList.style.maxHeight = `${Math.max(64, availableHeight - 8)}px`;

    const useAbove = spaceBelow < Math.min(160, popup.scrollHeight) && spaceAbove > spaceBelow;
    const popupHeight = Math.min(popup.offsetHeight, availableHeight);
    const top = useAbove
      ? Math.max(viewportPadding, rect.top - gap - popupHeight)
      : Math.min(window.innerHeight - viewportPadding - popupHeight, rect.bottom + gap);
    const left = Math.max(
      viewportPadding,
      Math.min(rect.left, window.innerWidth - viewportPadding - width),
    );
    popup.style.left = `${Math.round(left)}px`;
    popup.style.top = `${Math.round(top)}px`;
  }

  function focusEditorSelectOption(index) {
    const items = Array.from(editorSelectList?.querySelectorAll?.(".dpr-select-option") || []);
    if (!items.length) return;
    const numericIndex = Number.isFinite(Number(index)) ? Number(index) : 0;
    const safeIndex = ((numericIndex % items.length) + items.length) % items.length;
    items[safeIndex].focus();
  }

  function chooseEditorSelectOption(select, index) {
    const option = select?.options?.[index];
    if (!option || option.disabled) return;
    const trigger = editorSelectTrigger(select);
    select.value = option.value;
    syncEditorSelect(select);
    closeEditorSelectPopup();
    select.dispatchEvent(new Event("change", { bubbles: true }));
    if (trigger?.isConnected) trigger.focus();
  }

  function renderEditorSelectPopup(select) {
    ensureEditorSelectPopup();
    if (!editorSelectList) return;
    editorSelectList.replaceChildren();
    Array.from(select?.options || []).forEach((option, index) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "dpr-select-option";
      item.setAttribute("role", "option");
      item.setAttribute("aria-selected", option.selected ? "true" : "false");
      item.dataset.index = String(index);
      item.disabled = !!option.disabled;
      if (option.selected) item.classList.add("selected");

      const label = document.createElement("span");
      label.className = "dpr-select-option-label";
      label.textContent = cleanText(option.textContent) || "Select";
      const check = document.createElement("svg");
      check.classList.add("dpr-select-option-check");
      check.setAttribute("viewBox", "0 0 12 12");
      check.setAttribute("aria-hidden", "true");
      check.innerHTML = '<path d="M2 6.2 4.8 9 10 3"></path>';
      item.append(label, check);
      item.addEventListener("mousedown", (event) => event.preventDefault());
      item.addEventListener("click", () => chooseEditorSelectOption(select, index));
      editorSelectList.appendChild(item);
    });
  }

  function openEditorSelectPopup(select, { focus = false } = {}) {
    const trigger = editorSelectTrigger(select);
    if (!trigger || trigger.disabled) return;
    closeTokenMenu();
    if (activeEditorSelect && activeEditorSelect !== select) closeEditorSelectPopup();
    activeEditorSelect = select;
    renderEditorSelectPopup(select);
    ensureEditorSelectPopup().classList.add("open");
    trigger.setAttribute("aria-expanded", "true");
    positionEditorSelectPopup(select);
    if (focus) {
      const selectedIndex = Math.max(0, select.selectedIndex);
      focusEditorSelectOption(selectedIndex);
    }
  }

  function enhanceEditorSelect(select) {
    if (!select) return null;
    const existing = select.closest?.(".dpr-select-control");
    if (existing) {
      syncEditorSelect(select);
      return existing;
    }
    const control = document.createElement("div");
    control.className = "dpr-select-control";
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "dpr-select-trigger";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    trigger.setAttribute("aria-controls", "dprEditorSelectPopup");
    trigger.setAttribute("aria-label", select.getAttribute("aria-label") || "Select option");
    const value = document.createElement("span");
    value.className = "dpr-select-value";
    const caret = document.createElement("span");
    caret.className = "dpr-select-caret";
    caret.setAttribute("aria-hidden", "true");
    trigger.append(value, caret);

    select.parentNode?.insertBefore(control, select);
    select.classList.add("dpr-native-select");
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");
    control.append(select, trigger);
    trigger.addEventListener("click", () => {
      if (activeEditorSelect === select) closeEditorSelectPopup();
      else openEditorSelectPopup(select);
    });
    trigger.addEventListener("keydown", (event) => {
      if (!["ArrowDown", "ArrowUp", "Home", "End", "Enter", " "].includes(event.key)) return;
      event.preventDefault();
      openEditorSelectPopup(select, { focus: true });
      if (event.key === "Home") focusEditorSelectOption(0);
      if (event.key === "End") focusEditorSelectOption(select.options.length - 1);
    });
    select.addEventListener("change", () => syncEditorSelect(select));
    syncEditorSelect(select);
    return control;
  }

  function closeTokenMenu() {
    if (openTokenMenu) {
      const menu = openTokenMenu;
      openTokenMenu = null;
      menu.classList.remove("open");
      menu.remove();
    }
  }

  function positionTokenMenu(menu, anchor) {
    const viewportGutter = 8;
    const menuGap = 4;
    const maximumHeight = 220;
    const anchorRect = anchor.getBoundingClientRect();
    const availableWidth = Math.max(0, window.innerWidth - (viewportGutter * 2));
    const menuWidth = Math.min(Math.max(anchorRect.width, 220), availableWidth);
    const spaceBelow = window.innerHeight - anchorRect.bottom - menuGap - viewportGutter;
    const spaceAbove = anchorRect.top - menuGap - viewportGutter;
    const preferredHeight = Math.min(menu.scrollHeight, maximumHeight);
    const openAbove = spaceBelow < preferredHeight && spaceAbove > spaceBelow;
    const availableHeight = Math.max(40, openAbove ? spaceAbove : spaceBelow);
    const menuHeight = Math.min(preferredHeight, availableHeight);
    const maximumLeft = window.innerWidth - viewportGutter - menuWidth;
    const left = Math.max(viewportGutter, Math.min(anchorRect.left, maximumLeft));
    const top = openAbove
      ? Math.max(viewportGutter, anchorRect.top - menuGap - menuHeight)
      : Math.min(anchorRect.bottom + menuGap, window.innerHeight - viewportGutter - menuHeight);

    menu.style.width = `${Math.round(menuWidth)}px`;
    menu.style.maxHeight = `${Math.floor(Math.min(maximumHeight, availableHeight))}px`;
    menu.style.left = `${Math.round(left)}px`;
    menu.style.top = `${Math.round(top)}px`;
  }

  function suggestionsForField(kind, fieldName, activeCondition = null) {
    const state = stateForProject(editorProjectName);
    const reserving = reservingFieldOption(state.options, fieldName);
    if (kind === "request") return reserving?.types || [];
    const sourceMeasure = cleanText(editSourceMeasure?.value || editorDraft?.target?.source_measure);
    const conditionIndex = editorUi?.then?.indexOf(activeCondition) ?? -1;
    const compatible = buildDatasetFieldSuggestions(
      state.options,
      sourceMeasure,
      fieldName,
      editorUi?.then || [],
      { ignoreConditionIndex: conditionIndex },
    );
    if (compatible.length) return compatible;
    const datasetWide = buildDatasetFieldSuggestions(state.options, sourceMeasure, fieldName);
    if (datasetWide.length) return datasetWide;
    if (hasAuthoritativeDatasetFieldVocabulary(state.options, sourceMeasure, fieldName)) return [];
    if (reserving) {
      return reserving.members?.length ? reserving.members : (reserving.types || []);
    }
    return optionForField(state.options, fieldName)?.values || [];
  }

  function discardOriginalConditionValueTypes(condition) {
    if (condition && Object.prototype.hasOwnProperty.call(condition, "_rawValues")) {
      condition._rawValues = [];
    }
  }

  function createTokenBox(condition, kind) {
    const box = document.createElement("div");
    box.className = "dpr-token-box";

    const input = document.createElement("input");
    input.type = "text";
    input.spellcheck = false;
    input.className = "dpr-token-input";
    input.placeholder = condition.values.length ? "" : "Type a value or pick from the list";

    const menu = document.createElement("div");
    menu.className = "dpr-token-menu";

    const commit = (text) => {
      const value = cleanText(text);
      if (!value || condition.values.includes(value)) {
        input.value = "";
        return;
      }
      discardOriginalConditionValueTypes(condition);
      condition.values.push(value);
      input.value = "";
      renderEditorConditions({ focus: { kind, condition } });
    };

    const refreshMenu = () => {
      const query = input.value.trim().toLowerCase();
      const suggestions = suggestionsForField(kind, condition.field, condition);
      if (!suggestions.length) {
        closeTokenMenu();
        return;
      }
      const items = suggestions.filter((value) => !query || value.toLowerCase().includes(query));
      menu.innerHTML = "";
      if (!items.length) {
        const empty = document.createElement("div");
        empty.className = "dpr-token-menu-empty";
        empty.textContent = "No matches - press Enter to add as typed";
        menu.appendChild(empty);
      }
      for (const value of items) {
        const item = document.createElement("div");
        item.className = "dpr-token-menu-item";
        const label = document.createElement("span");
        label.textContent = value;
        item.appendChild(label);
        if (condition.values.includes(value)) {
          const tick = document.createElement("span");
          tick.className = "dpr-token-menu-tick";
          tick.textContent = "✓";
          item.appendChild(tick);
        }
        item.addEventListener("mousedown", (event) => {
          event.preventDefault();
          if (condition.values.includes(value)) {
            discardOriginalConditionValueTypes(condition);
            condition.values = condition.values.filter((item2) => item2 !== value);
            renderEditorConditions({ focus: { kind, condition } });
          } else {
            commit(value);
          }
        });
        menu.appendChild(item);
      }
      closeEditorSelectPopup();
      closeTokenMenu();
      document.body.appendChild(menu);
      menu.classList.add("open");
      openTokenMenu = menu;
      positionTokenMenu(menu, box);
    };

    const conditionIndex = kind === "then" ? (editorUi?.then?.indexOf(condition) ?? -1) : -1;
    for (const [valueIndex, value] of condition.values.entries()) {
      const chip = document.createElement("span");
      chip.className = "dpr-token";
      const tokenState = editorComboAnalysis?.tokens?.find((item) => (
        item.conditionIndex === conditionIndex
        && item.valueIndex === valueIndex
      ));
      if (tokenState?.status === "bad" || tokenState?.status === "warn") {
        chip.classList.add(tokenState.status);
        chip.setAttribute("aria-label", `${value}. ${tokenState.message}`);
        attachArcrhoTooltip(chip, tokenState.message);
      }
      const text = document.createElement("span");
      text.textContent = value;
      chip.appendChild(text);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "dpr-token-remove";
      remove.textContent = "×";
      remove.setAttribute("aria-label", `Remove ${value}`);
      remove.addEventListener("click", () => {
        discardOriginalConditionValueTypes(condition);
        condition.values = condition.values.filter((item) => item !== value);
        renderEditorConditions({ focus: { kind, condition } });
      });
      chip.appendChild(remove);
      box.appendChild(chip);
    }

    input.addEventListener("focus", () => {
      box.classList.add("focus");
      refreshMenu();
    });
    input.addEventListener("blur", () => box.classList.remove("focus"));
    input.addEventListener("input", refreshMenu);
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === ",") {
        event.preventDefault();
        commit(input.value);
      } else if (event.key === "Backspace" && !input.value && condition.values.length) {
        discardOriginalConditionValueTypes(condition);
        condition.values.pop();
        renderEditorConditions({ focus: { kind, condition } });
      } else if (event.key === "Escape") {
        closeTokenMenu();
      }
    });
    box.addEventListener("mousedown", (event) => {
      if (event.target === box) {
        event.preventDefault();
        input.focus();
      }
    });

    box.appendChild(input);
    return box;
  }

  function createConditionRow(condition, kind) {
    const state = stateForProject(editorProjectName);
    const request = kind === "request";
    const row = document.createElement("div");
    row.className = "dpr-condition-row";
    row.dataset.kind = kind;

    const fieldWrap = document.createElement("div");
    fieldWrap.className = "dpr-condition-field-wrap";

    const fieldSelect = document.createElement("select");
    fieldSelect.className = "dpr-condition-field";
    const fieldOptions = request
      ? buildFieldDisplayOptions(state.options.reservingClassFields)
      : buildFieldDisplayOptions(state.options.sourceFields);
    setSelectOptions(fieldSelect, fieldOptions, condition.field, "Select field");

    const badge = document.createElement("span");
    badge.className = "dpr-condition-level";
    const fieldInfo = request
      ? reservingFieldOption(state.options, condition.field)
      : optionForField(state.options, condition.field);
    const level = Number(fieldInfo?.level) || null;
    badge.textContent = level ? `Level ${level}` : "Raw field";
    badge.classList.toggle("raw", !level);
    condition.level = request ? (level || undefined) : undefined;

    fieldSelect.addEventListener("change", () => {
      condition.field = cleanText(fieldSelect.value);
      discardOriginalConditionValueTypes(condition);
      condition.values = [];
      renderEditorConditions({ focus: { kind, condition } });
    });

    const operatorOptions = request ? REQUEST_UI_OPERATORS : UI_OPERATORS;
    const operatorSelect = document.createElement("select");
    operatorSelect.className = "dpr-condition-operator";
    setSelectOptions(operatorSelect, operatorOptions.map((item) => ({
      value: item.id,
      label: item.multi ? operatorLabel(item.id, condition.values.length) : item.label,
    })), condition.operator || "is");
    operatorSelect.addEventListener("change", () => {
      condition.operator = cleanText(operatorSelect.value) || "is";
      const definition = uiOperatorDefinition(condition.operator);
      if (definition.noValue) {
        discardOriginalConditionValueTypes(condition);
        condition.values = [];
      }
      if (definition.single && condition.values.length > 1) {
        condition.values = condition.values.slice(0, 1);
      }
      renderEditorConditions({ focus: { kind, condition } });
    });
    const operatorControl = enhanceEditorSelect(operatorSelect);

    const definition = uiOperatorDefinition(condition.operator || "is");
    let valueControl;
    if (definition.noValue) {
      valueControl = document.createElement("span");
      valueControl.className = "dpr-condition-novalue";
      valueControl.textContent = "no value needed";
    } else if (definition.single) {
      const valueInput = document.createElement("input");
      valueInput.className = "dpr-condition-value";
      valueInput.type = "text";
      valueInput.spellcheck = false;
      valueInput.placeholder = "Value";
      valueInput.value = condition.values[0] || "";
      valueInput.addEventListener("input", () => {
        discardOriginalConditionValueTypes(condition);
        condition.values = cleanText(valueInput.value) ? [cleanText(valueInput.value)] : [];
        refreshEditorComboAnalysis({ refreshTokens: true });
        updateEditorSummary();
      });
      valueInput.addEventListener("blur", () => {
        setTimeout(() => {
          if (editorUi?.then?.includes(condition)) renderEditorConditions();
        }, 0);
      });
      valueControl = valueInput;
    } else {
      valueControl = createTokenBox(condition, kind);
    }

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "dpr-condition-remove";
    remove.setAttribute("aria-label", "Remove condition");
    remove.innerHTML = `
      <svg viewBox="0 0 10 10" aria-hidden="true">
        <line x1="2" y1="2" x2="8" y2="8"></line>
        <line x1="8" y1="2" x2="2" y2="8"></line>
      </svg>
    `;
    remove.addEventListener("click", () => {
      const list = request ? editorUi.request : editorUi.then;
      const index = list.indexOf(condition);
      if (index >= 0) list.splice(index, 1);
      renderEditorConditions();
    });

    fieldWrap.append(enhanceEditorSelect(fieldSelect), badge);
    row.appendChild(fieldWrap);
    row.appendChild(operatorControl);
    row.appendChild(valueControl);
    row.appendChild(remove);
    return row;
  }

  function renderConditionList(container, conditions, kind, emptyText) {
    if (!container) return;
    container.innerHTML = "";
    conditions.forEach((condition, index) => {
      if (index > 0) {
        const joint = document.createElement("div");
        joint.className = "dpr-condition-and";
        joint.textContent = "AND";
        container.appendChild(joint);
      }
      container.appendChild(createConditionRow(condition, kind));
    });
    const empty = document.createElement("div");
    empty.className = "dpr-condition-empty";
    empty.textContent = emptyText;
    empty.hidden = conditions.length > 0;
    container.appendChild(empty);
  }

  function renderVocabularyWarning() {
    if (!vocabWarningHost) return;
    vocabWarningHost.innerHTML = "";
    const messages = normalizeOptionList(
      (editorComboAnalysis?.issues || []).map((item) => item.message),
    );
    vocabWarningHost.classList.toggle("bad", editorComboAnalysis?.status === "bad");
    vocabWarningHost.classList.toggle(
      "warn",
      !!messages.length && editorComboAnalysis?.status !== "bad",
    );
    vocabWarningHost.hidden = messages.length === 0;
    for (const [index, message] of messages.entries()) {
      if (index > 0) vocabWarningHost.appendChild(document.createElement("br"));
      vocabWarningHost.append(`\u26a0 ${message}`);
    }
  }

  function refreshRenderedTokenStates() {
    const rows = thenConditions?.querySelectorAll?.(".dpr-condition-row") || [];
    rows.forEach((row, conditionIndex) => {
      row.querySelectorAll(".dpr-token").forEach((chip, valueIndex) => {
        const tokenState = editorComboAnalysis?.tokens?.find((item) => (
          item.conditionIndex === conditionIndex && item.valueIndex === valueIndex
        ));
        chip.classList.remove("bad", "warn");
        if (tokenState?.status === "bad" || tokenState?.status === "warn") {
          chip.classList.add(tokenState.status);
          chip.setAttribute("aria-label", `${tokenState.value}. ${tokenState.message}`);
          chip.setAttribute("aria-description", tokenState.message);
        } else {
          chip.removeAttribute("aria-label");
          chip.removeAttribute("aria-description");
        }
      });
    });
  }

  function refreshEditorComboAnalysis({ refreshTokens = false } = {}) {
    if (!editorUi) return;
    const state = stateForProject(editorProjectName);
    editorComboAnalysis = analyzeDatasetConditionCombos(
      state.options,
      cleanText(editSourceMeasure?.value || editorDraft?.target?.source_measure),
      editorUi.then,
    );
    if (refreshTokens) refreshRenderedTokenStates();
    renderVocabularyWarning();
  }

  function renderEditorConditions({ focus = null } = {}) {
    if (!editorUi) return;
    closeEditorSelectPopup();
    closeTokenMenu();
    refreshEditorComboAnalysis();
    renderConditionList(
      requestConditions,
      editorUi.request,
      "request",
      "No conditions - applies to any requested coverage.",
    );
    renderConditionList(
      thenConditions,
      editorUi.then,
      "then",
      "No conditions yet - add one listing the values to keep or exclude.",
    );
    renderVerbGroup();
    updateEditorSummary();
    if (focus) {
      const container = focus.kind === "request" ? requestConditions : thenConditions;
      const list = focus.kind === "request" ? editorUi.request : editorUi.then;
      const index = list.indexOf(focus.condition);
      const row = container?.querySelectorAll?.(".dpr-condition-row")?.[index];
      row?.querySelector?.(".dpr-token-input")?.focus?.();
    }
  }

  function renderVerbGroup() {
    if (!actionVerbGroup || !editorUi) return;
    actionVerbGroup.value = editorUi.verb === "exclude_members" ? "exclude_members" : "keep_members";
    syncEditorSelect(actionVerbGroup);
  }

  function isReservingFieldName(fieldName) {
    return !!reservingFieldOption(stateForProject(editorProjectName).options, fieldName);
  }

  function collectEditorRule() {
    const state = stateForProject(editorProjectName);
    const rule = normalizeRule(editorDraft || {});
    rule.name = cleanText(editName?.value);
    rule.enabled = !!editEnabled?.checked;
    rule.target.source_measure = cleanText(editSourceMeasure?.value);
    rule.request_conditions.all = editorUi.request
      .filter((condition) => cleanText(condition.field))
      .map((condition) => jsonConditionFromUi(condition));
    const split = splitThenConditions(editorUi.then, {
      actionType: editorUi.verb,
      isReservingField: isReservingFieldName,
    });
    rule.row_conditions.all = split.rowConditions.map((condition) => normalizeCondition(condition));
    rule.action.type = editorUi.verb === "exclude_members" ? "exclude_members" : "keep_members";
    rule.action.field = split.action.field;
    rule.action.members = split.action.members;
    const actionLevel = resolveActionLevelForField(state.options, split.action.field);
    if (actionLevel) rule.action.level = actionLevel;
    else delete rule.action.level;
    return { rule, splitError: split.error };
  }

  function appendSummaryBold(host, text) {
    const bold = document.createElement("b");
    bold.textContent = cleanText(text);
    host.appendChild(bold);
  }

  function appendRichConditionSummary(host, condition) {
    const field = cleanText(condition?.field) || "(field)";
    const operator = cleanText(condition?.operator || "equals");
    const values = valuesFromCondition(condition);
    appendSummaryBold(host, field);
    if (operator === "is_blank" || operator === "is_not_blank") {
      host.append(` ${operatorLabel(operator)}`);
      return;
    }
    host.append(` ${operatorLabel(operator, values.length)} `);
    if (!values.length) {
      appendSummaryBold(host, "(value)");
      return;
    }
    values.forEach((value, index) => {
      if (index > 0) host.append(", ");
      appendSummaryBold(host, value);
    });
  }

  function appendSummaryVerb(host, text, kind) {
    const verb = document.createElement("span");
    verb.className = `dpr-summary-verb ${kind}`;
    verb.textContent = text;
    host.appendChild(verb);
  }

  function renderRichEditorSummary(rule) {
    if (!editSummary) return;
    editSummary.replaceChildren();
    editSummary.append("For ");
    appendSummaryBold(
      editSummary,
      cleanText(rule.target.source_measure) || "(source measure)",
    );
    editSummary.append(", when ");
    if (rule.request_conditions.all.length) {
      rule.request_conditions.all.forEach((condition, index) => {
        if (index > 0) editSummary.append(" and ");
        appendRichConditionSummary(editSummary, condition);
      });
    } else {
      appendSummaryBold(editSummary, "any requested coverage");
    }
    editSummary.append(", ");

    const actionCondition = {
      field: rule.action.field,
      operator: rule.action.members.length > 1 ? "in" : "equals",
      value: rule.action.members.length > 1
        ? rule.action.members
        : (rule.action.members[0] || "(no members)"),
    };
    const filters = rule.row_conditions.all;
    const keep = rule.action.type === "keep_members";
    appendSummaryVerb(editSummary, keep ? "keep only" : "exclude", keep ? "keep" : "exclude");
    editSummary.append(" rows where ");
    if (!keep && filters.length) {
      filters.forEach((condition, index) => {
        if (index > 0) editSummary.append(" and ");
        appendRichConditionSummary(editSummary, condition);
      });
      editSummary.append(" and ");
    }
    appendRichConditionSummary(editSummary, actionCondition);
    if (keep && filters.length) {
      editSummary.append(" among rows where ");
      filters.forEach((condition, index) => {
        if (index > 0) editSummary.append(" and ");
        appendRichConditionSummary(editSummary, condition);
      });
      editSummary.append(" (other rows are untouched)");
    }
    editSummary.append(".");
  }

  function updateEditorSummary() {
    if (!editSummary || !editorUi) return;
    const { rule } = collectEditorRule();
    const displayRule = cloneJson(rule);
    displayRule.target.source_measure = datasetTypeLabelForSourceMeasure(
      rule.target.source_measure,
      stateForProject(editorProjectName).options.sourceMeasureOptions,
    );
    renderRichEditorSummary(displayRule);
    if (editName && !cleanText(editName.value)) {
      editName.placeholder = composeAutoRuleName(displayRule, {
        datasetLabel: displayRule.target.source_measure,
      });
    }
    if (autoNamePill) {
      const hasManualName = !!cleanText(editName?.value);
      autoNamePill.hidden = hasManualName;
      autoNamePill.classList.toggle("hidden", hasManualName);
    }
    if (editEnabledLabel) {
      editEnabledLabel.textContent = editEnabled?.checked ? "Enabled" : "Disabled";
    }
    if (keepHint) {
      keepHint.hidden = !(
        editorUi.verb === "keep_members" && rule.row_conditions.all.length > 0
      );
    }
  }

  function setEditorError(message = "") {
    if (!editError) return;
    editError.textContent = cleanText(message);
    editError.hidden = !cleanText(message);
  }

  function newRule(state) {
    const defaultMeasure = state.options.sourceMeasureOptions[0]?.value
      || state.options.sourceMeasures[0]
      || "";
    const defaultField = state.options.reservingClassFields[0]?.field || "";
    const defaultFieldInfo = reservingFieldOption(state.options, defaultField);
    return normalizeRule({
      id: createRuleId(),
      name: "",
      enabled: true,
      target: { source_measure: defaultMeasure },
      request_conditions: { all: [] },
      row_conditions: { all: [] },
      action: {
        type: "keep_members",
        field: defaultField,
        level: defaultFieldInfo?.level || undefined,
        members: [],
      },
    });
  }

  function editorUiFromRule(rule) {
    const request = rule.request_conditions.all.map((condition) => uiConditionFromJson(condition));
    const then = [];
    if (rule.action.field) {
      then.push({
        field: rule.action.field,
        operator: "is",
        values: [...rule.action.members],
      });
    }
    for (const condition of rule.row_conditions.all) {
      then.push(uiConditionFromJson(condition));
    }
    return {
      verb: rule.action.type === "exclude_members" ? "exclude_members" : "keep_members",
      request,
      then,
    };
  }

  function openEditor(projectName, index = -1, { duplicate = false } = {}) {
    const name = cleanText(projectName);
    if (!name || !editor) return;
    const state = stateForProject(name);
    editorProjectName = name;
    editorRuleIndex = Number.isInteger(index) ? index : -1;
    editorMode = editorRuleIndex >= 0 && !duplicate ? "edit" : "add";
    if (editorRuleIndex >= 0 && editorRuleIndex < state.document.rules.length) {
      editorDraft = cloneJson(state.document.rules[editorRuleIndex]);
      if (duplicate) {
        editorDraft.id = createRuleId();
        editorDraft.name = `${editorDraft.name || "Rule"} Copy`;
      }
    } else {
      editorDraft = newRule(state);
    }
    editorUi = editorUiFromRule(normalizeRule(editorDraft));

    if (editorTitle) editorTitle.textContent = editorMode === "edit" ? "Edit Rule" : "Add rule";
    if (editName) editName.value = editorDraft.name;
    if (editEnabled) editEnabled.checked = editorDraft.enabled !== false;
    setSelectOptions(
      editSourceMeasure,
      state.options.sourceMeasureOptions,
      editorDraft.target.source_measure,
      "Select dataset type",
    );
    renderEditorConditions();
    setEditorError("");
    editor.style.left = "50%";
    editor.style.top = window.innerWidth <= 760 || window.innerHeight <= 560 ? "8px" : "52px";
    editor.style.transform = "translateX(-50%)";
    editor.classList.add("show");
    editor.setAttribute("aria-hidden", "false");
    setTimeout(() => {
      keepEditorInViewport();
      editName?.focus();
    }, 0);
  }

  function closeEditor() {
    if (!editor) return;
    closeEditorSelectPopup();
    closeTokenMenu();
    editor.classList.remove("show");
    editor.setAttribute("aria-hidden", "true");
    editorProjectName = "";
    editorRuleIndex = -1;
    editorMode = "add";
    editorDraft = null;
    editorUi = null;
    editorComboAnalysis = null;
    editorDragState = null;
    editor.classList.remove("dragging");
    if (vocabWarningHost) {
      vocabWarningHost.innerHTML = "";
      vocabWarningHost.hidden = true;
      vocabWarningHost.classList.remove("bad", "warn");
    }
    setEditorError("");
  }

  function startEditorDrag(event) {
    if (!editor || event.button !== 0) return;
    if (event.target?.closest?.("button, input, select, label")) return;
    closeEditorSelectPopup();
    closeTokenMenu();
    const rect = editor.getBoundingClientRect();
    editor.style.left = `${Math.round(rect.left)}px`;
    editor.style.top = `${Math.round(rect.top)}px`;
    editor.style.transform = "none";
    editorDragState = {
      pointerId: event.pointerId,
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
    };
    editor.classList.add("dragging");
    event.currentTarget?.setPointerCapture?.(event.pointerId);
    event.preventDefault();
  }

  function moveEditor(event) {
    if (!editor || !editorDragState || event.pointerId !== editorDragState.pointerId) return;
    const position = clampFloatingEditorPosition({
      left: event.clientX - editorDragState.offsetX,
      top: event.clientY - editorDragState.offsetY,
      width: editor.offsetWidth,
      height: editor.offsetHeight,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
    });
    editor.style.left = `${Math.round(position.left)}px`;
    editor.style.top = `${Math.round(position.top)}px`;
  }

  function stopEditorDrag(event) {
    if (!editorDragState || (event?.pointerId !== undefined && event.pointerId !== editorDragState.pointerId)) return;
    editorDragState = null;
    editor?.classList.remove("dragging");
  }

  function keepEditorInViewport() {
    if (!editor?.classList?.contains("show")) return;
    const rect = editor.getBoundingClientRect();
    const safePadding = 8;
    const alreadyVisible = rect.left >= safePadding
      && rect.top >= safePadding
      && rect.right <= window.innerWidth - safePadding
      && rect.bottom <= window.innerHeight - safePadding;
    if (alreadyVisible) return;
    const position = clampFloatingEditorPosition({
      left: rect.left,
      top: rect.top,
      width: rect.width,
      height: rect.height,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      padding: safePadding,
    });
    editor.style.left = `${Math.round(position.left)}px`;
    editor.style.top = `${Math.round(position.top)}px`;
    editor.style.transform = "none";
  }

  function wireScrollbarActivity(scrollHost) {
    if (!scrollHost || scrollHost.dataset.scrollbarActivityWired === "1") return;
    scrollHost.dataset.scrollbarActivityWired = "1";
    let idleTimer = 0;
    scrollHost.addEventListener("scroll", () => {
      scrollHost.classList.add("isScrolling");
      if (idleTimer) clearTimeout(idleTimer);
      idleTimer = setTimeout(() => scrollHost.classList.remove("isScrolling"), 550);
    }, { passive: true });
    scrollHost.addEventListener("pointermove", (event) => {
      const rect = scrollHost.getBoundingClientRect();
      const scrollbarWidth = Math.max(0, scrollHost.offsetWidth - scrollHost.clientWidth);
      const scrollbarHeight = Math.max(0, scrollHost.offsetHeight - scrollHost.clientHeight);
      const overVerticalLane = scrollHost.scrollHeight > scrollHost.clientHeight
        && scrollbarWidth > 0
        && event.clientX >= rect.right - Math.max(scrollbarWidth, 14);
      const overHorizontalLane = scrollHost.scrollWidth > scrollHost.clientWidth
        && scrollbarHeight > 0
        && event.clientY >= rect.bottom - Math.max(scrollbarHeight, 14);
      scrollHost.classList.toggle("isScrollbarHover", overVerticalLane || overHorizontalLane);
    }, { passive: true });
    scrollHost.addEventListener("pointerleave", () => {
      scrollHost.classList.remove("isScrollbarHover");
    }, { passive: true });
  }

  function validateEditorRule(rule, splitError) {
    if (!rule.target.source_measure) return "Dataset type is required.";
    for (const condition of rule.request_conditions.all) {
      if (!condition.field || valuesFromCondition(condition).length === 0) {
        return "Every requested-coverage condition needs a field and value.";
      }
    }
    if (splitError) return splitError;
    for (const condition of rule.row_conditions.all) {
      const noValue = condition.operator === "is_blank" || condition.operator === "is_not_blank";
      if (!condition.field || (!noValue && valuesFromCondition(condition).length === 0)) {
        return "Every condition needs a field and value.";
      }
    }
    if (!rule.action.field || !rule.action.members.length) {
      return "Add at least one \"is\" condition listing the values to keep or exclude.";
    }
    return "";
  }

  async function validateDocument(projectName, rules, { allowInvalid = false } = {}) {
    const response = await fetchImpl("/data_processing_rules/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_name: projectName,
        data: { rules },
      }),
    });
    const payload = await readJsonResponse(response);
    if (payload?.valid === false && !allowInvalid) {
      const errors = Array.isArray(payload?.errors) ? payload.errors.map(cleanText).filter(Boolean) : [];
      throw new Error(errors.join("; ") || "Data processing rules are invalid.");
    }
    return payload;
  }

  function publishProgress(action, progressId, details = {}) {
    publishShellProgress?.({
      type: "arcrho:project-settings-progress",
      action,
      progressId,
      ...details,
    });
  }

  function revisionConflictError() {
    const error = new Error("Rules changed in another session. The latest version has been reloaded.");
    error.statusCode = 409;
    return error;
  }

  /**
   * Save on Arco Engine, following the job in the shell's progress window.
   *
   * The Engine runs the same save next to the data, so the walk over every
   * generated dataset that follows the write is local disk instead of one
   * network round trip per file. The terminal status carries the save
   * response, so nothing is re-read afterwards. The rules are only ever
   * saved there: with no Engine or no server the save fails and says why.
   */
  async function saveRulesOnEngine(name, rules, expectedRevision) {
    const requestId = createDataProcessingRulesRequestId();
    const progressId = `rules-save-${requestId}`;
    publishProgress("open", progressId, {
      title: "Save Data Processing Rules",
      label: `Submitting the save for "${name}"...`,
      completed: 0,
      total: 0,
      countText: "Working...",
    });
    try {
      const response = await fetchImpl("/data_processing_rules/save_job", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_name: name,
          request_id: requestId,
          expected_revision: expectedRevision,
          data: { rules },
        }),
      });
      const submitted = await readJsonResponse(response);
      const terminal = await waitForDataProcessingRulesJob({
        fetchImpl,
        projectName: name,
        jobId: submitted?.job_id,
        onProgress: (progress) => publishProgress("update", progressId, {
          label: progress.label,
          completed: progress.completed,
          total: progress.total,
          countText: progress.total > 0 ? "" : "Working...",
        }),
      });
      publishProgress("update", progressId, {
        label: "Data processing rules saved.",
        completed: 1,
        total: 1,
        countText: "",
      });
      publishProgress("close", progressId, { autoCloseMs: 850 });
      return terminal?.result || {};
    } catch (error) {
      publishProgress("close", progressId);
      if (error?.statusCode === 409) throw revisionConflictError();
      throw error;
    }
  }

  async function saveRules(projectName, rules, { statusMessage = "Saving data processing rules..." } = {}) {
    const name = cleanText(projectName);
    const state = stateForProject(name);
    setRulesStatus(statusMessage);
    try {
      const payload = await saveRulesOnEngine(name, rules, state.document.revision);
      state.document = normalizeDocument(payload?.data || {});
      state.options = mergeOptions(normalizeDataProcessingRulesOptions(payload?.options || {}), state.options);
      state.semanticHash = cleanText(payload?.semantic_hash);
      state.loaded = true;
      renderRules(name);
      // The Engine save reports the datasets and methods it refreshed after
      // the write.
      const outcome = describeDataProcessingRulesSaveResult(payload);
      const suffix = outcome.text ? ` ${outcome.text}` : "";
      setRulesStatus(`Saved revision ${state.document.revision}.${suffix}`, outcome.failed);
      setStatus(`Saved data processing rules: ${name}.`);
      await loadAuditLog(name, true);
      return true;
    } catch (error) {
      // Another session saved first: the editor's copy is stale, so the
      // latest document replaces it before the user tries again.
      if (error?.statusCode === 409) await loadRules(name, { force: true });
      setRulesStatus(`Save error: ${error.message}`, true);
      setStatus(`Data processing rules save error: ${error.message}`);
      return false;
    }
  }

  async function applyEditor() {
    if (!editorProjectName || !editorDraft || !editorUi) return;
    const state = stateForProject(editorProjectName);
    const { rule, splitError } = collectEditorRule();
    if (!rule.name) {
      rule.name = composeAutoRuleName(rule, {
        datasetLabel: datasetTypeLabelForSourceMeasure(
          rule.target.source_measure,
          state.options.sourceMeasureOptions,
        ),
      });
    }
    const error = validateEditorRule(rule, splitError);
    if (error) {
      setEditorError(error);
      return;
    }
    const nextRules = state.document.rules.map((item) => cloneJson(item));
    if (editorMode === "edit" && editorRuleIndex >= 0 && editorRuleIndex < nextRules.length) {
      nextRules[editorRuleIndex] = rule;
    } else {
      nextRules.push(rule);
    }

    setEditorError("");
    if (editorSaveButton) editorSaveButton.disabled = true;
    try {
      const validation = await validateDocument(
        editorProjectName,
        nextRules,
        { allowInvalid: true },
      );
      if (validation?.options && typeof validation.options === "object") {
        state.options = mergeOptions(
          normalizeDataProcessingRulesOptions(validation.options),
          state.options,
        );
        renderRules(editorProjectName);
        const currentMeasure = cleanText(
          editSourceMeasure?.value || editorDraft?.target?.source_measure,
        );
        setSelectOptions(
          editSourceMeasure,
          state.options.sourceMeasureOptions,
          currentMeasure,
          "Select dataset type",
        );
        renderEditorConditions();
      }
      if (validation?.valid === false) {
        const errors = Array.isArray(validation?.errors)
          ? validation.errors.map(cleanText).filter(Boolean)
          : [];
        const currentRuleNumber = editorMode === "edit" && editorRuleIndex >= 0
          ? editorRuleIndex + 1
          : nextRules.length;
        const grouped = groupEditorValidationErrors(errors, currentRuleNumber);
        setEditorError(grouped.message || "Data processing rules are invalid.");
        setRulesStatus(
          `Cannot save: ${errors.join("; ") || "data processing rules are invalid."}`,
          true,
        );
        return;
      }
      const saved = await saveRules(editorProjectName, nextRules);
      if (saved) closeEditor();
    } catch (errorValue) {
      setEditorError(errorValue.message);
    } finally {
      if (editorSaveButton) editorSaveButton.disabled = false;
    }
  }

  async function validateAll(projectName) {
    const name = cleanText(projectName);
    if (!name) {
      setRulesStatus("Select a project first.", true);
      return;
    }
    const state = stateForProject(name);
    setRulesStatus("Validating data processing rules...");
    try {
      const payload = await validateDocument(name, state.document.rules, { allowInvalid: true });
      if (payload?.options && typeof payload.options === "object") {
        state.options = mergeOptions(
          normalizeDataProcessingRulesOptions(payload.options),
          state.options,
        );
        renderRules(name);
        if (editorProjectName === name && editorUi) {
          const currentMeasure = cleanText(editSourceMeasure?.value || editorDraft?.target?.source_measure);
          setSelectOptions(
            editSourceMeasure,
            state.options.sourceMeasureOptions,
            currentMeasure,
            "Select dataset type",
          );
          renderEditorConditions();
        }
      }
      if (payload?.valid === false) {
        const errors = Array.isArray(payload?.errors) ? payload.errors.map(cleanText).filter(Boolean) : [];
        throw new Error(errors.join("; ") || "Data processing rules are invalid.");
      }
      const warnings = Array.isArray(payload?.warnings) ? payload.warnings : [];
      setRulesStatus(warnings.length
        ? `Rules are valid with ${warnings.length} warning(s): ${warnings.join("; ")}`
        : "All data processing rules are valid.");
    } catch (error) {
      setRulesStatus(`Validation error: ${error.message}`, true);
    }
  }

  function showJson(projectName) {
    const name = cleanText(projectName);
    if (!name) {
      setRulesStatus("Select a project first.", true);
      return;
    }
    if (!jsonOverlay || !jsonBody) return;
    const state = stateForProject(name);
    jsonBody.textContent = JSON.stringify(state.document, null, 2);
    jsonOverlay.classList.add("show");
    jsonOverlay.setAttribute("aria-hidden", "false");
  }

  function closeJson() {
    if (!jsonOverlay) return;
    jsonOverlay.classList.remove("show");
    jsonOverlay.setAttribute("aria-hidden", "true");
  }

  function hideRowContextMenu() {
    rowContextMenu?.classList.remove("show");
    contextRuleIndex = -1;
  }

  function showRowContextMenu(event) {
    const row = event.target?.closest?.("[data-index]");
    if (!row || !rulesBody?.contains(row) || !rowContextMenu) return;
    const index = Number(row.dataset.index);
    const state = stateForProject(selectedProjectName);
    if (!Number.isInteger(index) || index < 0 || index >= state.document.rules.length) return;
    event.preventDefault();
    event.stopPropagation();
    hideContextMenu();
    hideFolderContextMenu();
    hideTreeContextMenu();
    hideDatasetTypesRowContextMenu();
    hideReservingClassTypesRowContextMenu();
    contextRuleIndex = index;
    const toggleItem = rowContextMenu.querySelector('[data-action="toggle"]');
    if (toggleItem) {
      toggleItem.textContent = state.document.rules[index].enabled ? "Disable" : "Enable";
    }
    positionContextMenu(rowContextMenu, event.clientX, event.clientY);
  }

  async function executeRuleAction(action, index) {
    const name = selectedProjectName;
    const state = stateForProject(name);
    if (!Number.isInteger(index) || index < 0 || index >= state.document.rules.length) return;
    if (action === "edit") {
      openEditor(name, index);
      return;
    }
    if (action === "duplicate") {
      openEditor(name, index, { duplicate: true });
      return;
    }
    if (action === "toggle") {
      const rules = state.document.rules.map((rule) => cloneJson(rule));
      rules[index].enabled = !rules[index].enabled;
      await saveRules(name, rules, { statusMessage: "Updating rule state..." });
      return;
    }
    if (action === "delete") {
      const rule = state.document.rules[index];
      const confirmed = await showConfirm(
        `Delete data processing rule "${rule.name || rule.id}"?`,
        "Delete data processing rule",
      );
      if (!confirmed) return;
      const rules = state.document.rules
        .filter((_rule, currentIndex) => currentIndex !== index)
        .map((item) => cloneJson(item));
      await saveRules(name, rules, { statusMessage: "Deleting data processing rule..." });
    }
  }

  async function handleTableAction(event) {
    const button = event.target?.closest?.("[data-action]");
    if (!button || !rulesBody?.contains(button)) return;
    if (button.matches?.(".dpr-enabled-checkbox")) event.preventDefault();
    await executeRuleAction(cleanText(button.dataset.action), Number(button.dataset.index));
  }

  async function handleContextMenuAction(event) {
    const item = event.target?.closest?.("[data-action]");
    if (!item || !rowContextMenu?.contains(item)) return;
    const action = cleanText(item.dataset.action);
    const index = contextRuleIndex;
    hideRowContextMenu();
    await executeRuleAction(action, index);
  }

  function wireUi() {
    const editorHeader = editor?.querySelector?.(".dpr-editor-header");
    enhanceEditorSelect(editSourceMeasure);
    enhanceEditorSelect(actionVerbGroup)?.classList.add("dpr-verb-group");
    editorHeader?.addEventListener("pointerdown", startEditorDrag);
    window.addEventListener("pointermove", moveEditor, { passive: true });
    window.addEventListener("pointerup", stopEditorDrag, { passive: true });
    window.addEventListener("pointercancel", stopEditorDrag, { passive: true });
    window.addEventListener("resize", () => {
      closeEditorSelectPopup();
      closeTokenMenu();
      keepEditorInViewport();
    }, { passive: true });
    const editorBody = editor?.querySelector?.(".dpr-editor-body");
    wireScrollbarActivity(editorBody);
    editorBody?.addEventListener("scroll", () => {
      closeEditorSelectPopup();
      closeTokenMenu();
    }, { passive: true });
    rulesBody?.addEventListener("click", handleTableAction);
    rulesBody?.addEventListener("contextmenu", showRowContextMenu);
    rulesBody?.addEventListener("dragstart", handleRuleDragStart);
    rulesBody?.addEventListener("dragover", handleRuleDragOver);
    rulesBody?.addEventListener("drop", handleRuleDrop);
    rulesBody?.addEventListener("dragend", clearRuleDragState);
    rowContextMenu?.addEventListener("click", handleContextMenuAction);
    addButton?.addEventListener("click", () => {
      if (!selectedProjectName) {
        setRulesStatus("Select a project first.", true);
        return;
      }
      openEditor(selectedProjectName);
    });
    validateButton?.addEventListener("click", () => validateAll(selectedProjectName));
    jsonButton?.addEventListener("click", () => showJson(selectedProjectName));
    editorClose?.addEventListener("click", closeEditor);
    editorCancelButton?.addEventListener("click", closeEditor);
    editorSaveButton?.addEventListener("click", applyEditor);
    addRequestConditionButton?.addEventListener("click", () => {
      const state = stateForProject(editorProjectName);
      editorUi?.request.push({
        field: state.options.reservingClassFields[0]?.field || "",
        operator: "is",
        values: [],
      });
      renderEditorConditions();
    });
    addThenConditionButton?.addEventListener("click", () => {
      const state = stateForProject(editorProjectName);
      editorUi?.then.push({
        field: state.options.sourceFields[0]?.field || "",
        operator: "is",
        values: [],
      });
      renderEditorConditions();
    });
    actionVerbGroup?.addEventListener("change", () => {
      if (!editorUi) return;
      editorUi.verb = actionVerbGroup.value === "exclude_members" ? "exclude_members" : "keep_members";
      updateEditorSummary();
    });
    editName?.addEventListener("input", updateEditorSummary);
    editEnabled?.addEventListener("change", updateEditorSummary);
    editSourceMeasure?.addEventListener("change", () => renderEditorConditions());
    jsonClose?.addEventListener("click", closeJson);
    jsonOverlay?.addEventListener("mousedown", (event) => {
      if (event.target === jsonOverlay) closeJson();
    });
    document.addEventListener("mousedown", (event) => {
      if (openTokenMenu
          && !openTokenMenu.contains(event.target)
          && !event.target?.closest?.(".dpr-token-box")) {
        closeTokenMenu();
      }
      if (activeEditorSelect
          && !editorSelectPopup?.contains?.(event.target)
          && !event.target?.closest?.(".dpr-select-control")) {
        closeEditorSelectPopup();
      }
    });
    document.addEventListener("click", (event) => {
      if (!rowContextMenu?.contains(event.target)) hideRowContextMenu();
    });
    document.addEventListener("contextmenu", (event) => {
      if (!rulesBody?.contains(event.target) && !rowContextMenu?.contains(event.target)) {
        hideRowContextMenu();
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      if (activeEditorSelect) {
        closeEditorSelectPopup({ restoreFocus: true });
        return;
      }
      if (openTokenMenu) {
        closeTokenMenu();
        return;
      }
      if (rowContextMenu?.classList.contains("show")) {
        hideRowContextMenu();
        return;
      }
      if (jsonOverlay?.classList.contains("show")) {
        closeJson();
        return;
      }
      if (editor?.classList.contains("show")) closeEditor();
    });
  }

  wireUi();

  return {
    loadRules,
    renderRules,
    renderRulesEmpty: renderEmpty,
    renderRulesLoading: renderLoading,
    openEditor,
    closeEditor,
    hideRowContextMenu,
    setRulesStatus,
    validateAll,
  };
}
