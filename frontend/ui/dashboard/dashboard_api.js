// App-server calls the Dashboards page makes. Project, class, dataset and connection lists come
// from the routes the rest of the app already uses; the `/dashboard/*` routes are this page's own.

async function request(path, body = undefined) {
  const response = await fetch(path, body === undefined
    ? undefined
    : { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data?.detail;
    throw new Error(typeof detail === "string" && detail ? detail : `The request failed (${response.status}).`);
  }
  return data;
}

const query = (params) => new URLSearchParams(params).toString();

export const api = {
  list: () => request("/dashboard/list"),
  load: (path) => request("/dashboard/load", { path }),
  save: (name, data, prevPath, overwrite = false) => request("/dashboard/save", { name, data, prev_path: prevPath || "", overwrite }),
  remove: (path) => request("/dashboard/delete", { path }),
  library: () => request("/dashboard/library"),
  saveAsset: (name, widget, category = "") => request("/dashboard/library/save", { name, widget, category }),
  deleteAsset: (id) => request("/dashboard/library/delete", { id }),
  loadSource: (source) => request("/dashboard/source/load", { source }),
  sourceFields: (source) => request("/dashboard/source/fields", { source }),

  projects: async () => (await request("/arcrho/projects")).projects || [],
  reservingClasses: async (project) => (await request(`/reserving_class_paths_with_data?${query({ project_name: project })}`)).reserving_classes || [],
  datasets: async (project, reservingClass) => (await request(`/datasets/cached?${query({ project_name: project, reserving_class: reservingClass })}`)).files || [],
  connections: async (engine) => {
    const data = await request(engine === "snowflake" ? "/snowflake/connections" : "/sqlserver/connections");
    return { names: Object.keys(data.connections || {}), fallback: data.defaultConnection || "" };
  },
};
