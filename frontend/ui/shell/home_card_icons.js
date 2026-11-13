// One owner for Home launch-card iconography. Built-in cards and custom shortcut cards both render
// through `homeCardIcon`, so a tab type looks the same wherever it is pinned. The accent color for
// each `kind` lives in `.homeIconBox.<kind>` in shell.css.

const ICON_PATHS = {
  files: '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H10l2 2h6.5A2.5 2.5 0 0 1 21 9.5v7A2.5 2.5 0 0 1 18.5 19h-13A2.5 2.5 0 0 1 3 16.5z"></path><path d="M7 11h10M7 14h7"></path>',
  project: '<rect x="3.3" y="3.3" width="7.5" height="7.5" rx="1.8"></rect><rect x="13.2" y="3.3" width="7.5" height="7.5" rx="1.8"></rect><rect x="3.3" y="13.2" width="7.5" height="7.5" rx="1.8"></rect><rect x="13.2" y="13.2" width="7.5" height="7.5" rx="1.8"></rect>',
  history: '<path d="M4 12a8 8 0 1 0 2.3-5.7"></path><path d="M4 5v5h5"></path><path d="M12 8v5l3 2"></path>',
  workflow: '<rect x="3" y="4" width="6" height="5" rx="1.2"></rect><rect x="15" y="4" width="6" height="5" rx="1.2"></rect><rect x="9" y="15" width="6" height="5" rx="1.2"></rect><path d="M9 6.5h6"></path><path d="M6 9v3.5h6V15"></path><path d="M18 9v3.5h-6"></path>',
  scripting: '<rect x="3" y="5" width="18" height="14" rx="2"></rect><path d="M7 9l3 3-3 3"></path><path d="M12 15h5"></path>',
  dataset: '<ellipse cx="12" cy="5" rx="7" ry="3"></ellipse><path d="M5 5v10c0 1.7 3.1 3 7 3s7-1.3 7-3V5"></path><path d="M5 10c0 1.7 3.1 3 7 3s7-1.3 7-3"></path>',
  dfm: '<path d="M4 18h16"></path><path d="M6 15l4-5 4 3 4-7"></path><circle cx="6" cy="15" r="1.2"></circle><circle cx="10" cy="10" r="1.2"></circle><circle cx="14" cy="13" r="1.2"></circle><circle cx="18" cy="6" r="1.2"></circle>',
  projectInstance: '<rect x="3.5" y="4.5" width="17" height="15" rx="2"></rect><path d="M3.5 9h17"></path><path d="M9 9v10.5"></path><path d="M12 12.5h6"></path><path d="M12 16h4"></path>',
  agentGuide: '<rect x="4" y="6" width="16" height="12" rx="2.5"></rect><circle cx="9.5" cy="12" r="1.2"></circle><circle cx="14.5" cy="12" r="1.2"></circle><path d="M12 3.5V6"></path><path d="M2.5 11v2.5"></path><path d="M21.5 11v2.5"></path>',
  theme: '<path d="M12 3.5a8.5 8.5 0 1 0 0 17c1.1 0 1.8-.8 1.8-1.7 0-.5-.2-.9-.5-1.2-.3-.4-.5-.8-.5-1.2 0-1 .8-1.7 1.8-1.7h2.2a3.7 3.7 0 0 0 3.7-3.7c0-4-3.8-7.5-8.5-7.5z"></path><circle cx="7.6" cy="11.2" r="1.2"></circle><circle cx="10.4" cy="7.3" r="1.2"></circle><circle cx="15" cy="7.6" r="1.2"></circle>',
  server: '<rect x="3.5" y="4" width="17" height="6.5" rx="1.6"></rect><rect x="3.5" y="13.5" width="17" height="6.5" rx="1.6"></rect><circle cx="7.3" cy="7.25" r="1"></circle><circle cx="7.3" cy="16.75" r="1"></circle><path d="M11 7.25h6M11 16.75h6"></path>',
  shortcut: '<path d="M10.5 13.5a4 4 0 0 0 5.7 0l2.6-2.6a4 4 0 0 0-5.7-5.7l-1.2 1.2"></path><path d="M13.5 10.5a4 4 0 0 0-5.7 0l-2.6 2.6a4 4 0 0 0 5.7 5.7l1.2-1.2"></path>',
};

// Kinds whose artwork is a file in `home-card-icons/`, applied as a mask by that folder's
// stylesheet. New cards are added here rather than to `ICON_PATHS` above.
const FILE_ICON_KINDS = new Set(["dashboard"]);

// Restorable tab type -> icon kind. Types absent here fall back to the generic shortcut glyph.
const TAB_TYPE_ICON_KINDS = {
  file_explorer: "files",
  project_settings: "project",
  browsing_history: "history",
  workflow: "workflow",
  scripting: "scripting",
  dataset: "dataset",
  dfm: "dfm",
  project_instance: "projectInstance",
  agent_guide: "agentGuide",
  server: "server",
  dashboard: "dashboard",
};

export function homeCardIconKind(tabType) {
  return TAB_TYPE_ICON_KINDS[String(tabType || "").trim().toLowerCase()] || "shortcut";
}

export function homeCardIcon(kind) {
  if (FILE_ICON_KINDS.has(kind)) {
    return `<div class="homeIconBox ${kind}" aria-hidden="true"><span class="homeIcon homeCardFileIcon" data-home-icon="${kind}"></span></div>`;
  }
  const safeKind = ICON_PATHS[kind] ? kind : "shortcut";
  return `<div class="homeIconBox ${safeKind}" aria-hidden="true"><svg class="homeIcon" viewBox="0 0 24 24">${ICON_PATHS[safeKind]}</svg></div>`;
}

export function homeCardIconForTabType(tabType) {
  return homeCardIcon(homeCardIconKind(tabType));
}
