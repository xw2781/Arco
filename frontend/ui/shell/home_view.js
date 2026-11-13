import { shell } from "./shell_context.js?v=20260510a";
import { homeCardIcon } from "./home_card_icons.js?v=20260926a";
import { initHomeShortcuts } from "./home_shortcuts_view.js?v=20260926a";
import { openColorThemeDialog } from "./color_theme_dialog.js?v=20260923c";

let homeWired = false;
let cachedHomeBrandName = null;
let homeBrandNamePromise = null;

const DEFAULT_HOME_BRAND_NAME = "Arco";
const HOME_AVATAR_TEXT = "#526071";

export function getHomeBrandInitial(name) {
  const text = String(name || "").trim();
  const firstAscii = Array.from(text).find((char) => /^[A-Za-z0-9]$/.test(char));
  return firstAscii ? firstAscii.toUpperCase() : "#";
}

function createHomeBrandMarkSvg(initial) {
  const safeInitial = getHomeBrandInitial(initial);
  return `
    <svg viewBox="0 0 32 32" role="img" aria-label="${safeInitial} initial mark" focusable="false">
      <text x="16" y="21" text-anchor="middle" fill="${HOME_AVATAR_TEXT}" font-family="Segoe UI, Arial, sans-serif" font-size="14" font-weight="700">${safeInitial}</text>
    </svg>
  `;
}

function applyHomeBrandIdentity(homeView, userName) {
  const displayName = String(userName || "").trim() || DEFAULT_HOME_BRAND_NAME;
  const initial = getHomeBrandInitial(displayName);
  const title = homeView.querySelector(".homeBrandTitle");
  const mark = homeView.querySelector(".homeBrandMark");
  if (title) title.textContent = displayName;
  if (mark) mark.innerHTML = createHomeBrandMarkSvg(initial);
}

async function updateHomeBrandIdentity(homeView) {
  if (cachedHomeBrandName) {
    applyHomeBrandIdentity(homeView, cachedHomeBrandName);
    return;
  }
  if (!homeBrandNamePromise) {
    homeBrandNamePromise = fetch("/app/user-identity")
      .then((response) => {
        if (!response.ok) throw new Error(`User identity request failed (${response.status}).`);
        return response.json();
      })
      .then((identity) => String(identity?.display_name || identity?.login_name || "").trim())
      .catch(async () => {
        const hostApi = window.ADAHost;
        if (!hostApi?.getWindowsUserName) return "";
        return String(await hostApi.getWindowsUserName() || "").trim();
      })
      .then((displayName) => displayName || DEFAULT_HOME_BRAND_NAME);
  }
  try {
    cachedHomeBrandName = await homeBrandNamePromise;
    applyHomeBrandIdentity(homeView, cachedHomeBrandName);
  } catch {
    applyHomeBrandIdentity(homeView, DEFAULT_HOME_BRAND_NAME);
  }
}

export function renderHomeViewOnce(homeView) {
  if (!homeView) return;
  if (!homeView.dataset.rendered) {
    homeView.innerHTML = `
      <div class="homeLayout">
        <main class="homeMain">
          <section id="homeLaunchPage" class="homePage homeLaunchPage" aria-label="Launch Center">
            <div class="homeWelcomePanel">
              <div class="homeBrand">
                <div class="homeBrandMark" aria-hidden="true">${createHomeBrandMarkSvg(DEFAULT_HOME_BRAND_NAME)}</div>
                <div class="homeBrandText">
                  <div class="homeBrandTitle">Arco</div>
                  <div class="homeBrandSub">Power User</div>
                </div>
              </div>
              <div class="homeWelcomeDivider" aria-hidden="true"></div>
              <div class="homeWelcomeMessage">
                <div class="homeWelcomeTitle">Welcome to Arco</div>
                <div class="homeWelcomeText">Choose a workspace below to begin your work.</div>
              </div>
            </div>
            <div id="homeLaunchGeneralGroup" class="homeGroup">
              <div class="groupTitle">General</div>
              <div class="cards">
                <div class="card clickable" id="cardFileExplorer">${homeCardIcon("files")}<div><h3>File Browser</h3><div class="muted">Browse favorite folders and open local files.</div></div></div>
                <div class="card clickable" id="cardProjectSettings">${homeCardIcon("project")}<div><h3>Project Explorer</h3><div class="muted">Browse and manage projects.</div></div></div>
                <div class="card clickable" id="cardBrowsingHistory">${homeCardIcon("history")}<div><h3>Browsing History</h3><div class="muted">Restore recent pages and dataset views.</div></div></div>
                <div class="card clickable" id="cardColorTheme" role="button" tabindex="0">${homeCardIcon("theme")}<div><h3>Color Theme</h3><div class="muted">Preview table styles and switch between Light and Dark.</div></div></div>
                <div class="card clickable" id="cardDashboards">${homeCardIcon("dashboard")}<div><h3>Dashboards</h3><div class="muted">Build interactive charts from project data.</div></div></div>
                <div class="card clickable" id="cardServer">${homeCardIcon("server")}<div><h3>Server Connections</h3><div class="muted">Connect to Arco servers and databases.</div></div></div>
              </div>
            </div>
            <div id="homeLaunchAutomationGroup" class="homeGroup">
              <div class="groupTitle">Automation</div>
              <div class="cards">
                <div class="card clickable" id="cardNewWorkflow">${homeCardIcon("workflow")}<div><h3>New Workflow</h3><div class="muted">Build or load a workflow tab.</div></div></div>
                <div class="card clickable" id="cardScripting">${homeCardIcon("scripting")}<div><h3>Arcode</h3><div class="muted">Open the scripting app.</div></div></div>
              </div>
            </div>
            <div id="homeShortcutGroups" class="homeShortcutGroups"></div>
          </section>
        </main>
      </div>
    `;
    homeView.dataset.rendered = "1";
  }
  updateHomeBrandIdentity(homeView);
  if (!homeWired) {
    document.getElementById("cardNewWorkflow")?.addEventListener("click", () => shell.openWorkflowTab?.());
    document.getElementById("cardFileExplorer")?.addEventListener("click", () => shell.openFileExplorerTab?.());
    document.getElementById("cardProjectSettings")?.addEventListener("click", () => shell.openProjectSettingsTab?.());
    document.getElementById("cardBrowsingHistory")?.addEventListener("click", () => shell.openBrowsingHistoryTab?.());
    document.getElementById("cardServer")?.addEventListener("click", () => shell.openServerTab?.());
    document.getElementById("cardDashboards")?.addEventListener("click", () => shell.openDashboardTab?.());
    document.getElementById("cardScripting")?.addEventListener("click", () => shell.openScriptingTab?.({ forceNew: true }));
    const colorThemeCard = document.getElementById("cardColorTheme");
    colorThemeCard?.addEventListener("click", () => openColorThemeDialog());
    colorThemeCard?.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      openColorThemeDialog();
    });
    homeWired = true;
  }
  initHomeShortcuts(homeView.querySelector("#homeShortcutGroups"));
}
