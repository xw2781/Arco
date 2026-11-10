import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const projectOpsSource = await readFile(
  new URL("../ui/project_settings/project_settings_project_ops.js", import.meta.url),
  "utf8",
);
const duplicateJobSource = await readFile(
  new URL("../ui/project_settings/project_settings_duplicate_job.js", import.meta.url),
  "utf8",
);
const duplicateJobHelpers = await import(
  `data:text/javascript;base64,${Buffer.from(duplicateJobSource).toString("base64")}`
);
const { waitForDuplicateProjectJob } = duplicateJobHelpers;
const projectOpsTestSource = projectOpsSource.replace(
  /import \{[\s\S]*?from "\/ui\/project_settings\/project_settings_duplicate_job\.js\?v=[^"]+";\s*/u,
  `
const ensureFolderPathInList = () => {};
const joinProjectTreePath = (folder, name) => [folder, name].filter(Boolean).join("/");
const normalizeTreePath = (value) => String(value || "");
const pathEqualsCI = (left, right) => String(left).toLowerCase() === String(right).toLowerCase();
const splitProjectTreePath = (full) => {
  const parts = String(full || "").split("/").filter(Boolean);
  return { folderPath: parts.slice(0, -1).join("/"), projectName: parts[parts.length - 1] || "" };
};
const {
  clearPendingDuplicateJob,
  createDuplicateRequestId,
  createDuplicateWorkspaceScope,
  loadPendingDuplicateJob,
  readDuplicateResponseError,
  savePendingDuplicateJob,
  waitForDuplicateProjectJob,
} = globalThis.__duplicateJobHelpers;
`,
);
globalThis.__duplicateJobHelpers = duplicateJobHelpers;
const { createProjectOpsFeature } = await import(
  `data:text/javascript;base64,${Buffer.from(projectOpsTestSource).toString("base64")}`
);
delete globalThis.__duplicateJobHelpers;

class MemoryStorage {
  constructor() { this.values = new Map(); }
  getItem(key) { return this.values.has(key) ? this.values.get(key) : null; }
  setItem(key, value) { this.values.set(key, String(value)); }
  removeItem(key) { this.values.delete(key); }
}

const NO_STORAGE_OVERRIDE = Symbol("NO_STORAGE_OVERRIDE");

function response(body, status = 200) {
  const raw = JSON.stringify(body);
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => raw,
  };
}

function pendingRecord(workspaceRoot = "E:\\Arco Server", overrides = {}) {
  return {
    version: 3,
    sourceKey: "project_map",
    workspaceScope: duplicateJobHelpers.createDuplicateWorkspaceScope(workspaceRoot),
    requestId: "job-resume",
    sourceName: "Source Project",
    targetName: "Source Project (2)",
    sourceFolderPath: "Pricing",
    submittedAt: 100,
    submissionAcknowledged: true,
    metadataFinalized: false,
    ...overrides,
  };
}

function makeFeature({
  fetchImpl,
  storage = new MemoryStorage(),
  workspaceRoot = "E:\\Arco Server",
  requestId = "job-123",
  projectPaths,
  saveFolderStructure,
  publishShellProgress = () => {},
  setStatus = () => {},
  showDialog = async () => "Source Project (2)",
}) {
  const projectData = {
    customFolders: ["Pricing"],
    projectPaths: projectPaths || ["Pricing/Source Project"],
  };
  const sequence = [];
  const feature = createProjectOpsFeature({
    defaultSource: "project_map",
    fetchImpl,
    ...(storage === NO_STORAGE_OVERRIDE ? {} : { pendingJobStorage: storage }),
    duplicateRequestIdFactory: () => requestId,
    store: {
      getProjectData: () => projectData,
      getProjectFolderFromStructure: () => "Pricing",
      listProjectNames: () => projectData.projectPaths.map(
        (path) => String(path).split("/").filter(Boolean).pop() || "",
      ),
      saveFolderStructure: saveFolderStructure || (async () => sequence.push("save-structure")),
      buildTreeData: () => sequence.push("build-tree"),
      findProjectBySnapshot: () => null,
    },
    treeView: {
      expandFolder: () => sequence.push("expand-folder"),
      render: () => sequence.push("render-tree"),
    },
    setStatus,
    showDialog,
    showConfirm: async () => true,
    publishShellProgress: (message) => {
      sequence.push(`progress-${message.action}`);
      publishShellProgress(message);
    },
    waitForDuplicatePoll: async (delayMs) => sequence.push(`wait-${delayMs}`),
    appendAuditLogAction: async () => sequence.push("audit"),
    getSelectedProject: () => null,
    setSelectedProject: () => {},
    selectProject: () => {},
    showProjectDetails: () => {},
    clearProjectSelection: () => {},
    reloadProjectData: async () => sequence.push("reload"),
  });
  feature.setWorkspaceRoot(workspaceRoot);
  const targetPathCount = () => projectData.projectPaths.filter(
    (path) => String(path).toLowerCase() === "pricing/source project (2)",
  ).length;
  return {
    feature,
    project: { name: "Source Project", folder: "Pricing" },
    projectData,
    sequence,
    storage,
    targetPathCount,
  };
}

test("fresh duplicate persists before polling and finalizes registry metadata after Engine success", async () => {
  const progressMessages = [];
  const statusPayloads = [
    { ok: true, status: "queued", updated_at: "1", progress: { stage: "queued", completed: 0, total: 0, label: "Queued..." } },
    { ok: true, status: "processing", updated_at: "2", progress: { stage: "copying", completed: 1, total: 3, label: "Copying..." } },
    { ok: true, status: "success", updated_at: "3", progress: { stage: "complete", completed: 3, total: 3, label: "Complete" } },
  ];
  let duplicateBody = null;
  let preparedAtPost = null;
  const statusOptions = [];
  const fetchImpl = async (url, options = {}) => {
    if (url.endsWith("/duplicate_project_folder") && options.method === "POST") {
      duplicateBody = JSON.parse(options.body);
      preparedAtPost = JSON.parse([...context.storage.values.values()][0]);
      return response({ ok: true, job_id: "job-123", status: "queued" }, 202);
    }
    if (url.endsWith("/status/job-123")) {
      statusOptions.push(options);
      return response(statusPayloads.shift());
    }
    throw new Error(`Unexpected request: ${url}`);
  };
  const context = makeFeature({
    fetchImpl,
    publishShellProgress: (message) => progressMessages.push(message),
  });

  await context.feature.duplicateProject(context.project);

  assert.deepEqual(duplicateBody, {
    old_name: "Source Project",
    new_name: "Source Project (2)",
    request_id: "job-123",
  });
  assert.equal(preparedAtPost.requestId, "job-123");
  assert.equal(preparedAtPost.submissionAcknowledged, false);
  assert.equal(context.targetPathCount(), 1);
  assert.ok(context.sequence.indexOf("wait-750") < context.sequence.indexOf("save-structure"));
  assert.ok(statusOptions.every((options) => options.cache === "no-store"));
  assert.equal(context.storage.values.size, 0);
  assert.equal(progressMessages.at(-1).autoCloseMs, 850);
});

test("a lost POST response is recovered by replaying the same prepared request after reload", async () => {
  const storage = new MemoryStorage();
  globalThis.alert = () => {};
  const postBodies = [];
  let postAttempts = 0;
  const fetchImpl = async (url, options = {}) => {
    if (url.endsWith("/duplicate_project_folder") && options.method === "POST") {
      postAttempts += 1;
      postBodies.push(JSON.parse(options.body));
      if (postAttempts === 1) throw new Error("response connection lost");
      return response({ ok: true, job_id: "job-lost-response", status: "processing" }, 202);
    }
    if (url.endsWith("/status/job-lost-response")) {
      return response({ ok: true, status: "success", progress: { completed: 1, total: 1, label: "Complete" } });
    }
    throw new Error(`Unexpected request: ${url}`);
  };
  const first = makeFeature({
    fetchImpl,
    storage,
    requestId: "job-lost-response",
  });

  await first.feature.duplicateProject(first.project);

  assert.equal(storage.values.size, 1);
  assert.equal(JSON.parse([...storage.values.values()][0]).submissionAcknowledged, false);
  const reloaded = makeFeature({ fetchImpl, storage });
  assert.equal(await reloaded.feature.resumePendingDuplicateProject(), true);
  assert.equal(postAttempts, 2);
  assert.deepEqual(postBodies[1], postBodies[0]);
  assert.equal(reloaded.targetPathCount(), 1);
  assert.equal(storage.values.size, 0);
});

test("a missing accepted-job status replays the same submission before polling again", async () => {
  const storage = new MemoryStorage();
  globalThis.alert = () => {};
  const postBodies = [];
  let statusAttempts = 0;
  const fetchImpl = async (url, options = {}) => {
    if (url.endsWith("/duplicate_project_folder") && options.method === "POST") {
      postBodies.push(JSON.parse(options.body));
      return response({ ok: true, job_id: "job-status-repair", status: "queued" }, 202);
    }
    if (url.endsWith("/status/job-status-repair")) {
      statusAttempts += 1;
      if (statusAttempts === 1) return response({ detail: "not found" }, 404);
      return response({ ok: true, status: "success", progress: { completed: 1, total: 1, label: "Complete" } });
    }
    throw new Error(`Unexpected request: ${url}`);
  };
  const context = makeFeature({
    fetchImpl,
    storage,
    requestId: "job-status-repair",
  });

  await context.feature.duplicateProject(context.project);
  assert.equal(JSON.parse([...storage.values.values()][0]).submissionAcknowledged, false);
  await context.feature.duplicateProject(context.project);

  assert.equal(postBodies.length, 2);
  assert.deepEqual(postBodies[1], postBodies[0]);
  assert.equal(storage.values.size, 0);
});

test("definitive submission rejection clears prepared state while uncertain failures retain it", async () => {
  globalThis.alert = () => {};
  for (const [httpStatus, expectedSize] of [
    [404, 0], [409, 0], [422, 0],
    [408, 1], [423, 1], [425, 1], [429, 1], [500, 1],
  ]) {
    const storage = new MemoryStorage();
    const requestId = `job-submit-${httpStatus}`;
    const context = makeFeature({
      storage,
      requestId,
      fetchImpl: async (url, options = {}) => {
        assert.ok(url.endsWith("/duplicate_project_folder"));
        assert.equal(JSON.parse(options.body).request_id, requestId);
        return response({ detail: `HTTP ${httpStatus}` }, httpStatus);
      },
    });

    await context.feature.duplicateProject(context.project);

    assert.equal(storage.values.size, expectedSize, `HTTP ${httpStatus} retention policy`);
  }
});

test("request IDs and workspace scopes are safe and deterministic", () => {
  assert.equal(
    duplicateJobHelpers.createDuplicateRequestId({ randomUUID: () => "01234567-89ab-cdef-0123-456789abcdef" }),
    "psdup_01234567-89ab-cdef-0123-456789abcdef",
  );
  const defaultScope = duplicateJobHelpers.createDuplicateWorkspaceScope("E:\\Arco Server");
  assert.equal(
    defaultScope,
    duplicateJobHelpers.createDuplicateWorkspaceScope({
      workspace_root: "e:/arco server/",
      paths: { projects_dir: "PROJECTS", requests_dir: "requests" },
    }),
  );
  assert.notEqual(
    defaultScope,
    duplicateJobHelpers.createDuplicateWorkspaceScope({
      workspace_root: "E:\\Arco Server",
      paths: { projects_dir: "project-data", requests_dir: "requests" },
    }),
  );
  assert.notEqual(
    defaultScope,
    duplicateJobHelpers.createDuplicateWorkspaceScope({
      workspace_root: "E:\\Arco Server",
      paths: { projects_dir: "projects", requests_dir: "engine-requests" },
    }),
  );
});

test("registry finalization failure preserves target and pending record, then reload resumes idempotently", async () => {
  const storage = new MemoryStorage();
  const alerts = [];
  globalThis.alert = (message) => alerts.push(message);
  const fetchImpl = async (url, options = {}) => {
    if (url.endsWith("/duplicate_project_folder") && options.method === "POST") {
      return response({ ok: true, job_id: "job-resume", status: "queued" }, 202);
    }
    if (url.endsWith("/status/job-resume")) {
      return response({ ok: true, status: "success", progress: { completed: 2, total: 2, label: "Copied" } });
    }
    throw new Error(`Unexpected request (server target must not be deleted): ${url}`);
  };
  let firstSequence;
  const first = makeFeature({
    fetchImpl,
    storage,
    requestId: "job-resume",
    saveFolderStructure: async () => {
      firstSequence.push("save-structure");
      throw new Error("registry write failed");
    },
  });
  firstSequence = first.sequence;

  await first.feature.duplicateProject(first.project);

  assert.ok(first.sequence.includes("save-structure"));
  assert.doesNotMatch(first.sequence.join(" "), /rollback|delete-folder/u);
  assert.match(alerts[0], /server-side copy state were both preserved/u);
  assert.equal(first.targetPathCount(), 0);
  assert.equal(storage.values.size, 1);

  const resumed = makeFeature({
    fetchImpl,
    storage,
    projectPaths: ["Pricing/Source Project", "Pricing/Source Project (2)"],
  });
  assert.equal(await resumed.feature.resumePendingDuplicateProject(), true);
  assert.equal(resumed.sequence.filter((value) => value === "save-structure").length, 0);
  assert.equal(resumed.targetPathCount(), 1);
  assert.equal(await resumed.feature.resumePendingDuplicateProject(), false);
  assert.equal(storage.values.size, 0);
});

test("metadata-finalized recovery skips polling and all duplicate registry writes", async () => {
  const storage = new MemoryStorage();
  duplicateJobHelpers.savePendingDuplicateJob(storage, pendingRecord(undefined, { metadataFinalized: true }));
  const context = makeFeature({
    storage,
    projectPaths: ["Pricing/Source Project", "Pricing/Source Project (2)"],
    fetchImpl: async () => { throw new Error("Finalized recovery must not poll."); },
  });

  assert.equal(await context.feature.resumePendingDuplicateProject(), true);
  assert.equal(context.sequence.filter((value) => value === "save-structure").length, 0);
  assert.equal(context.targetPathCount(), 1);
  assert.equal(context.storage.values.size, 0);
});

test("a workspace switch cannot resume or clean another workspace record", async () => {
  const storage = new MemoryStorage();
  duplicateJobHelpers.savePendingDuplicateJob(storage, pendingRecord("E:\\Server A"));
  const requests = [];
  const context = makeFeature({
    storage,
    workspaceRoot: "E:\\Server B",
    fetchImpl: async (url) => { requests.push(url); throw new Error("unexpected"); },
  });

  assert.equal(await context.feature.resumePendingDuplicateProject(), false);
  assert.deepEqual(requests, []);
  assert.equal(storage.values.size, 1);
  assert.doesNotMatch([...storage.values.values()][0], /E:\\\\Server A/u);
});

test("an active workspace switch preserves the original job for later recovery", async () => {
  const storage = new MemoryStorage();
  globalThis.alert = () => {};
  let releaseFirstStatus;
  let markStatusRequested;
  let statusCalls = 0;
  const firstStatus = new Promise((resolve) => { releaseFirstStatus = resolve; });
  const statusRequested = new Promise((resolve) => { markStatusRequested = resolve; });
  const fetchImpl = async (url, options = {}) => {
    if (url.endsWith("/duplicate_project_folder") && options.method === "POST") {
      return response({ ok: true, job_id: "job-workspace-switch", status: "queued" }, 202);
    }
    if (url.endsWith("/status/job-workspace-switch")) {
      statusCalls += 1;
      if (statusCalls === 1) {
        markStatusRequested();
        return firstStatus;
      }
      return response({ ok: true, status: "success", progress: { completed: 1, total: 1, label: "Complete" } });
    }
    throw new Error(`Unexpected request: ${url}`);
  };
  const context = makeFeature({
    fetchImpl,
    storage,
    workspaceRoot: "E:\\Server A",
    requestId: "job-workspace-switch",
  });
  const running = context.feature.duplicateProject(context.project);
  await statusRequested;
  context.feature.setWorkspaceRoot("E:\\Server B");
  releaseFirstStatus(response({
    ok: true,
    status: "success",
    progress: { completed: 1, total: 1, label: "Complete" },
  }));
  await running;

  assert.equal(storage.values.size, 1);
  assert.equal(context.targetPathCount(), 0);
  assert.equal(await context.feature.resumePendingDuplicateProject(), false);
  context.feature.setWorkspaceRoot("E:\\Server A");
  assert.equal(await context.feature.resumePendingDuplicateProject(), true);
  assert.equal(context.targetPathCount(), 1);
  assert.equal(storage.values.size, 0);
});

test("localStorage write failure continues the submitted job in memory", async (t) => {
  t.mock.method(console, "warn", () => {});
  const storage = new MemoryStorage();
  storage.setItem = () => { throw new Error("storage disabled"); };
  const fetchImpl = async (url, options = {}) => {
    if (url.endsWith("/duplicate_project_folder") && options.method === "POST") {
      return response({ ok: true, job_id: "job-memory", status: "queued" }, 202);
    }
    if (url.endsWith("/status/job-memory")) {
      return response({ ok: true, status: "success", progress: { completed: 1, total: 1, label: "Complete" } });
    }
    throw new Error(`Unexpected request: ${url}`);
  };
  const context = makeFeature({ fetchImpl, storage, requestId: "job-memory" });

  await context.feature.duplicateProject(context.project);

  assert.equal(context.targetPathCount(), 1);
  assert.ok(context.sequence.includes("save-structure"));
});

test("in-memory recovery retries finalization when localStorage and the first registry write fail", async (t) => {
  t.mock.method(console, "warn", () => {});
  const storage = new MemoryStorage();
  storage.setItem = () => { throw new Error("storage disabled"); };
  let structureAttempts = 0;
  let submissions = 0;
  const fetchImpl = async (url, options = {}) => {
    if (url.endsWith("/duplicate_project_folder") && options.method === "POST") {
      submissions += 1;
      return response({ ok: true, job_id: "job-memory-retry", status: "queued" }, 202);
    }
    if (url.endsWith("/status/job-memory-retry")) {
      return response({ ok: true, status: "success", progress: { completed: 1, total: 1, label: "Complete" } });
    }
    throw new Error(`Unexpected request: ${url}`);
  };
  const context = makeFeature({
    fetchImpl,
    storage,
    requestId: "job-memory-retry",
    saveFolderStructure: async () => {
      structureAttempts += 1;
      if (structureAttempts === 1) throw new Error("first registry write failed");
    },
  });

  await context.feature.duplicateProject(context.project);
  assert.equal(context.targetPathCount(), 0);
  await context.feature.duplicateProject(context.project);

  assert.equal(submissions, 1);
  assert.equal(structureAttempts, 2);
  assert.equal(context.targetPathCount(), 1);
});

test("storage cleanup failure cannot turn committed metadata into a duplicate failure", async () => {
  const storage = new MemoryStorage();
  storage.removeItem = () => { throw new Error("storage cleanup disabled"); };
  const alerts = [];
  const statuses = [];
  globalThis.alert = (message) => alerts.push(message);
  const fetchImpl = async (url, options = {}) => {
    if (url.endsWith("/duplicate_project_folder") && options.method === "POST") {
      return response({ ok: true, job_id: "job-clear-failure", status: "queued" }, 202);
    }
    if (url.endsWith("/status/job-clear-failure")) {
      return response({ ok: true, status: "success", progress: { completed: 1, total: 1, label: "Complete" } });
    }
    throw new Error(`Unexpected request: ${url}`);
  };
  const context = makeFeature({
    fetchImpl,
    storage,
    requestId: "job-clear-failure",
    setStatus: (message) => statuses.push(message),
  });

  await context.feature.duplicateProject(context.project);

  assert.equal(context.targetPathCount(), 1);
  assert.match(statuses.at(-1), /^Duplicated /u);
  assert.deepEqual(alerts, []);
  assert.equal(await context.feature.resumePendingDuplicateProject(), false);
});

test("cleanup never removes a newer job from the same workspace scope", () => {
  const storage = new MemoryStorage();
  const newer = pendingRecord(undefined, { requestId: "job-newer" });
  duplicateJobHelpers.savePendingDuplicateJob(storage, newer);

  assert.equal(duplicateJobHelpers.clearPendingDuplicateJob(
    storage,
    newer.sourceKey,
    newer.workspaceScope,
    "job-older",
  ), false);
  assert.equal(
    duplicateJobHelpers.loadPendingDuplicateJob(
      storage,
      newer.sourceKey,
      newer.workspaceScope,
    )?.requestId,
    "job-newer",
  );
});

test("recovery records reject absolute server paths", () => {
  const storage = new MemoryStorage();
  assert.throws(
    () => duplicateJobHelpers.savePendingDuplicateJob(
      storage,
      pendingRecord(undefined, { sourceFolderPath: "E:\\Arco Server\\projects" }),
    ),
    /unavailable/u,
  );
  assert.equal(storage.values.size, 0);
});

test("a throwing localStorage getter does not prevent Project Settings initialization", async () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    get() { throw new Error("storage blocked"); },
  });
  try {
    const context = makeFeature({
      storage: NO_STORAGE_OVERRIDE,
      fetchImpl: async () => { throw new Error("not called"); },
    });
    assert.equal(await context.feature.resumePendingDuplicateProject(), false);
  } finally {
    if (original) Object.defineProperty(globalThis, "localStorage", original);
    else delete globalThis.localStorage;
  }
});

test("close requests are blocked only while duplication is active", async () => {
  let releaseSubmit;
  const alerts = [];
  globalThis.alert = (message) => alerts.push(message);
  const submitResponse = new Promise((resolve) => { releaseSubmit = resolve; });
  const fetchImpl = async (url, options = {}) => {
    if (url.endsWith("/duplicate_project_folder") && options.method === "POST") return submitResponse;
    if (url.endsWith("/status/job-close")) {
      return response({ ok: true, status: "success", progress: { completed: 1, total: 1, label: "Complete" } });
    }
    throw new Error(`Unexpected request: ${url}`);
  };
  const context = makeFeature({ fetchImpl, requestId: "job-close" });
  const running = context.feature.duplicateProject(context.project);
  await Promise.resolve();

  assert.equal(context.feature.requestClose(), true);
  releaseSubmit(response({ ok: true, job_id: "job-close", status: "queued" }, 202));
  await running;
  assert.equal(context.feature.requestClose(), false);
  assert.match(alerts[0], /still running or finalizing/u);
});

test("unchanged valid status stops at the idle threshold and retains uncertainty", async () => {
  let clock = 100;
  await assert.rejects(
    waitForDuplicateProjectJob({
      fetchImpl: async () => response({
        ok: true,
        status: "processing",
        updated_at: "same",
        progress: { stage: "copying", completed: 0, total: 0, label: "Copying" },
      }),
      statusUrl: "/status/job-stale",
      jobId: "job-stale",
      now: () => clock,
      waitForPoll: async () => { clock += 750; },
      staleStatusMs: 800,
    }),
    (error) => error?.code === "DUPLICATE_STATUS_STALE" && /record was retained/u.test(error.message),
  );
});

test("recovery-required Engine error remains distinct from ordinary terminal error", async () => {
  await assert.rejects(
    waitForDuplicateProjectJob({
      fetchImpl: async () => response({
        ok: true,
        status: "error",
        message: "Target preserved",
        progress: { stage: "recovery_required", completed: 0, total: 0, label: "Recovery required" },
      }),
      statusUrl: "/status/job-recovery",
      jobId: "job-recovery",
    }),
    (error) => error?.code === "DUPLICATE_JOB_RECOVERY_REQUIRED",
  );
});

test("recovery-required retains the pending record while an ordinary terminal error clears it", async () => {
  globalThis.alert = () => {};
  for (const [stage, expectedSize] of [["recovery_required", 1], ["failed", 0]]) {
    const storage = new MemoryStorage();
    const jobId = `job-${stage}`;
    const fetchImpl = async (url, options = {}) => {
      if (url.endsWith("/duplicate_project_folder") && options.method === "POST") {
        return response({ ok: true, job_id: jobId, status: "queued" }, 202);
      }
      if (url.endsWith(`/status/${jobId}`)) {
        return response({
          ok: true,
          status: "error",
          message: "Engine stopped",
          progress: { stage, completed: 0, total: 1, label: "Stopped" },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    };
    const context = makeFeature({ fetchImpl, storage, requestId: jobId });

    await context.feature.duplicateProject(context.project);

    assert.equal(storage.values.size, expectedSize, `${stage} retention policy`);
  }
});

test("transient status failures retry but eventually preserve the uncertain job", async () => {
  const waits = [];
  await assert.rejects(
    waitForDuplicateProjectJob({
      fetchImpl: async () => { throw new Error("network unavailable"); },
      statusUrl: "/status/job-uncertain",
      jobId: "job-uncertain",
      waitForPoll: async (delayMs) => waits.push(delayMs),
      maxStatusRetries: 2,
    }),
    (error) => error?.code === "DUPLICATE_STATUS_UNAVAILABLE",
  );
  assert.deepEqual(waits, [750, 750]);
});

function registryLockedError() {
  const error = new Error("Project registry save failed: the project registry is locked. Another user may have it open.");
  error.code = "PROJECT_REGISTRY_LOCKED";
  return error;
}

function completedCopyFetch(jobId) {
  return async (url, options = {}) => {
    if (url.endsWith("/duplicate_project_folder") && options.method === "POST") {
      return response({ ok: true, job_id: jobId, status: "queued" }, 202);
    }
    if (url.endsWith(`/status/${jobId}`)) {
      return response({ ok: true, status: "success", progress: { completed: 2, total: 2, label: "Copied" } });
    }
    throw new Error(`Unexpected request: ${url}`);
  };
}

test("a momentarily locked registry is retried and the duplicate finishes without an error", async () => {
  const storage = new MemoryStorage();
  const alerts = [];
  globalThis.alert = (message) => alerts.push(message);
  let saveAttempts = 0;
  let context;
  context = makeFeature({
    fetchImpl: completedCopyFetch("job-lock-retry"),
    storage,
    requestId: "job-lock-retry",
    saveFolderStructure: async () => {
      saveAttempts += 1;
      context.sequence.push("save-structure");
      if (saveAttempts < 3) throw registryLockedError();
    },
  });

  await context.feature.duplicateProject(context.project);

  assert.equal(saveAttempts, 3);
  assert.deepEqual(context.sequence.filter((value) => value.startsWith("wait-")), ["wait-750", "wait-750"]);
  assert.deepEqual(alerts, []);
  assert.equal(context.targetPathCount(), 1);
  assert.equal(storage.values.size, 0, "finished duplicate leaves no pending record");
});

test("a registry that stays locked still fails after the bounded retries and keeps the pending record", async () => {
  const storage = new MemoryStorage();
  const alerts = [];
  globalThis.alert = (message) => alerts.push(message);
  let saveAttempts = 0;
  const context = makeFeature({
    fetchImpl: completedCopyFetch("job-lock-stuck"),
    storage,
    requestId: "job-lock-stuck",
    saveFolderStructure: async () => {
      saveAttempts += 1;
      throw registryLockedError();
    },
  });

  await context.feature.duplicateProject(context.project);

  assert.equal(saveAttempts, 3);
  assert.equal(context.sequence.filter((value) => value === "wait-750").length, 2);
  assert.match(alerts[0], /project registry is locked/u);
  assert.match(alerts[0], /server-side copy state were both preserved/u);
  assert.equal(context.targetPathCount(), 0);
  assert.equal(storage.values.size, 1, "pending record survives for recovery");
});

test("a non-lock registry failure is not retried", async () => {
  const storage = new MemoryStorage();
  globalThis.alert = () => {};
  let saveAttempts = 0;
  const context = makeFeature({
    fetchImpl: completedCopyFetch("job-plain-failure"),
    storage,
    requestId: "job-plain-failure",
    saveFolderStructure: async () => {
      saveAttempts += 1;
      throw new Error("Project registry save failed: HTTP 500");
    },
  });

  await context.feature.duplicateProject(context.project);

  assert.equal(saveAttempts, 1);
  assert.equal(context.sequence.filter((value) => value === "wait-750").length, 0);
});

test("Cancel during the copy posts the cancel request and a cancelled status settles the job quietly", async () => {
  const storage = new MemoryStorage();
  const alerts = [];
  const progressMessages = [];
  globalThis.alert = (message) => alerts.push(message);
  const statuses = [];
  let cancelPosts = 0;
  let context;
  const fetchImpl = async (url, options = {}) => {
    if (url.endsWith("/duplicate_project_folder") && options.method === "POST") {
      return response({ ok: true, job_id: "job-cancel", status: "queued" }, 202);
    }
    if (url.endsWith("/duplicate_project_folder/cancel/job-cancel") && options.method === "POST") {
      cancelPosts += 1;
      statuses.push("cancel-posted");
      return response({ ok: true, job_id: "job-cancel", status: "processing", cancel_requested: true }, 202);
    }
    if (url.endsWith("/status/job-cancel")) {
      statuses.push("poll");
      if (statuses.filter((value) => value === "poll").length === 1) {
        // The user presses Cancel on the shell progress window mid-copy.
        assert.equal(context.feature.cancelDuplicateProject("project-duplicate-job-cancel"), true);
        assert.equal(context.feature.cancelDuplicateProject("project-duplicate-job-cancel"), true, "a second press is harmless");
        return response({ ok: true, status: "processing", progress: { stage: "reserving_classes", completed: 1, total: 3, label: "Copying" } });
      }
      return response({ ok: true, status: "cancelled", message: "Project duplication was cancelled before the copy was published.", progress: { stage: "cancelled", completed: 1, total: 3, label: "Project duplication cancelled" } });
    }
    throw new Error(`Unexpected request: ${url}`);
  };
  context = makeFeature({
    fetchImpl,
    storage,
    requestId: "job-cancel",
    publishShellProgress: (message) => progressMessages.push(message),
    saveFolderStructure: async () => { throw new Error("registry must not be written for a cancelled copy"); },
  });

  await context.feature.duplicateProject(context.project);

  assert.equal(cancelPosts, 1);
  assert.deepEqual(statuses, ["poll", "cancel-posted", "poll"]);
  assert.deepEqual(alerts, [], "a cancel is not an error dialog");
  assert.equal(context.targetPathCount(), 0);
  assert.equal(storage.values.size, 0, "a cancelled job is settled, not retained for recovery");
  assert.equal(progressMessages[0].action, "open");
  assert.equal(progressMessages[0].cancellable, true);
  const cancelling = progressMessages.find((message) => /Cancelling copy/u.test(String(message.label || "")));
  assert.ok(cancelling, "the window shows the cancel in progress");
  const last = progressMessages[progressMessages.length - 1];
  assert.equal(last.action, "close");
  assert.equal(last.autoCloseMs, 850);
  assert.match(progressMessages[progressMessages.length - 2].label, /Cancelled copy/u);
  assert.equal(progressMessages[progressMessages.length - 2].cancellable, false);
  assert.equal(context.feature.cancelDuplicateProject(), false, "nothing is cancellable once the job is settled");
});

test("Cancel pressed before the submission is acknowledged goes out as soon as the job is known", async () => {
  const storage = new MemoryStorage();
  globalThis.alert = () => {};
  const order = [];
  let context;
  const fetchImpl = async (url, options = {}) => {
    if (url.endsWith("/duplicate_project_folder") && options.method === "POST") {
      order.push("submit");
      assert.equal(context.feature.cancelDuplicateProject(), true);
      return response({ ok: true, job_id: "job-early", status: "queued" }, 202);
    }
    if (url.endsWith("/cancel/job-early")) {
      order.push("cancel");
      return response({ ok: true, job_id: "job-early", status: "queued", cancel_requested: true }, 202);
    }
    if (url.endsWith("/status/job-early")) {
      order.push("poll");
      return response({ ok: true, status: "cancelled", progress: { stage: "cancelled", completed: 0, total: 0, label: "Cancelled" } });
    }
    throw new Error(`Unexpected request: ${url}`);
  };
  context = makeFeature({ fetchImpl, storage, requestId: "job-early" });

  await context.feature.duplicateProject(context.project);

  assert.deepEqual(order, ["submit", "cancel", "poll"]);
  assert.equal(storage.values.size, 0);
});

test("Cancel is refused once the copy is published and only the registry step remains", async () => {
  const storage = new MemoryStorage();
  globalThis.alert = () => {};
  const statusMessages = [];
  const progressMessages = [];
  let context;
  let cancelPosts = 0;
  const fetchImpl = async (url, options = {}) => {
    if (url.endsWith("/duplicate_project_folder") && options.method === "POST") {
      return response({ ok: true, job_id: "job-late", status: "queued" }, 202);
    }
    if (url.endsWith("/cancel/job-late")) { cancelPosts += 1; return response({ ok: true }, 202); }
    if (url.endsWith("/status/job-late")) {
      return response({ ok: true, status: "success", progress: { completed: 2, total: 2, label: "Copied" } });
    }
    throw new Error(`Unexpected request: ${url}`);
  };
  context = makeFeature({
    fetchImpl,
    storage,
    requestId: "job-late",
    setStatus: (message) => statusMessages.push(message),
    publishShellProgress: (message) => progressMessages.push(message),
    saveFolderStructure: async () => {
      assert.equal(context.feature.cancelDuplicateProject(), false);
    },
  });

  await context.feature.duplicateProject(context.project);

  assert.equal(cancelPosts, 0);
  assert.ok(statusMessages.some((message) => /already finished; it will be registered/u.test(message)));
  const finalizing = progressMessages.find((message) => /Finalizing/u.test(String(message.label || "")));
  assert.equal(finalizing.cancellable, false, "the Cancel button is withdrawn while finalizing");
  assert.equal(context.targetPathCount(), 1);
});

test("a cancelled status is reported with its own code by the poll helper", async () => {
  await assert.rejects(
    waitForDuplicateProjectJob({
      fetchImpl: async () => response({ ok: true, status: "cancelled", message: "Stopped by user.", progress: { completed: 1, total: 3 } }),
      statusUrl: "/status/job-x",
      jobId: "job-x",
      waitForPoll: async () => {},
    }),
    (error) => error?.code === "DUPLICATE_JOB_CANCELLED" && /Stopped by user/u.test(error.message),
  );
});

test("an unknown status keeps polling and never counts as a failure or a stall", async () => {
  let clock = 100;
  const processing = () => response({
    ok: true,
    status: "processing",
    updated_at: "same",
    progress: { stage: "copying", completed: 1, total: 3, label: "Copying" },
  });
  const responses = [
    processing(),
    ...Array.from({ length: 12 }, () => response({ ok: true, job_id: "job-unknown", unknown: true })),
    processing(),
    response({ ok: true, status: "success", progress: { completed: 3, total: 3 } }),
  ];
  const counts = [];
  const result = await waitForDuplicateProjectJob({
    fetchImpl: async () => responses.shift(),
    statusUrl: "/status/job-unknown",
    jobId: "job-unknown",
    onProgress: (progress) => counts.push(progress.countText),
    now: () => clock,
    waitForPoll: async () => { clock += 750; },
    staleStatusMs: 2000,
    maxStatusRetries: 2,
  });
  assert.equal(result.status, "success");
  assert.ok(counts.includes("Reconnecting..."));
});
