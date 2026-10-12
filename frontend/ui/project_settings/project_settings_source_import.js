/**
 * Source Data - saving the single-table import settings and running an import.
 *
 * Every path an import can take lives here, behind an injected `fetchImpl`, so
 * each call sequence is pinned by a test with a stub fetch
 * (tests/project_settings_source_import.test.mjs):
 *
 * - a CSV the server can read is imported by the refresh job on the server;
 * - a CSV only this PC can read, a SQL Server table, and a combined source are
 *   read here and uploaded, then the job runs with the import off.
 *
 * A combined source is saved by project_settings_combined_source.js, which owns
 * its routes; this module only imports it.
 */

export const SOURCE_TYPE_COMBINED = "combined";

/** How far the upload has got, for the progress window's title. */
export function describeSourceUploadProgress(progress) {
  if (progress?.phase === "committing") return "Writing the table on Arco Server...";
  const mb = (bytes) => (Number(bytes || 0) / (1024 * 1024)).toFixed(1);
  const sent = progress?.total_bytes
    ? `${mb(progress.bytes_sent)} of ${mb(progress.total_bytes)} MB`
    : `${mb(progress?.bytes_sent)} MB`;
  return `${sent}, ${Number(progress?.rows_sent || 0).toLocaleString("en-US")} rows`;
}

/** The route on this PC that reads and uploads a source, and the progress title. */
export function localImportRequest(sourceType) {
  if (sourceType === "mssql") return { url: "/source_table/import", title: "Uploading table from SQL Server..." };
  if (sourceType === SOURCE_TYPE_COMBINED) {
    return { url: "/source_table/combined/import", title: "Combining and uploading tables..." };
  }
  return { url: "/source_table/refresh", title: "Uploading CSV file..." };
}

export function createSourceImport(deps = {}) {
  const {
    fetchImpl,
    readResponseErrorDetail = async (res) => `Request failed (${res?.status}).`,
    getProjectName = () => "",
    // The refresh job: { isRunning(), loadPlan(name), runJob(name, options) }.
    sourceRefresh,
    applySourceState = () => {},
    setSourceStatus = () => {},
    setStatus = () => {},
    showProgress = () => {},
    hideProgress = () => {},
    // Everything the page shows about the source table, reloaded after a refresh.
    reloadViews = async () => {},
    progressPollMs = 500,
  } = deps;
  const fetch = (...args) => fetchImpl(...args);

  /**
   * Persist the import settings chosen in the panel.
   *
   * The whole import source description goes through `/source_table/profile`:
   * the SQL Server profile lives in the project's own import record, and a CSV
   * selection is written into `field_mapping.json::table_path` by that same
   * endpoint, so each value keeps a single writer.
   */
  async function saveImportSettings(sourceType, mssql, csvPath) {
    const name = String(getProjectName() || "").trim();
    if (!name) return false;
    try {
      const body = { project_name: name, source_type: sourceType, mssql };
      if (sourceType === "csv") {
        body.csv_path = String(csvPath || "").trim();
      }
      const res = await fetch("/source_table/profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(await readResponseErrorDetail(res));
      applySourceState(await res.json());
      return true;
    } catch (err) {
      setSourceStatus(err.message || "Could not save the import settings.", "error");
      setStatus(`Failed to save the import settings: ${err.message}`);
      return false;
    }
  }

  /**
   * Read a source only this PC can open - a SQL Server table, as the user's own
   * login, a CSV on a drive only this PC has, or every table of a combined
   * source - and upload it to Arco Server, which writes the project master
   * table. An interrupted CSV upload resumes on the next try while the file is
   * unchanged.
   */
  async function importSourceDataLocally(name, sourceType) {
    const { url, title } = localImportRequest(sourceType);
    showProgress(title);
    let finished = false;
    const query = new URLSearchParams({ project_name: name }).toString();
    const timer = setInterval(async () => {
      try {
        const res = await fetch(`/source_table/upload_progress?${query}`);
        const progress = res.ok ? await res.json() : null;
        if (!finished && progress?.active) {
          showProgress(`${title} ${describeSourceUploadProgress(progress)}`);
        }
      } catch {
        // The import's own answer reports a failure.
      }
    }, progressPollMs);
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_name: name }),
      });
      if (!res.ok) return { ok: false, error: await readResponseErrorDetail(res) };
      const out = await res.json();
      applySourceState(out);
      return { ok: true, rowCount: Number(out?.last_import?.row_count || 0) };
    } catch (err) {
      return { ok: false, error: err.message || "The import failed." };
    } finally {
      finished = true;
      clearInterval(timer);
      hideProgress();
    }
  }

  /**
   * Rebuild the project-owned master table from the saved import settings, then
   * refresh everything derived from it.
   *
   * The work runs on the ArcRho Server host as one Engine job: the import lands
   * on local disk instead of crossing this machine twice, and the job continues
   * into the project's dependency graph, regenerating every engine-built dataset
   * and re-running the methods that depend on them. Only when the server cannot
   * reach the configured source - a SQL Server profile, which authenticates as
   * the caller, a CSV path only this machine can open, or a combined source,
   * which the server never re-reads - is it read here and uploaded, and even
   * then the dependent refresh still runs on the server.
   *
   * `scope` is what the Import Scope step chose: the engine-built dataset types
   * to regenerate and the reserving class types whose classes are refreshed.
   * Either list left empty means all of them.
   *
   * With no Engine available, a source the server can read is not imported at
   * all: the import is the job. A source only this PC can read has already been
   * copied in by then, so the server rebuilds the table summary and the
   * reserving-class values from it and the generated caches are cleared, which
   * covers the whole project regardless of the chosen scope.
   */
  async function importSourceData(sourceType, scope = {}) {
    const name = String(getProjectName() || "").trim();
    if (!name) return { ok: false, error: "Select a project first." };
    if (sourceRefresh.isRunning()) return { ok: false, error: "A source table refresh is already running." };

    const isSql = sourceType === "mssql";
    const plan = await sourceRefresh.loadPlan(name);
    // Without the plan this page cannot tell a source the server imports from
    // one only this PC can read, so it imports nothing rather than guess.
    if (!plan) return { ok: false, error: "Could not reach Arco Server to plan the import. Try again." };
    if (plan.busy) {
      return {
        ok: false,
        error: "A source table refresh is already running for this project. Wait for it to finish.",
      };
    }

    // Importing has always meant "the raw data changed": this page used to
    // delete every generated dataset cache so each one recomputed whenever it
    // was next opened. The job rebuilds them instead, which touches the same
    // objects and leaves none of them empty in the meantime. The server plan
    // never offers to import a combined source.
    const importOnServer = !isSql && sourceType !== SOURCE_TYPE_COMBINED && !!plan?.server_can_import;
    let rowCount = 0;
    if (!importOnServer) {
      const local = await importSourceDataLocally(name, sourceType);
      if (!local.ok) return local;
      rowCount = local.rowCount;
    }

    const job = await sourceRefresh.runJob(name, {
      importSource: importOnServer,
      refreshDependents: true,
      datasetTypes: scope?.datasetTypes || [],
      reservingClassTypes: scope?.reservingClassTypes || [],
    });
    if (job.unavailable) {
      // No Engine. A server-readable source is imported only by the job, so
      // nothing ran; this PC never copies it over the share instead.
      if (importOnServer) {
        return {
          ok: false,
          error: "Arco Engine is unavailable, so the table could not be imported. Try again once it is running.",
        };
      }
      setStatus(
        `Imported ${rowCount.toLocaleString("en-US")} row(s) into "${name}". `
        + "Arco Engine is unavailable, so dependents will refresh when each object is opened.",
      );
      await reloadViews(name, { forceRefresh: true });
      return { ok: true, rowCount };
    }
    if (!job.ok) {
      await reloadViews(name, { forceRefresh: false });
      return { ok: false, error: job.error };
    }
    await reloadViews(name, { forceRefresh: false });
    return { ok: true, rowCount: Number(job.result?.row_count || rowCount || 0) };
  }

  return { saveImportSettings, importSourceData };
}
