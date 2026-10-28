/* Transport for the Stochastic Consolidation page: the /stochastic-consolidation
   routes (load, consolidate without writing, the segment picker's
   candidates, and the revision-aware save). */

function text(value) {
  return String(value ?? "").trim();
}

async function requestJson(path, body, options = {}) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
    signal: options.signal,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload?.ok === false) {
    const error = new Error(text(payload?.detail || payload?.error) || `HTTP ${response.status}`);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

function classBody({ project_name, reserving_class } = {}) {
  return {
    project_name: text(project_name),
    reserving_class: text(reserving_class),
  };
}

function saveBody({
  project_name,
  reserving_class,
  method,
  notes,
  expected_owned_revision,
  expected_derived_revision,
  plan_fingerprint,
} = {}) {
  return {
    ...classBody({ project_name, reserving_class }),
    method,
    notes: String(notes ?? ""),
    ...(text(expected_owned_revision) ? { expected_owned_revision: text(expected_owned_revision) } : {}),
    ...(text(expected_derived_revision) ? { expected_derived_revision: text(expected_derived_revision) } : {}),
    ...(text(plan_fingerprint) ? { plan_fingerprint: text(plan_fingerprint) } : {}),
  };
}

export function loadStochasticConsolidation(identity = {}, options = {}) {
  return requestJson("/stochastic-consolidation/load", {
    ...classBody(identity),
    method_name: text(identity.method_name),
  }, options);
}

/* Runs the page's settings on the server and returns the result without
   writing anything; Save publishes the same run. */
export function consolidateStochasticConsolidation({ project_name, reserving_class, method } = {}, options = {}) {
  return requestJson("/stochastic-consolidation/consolidate", {
    ...classBody({ project_name, reserving_class }),
    method,
  }, options);
}

/* source_project_name lists the bootstraps of another project, for a segment
   taken from there; blank lists the consolidation's own project. */
export function listStochasticConsolidationCandidates(identity = {}, options = {}) {
  const source = text(identity.source_project_name);
  return requestJson("/stochastic-consolidation/segments/candidates", {
    ...classBody(identity),
    ...(source ? { source_project_name: source } : {}),
  }, options);
}

export function planStochasticConsolidationSave(input = {}, options = {}) {
  return requestJson("/stochastic-consolidation/save/plan", saveBody(input), options);
}

export function saveStochasticConsolidation(input = {}, options = {}) {
  return requestJson("/stochastic-consolidation/save", saveBody(input), options);
}
