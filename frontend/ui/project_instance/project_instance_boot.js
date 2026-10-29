import { fetchProjectDatasetTypes } from "/ui/shared/dataset/dataset_types_source.js";
import {
  getProjectUserPreferencesPath,
  loadProjectUserPreferences,
  saveProjectUserPreferences,
  scheduleProjectUserPreferencesSave,
} from "/ui/shared/services/project_user_preferences.js";
import { openReservingClassPicker } from "/ui/shared/components/pickers/reserving_class_picker.js?v=20260925a";
import "/ui/shared/integrations/zoom_bridge.js?v=20260521a";

import { createProjectInstanceContext } from "./project_instance_context.js?v=20261020a";
import { installProjectInstanceUtils } from "./project_instance_utils.js?v=20260607d";
import { installProjectInstanceLoading } from "./project_instance_loading.js?v=20260809b";
import { installProjectInstanceDatasetCache } from "./project_instance_dataset_cache.js?v=20261020a";
import { installProjectInstancePreferences } from "./project_instance_preferences.js?v=20260824g";
import { installProjectInstanceExcelLinks } from "./project_instance_excel_links.js?v=20260919a";
import { installProjectInstanceDependencyGraph } from "./project_instance_dependency_graph.js?v=20261020a";
import { installProjectInstanceDatasetTable } from "./project_instance_dataset_table.js?v=20261013group1";
import { installProjectInstanceDatasetAddPicker } from "./project_instance_dataset_add_picker.js?v=20260611a";
import { installProjectInstancePathPanel } from "./project_instance_path_panel.js?v=20260920a";
import { installProjectInstanceWindows } from "./project_instance_windows.js?v=20261029a";
import { installProjectInstanceHiddenTabs } from "./project_instance_hidden_tabs.js?v=20261029a";
import { installProjectInstanceReviewTable } from "./project_instance_review_table.js?v=20260828f";
import { installProjectInstanceMessages } from "./project_instance_messages.js?v=20260929smb";
import { installProjectInstanceBusyBanner } from "./project_instance_busy_banner.js?v=20260813c";
import { installProjectInstanceDeleteGuard } from "./project_instance_delete_guard.js?v=20260817a";

export async function bootProjectInstance() {
  const ctx = createProjectInstanceContext({
    fetchProjectDatasetTypes,
    getProjectUserPreferencesPath,
    loadProjectUserPreferences,
    saveProjectUserPreferences,
    scheduleProjectUserPreferencesSave,
    openReservingClassPicker,
  });

  installProjectInstanceUtils(ctx);
  installProjectInstanceLoading(ctx);
  installProjectInstanceDatasetCache(ctx);
  installProjectInstancePreferences(ctx);
  installProjectInstanceExcelLinks(ctx);
  installProjectInstanceDependencyGraph(ctx);
  installProjectInstanceDatasetTable(ctx);
  installProjectInstanceDatasetAddPicker(ctx);
  installProjectInstancePathPanel(ctx);
  installProjectInstanceWindows(ctx);
  installProjectInstanceHiddenTabs(ctx);
  installProjectInstanceReviewTable(ctx);
  installProjectInstanceMessages(ctx);
  installProjectInstanceBusyBanner(ctx);
  installProjectInstanceDeleteGuard(ctx);

  const { api, els, projectName, state } = ctx;
  await api.applyHostFrameCornerStyle();
  api.initHiddenTabsArea();
  api.initCachedDatasetToolbar();
  api.initProjectInstancePreferences();
  api.initExcelLinkManager();
  api.initDependencyGraph();
  api.initLeftPanelResizer();
  api.initDatasetTableInteractions();
  api.initDatasetAddPickerInteractions();
  api.initDatasetWindowShortcuts();
  window.addEventListener("resize", api.syncMaximizedDatasetWindows);
  if (!projectName) {
    api.setStatus("Project name is missing.", true);
    api.setEmptyTable("Project name is missing.");
    if (els.pathTree) els.pathTree.innerHTML = '<div class="ptree-empty">Project name is missing.</div>';
    api.finishPageLoading();
    return;
  }
  await api.loadDatasetTablePreferences();
  api.startReservingClassBusyWatch();
  await Promise.all([api.loadPathTree(), api.loadDatasets()]);
  state.projectInstanceBootComplete = true;
  if (state.pendingProjectInstanceRestoreState) {
    const restoreState = state.pendingProjectInstanceRestoreState;
    state.pendingProjectInstanceRestoreState = null;
    await api.applyProjectInstanceRestoreState(restoreState);
  } else {
    api.notifyProjectInstanceStateChanged();
  }
}
