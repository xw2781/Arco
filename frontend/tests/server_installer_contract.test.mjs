import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";


const frontendInstaller = fs.readFileSync(
  new URL("../build/installer/installer.nsh", import.meta.url),
  "utf8"
);
const detector = fs.readFileSync(
  new URL("../build/installer/detect_arcrho_server_root.ps1", import.meta.url),
  "utf8"
);
const serverInstaller = fs.readFileSync(
  new URL("../../server-components/server-installer/server_installer.nsi", import.meta.url),
  "utf8"
);
const releaseBuilder = fs.readFileSync(
  new URL("../../server-components/server-installer/build_release.py", import.meta.url),
  "utf8"
);


test("desktop setup reads the configured workspace before drive-name scanning", () => {
  const configuredCall = frontendInstaller.indexOf(
    "Call ArcRho_DetectConfiguredServerRoot"
  );
  const driveScan = frontendInstaller.indexOf(
    '!insertmacro ArcRho_CheckServerRoot "C:"',
    configuredCall
  );
  assert.ok(configuredCall >= 0);
  assert.ok(driveScan > configuredCall);
  assert.match(
    frontendInstaller,
    /SetOutPath "\$PLUGINSDIR"[\s\S]*File \/oname=detect_arcrho_server_root\.ps1/
  );
  assert.match(detector, /workspace_paths\.json/);
  assert.match(detector, /\.workspace_root/);
  assert.match(detector, /Test-Path -LiteralPath \$root -PathType Container/);
});


test("desktop setup starts only an already-installed local deployment", () => {
  assert.match(
    frontendInstaller,
    /Function ArcRho_DetectDataEngineInstalled[\s\S]*Arco Launcher\\Arco Launcher\.exe/
  );
  assert.match(
    frontendInstaller,
    /\$ArcRhoServerRootIsLocal == "1"[\s\S]*\$ArcRhoDataEngineInstalled == "1"[\s\S]*NSD_Check/
  );
  assert.match(frontendInstaller, /Use Arco Server Components Setup on the host PC/);
  assert.match(frontendInstaller, /Server binaries are delivered separately/);
  assert.doesNotMatch(frontendInstaller, /ArcRhoServerPayload|payload-manifest\.json/);
});


test("server setup delegates mutation to the frozen transactional helper", () => {
  assert.match(releaseBuilder, /ArcRho-Server-Setup-\{version\}\.exe/);
  assert.match(
    serverInstaller,
    /\\d\\d\.exe" auto --root "\$WorkspaceRoot" --payload/
  );
  assert.match(
    serverInstaller,
    /\\d\\d\.exe" uninstall --root "\$WorkspaceRoot"/
  );
  assert.match(serverInstaller, /WriteUninstaller/);
  assert.match(serverInstaller, /Shared workspace data was preserved/);
  assert.doesNotMatch(serverInstaller, /RMDir \/r "\$WorkspaceRoot/);
});


test("desktop setup closes every process running from the install folder before touching it", () => {
  const closer = fs.readFileSync(
    new URL("../build/installer/close_arcrho_processes.ps1", import.meta.url),
    "utf8"
  );
  const nsh = frontendInstaller.replace(/\r\n/g, "\n");
  // The macro replaces electron-builder's main-executable-only check in both
  // the installer and the uninstaller, so it must sit outside the installer-only block.
  const macroIndex = nsh.indexOf("!macro customCheckAppRunning");
  const installerOnlyIndex = nsh.indexOf("!ifndef BUILD_UNINSTALLER\n  ; A setup the app started for an update goes back");
  assert.ok(macroIndex >= 0);
  assert.ok(installerOnlyIndex > macroIndex);
  assert.match(
    nsh,
    /!macro customCheckAppRunning[\s\S]*File \/oname=\$PLUGINSDIR\\close_arcrho_processes\.ps1/
  );
  assert.match(nsh, /-InstallDir "\$INSTDIR" -DetectOnly/);
  assert.match(nsh, /MB_RETRYCANCEL[^\n]*could not be closed[^\n]*Task Manager/);
  // A process stuck in Windows' own teardown goes within minutes, so setup
  // waits that out with a status line before it asks the user.
  assert.match(
    nsh,
    /DetailPrint "Waiting for Windows to finish closing \$\(\^Name\)\.\.\."\n[^\n]*close_arcrho_processes\.ps1" -InstallDir "\$INSTDIR" -WaitSeconds 300'[\s\S]*?MB_RETRYCANCEL/
  );
  assert.match(closer, /\[int\]\$WaitSeconds = 15/);
  assert.match(closer, /Wait-ForExit \$WaitSeconds/);
  assert.match(closer, /Win32_Process/);
  assert.match(closer, /CloseMainWindow\(\)/);
  assert.match(closer, /Stop-Process -Id \$process\.ProcessId -Force/);
  assert.doesNotMatch(closer, /\.MainModule/, "MainModule is refused across the 32/64-bit boundary");
});


test("a setup the app starts for an update shows only the file progress page", () => {
  const nsh = frontendInstaller.replace(/\r\n/g, "\n");
  assert.match(nsh, /!macro customInstallMode[\s\S]*\$isForceCurrentInstall "1"/);
  assert.match(
    nsh,
    /Function ArcRho_ExcelAddInOptions_Show\n[^\n]*\n[^\n]*\n\s*\$\{If\} \$ArcRhoIsUpdate == "1"\n\s*Abort/
  );
  assert.match(
    nsh,
    /!macro customFinishPage[\s\S]*Function ArcRho_FinishPage_Pre[\s\S]*Call ArcRho_StartApp\n\s*Abort/
  );
  assert.match(nsh, /MUI_PAGE_CUSTOMFUNCTION_PRE ArcRho_FinishPage_Pre/);
  assert.match(
    nsh,
    /Function ArcRho_StartApp[\s\S]*\$\{StdUtils\.ExecShellAsUser\} \$0 "\$launchLink" "open" "\$ArcRhoStartAppArgs"/
  );
  // electron-builder's install section already expands common.nsh's StartApp
  // macro, and it declares a variable, so a second expansion here would end
  // every build with 'variable "startAppArgs" already declared'.
  assert.doesNotMatch(nsh, /!insertmacro StartApp/);
});


test("server release staging builds every component without live deployment", () => {
  assert.match(releaseBuilder, /environment\["ARCRHO_STAGE_ONLY"\] = "1"/);
  assert.match(releaseBuilder, /build_manifest\(version, component_roots\)/);
  assert.match(releaseBuilder, /ArcRho-Server-Setup-\{version\}\.exe/);
  assert.match(releaseBuilder, /version != current_version/);
  assert.match(releaseBuilder, /payload_copy_ignore/);
  assert.match(releaseBuilder, /__pycache__/);
  assert.match(releaseBuilder, /migration/);
});
