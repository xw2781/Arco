import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  canonicalizeMacroContext,
  macroContextFingerprint,
} from "../ui/macro/macro_context_fingerprint.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("Arcode routes its single Run action from the current source", () => {
  const js = read("../ui/arcode/code-editor/index.js");
  const framework = read("../ui/arcode/shared/editor_framework.js");
  const css = read("../ui/arcode/shared/editor_framework.css");

  assert.match(framework, /id: "runBtn"/);
  assert.doesNotMatch(framework, /runInArcRhoBtn/);
  assert.match(js, /scriptingFetch\("\/scripting\/run-in-arcrho"/);
  assert.match(js, /JSON\.stringify\(\{[\s\S]*?\bsource,/);
  assert.match(js, /source_path: page\.path/);
  assert.match(js, /function isArcRhoMacroSource\(code\)/);
  assert.match(js, /<arcrho-macro>/);
  assert.match(js, /run_macro/);
  // One Run command. A selection is a fragment, so it runs locally; only a
  // whole macro file is routed to ArcRho.
  assert.match(js, /!selectionOnly && isArcRhoMacroSource\(code\) \? runInArcRho\(code\) : runPython\(code\)/);
  assert.doesNotMatch(js, /runSelectionBtn/);
  assert.doesNotMatch(js, /runInArcRhoBtn/);
  assert.match(js, /scriptingFetch\("\/scripting\/run-stream"/);

  const classifierSource = js.match(/function isArcRhoMacroSource\(code\) \{[\s\S]*?\n\}/)?.[0] || "";
  const classify = Function(`${classifierSource}\nreturn isArcRhoMacroSource;`)();
  const maintainedMacro = read("../../python-api/macros/show_diagnostic_triangle.py");
  assert.equal(classify(maintainedMacro), true);
  assert.equal(classify("def run_macro(active_dfm):\n    return active_dfm\n"), true);
  assert.equal(classify("print('ordinary local script')\n"), false);

  const toolbarRule = css.match(/\.ce-toolbar\s*\{([^}]*)\}/)?.[1] || "";
  const buttonRule = css.match(/\.ce-btn\s*\{([^}]*)\}/)?.[1] || "";
  assert.match(toolbarRule, /overflow-x:\s*auto/);
  assert.match(buttonRule, /flex:\s*0 0 auto/);
  assert.match(buttonRule, /min-width:\s*max-content/);
  assert.match(buttonRule, /white-space:\s*nowrap/);
});

test("ArcRho captures and reapplies an exact DFM target around source execution", () => {
  const automation = read("../ui/shell/ui_automation.js");
  const macro = read("../ui/macro/macro_window.js");
  const projectMessages = read("../ui/project_instance/project_instance_messages.js");

  assert.match(automation, /macro\.captureActiveDfmContext/);
  assert.match(automation, /macro\.reviewAndApplyResult/);
  assert.match(macro, /capturedExternalMacroTargets/);
  assert.match(macro, /fingerprint/);
  assert.match(macro, /changed while the macro was running/);
  assert.match(macro, /Macro review expired before the result could be applied/);
  assert.match(macro, /active_dfm will be None/);
  assert.match(projectMessages, /message\?\.targetWindowId/);
  assert.match(projectMessages, /findWindowByInstance\(targetWindowId\)/);
});

test("Macro windows keep their size while the host window is resized", () => {
  const macro = read("../ui/macro/macro_window.js");
  const library = read("../ui/macro/macro_library_window.js");
  const frame = read("../ui/macro/macro_window_frame.js");

  assert.match(frame, /function lockSize\(\)/);
  assert.match(frame, /function initResize\(\)/);
  assert.doesNotMatch(frame, /addEventListener\("resize"/);
  assert.match(macro, /createMacroWindowFrame/);
  assert.match(library, /createMacroWindowFrame/);
  assert.match(macro, /macroWindowFrame\?\.lockSize\(\)/);
  assert.match(library, /libraryWindowFrame\?\.lockSize\(\)/);
});

test("Macro lists share keyboard selection and pointer-captured drag", () => {
  const macro = read("../ui/macro/macro_window.js");
  const library = read("../ui/macro/macro_library_window.js");
  const interactions = read("../ui/macro/macro_list_interactions.js");
  const css = read("../ui/macro/macro_window.css");

  assert.match(interactions, /setPointerCapture\(event\.pointerId\)/);
  assert.match(interactions, /event\.key === "ArrowDown"/);
  assert.match(interactions, /event\.key === "ArrowUp"/);
  assert.match(macro, /initMacroListKeyboard\(macroList/);
  assert.match(macro, /initMacroListDrag\(macroList, macroWindow, \{[\s\S]*?reorder: true/);
  // Dragged clear of the window a macro is deleted, unless it lands on the Flight Deck.
  assert.match(macro, /outsideTarget: \(element\) => \{[\s\S]*?kind: "deck"[\s\S]*?kind: "remove"/);
  assert.match(library, /initMacroListKeyboard\(libraryList/);
  assert.match(library, /initMacroListDrag\(libraryList, libraryWindow/);
  assert.match(library, /closest\?\.\("#macroWindow"\)/);
  assert.doesNotMatch(library, /reorder: true/);
  // Rows carry no native tooltip; the description pane holds that text.
  assert.doesNotMatch(macro, /item\.title = /);
  assert.doesNotMatch(library, /item\.title = /);
  // The display order is a local-user preference under %APPDATA%\Arco\prefs,
  // written by the desktop host, never browser storage.
  const preload = read("../electron/preload.js");
  const main = read("../electron/main.js");
  assert.match(macro, /getHostApi\(\)\?\.loadMacroPreferences\?\.\(\)/);
  assert.match(macro, /getHostApi\(\)\?\.saveMacroPreferences\?\.\(\{ version: 1, order \}\)/);
  assert.doesNotMatch(macro, /arcrho_macro_order|MACRO_ORDER_KEY/);
  assert.match(preload, /loadMacroPreferences:\s*\(\)\s*=>\s*invoke\("macro-preferences-load"\)/u);
  assert.match(preload, /saveMacroPreferences:\s*\(preferences\)\s*=>\s*invoke\("macro-preferences-save",\s*\{ preferences \}\)/u);
  assert.match(main, /const MACRO_PREFS_FILE = "macro_prefs\.json"/u);
  assert.match(main, /ipcMain\.handle\("macro-preferences-load"/u);
  assert.match(main, /ipcMain\.handle\("macro-preferences-save"/u);
  // Both windows open at the same default size.
  const macroHeight = css.match(/#macroWindow \{[^}]*height: min\((\d+)px/)?.[1];
  const libraryHeight = css.match(/#macroLibraryWindow \{[^}]*height: min\((\d+)px/)?.[1];
  assert.equal(libraryHeight, macroHeight);
});

test("ArcRho automation error dialogs render the close mark as SVG", () => {
  const automation = read("../ui/shell/ui_automation.js");

  assert.match(automation, /normalized === "error"/);
  assert.match(automation, /content: '<svg viewBox="0 0 24 24"/);
  assert.match(automation, /<path d="M7 7l10 10"><\/path><path d="M17 7L7 17"><\/path>/);
  assert.match(automation, /\$\{icon\.content\}/);
  assert.doesNotMatch(automation, /normalized === "error"\) return \{ text: "x"/);
});

test("ArcRho macro validation ignores volatile timestamps but detects live DFM edits", () => {
  const initial = {
    activeJson: {
      "method_metadata": { "last_modified": "2026-07-22T12:00:00.000Z" },
      "ratios_tab": { "ratio_values": [[1.1, 1.2]], "cell_notes": {} },
    },
    dirty: true,
    fields: { methodName: "Paid Ultimate", project: "Example" },
    methodPath: "E:\\Arco Server\\projects\\Example\\Paid Ultimate.json",
  };
  const recaptured = {
    ...initial,
    activeJson: {
      ...initial.activeJson,
      "method_metadata": { "last_modified": "2026-07-22T12:00:05.000Z" },
    },
    dirty: false,
    fields: { project: "Example", methodName: "Paid Ultimate" },
  };
  const edited = {
    ...recaptured,
    activeJson: {
      ...recaptured.activeJson,
      "ratios_tab": { "ratio_values": [[1.1, 1.2]], "cell_notes": { Summary: { Paid: "Changed" } } },
    },
  };

  assert.equal(macroContextFingerprint(initial), macroContextFingerprint(recaptured));
  assert.notEqual(macroContextFingerprint(initial), macroContextFingerprint(edited));
  assert.equal(canonicalizeMacroContext(initial).activeJson["method_metadata"]["last_modified"], undefined);
  assert.equal(initial.activeJson["method_metadata"]["last_modified"], "2026-07-22T12:00:00.000Z");
});

test("standalone Arcode packages the first-party ArcRho API", () => {
  const spec = read("../build/arcode_server.spec");
  const fullRouter = read("../app_server/api/scripting_router.py");
  const arcodeRouter = read("../app_server/api/arcode_scripting_router.py");

  assert.match(spec, /python_api_src/);
  assert.match(spec, /collect_submodules\("arcrho_api"\)/);
  assert.match(fullRouter, /@router\.post\("\/scripting\/run-in-arcrho"\)/);
  assert.match(arcodeRouter, /@router\.post\("\/scripting\/run-in-arcrho"\)/);
});

test("packaged ArcRho server resolves the monorepo ArcRho API before collecting it", () => {
  const spec = read("../build/server.spec");
  const pathInsertion = spec.indexOf("sys.path.insert(0, str(python_api_src))");
  const submoduleCollection = spec.indexOf("collect_submodules('arcrho_api')");

  assert.ok(pathInsertion >= 0);
  assert.ok(submoduleCollection > pathInsertion);
});
