/** Shared formula identity, dataset catalog, and hosted matrix reads. */
import { loadProjectValidValueList } from "/ui/shared/services/valid_value_lists.js";

export function formulaPageIdentity() {
  const query = new URLSearchParams(globalThis.location?.search || "");
  return {
    project_name: String(document.getElementById("projectSelect")?.value || query.get("project") || "").trim(),
    reserving_class: String(document.getElementById("pathInput")?.value || query.get("path") || query.get("class") || "").trim(),
  };
}

export async function formulaRequest(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok || payload?.ok === false) throw new Error(payload?.detail || payload?.error || `HTTP ${response.status}`);
  return payload;
}

/** Each dataset of a class with its Triangle/Vector format. */
export async function formulaDatasets(identity = formulaPageIdentity(), signal) {
  if (!identity.project_name || !identity.reserving_class) return [];
  const payload = await formulaRequest(`/datasets/cached?${new URLSearchParams(identity)}`, { signal, cache: "no-store" });
  return (payload.files || []).map(item => ({ name: String(item.name || ""), format: String(item.data_format || "") })).filter(item => item.name);
}

export async function formulaDatasetNames(identity = formulaPageIdentity(), signal) {
  return (await formulaDatasets(identity, signal)).map(item => item.name);
}

export const formulaProjects = () => loadProjectValidValueList();

export async function formulaReservingClasses(projectName) {
  if (!projectName) return [];
  const payload = await formulaRequest(`/reserving_class_paths_with_data?${new URLSearchParams({ project_name: projectName })}`);
  // Dot folders are import staging areas, not reserving classes.
  return (payload.reserving_classes || []).map(String).filter(name => !name.startsWith("."));
}

export async function formulaContextOptions(name, identity) {
  const names = name === "Path"
    ? await formulaReservingClasses(identity?.project_name)
    : await formulaProjects();
  return [{ label: name === "Path" ? "Current RC (empty argument)" : "Current project (empty argument)", value: "" }, ...names.map(value => ({ label: value, value }))];
}

export async function resolveFormulaDatasets(references, identity, signal) {
  if (!references.length) return [];
  identity ??= formulaPageIdentity();
  const payload = await formulaRequest("/dataset/internal_links/resolve", {
    method: "POST", headers: { "Content-Type": "application/json" }, signal,
    body: JSON.stringify({ ...identity, references }),
  });
  if (payload.results?.length !== references.length) throw new Error("Dataset reference response is incomplete.");
  return payload.results.map(result => {
    const rows = result.row_count, cols = result.column_count;
    if (!rows || !cols || result.cells?.length !== rows * cols) throw new Error("Dataset reference has no values.");
    return { rows, cols, values: Array.from({ length: rows }, (_, r) => result.cells.slice(r * cols, (r + 1) * cols).map(cell => cell.value)) };
  });
}

export function formulaMatrixLiteral(matrix) {
  return `{${matrix.values.map(row => row.map(value => value == null ? '""' : String(value)).join(",")).join(";")}}`;
}
