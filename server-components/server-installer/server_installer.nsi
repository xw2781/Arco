Unicode true
RequestExecutionLevel user
SetCompressor /SOLID lzma

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "nsDialogs.nsh"

!ifndef PRODUCT_VERSION
  !error "PRODUCT_VERSION is required"
!endif
!ifndef WINDOWS_VERSION
  !error "WINDOWS_VERSION is required"
!endif
!ifndef OUTPUT_FILE
  !error "OUTPUT_FILE is required"
!endif
!ifndef PAYLOAD_DIR
  !error "PAYLOAD_DIR is required"
!endif
!ifndef DEPLOYER_EXE
  !error "DEPLOYER_EXE is required"
!endif

Name "ArcRho Server Components ${PRODUCT_VERSION}"
OutFile "${OUTPUT_FILE}"
InstallDir "$LOCALAPPDATA\Programs\ArcRho Server Components"
BrandingText "ArcRho Server Components"

VIProductVersion "${WINDOWS_VERSION}"
VIAddVersionKey "ProductName" "ArcRho Server Components"
VIAddVersionKey "ProductVersion" "${PRODUCT_VERSION}"
VIAddVersionKey "FileDescription" "ArcRho Server Components Setup"
VIAddVersionKey "FileVersion" "${PRODUCT_VERSION}"
VIAddVersionKey "LegalCopyright" "Copyright ArcRho contributors"

Var WorkspaceRoot
Var WorkspaceRootInput
Var ConfigureFrontend
Var ConfigureFrontendCheckbox

!define MUI_ABORTWARNING
!define MUI_ICON "${NSISDIR}\Contrib\Graphics\Icons\modern-install.ico"
!define MUI_UNICON "${NSISDIR}\Contrib\Graphics\Icons\modern-uninstall.ico"

!insertmacro MUI_PAGE_WELCOME
Page custom WorkspacePageShow WorkspacePageLeave
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_NOAUTOCLOSE
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

!insertmacro MUI_LANGUAGE "English"

Function .onInit
  StrCpy $ConfigureFrontend "0"
  ${If} ${FileExists} "E:\*.*"
    StrCpy $WorkspaceRoot "E:\Arco Server"
  ${Else}
    StrCpy $WorkspaceRoot "$PROFILE\Arco Server"
  ${EndIf}

  ${If} ${FileExists} "$APPDATA\Arco\workspace_paths.json"
  ${OrIf} ${FileExists} "$LOCALAPPDATA\Programs\ArcRho\ArcRho.exe"
  ${OrIf} ${FileExists} "$LOCALAPPDATA\Programs\arcrho-electron\ArcRho.exe"
    StrCpy $ConfigureFrontend "1"
  ${EndIf}
FunctionEnd

Function WorkspaceBrowse
  nsDialogs::SelectFolderDialog "Select the local ArcRho Server workspace" "$WorkspaceRoot"
  Pop $0
  ${If} $0 != error
    StrCpy $WorkspaceRoot $0
    ${NSD_SetText} $WorkspaceRootInput $WorkspaceRoot
  ${EndIf}
FunctionEnd

Function WorkspacePageShow
  !insertmacro MUI_HEADER_TEXT "ArcRho Server Workspace" "Choose where shared server data and components will live."
  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}

  ${NSD_CreateLabel} 0 0 100% 34u "Choose a writable folder on this PC's local fixed disk. Setup can install into a new workspace or safely adopt, upgrade, or repair an existing one."
  Pop $1
  ${NSD_CreateDirRequest} 0 42u 82% 12u "$WorkspaceRoot"
  Pop $WorkspaceRootInput
  ${NSD_CreateBrowseButton} 84% 41u 16% 14u "Browse..."
  Pop $2
  ${NSD_OnClick} $2 WorkspaceBrowse

  ${NSD_CreateCheckbox} 0 72u 100% 18u "Configure ArcRho Desktop for this workspace"
  Pop $ConfigureFrontendCheckbox
  ${If} $ConfigureFrontend == "1"
    ${NSD_Check} $ConfigureFrontendCheckbox
  ${EndIf}

  ${NSD_CreateLabel} 0 102u 100% 42u "Projects, requests, configuration, credentials, and runtime history are preserved during upgrades, repairs, and uninstall. Only installer-owned component binaries are replaced or removed."
  Pop $3
  nsDialogs::Show
FunctionEnd

Function WorkspacePageLeave
  ${NSD_GetText} $WorkspaceRootInput $WorkspaceRoot
  ${If} $WorkspaceRoot == ""
    MessageBox MB_ICONEXCLAMATION|MB_OK "Choose an ArcRho Server workspace folder."
    Abort
  ${EndIf}
  ${NSD_GetState} $ConfigureFrontendCheckbox $0
  ${If} $0 == ${BST_CHECKED}
    StrCpy $ConfigureFrontend "1"
  ${Else}
    StrCpy $ConfigureFrontend "0"
  ${EndIf}

  ${If} ${FileExists} "$WorkspaceRoot\apps\.arcrho-server-installer\install-receipt.json"
    ReadRegStr $1 HKCU "Software\ArcRho\ServerComponents" "Version"
    ${If} $1 == "${PRODUCT_VERSION}"
      MessageBox MB_ICONQUESTION|MB_YESNO "ArcRho Server Components ${PRODUCT_VERSION} is already installed in this workspace.$\r$\n$\r$\nRepair the deployment now? Projects, requests, configuration, credentials, and runtime history will be preserved." IDYES +2
      Abort
    ${Else}
      MessageBox MB_ICONQUESTION|MB_YESNO "This workspace already has a managed ArcRho Server deployment.$\r$\n$\r$\nContinue with a validated upgrade? Downgrades are blocked and shared data will be preserved." IDYES +2
      Abort
    ${EndIf}
  ${ElseIf} ${FileExists} "$WorkspaceRoot\config\*.*"
  ${OrIf} ${FileExists} "$WorkspaceRoot\projects\*.*"
  ${OrIf} ${FileExists} "$WorkspaceRoot\requests\*.*"
  ${OrIf} ${FileExists} "$WorkspaceRoot\apps\*.*"
    MessageBox MB_ICONQUESTION|MB_YESNO "This is an existing unreceipted workspace.$\r$\n$\r$\nAdopt it and install or upgrade the five ArcRho Server components? Existing shared data and unrelated apps will be preserved." IDYES +2
    Abort
  ${EndIf}
FunctionEnd

Section "ArcRho Server Components" SEC_SERVER
  SetDetailsPrint both
  DetailPrint "Verifying and deploying ArcRho Server Components ${PRODUCT_VERSION}..."
  InitPluginsDir
  ; Keep extraction prefixes short so deeply nested Bridge resources remain
  ; below the legacy Windows path boundary even under a long user profile.
  SetOutPath "$PLUGINSDIR\d"
  File /oname=d.exe "${DEPLOYER_EXE}"
  SetOutPath "$PLUGINSDIR\p"
  File /r "${PAYLOAD_DIR}\*.*"

  StrCpy $0 ""
  ${If} $ConfigureFrontend == "1"
    StrCpy $0 "--configure-frontend"
  ${EndIf}
  nsExec::ExecToStack '"$PLUGINSDIR\d\d.exe" auto --root "$WorkspaceRoot" --payload "$PLUGINSDIR\p" --manifest "$PLUGINSDIR\p\payload-manifest.json" $0'
  Pop $1
  Pop $2
  ${If} $2 != ""
    DetailPrint "$2"
  ${EndIf}
  ${If} $1 != 0
    MessageBox MB_ICONSTOP|MB_OK "ArcRho Server Components setup failed.$\r$\n$\r$\n$2"
    SetErrorLevel $1
    Abort
  ${EndIf}

  CreateDirectory "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\ArcRho\ServerComponents" "WorkspaceRoot" "$WorkspaceRoot"
  WriteRegStr HKCU "Software\ArcRho\ServerComponents" "Version" "${PRODUCT_VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ArcRho Server Components" "DisplayName" "ArcRho Server Components"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ArcRho Server Components" "DisplayVersion" "${PRODUCT_VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ArcRho Server Components" "Publisher" "ArcRho"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ArcRho Server Components" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ArcRho Server Components" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ArcRho Server Components" "NoRepair" 1
  DetailPrint "ArcRho Server Components ${PRODUCT_VERSION} deployed to $WorkspaceRoot."
SectionEnd

Section "Uninstall"
  SetDetailsPrint both
  ReadRegStr $WorkspaceRoot HKCU "Software\ArcRho\ServerComponents" "WorkspaceRoot"
  ${If} $WorkspaceRoot == ""
    MessageBox MB_ICONSTOP|MB_OK "The ArcRho Server workspace location is missing. No server data or components were removed."
    Abort
  ${EndIf}

  InitPluginsDir
  SetOutPath "$PLUGINSDIR\d"
  File /oname=d.exe "${DEPLOYER_EXE}"
  nsExec::ExecToStack '"$PLUGINSDIR\d\d.exe" uninstall --root "$WorkspaceRoot"'
  Pop $0
  Pop $1
  ${If} $1 != ""
    DetailPrint "$1"
  ${EndIf}
  ${If} $0 != 0
    MessageBox MB_ICONSTOP|MB_OK "ArcRho Server Components could not be removed.$\r$\n$\r$\n$1"
    SetErrorLevel $0
    Abort
  ${EndIf}

  DeleteRegKey HKCU "Software\ArcRho\ServerComponents"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ArcRho Server Components"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DetailPrint "Component binaries and startup integration were removed. Shared workspace data was preserved at $WorkspaceRoot."
SectionEnd
