import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = async (path) => (await readFile(new URL(path, import.meta.url), "utf8")).replaceAll("\r\n", "\n");
const importSource = (source) => import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

const model = await import(new URL("../ui/server/server_model.js", import.meta.url));

// shell_messages.js with its imports replaced, so the switch handler runs against a fake shell.
const shellMessages = await importSource(
  (await read("../ui/shell/shell_messages.js"))
    .replace(/import \{ shell \} from "\.\/shell_context\.js\?v=[^"]+";/u, "const shell = new Proxy({}, { get: (_, key) => globalThis.__serverSwitchShell?.[key] });")
    .replace(/import \{ normalizeBrowsingHistoryEntry \} from "[^"]+";/u, "const normalizeBrowsingHistoryEntry = (v) => v;")
    .replace(
      /import \{ normalizeProjectInstanceState, normalizeShellActivityEntry \} from "[^"]+";/u,
      "const normalizeProjectInstanceState = (v) => v; const normalizeShellActivityEntry = (v) => v;",
    )
    .replace(/import \{[^}]*\} from "\.\/ui_automation\.js\?v=[^"]+";/u, "const closeAutomationProgress = () => {}, openAutomationProgress = () => {}, updateAutomationProgress = () => {};"),
);

// shell_activity_history.js and tab_actions.js, the second wired to the first and a fake shell.
const activity = await importSource(
  (await read("../ui/shell/shell_activity_history.js"))
    .replace(/import \{ localDayKey \} from "[^"]+";/u, "const localDayKey = () => \"2026-09-26\";"),
);
globalThis.__serverTabStubs = {
  isFloatingTab: () => false,
  getLastViewedDatasetInputs: () => null,
  normalizeBrowsingHistoryEntry: (value) => value,
  normalizeFolderKey: activity.normalizeFolderKey,
  normalizeProjectInstanceState: activity.normalizeProjectInstanceState,
  normalizeShellActivityEntry: activity.normalizeShellActivityEntry,
  pushShellActivityHistoryEntry: async () => {},
  ALLOWED_DFM_TABS: new Set(["details"]),
};
const tabActions = await importSource(
  "const shell = new Proxy({}, { get: (_, key) => globalThis.__serverTabShell?.[key] });\n"
  + "const { isFloatingTab, getLastViewedDatasetInputs, normalizeBrowsingHistoryEntry, normalizeFolderKey, normalizeProjectInstanceState, normalizeShellActivityEntry, pushShellActivityHistoryEntry, ALLOWED_DFM_TABS } = globalThis.__serverTabStubs;\n"
  + (await read("../ui/shell/tab_actions.js")).replace(/^import[\s\S]*?;\n/gmu, ""),
);

const LISTING = {
  active_profile: "default",
  default_profile: "default",
  profiles: [
    {
      id: "default",
      name: "Production",
      root: "E:\\Arco Server",
      gateway_config: "C:\\AppData\\Arco\\arcrho_gateway.json",
      gateway_url: "http://NE7SASWPN02:28767",
      user: "alice",
      credential_exists: true,
      active: true,
    },
    {
      id: "local",
      name: "Local test",
      root: "C:\\Arco Server",
      gateway_config: "C:\\AppData\\Arco\\arcrho_gateway.local.json",
      gateway_url: "http://127.0.0.1:28767",
      user: "",
      credential_exists: false,
      active: false,
    },
  ],
  current: {
    root: "C:\\Arco Server",
    gateway_config: "C:\\AppData\\Arco\\arcrho_gateway.local.json",
    gateway_url: "http://127.0.0.1:28767",
    user: "alice",
    credential_exists: true,
  },
  set_at_launch: { root: "", gateway_config: "" },
};

test("the list names each server by name and address and marks the active one", () => {
  const rows = model.buildServerRows(LISTING);

  assert.deepEqual(rows.map((row) => row.label), [
    "Production \u2014 NE7SASWPN02:28767",
    "Local test \u2014 127.0.0.1:28767",
  ]);
  assert.deepEqual(rows.map((row) => [row.chip, row.canSwitch]), [["Active", false], ["", true]]);
  assert.equal(rows[1].details.folder, "C:\\Arco Server");
  assert.equal(rows[1].details.credentialExists, false);
  assert.equal(model.healthQuery(rows[1]), "?id=local");
  assert.equal(model.serverLabel("No address", ""), "No address");
});

test("a server set at launch leads the list and nothing can be switched", () => {
  const listing = { ...LISTING, set_at_launch: { root: "C:\\Arco Server", gateway_config: "" } };
  const rows = model.buildServerRows(listing);

  assert.equal(model.isSetAtLaunch(listing), true);
  assert.equal(rows[0].key, model.CURRENT_SERVER_KEY);
  assert.equal(rows[0].label, "Set at launch \u2014 127.0.0.1:28767");
  assert.equal(rows[0].chip, "In Use");
  assert.equal(model.healthQuery(rows[0]), "", "the launch row asks for this window's own server");
  assert.ok(rows.every((row) => !row.canSwitch));
  assert.ok(rows.slice(1).every((row) => !row.chip), "the saved active profile is not the one in use");
});

test("the title-bar badge names any server but production, with its address and folder in the tooltip", () => {
  assert.equal(model.activeServerBadge(LISTING), null, "production shows no badge");
  assert.equal(model.activeServerBadge(null), null);

  const switched = { ...LISTING, active_profile: "local" };
  assert.deepEqual(model.activeServerBadge(switched), {
    text: "Local test",
    title: "Local test \u2014 127.0.0.1:28767\nC:\\Arco Server",
  });

  // A launch override shows the badge even while the saved active profile is production.
  const launched = { ...LISTING, set_at_launch: { root: "C:\\Arco Server", gateway_config: "" } };
  assert.deepEqual(model.activeServerBadge(launched), {
    text: "Set at launch",
    title: "Set at launch \u2014 127.0.0.1:28767\nC:\\Arco Server",
  });
});

test("the shell reads the server once, shows the badge, and opens the Server tab from it", async () => {
  const badgeModule = await importSource(
    (await read("../ui/shell/server_badge.js"))
      .replace(/import \{ shell \} from "[^"]+";/u, "const shell = new Proxy({}, { get: (_, key) => globalThis.__badgeShell?.[key] });")
      .replace(
        /import \{ activeServerBadge \} from "[^"]+";/u,
        `import { activeServerBadge } from ${JSON.stringify(new URL("../ui/server/server_model.js", import.meta.url).href)};`,
      ),
  );
  const elements = {
    titlebarServerBadge: { hidden: true, title: "", listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; } },
    titlebarServerName: { textContent: "" },
  };
  const requests = [];
  let opened = 0;
  const realFetch = globalThis.fetch;
  globalThis.document = { getElementById: (id) => elements[id] || null };
  globalThis.__badgeShell = { openServerTab: () => { opened += 1; } };
  globalThis.fetch = async (url) => {
    requests.push(url);
    return { ok: true, json: async () => ({ ...LISTING, active_profile: "local" }) };
  };
  try {
    await badgeModule.initServerBadge();
    const button = elements.titlebarServerBadge;
    assert.deepEqual(requests, ["/server_profiles"]);
    assert.equal(button.hidden, false);
    assert.equal(elements.titlebarServerName.textContent, "Local test");
    assert.match(button.title, /127\.0\.0\.1:28767/u);
    button.listeners.click();
    assert.equal(opened, 1);

    badgeModule.renderServerBadge(model.activeServerBadge(LISTING));
    assert.equal(button.hidden, true, "production hides it");
  } finally {
    delete globalThis.document;
    delete globalThis.__badgeShell;
    globalThis.fetch = realFetch;
  }

  const [index, uiShell] = await Promise.all([read("../ui/index.html"), read("../ui/shell/ui_shell.js")]);
  assert.match(index, /<button id="titlebarServerBadge" class="host-nodrag" type="button" hidden>/u);
  assert.match(uiShell, /import \{ initServerBadge \} from "\.\/server_badge\.js\?v=/u);
  assert.match(uiShell, /void initServerBadge\(\);/u);
});

test("only the server in use offers Sign in again, a launch-time server included", () => {
  assert.deepEqual(model.buildServerRows(LISTING).map((row) => row.canSignIn), [true, false]);
  const launched = { ...LISTING, set_at_launch: { root: "C:\Arco Server", gateway_config: "C:\t\g.json" } };
  assert.deepEqual(model.buildServerRows(launched).map((row) => row.canSignIn), [true, false, false]);
  assert.equal(model.signInResultMessage({ signed_in: { user: "alice" } }), "Signed in again as alice.");
  assert.equal(model.signInResultMessage({}), "Signed in again.");
});

test("every sign-in error the app server raises is one the status bar offers Sign in again for", async () => {
  const source = await read("../app_server/services/hosted_save_http_client.py");
  const messages = ["SIGN_IN_MESSAGE", "NOT_SIGNED_IN_MESSAGE"].map(
    (name) => source.match(new RegExp(`^${name} = "([^"]+)"`, "mu"))?.[1],
  );
  for (const message of messages) assert.ok(model.asksToSignIn(message), message);
  assert.equal(model.asksToSignIn("The server can't be reached. Try again once it is back."), false);
});

test("the status bar shows Sign in again beside a sign-in error and reports the new sign-in", async () => {
  const statusBar = await importSource(
    (await read("../ui/shell/status_bar.js"))
      .replace(/import \{ \$ \} from "[^"]+";/u, "const $ = (id) => globalThis.__statusEls[id] || null;")
      .replace(
        /from "\.\.\/server\/server_model\.js\?v=[^"]+";/u,
        `from ${JSON.stringify(new URL("../ui/server/server_model.js", import.meta.url).href)};`,
      ),
  );
  const classes = () => ({ add() {}, remove() {} });
  const button = { hidden: true, disabled: false, listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; } };
  const els = { statusText: { textContent: "", classList: classes() }, statusBar: { classList: classes() }, statusSignInBtn: button };
  globalThis.__statusEls = els;
  const requests = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    requests.push([url, init?.method]);
    return { ok: true, json: async () => ({ signed_in: { user: "alice" } }) };
  };
  try {
    statusBar.updateStatusBar("The server did not accept this PC's sign-in. Sign in to the server again.", { tone: "error" });
    assert.equal(button.hidden, false);
    statusBar.initStatusSignIn();
    await button.listeners.click();
    assert.deepEqual(requests, [["/server_profiles/sign_in", "POST"]]);
    assert.equal(els.statusText.textContent, "Signed in again as alice.");
    assert.equal(button.hidden, true);
  } finally {
    delete globalThis.__statusEls;
    globalThis.fetch = realFetch;
  }

  const [index, uiShell, page] = await Promise.all([
    read("../ui/index.html"), read("../ui/shell/ui_shell.js"), read("../ui/server/server.js"),
  ]);
  assert.match(index, /<span id="statusText">[^<]*<\/span>\n\s*<button id="statusSignInBtn" class="statusAction host-nodrag" type="button" hidden>Sign in again<\/button>/u);
  assert.match(uiShell, /initStatusSignIn\(\);/u);
  assert.match(page, /fetch\("\/server_profiles\/sign_in", \{ method: "POST" \}\)/u);
});

test("adding a server needs a checked folder, a name no saved server uses, and its address", () => {
  const address = "http://staging:28767";
  assert.match(model.addServerProblem(LISTING, { name: "Test", inspectedRoot: "", address }), /folder/u);
  assert.match(model.addServerProblem(LISTING, { name: " ", inspectedRoot: "C:\\X", address }), /name/u);
  assert.match(model.addServerProblem(LISTING, { name: "local TEST", inspectedRoot: "C:\\X", address }), /already/u);
  // The address is typed; the folder's own Gateway registry is server-only and never read.
  assert.match(model.addServerProblem(LISTING, { name: "Staging", inspectedRoot: "C:\\X", address: "" }), /address/u);
  assert.match(model.addServerProblem(LISTING, { name: "Staging", inspectedRoot: "C:\\X", address: "staging:28767" }), /address/u);
  assert.equal(model.addServerProblem(LISTING, { name: "Staging", inspectedRoot: "C:\\X", address }), "");
});

test("the page explains a blocked, failed or accepted switch", () => {
  assert.deepEqual(
    model.switchResultMessage({ ok: false, dirtyTabs: ["DFM 1", "Workflow 2"] }, "Local"),
    { text: "Save or close these tabs first: DFM 1, Workflow 2.", tone: "error" },
  );
  assert.equal(model.switchResultMessage({ ok: false, error: "Refused." }, "Local").text, "Refused.");
  assert.match(model.switchResultMessage({ ok: true, restartRequired: true }, "Local").text, /^Restarting/u);
});

function switchHarness({ tabs, response }) {
  const serverFrame = { posted: [], postMessage(message) { this.posted.push(message); } };
  const calls = { fetch: [], restart: 0 };
  globalThis.__serverSwitchShell = {
    state: { tabs: [{ id: "sv_1", type: "server", title: "Server", iframe: { contentWindow: serverFrame } }, ...tabs] },
    restartApplication: async () => { calls.restart += 1; },
  };
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    calls.fetch.push([url, JSON.parse(init.body)]);
    return { ok: response.status < 400, status: response.status, json: async () => response.body };
  };
  const restore = () => {
    globalThis.fetch = realFetch;
    delete globalThis.__serverSwitchShell;
  };
  return { serverFrame, calls, restore };
}

test("a switch is refused while any tab holds unsaved changes", async () => {
  const { serverFrame, calls, restore } = switchHarness({
    tabs: [{ id: "dfm_2", type: "dfm", title: "Paid DFM", isDirty: true }],
    response: { status: 200, body: {} },
  });
  try {
    const handled = await shellMessages.handleServerSwitchMessage(
      serverFrame, { type: "arcrho:server-switch", requestId: "r1", id: "local" },
    );
    assert.equal(handled, true);
    assert.deepEqual(serverFrame.posted, [
      { type: "arcrho:server-switch-result", requestId: "r1", ok: false, dirtyTabs: ["Paid DFM"] },
    ]);
    assert.deepEqual(calls.fetch, [], "nothing is activated");
    assert.equal(calls.restart, 0);
  } finally {
    restore();
  }
});

test("a clean switch activates the server and restarts the app", async () => {
  const { serverFrame, calls, restore } = switchHarness({
    tabs: [{ id: "dfm_2", type: "dfm", title: "Paid DFM", isDirty: false }],
    response: { status: 200, body: { restart_required: true } },
  });
  try {
    await shellMessages.handleServerSwitchMessage(serverFrame, { type: "arcrho:server-switch", requestId: "r2", id: "local" });
    assert.deepEqual(calls.fetch, [["/server_profiles/activate", { id: "local" }]]);
    assert.deepEqual(serverFrame.posted, [
      { type: "arcrho:server-switch-result", requestId: "r2", ok: true, restartRequired: true },
    ]);
    assert.equal(calls.restart, 1);
  } finally {
    restore();
  }
});

test("a refused activation is passed back and nothing restarts; other frames cannot ask", async () => {
  const { serverFrame, calls, restore } = switchHarness({
    tabs: [],
    response: { status: 409, body: { detail: "This window's server was set when it was launched." } },
  });
  try {
    await shellMessages.handleServerSwitchMessage(serverFrame, { type: "arcrho:server-switch", requestId: "r3", id: "local" });
    assert.equal(serverFrame.posted[0].ok, false);
    assert.match(serverFrame.posted[0].error, /set when it was launched/u);
    assert.equal(calls.restart, 0);

    const stranger = { postMessage() { throw new Error("must not reply"); } };
    assert.equal(
      await shellMessages.handleServerSwitchMessage(stranger, { type: "arcrho:server-switch", requestId: "r4", id: "local" }),
      false,
    );
    assert.equal(calls.fetch.length, 1);
  } finally {
    restore();
  }
});

test("the Server tab opens once and is restorable from history and Home shortcuts", () => {
  globalThis.__serverTabShell = { state: { tabs: [{ id: "home", type: "home" }], nextId: 1, activeId: "home" } };
  // Opening a tab schedules a history write; this test only needs the timer to exist.
  globalThis.window = { setTimeout: () => 0, clearTimeout: () => {} };
  try {
    const first = tabActions.openServerTab();
    const again = tabActions.openServerTab();
    assert.equal(again, first);
    assert.equal(globalThis.__serverTabShell.state.tabs.filter((tab) => tab.type === "server").length, 1);
    assert.equal(globalThis.__serverTabShell.state.activeId, first.id);

    const entry = tabActions.buildShellActivityEntry(first);
    assert.equal(entry.tabType, "server");
    globalThis.__serverTabShell.state.tabs = [{ id: "home", type: "home" }];
    const reopened = tabActions.openShellActivityHistoryEntry(entry);
    assert.equal(reopened.type, "server");
  } finally {
    delete globalThis.__serverTabShell;
    delete globalThis.window;
  }
});

test("Home, the tab host, the icons and the Server Connection dialog all reach the Server tab", async () => {
  const home = await read("../ui/shell/home_view.js");
  const host = await read("../ui/shell/iframe_host.js");
  const uiShell = await read("../ui/shell/ui_shell.js");
  const icons = await read("../ui/shell/tab-type-icons/tab_type_icons.css");
  const cardIcons = await read("../ui/shell/home_card_icons.js");
  const dialog = await read("../ui/shell/root_path_settings.js");
  const index = await read("../ui/index.html");
  const page = await read("../ui/server/server.js");

  assert.match(home, /id="cardServer">\$\{homeCardIcon\("server"\)\}/u);
  assert.match(home, /getElementById\("cardServer"\)\?\.addEventListener\("click", \(\) => shell\.openServerTab\?\.\(\)\)/u);
  assert.match(host, /tab\.type === "server"\) \{\s*iframe\.src = `\/ui\/server\/server\.html\?v=/u);
  assert.match(uiShell, /^\s*openServerTab,$/mu);
  assert.match(icons, /\[data-tab-type="server"\][^}]*server\.svg\?v=/su);
  assert.ok(existsSync(new URL("../ui/shell/tab-type-icons/server.svg", import.meta.url)));
  assert.match(cardIcons, /server: "server"/u);
  assert.match(index, /id="rootPathServerTabBtn"/u);
  assert.match(dialog, /rootPathServerTabBtn[\s\S]*shell\.openServerTab\?\.\(\)/u);
  // First run asks for the server's address, and the save carries it.
  assert.match(index, /id="rootPathGatewayInput"/u);
  assert.match(dialog, /gateway_url: \(\$\("rootPathGatewayInput"\)/u);
  // The page asks the app server for health; it never calls a Gateway itself.
  assert.match(page, /\/server_profiles\/health/u);
  assert.doesNotMatch(page, /\/api\/health/u);
});

test("component rows group by role with the stop switch, and stale heartbeats read as stale", () => {
  const groups = model.buildComponentGroups({
    source: "disk",
    checked_at: "2026-09-26 22:00:00",
    roles: [
      {
        role: "engine",
        label: "Engine",
        stop_switch: false,
        instances: [
          { name: "a.json", machine: "PC1", user: "alice", age_seconds: 2, status: "Active" },
          { name: "b.json", machine: "PC1", user: "alice", age_seconds: 9, status: "Stale" },
        ],
      },
      { role: "bridge", label: "Bridge", stop_switch: true, instances: [] },
      { role: "gateway", label: "Gateway", stop_switch: false, instances: [{ name: "g.json", machine: "", user: "", age_seconds: null, status: "Active" }] },
    ],
  });

  assert.deepEqual(groups.map((group) => [group.label, group.summary, group.stopSwitch]), [
    ["Engine", "1 active, 1 stale", false],
    ["Bridge", "Not running", true],
    ["Gateway", "1 active", false],
  ]);
  assert.deepEqual(groups[0].rows.map((row) => [row.machine, row.user, row.heard, row.status, row.stale]), [
    ["PC1", "alice", "2 s ago", "Active", false],
    ["PC1", "alice", "9 s ago", "Stale", true],
  ]);
  assert.deepEqual([groups[2].rows[0].machine, groups[2].rows[0].heard], ["Unknown", "Unknown"]);
});

test("last heard reads in seconds, minutes, then hours", () => {
  assert.equal(model.heardAgo(0), "0 s ago");
  assert.equal(model.heardAgo(59), "59 s ago");
  assert.equal(model.heardAgo(125), "2 min ago");
  assert.equal(model.heardAgo(7300), "2 h ago");
  assert.equal(model.heardAgo(null), "Unknown");
});

test("the component panel says where its answer came from, or why there is none", () => {
  assert.equal(model.componentPanelState(null).kind, "loading");
  assert.deepEqual(model.componentPanelState(null, "Request failed (409)."), { kind: "error", message: "Request failed (409)." });
  assert.deepEqual(
    model.componentPanelState({ answering: false, detail: "Gateway not answering.", roles: [] }),
    { kind: "silent", message: "Gateway not answering." },
  );
  assert.equal(
    model.componentPanelState({ answering: true, source: "disk", checked_at: "2026-09-26 22:00:05", roles: [] }).source,
    "Read from this PC's server folder at 22:00:05",
  );
  assert.match(model.componentPanelState({ answering: true, source: "gateway", checked_at: "", roles: [] }).source, /Gateway/u);
});

test("the component panel asks only while on screen, at once on return, then every five seconds", () => {
  const base = { visible: true, wasHidden: false, inFlight: false, lastFetchAt: 1000, now: 1000 + model.COMPONENT_REFRESH_MS - 1 };
  assert.equal(model.COMPONENT_REFRESH_MS, 5000);
  assert.equal(model.shouldRefreshComponents(base), false);
  assert.equal(model.shouldRefreshComponents({ ...base, now: 1000 + model.COMPONENT_REFRESH_MS }), true);
  assert.equal(model.shouldRefreshComponents({ ...base, visible: false, lastFetchAt: 0 }), false);
  assert.equal(model.shouldRefreshComponents({ ...base, wasHidden: true }), true);
  assert.equal(model.shouldRefreshComponents({ ...base, lastFetchAt: 0 }), true);
  assert.equal(model.shouldRefreshComponents({ ...base, lastFetchAt: 0, inFlight: true }), false);
});

test("the page asks the app server for component status and checks its own frame is shown", async () => {
  const page = await read("../ui/server/server.js");
  assert.match(page, /fetch\("\/server\/status"/u);
  assert.match(page, /frameElement[\s\S]*getClientRects\(\)\.length/u);
  assert.match(page, /visibilitychange/u);
});

// A status as the app server returns it for start and stop: the supervised roles, each with its
// heartbeats and stop switch.
function supervisedStatus({ running = [], stale = [], switches = [], available = true, detail = "" } = {}) {
  const roles = ["orchestrator", "engine", "gateway"];
  return {
    control: { available, detail, roles },
    roles: [...roles, "bridge"].map((role) => ({
      role,
      stop_switch: switches.includes(role),
      instances: [
        ...(running.includes(role) ? [{ name: `${role}.json`, status: "Active" }] : []),
        ...(stale.includes(role) ? [{ name: `${role}-old.json`, status: "Stale" }] : []),
      ],
    })),
  };
}

test("start and stop show only for a server this PC may control, and production says why not", () => {
  const note = "The production server is started and stopped from Admin Control on the Server PC.";
  assert.deepEqual(
    model.serverControlView(supervisedStatus({ available: false, detail: note }), null, 0),
    { show: false, note, canStart: false, canStop: false, progress: "" },
  );
  assert.equal(model.serverControlView(null, null, 0).show, false);

  const up = model.serverControlView(supervisedStatus({ running: ["orchestrator", "engine", "gateway"] }), null, 0);
  assert.deepEqual([up.show, up.canStart, up.canStop], [true, false, true]);
  const down = model.serverControlView(supervisedStatus({ stale: ["gateway"], switches: ["gateway"] }), null, 0);
  assert.deepEqual([down.canStart, down.canStop], [true, false]);
  // A running server with a stop switch left on can still be started, which clears it.
  const switchOn = model.serverControlView(supervisedStatus({ running: ["orchestrator", "engine", "gateway"], switches: ["engine"] }), null, 0);
  assert.deepEqual([switchOn.canStart, switchOn.canStop], [true, true]);
});

test("a start or stop shows its progress and ends when the heartbeats agree, or after ninety seconds", () => {
  const start = { kind: "start", startedAt: 1000 };
  const partly = supervisedStatus({ running: ["orchestrator", "engine"] });
  const view = model.serverControlView(partly, start, 13400);
  assert.deepEqual([view.progress, view.canStart, view.canStop], ["Starting... 12 s", false, false]);
  assert.equal(model.serverActionOutcome(partly, start, 13400), "waiting");
  assert.equal(model.serverActionOutcome(supervisedStatus({ running: ["orchestrator", "engine", "gateway"] }), start, 20000), "done");
  assert.equal(model.serverActionOutcome(partly, start, 1000 + model.SERVER_ACTION_TIMEOUT_MS), "timeout");

  const stop = { kind: "stop", startedAt: 1000 };
  assert.equal(model.serverActionOutcome(supervisedStatus({ running: ["gateway"], switches: ["gateway"] }), stop, 5000), "waiting");
  assert.equal(model.serverActionOutcome(supervisedStatus({ stale: ["gateway"], switches: ["gateway"] }), stop, 5000), "done");
  assert.equal(model.serverActionOutcome(null, null, 0), "");

  assert.deepEqual(model.serverActionMessage("stop", "done"), { text: "The server is stopped.", tone: "" });
  assert.equal(model.serverActionMessage("start", "timeout").tone, "error");
});

test("the page posts start and stop to the app server and confirms a stop first", async () => {
  const page = await read("../ui/server/server.js");
  assert.match(page, /fetch\(`\/server\/\$\{kind\}`, \{ method: "POST" \}\)/u);
  assert.match(page, /"svStopBtn"\)\.addEventListener\("click", confirmStop\)/u);
  assert.match(page, /title: "Stop Server"/u);
});
