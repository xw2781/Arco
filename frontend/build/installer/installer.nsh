; Custom NSIS script for richer installation detail output and progress text.

; electron-builder prepends this custom include before its own MUI2 include.
; Load MUI2 here so MUI_HEADER_TEXT is defined when the functions below are parsed.
!ifndef MUI_INCLUDED
  !include "MUI2.nsh"
!endif

!include "LogicLib.nsh"
!include "nsDialogs.nsh"

!ifndef BUILD_UNINSTALLER
  !define ARCRHO_PREFERRED_INSTALL_COMPUTER "NE7SASWPN02"
  !define ARCRHO_PREFERRED_INSTALL_DRIVE "E:"

  ; electron-builder expands this hook after common.nsh, whose default is
  ; "nevershow". Keep the log collapsed while exposing the native Show details
  ; control on the assisted installer page.
  !macro customHeader
    ShowInstDetails hide
  !macroend

  Var ArcRhoInstallExcelAddIn
  Var ArcRhoInstallExcelAddInCheckbox
  Var ArcRhoLaunchDataEngine
  Var ArcRhoLaunchDataEngineCheckbox
  Var ArcRhoServerRoot
  Var ArcRhoServerRootDetected
  Var ArcRhoServerRootIsLocal
  Var ArcRhoDataEngineInstalled
  Var ArcRhoServerDriveDropList
  Var ArcRhoExcelAddInPath
  Var ArcRhoPreferredInstallDirectory
  Var ArcRhoInstallLocationIsOwned
  Var ArcRhoIsUpdate
  Var ArcRhoStartAppArgs

  !macro ArcRho_PrintInstallDetail MSG
    ; Keep action-level output in the details list so it cannot replace the
    ; bar-derived percentage and time estimate in the status caption.
    SetDetailsPrint listonly
    DetailPrint "${MSG}"
  !macroend
!endif

ShowUninstDetails show

; Replaces electron-builder's running-app check, which closes only
; ${APP_EXECUTABLE_FILENAME}: the bundled app server and node runtime kept
; running from the same folder, so setup could only report that the app cannot
; be closed. This closes everything that runs from the installation folder and
; returns once it is gone. Expanded in the install section and in the
; uninstaller's init, so it uses no functions of its own.
!macro customCheckAppRunning
  InitPluginsDir
  File /oname=$PLUGINSDIR\close_arcrho_processes.ps1 "${PROJECT_DIR}\build\installer\close_arcrho_processes.ps1"
  ; A setup the app started for an update has that app's consent already; a
  ; setup run by hand still asks before closing anything.
  ${IfNot} ${isUpdated}
    nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\close_arcrho_processes.ps1" -InstallDir "$INSTDIR" -DetectOnly'
    Pop $0
    Pop $1
    ${If} $0 != 0
      MessageBox MB_OKCANCEL|MB_ICONEXCLAMATION "$(appRunning)" /SD IDOK IDOK +2
      Quit
    ${EndIf}
  ${EndIf}
  ${Do}
    DetailPrint "Closing $(^Name)..."
    nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\close_arcrho_processes.ps1" -InstallDir "$INSTDIR"'
    Pop $0
    Pop $1
    ${If} $0 == 0
      ${ExitDo}
    ${EndIf}
    ; A process Windows is still tearing down cannot be ended, even from Task
    ; Manager, but goes on its own within minutes, so wait before asking.
    DetailPrint "Waiting for Windows to finish closing $(^Name)..."
    nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\close_arcrho_processes.ps1" -InstallDir "$INSTDIR" -WaitSeconds 300'
    Pop $0
    Pop $1
    ${If} $0 == 0
      ${ExitDo}
    ${EndIf}
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "$(^Name) is still running and could not be closed:$\r$\n$\r$\n$1$\r$\nEnd it in Task Manager, or restart the computer if it cannot be ended, then click Retry." /SD IDCANCEL IDRETRY +2
    Quit
  ${Loop}
!macroend

!ifndef BUILD_UNINSTALLER
  ; A setup the app started for an update goes back into the existing
  ; installation, so the "who should this be installed for" page has nothing
  ; to ask. Expanded inside electron-builder's install-mode page function.
  !macro customInstallMode
    ${If} ${isUpdated}
      ${If} $hasPerUserInstallation == "1"
        StrCpy $isForceCurrentInstall "1"
      ${ElseIf} $hasPerMachineInstallation == "1"
        StrCpy $isForceMachineInstall "1"
      ${EndIf}
    ${EndIf}
  !macroend
!endif

!macro preInit
  SetDetailsPrint both
!macroend

!macro customInit
  SetDetailsPrint both
  ; electron-builder includes this file at the top of its generated script, ahead
  ; of both multiUser.nsh and its own !addplugindir lines, so the functions below
  ; can use neither its install-mode variables nor the StdUtils plugin. This macro
  ; is expanded inside .onInit after initMultiUser, where both are available, so
  ; decide there whether something already owns the install location.
  ; ${isUpdated} needs the StdUtils plugin, which page functions parsed at the
  ; top of the script cannot reach; they read this variable instead.
  StrCpy $ArcRhoIsUpdate "0"
  ${If} ${isUpdated}
    StrCpy $ArcRhoIsUpdate "1"
  ${EndIf}
  StrCpy $ArcRhoInstallLocationIsOwned ""
  !ifndef INSTALL_MODE_PER_ALL_USERS
    ${If} $perUserInstallationFolder != ""
      StrCpy $ArcRhoInstallLocationIsOwned "1"
    ${EndIf}
  !endif
  !ifdef INSTALL_MODE_PER_ALL_USERS_REQUIRED
    ${If} $perMachineInstallationFolder != ""
      StrCpy $ArcRhoInstallLocationIsOwned "1"
    ${EndIf}
  !endif
  ${StdUtils.GetParameter} $0 "D" ""
  ${If} $0 != ""
    StrCpy $ArcRhoInstallLocationIsOwned "1"
  ${EndIf}
  Call ArcRho_PreparePreferredInstallDirectory
  StrCpy $ArcRhoInstallExcelAddIn "1"
  Call ArcRho_DetectServerRoot
  ; Launching the data engine only makes sense on the computer that hosts the
  ; Arco Server folder; a network-drive root means the services run elsewhere.
  StrCpy $ArcRhoLaunchDataEngine "0"
  ${If} $ArcRhoServerRootIsLocal == "1"
  ${AndIf} $ArcRhoDataEngineInstalled == "1"
    StrCpy $ArcRhoLaunchDataEngine "1"
  ${EndIf}
  ${IfNot} ${Silent}
    ; Extract the observer before the InstFiles worker starts. It only reads
    ; the native bar and never executes installer script on the UI thread.
    InitPluginsDir
    File /oname=$PLUGINSDIR\ArcRhoInstallerProgress.exe "${PROJECT_DIR}\build\generated\ArcRhoInstallerProgress.exe"
  ${EndIf}
  DetailPrint "===== Installing Arco Workspace ====="
  DetailPrint "Preparing installation..."
!macroend

; This hook is inserted immediately before MUI_PAGE_INSTFILES.
!ifndef BUILD_UNINSTALLER
  !macro ArcRho_CheckServerRoot DRIVE
    ${If} $ArcRhoServerRoot == ""
    ${AndIf} ${FileExists} "${DRIVE}\Arco Server\*.*"
      StrCpy $ArcRhoServerRoot "${DRIVE}\Arco Server"
      StrCpy $ArcRhoServerRootDetected "1"
    ${EndIf}
  !macroend

  !macro ArcRho_AddDriveOption DRIVE
    ${If} ${FileExists} "${DRIVE}\*.*"
      ${NSD_CB_AddString} $ArcRhoServerDriveDropList "${DRIVE}"
      ${If} $ArcRhoServerRoot == ""
        StrCpy $ArcRhoServerRoot "${DRIVE}\Arco Server"
        ${NSD_CB_SelectString} $ArcRhoServerDriveDropList "${DRIVE}"
      ${EndIf}
    ${EndIf}
  !macroend

  !macro customWelcomePage
    Page custom ArcRho_ExcelAddInOptions_Show ArcRho_ExcelAddInOptions_Leave
  !macroend

  ; The build patcher expands this hidden page immediately before
  ; electron-builder's directory page, after install-mode selection.
  !macro customPageBeforeChangeDir
    Page custom ArcRho_InstallDirectory_Pre
  !macroend

  Function ArcRho_PreparePreferredInstallDirectory
    StrCpy $ArcRhoPreferredInstallDirectory ""

    ; Existing installations and explicit /D paths own their install location.
    ${If} $ArcRhoInstallLocationIsOwned == "1"
      Return
    ${EndIf}

    System::Call 'kernel32::GetComputerName(t.r0, *i ${NSIS_MAX_STRLEN}) i.r1'
    ${If} $1 == 0
    ${OrIf} $0 != "${ARCRHO_PREFERRED_INSTALL_COMPUTER}"
      Return
    ${EndIf}

    System::Call 'advapi32::GetUserName(t.r1, *i ${NSIS_MAX_STRLEN}) i.r2'
    ${If} $2 == 0
    ${OrIf} $1 == ""
      DetailPrint "Windows login name could not be detected; keeping the standard install location."
      Return
    ${EndIf}

    StrCpy $ArcRhoPreferredInstallDirectory "${ARCRHO_PREFERRED_INSTALL_DRIVE}\$1\${APP_FILENAME}"
    ClearErrors
    CreateDirectory "$ArcRhoPreferredInstallDirectory"
    ${If} ${Errors}
      DetailPrint "Could not create $ArcRhoPreferredInstallDirectory; keeping the standard install location."
      StrCpy $ArcRhoPreferredInstallDirectory ""
      Return
    ${EndIf}
    ${IfNot} ${FileExists} "$ArcRhoPreferredInstallDirectory\*.*"
      DetailPrint "Could not verify $ArcRhoPreferredInstallDirectory; keeping the standard install location."
      StrCpy $ArcRhoPreferredInstallDirectory ""
      Return
    ${EndIf}

    StrCpy $INSTDIR $ArcRhoPreferredInstallDirectory
    DetailPrint "Default install location: $INSTDIR"
  FunctionEnd

  Function ArcRho_InstallDirectory_Pre
    ; The mode-selection page rewrites $INSTDIR, so restore the prepared default
    ; only when this fresh install successfully created its preferred folder.
    ${If} $ArcRhoPreferredInstallDirectory != ""
      StrCpy $INSTDIR $ArcRhoPreferredInstallDirectory
    ${EndIf}
    Abort
  FunctionEnd

  Function ArcRho_DetectServerRoot
    StrCpy $ArcRhoServerRoot ""
    StrCpy $ArcRhoServerRootDetected "0"
    Call ArcRho_DetectConfiguredServerRoot
    ${If} $ArcRhoServerRoot == ""
      !insertmacro ArcRho_CheckServerRoot "C:"
      !insertmacro ArcRho_CheckServerRoot "D:"
      !insertmacro ArcRho_CheckServerRoot "E:"
      !insertmacro ArcRho_CheckServerRoot "F:"
      !insertmacro ArcRho_CheckServerRoot "G:"
      !insertmacro ArcRho_CheckServerRoot "H:"
      !insertmacro ArcRho_CheckServerRoot "I:"
      !insertmacro ArcRho_CheckServerRoot "J:"
      !insertmacro ArcRho_CheckServerRoot "K:"
      !insertmacro ArcRho_CheckServerRoot "L:"
      !insertmacro ArcRho_CheckServerRoot "M:"
      !insertmacro ArcRho_CheckServerRoot "N:"
      !insertmacro ArcRho_CheckServerRoot "O:"
      !insertmacro ArcRho_CheckServerRoot "P:"
      !insertmacro ArcRho_CheckServerRoot "Q:"
      !insertmacro ArcRho_CheckServerRoot "R:"
      !insertmacro ArcRho_CheckServerRoot "S:"
      !insertmacro ArcRho_CheckServerRoot "T:"
      !insertmacro ArcRho_CheckServerRoot "U:"
      !insertmacro ArcRho_CheckServerRoot "V:"
      !insertmacro ArcRho_CheckServerRoot "W:"
      !insertmacro ArcRho_CheckServerRoot "X:"
      !insertmacro ArcRho_CheckServerRoot "Y:"
      !insertmacro ArcRho_CheckServerRoot "Z:"
    ${EndIf}
    Call ArcRho_DetectServerRootIsLocal
    Call ArcRho_DetectDataEngineInstalled
  FunctionEnd

  Function ArcRho_DetectConfiguredServerRoot
    InitPluginsDir
    SetOutPath "$PLUGINSDIR"
    File /oname=detect_arcrho_server_root.ps1 "${PROJECT_DIR}\build\installer\detect_arcrho_server_root.ps1"
    nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\detect_arcrho_server_root.ps1"'
    Pop $0
    Pop $1
    ${If} $0 == 0
    ${AndIf} $1 != ""
      StrCpy $ArcRhoServerRoot $1
      StrCpy $ArcRhoServerRootDetected "1"
      DetailPrint "Configured Arco Server folder: $ArcRhoServerRoot"
    ${EndIf}
  FunctionEnd

  Function ArcRho_DetectServerRootIsLocal
    StrCpy $ArcRhoServerRootIsLocal "0"
    ${If} $ArcRhoServerRootDetected == "1"
      ; DRIVE_FIXED (3) means the detected root lives on this computer's own
      ; disk; mapped network drives report DRIVE_REMOTE (4).
      StrCpy $0 $ArcRhoServerRoot 3
      System::Call 'kernel32::GetDriveTypeW(w r0) i .r1'
      ${If} $1 == 3
        StrCpy $ArcRhoServerRootIsLocal "1"
      ${EndIf}
    ${EndIf}
  FunctionEnd

  Function ArcRho_DetectDataEngineInstalled
    StrCpy $ArcRhoDataEngineInstalled "0"
    ${If} $ArcRhoServerRoot != ""
      ${If} ${FileExists} "$ArcRhoServerRoot\apps\Arco Launcher\Arco Launcher.exe"
      ${OrIf} ${FileExists} "$ArcRhoServerRoot\apps\ADAS Shell\ADAS Shell.exe"
        StrCpy $ArcRhoDataEngineInstalled "1"
      ${EndIf}
    ${EndIf}
  FunctionEnd

  Function ArcRho_SetExcelAddInPath
    ${If} $ArcRhoServerRoot != ""
      StrCpy $ArcRhoExcelAddInPath "$ArcRhoServerRoot\Excel Add-ins\Arco.xlam"
    ${Else}
      StrCpy $ArcRhoExcelAddInPath ""
    ${EndIf}
  FunctionEnd

  Function ArcRho_ExcelAddInOptions_Show
    ; An update started from the app keeps the defaults this page would show
    ; pre-selected, so it has nothing to ask.
    ${If} $ArcRhoIsUpdate == "1"
      Abort
    ${EndIf}
    !insertmacro MUI_HEADER_TEXT "Setup Options" "Choose the optional Arco setup steps."

    nsDialogs::Create 1018
    Pop $0
    ${If} $0 == error
      Abort
    ${EndIf}

    ; The nsDialogs inner page is only ~140u tall, so every control below stays
    ; inside that box: intro at 0u, the server-root block at 16u-46u, the shared
    ; delivery note at 56u and the option checkboxes at 76u.
    ${NSD_CreateLabel} 0 0 100% 10u "Arco can register the Excel add-in and start data engine components."
    Pop $1

    ${If} $ArcRhoServerRootDetected == "1"
      ${NSD_CreateLabel} 0 16u 100% 10u "Arco Server folder: $ArcRhoServerRoot"
      Pop $1
      ${If} $ArcRhoServerRootIsLocal != "1"
        ${NSD_CreateLabel} 0 28u 100% 18u "This folder is on a network drive, so the data engine runs on the PC that hosts it and cannot be started from here."
        Pop $1
      ${ElseIf} $ArcRhoDataEngineInstalled != "1"
        ${NSD_CreateLabel} 0 28u 100% 18u "No server components found here. Use Arco Server Components Setup on the host PC."
        Pop $1
      ${EndIf}
    ${Else}
      ${NSD_CreateLabel} 0 16u 100% 10u "Drive for the Arco Server folder:"
      Pop $1
      ${NSD_CreateDropList} 0 28u 60u 80u ""
      Pop $ArcRhoServerDriveDropList
      StrCpy $ArcRhoServerRoot ""
      !insertmacro ArcRho_AddDriveOption "C:"
      !insertmacro ArcRho_AddDriveOption "D:"
      !insertmacro ArcRho_AddDriveOption "E:"
      !insertmacro ArcRho_AddDriveOption "F:"
      !insertmacro ArcRho_AddDriveOption "G:"
      !insertmacro ArcRho_AddDriveOption "H:"
      !insertmacro ArcRho_AddDriveOption "I:"
      !insertmacro ArcRho_AddDriveOption "J:"
      !insertmacro ArcRho_AddDriveOption "K:"
      !insertmacro ArcRho_AddDriveOption "L:"
      !insertmacro ArcRho_AddDriveOption "M:"
      !insertmacro ArcRho_AddDriveOption "N:"
      !insertmacro ArcRho_AddDriveOption "O:"
      !insertmacro ArcRho_AddDriveOption "P:"
      !insertmacro ArcRho_AddDriveOption "Q:"
      !insertmacro ArcRho_AddDriveOption "R:"
      !insertmacro ArcRho_AddDriveOption "S:"
      !insertmacro ArcRho_AddDriveOption "T:"
      !insertmacro ArcRho_AddDriveOption "U:"
      !insertmacro ArcRho_AddDriveOption "V:"
      !insertmacro ArcRho_AddDriveOption "W:"
      !insertmacro ArcRho_AddDriveOption "X:"
      !insertmacro ArcRho_AddDriveOption "Y:"
      !insertmacro ArcRho_AddDriveOption "Z:"
      ${NSD_CreateLabel} 0 44u 100% 10u "Add-in path: <drive>\Arco Server\Excel Add-ins\Arco.xlam"
      Pop $1
    ${EndIf}

    ${NSD_CreateLabel} 0 56u 100% 18u "Server binaries are delivered separately and are never installed or removed by this setup."
    Pop $1

    ${NSD_CreateCheckbox} 0 76u 48% 20u "Install Arco Excel add-in"
    Pop $ArcRhoInstallExcelAddInCheckbox
    ${If} $ArcRhoInstallExcelAddIn == "1"
      ${NSD_Check} $ArcRhoInstallExcelAddInCheckbox
    ${EndIf}

    ${NSD_CreateCheckbox} 50% 76u 50% 20u "Launch Arco data engine at login"
    Pop $ArcRhoLaunchDataEngineCheckbox
    ${If} $ArcRhoServerRootIsLocal == "1"
    ${AndIf} $ArcRhoDataEngineInstalled == "1"
      ${If} $ArcRhoLaunchDataEngine == "1"
        ${NSD_Check} $ArcRhoLaunchDataEngineCheckbox
      ${EndIf}
    ${Else}
      EnableWindow $ArcRhoLaunchDataEngineCheckbox 0
    ${EndIf}

    nsDialogs::Show
  FunctionEnd

  Function ArcRho_ExcelAddInOptions_Leave
    ${NSD_GetState} $ArcRhoInstallExcelAddInCheckbox $0
    ${If} $0 == ${BST_CHECKED}
      StrCpy $ArcRhoInstallExcelAddIn "1"
    ${Else}
      StrCpy $ArcRhoInstallExcelAddIn "0"
    ${EndIf}

    StrCpy $ArcRhoLaunchDataEngine "0"
    ${If} $ArcRhoServerRootIsLocal == "1"
    ${AndIf} $ArcRhoDataEngineInstalled == "1"
      ${NSD_GetState} $ArcRhoLaunchDataEngineCheckbox $0
      ${If} $0 == ${BST_CHECKED}
        StrCpy $ArcRhoLaunchDataEngine "1"
      ${EndIf}
    ${EndIf}

    ${If} $ArcRhoServerRootDetected != "1"
      ${NSD_GetText} $ArcRhoServerDriveDropList $0
      ${If} $0 != ""
        StrCpy $ArcRhoServerRoot "$0\Arco Server"
      ${EndIf}
    ${EndIf}
  FunctionEnd

  !macro customPageAfterChangeDir
    !define MUI_PAGE_CUSTOMFUNCTION_SHOW ArcRho_InstFiles_Show
  !macroend

  Function ArcRho_InstFiles_Show
    !insertmacro MUI_HEADER_TEXT "" "$(MUI_TEXT_INSTALLING_SUBTITLE)"
    !insertmacro ArcRho_PrintInstallDetail "Installer progress monitoring started."
    !insertmacro ArcRho_PrintInstallDetail "Preparing destination and installing Arco Workspace files..."
    FindWindow $0 "#32770" "" $HWNDPARENT
    GetDlgItem $1 $0 1004
    GetDlgItem $2 $0 1006
    ; Standard NSIS InstFiles control IDs: details list and Show details button.
    GetDlgItem $4 $0 1016
    GetDlgItem $5 $0 1027
    ${If} $1 == 0
    ${OrIf} $2 == 0
    ${OrIf} $4 == 0
    ${OrIf} $5 == 0
    ${OrIf} $0 == 0
      Return
    ${EndIf}

    SendMessage $2 0x000C 0 "STR:0% complete - Estimating time left..."
    System::Call "kernel32::GetCurrentProcessId() i.r3"
    ClearErrors
    Exec '"$PLUGINSDIR\ArcRhoInstallerProgress.exe" "$HWNDPARENT" "$0" "$1" "$2" "$4" "$5" "$3"'
    ${If} ${Errors}
      !insertmacro ArcRho_PrintInstallDetail "Progress text observer could not be started."
    ${EndIf}
  FunctionEnd

  Function ArcRho_InstFiles_CompleteProgressText
    FindWindow $0 "#32770" "" $HWNDPARENT
    GetDlgItem $1 $0 1006
    ${If} $0 == 0
    ${OrIf} $1 == 0
      Return
    ${EndIf}
    SendMessage $1 0x000C 0 "STR:100% complete - Installation complete."
  FunctionEnd

  !macro ArcRho_PrintCoreFileDetails
    !insertmacro ArcRho_PrintInstallDetail "Core application files extracted."
    !insertmacro ArcRho_PrintInstallDetail "Writing installer metadata..."
  !macroend

  ; electron-builder runs the matching hook after the embedded package is extracted.
  !macro customFiles_x64
    !insertmacro ArcRho_PrintCoreFileDetails
  !macroend

  !macro customFiles_ia32
    !insertmacro ArcRho_PrintCoreFileDetails
  !macroend

  !macro customFiles_arm64
    !insertmacro ArcRho_PrintCoreFileDetails
  !macroend

  ; Optional no-op hook used only to surface an action detail before final completion.
  !macro registerFileAssociations
    !insertmacro ArcRho_PrintInstallDetail "Creating shortcuts and registry entries..."
  !macroend

  Function ArcRho_InstallExcelAddIn
    InitPluginsDir
    File /oname=$PLUGINSDIR\install_arcrho_excel_addin.ps1 "${PROJECT_DIR}\build\installer\install_arcrho_excel_addin.ps1"
    Call ArcRho_SetExcelAddInPath

    ${If} $ArcRhoExcelAddInPath == ""
      !insertmacro ArcRho_PrintInstallDetail "Arco Excel add-in installation skipped because no Arco Server root was selected or detected."
      ${IfNot} ${Silent}
        MessageBox MB_ICONEXCLAMATION|MB_OK "Arco was installed, but the Excel add-in could not be installed automatically because no Arco Server root was selected or detected."
      ${EndIf}
      Return
    ${EndIf}

    !insertmacro ArcRho_PrintInstallDetail "Installing Arco Excel add-in..."
    !insertmacro ArcRho_PrintInstallDetail "Excel add-in path: $ArcRhoExcelAddInPath"
    nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -STA -File "$PLUGINSDIR\install_arcrho_excel_addin.ps1" -AddInPath "$ArcRhoExcelAddInPath"'
    Pop $0
    Pop $1

    ${If} $1 != ""
      !insertmacro ArcRho_PrintInstallDetail "$1"
    ${EndIf}

    ${If} $0 == 0
      !insertmacro ArcRho_PrintInstallDetail "Arco Excel add-in installed."
    ${Else}
      !insertmacro ArcRho_PrintInstallDetail "Arco Excel add-in installation failed with exit code $0."
      ${IfNot} ${Silent}
        MessageBox MB_ICONEXCLAMATION|MB_OK "Arco was installed, but the Excel add-in could not be registered automatically.$\r$\n$\r$\nTo add it manually, open Excel and go to File > Options > Add-ins, set Manage to Excel Add-ins, click Go, then Browse to:$\r$\n$ArcRhoExcelAddInPath$\r$\nIf Excel offers to copy the add-in to your local add-ins folder, choose No.$\r$\n$\r$\nThis usually means Excel is not allowed to run the add-in installer from that folder. In Excel, go to File > Options > Trust Center > Trust Center Settings > Trusted Locations, tick $\"Allow Trusted Locations on my network$\", then click Add new location and add:$\r$\n$ArcRhoServerRoot\Excel Add-ins$\r$\nwith $\"Subfolders of this location are also trusted$\" ticked."
      ${EndIf}
    ${EndIf}
  FunctionEnd

  Function ArcRho_LaunchDataEngineComponents
    ; Arco Launcher owns the startup registration and service launch: it
    ; recreates its own shortcut in the user's Startup folder and then starts
    ; the orchestrator and bridge, so the installer only needs to run it.
    StrCpy $0 "$ArcRhoServerRoot\apps\Arco Launcher\Arco Launcher.exe"
    ${IfNot} ${FileExists} "$0"
      StrCpy $0 "$ArcRhoServerRoot\apps\ADAS Shell\ADAS Shell.exe"
    ${EndIf}

    ${IfNot} ${FileExists} "$0"
      !insertmacro ArcRho_PrintInstallDetail "Arco data engine launch skipped because no Arco Launcher was found under $ArcRhoServerRoot\apps."
      ${IfNot} ${Silent}
        MessageBox MB_ICONEXCLAMATION|MB_OK "Arco was installed, but no server components were found under $ArcRhoServerRoot\apps. Run Arco Server Components Setup on the PC that locally hosts this workspace."
      ${EndIf}
      Return
    ${EndIf}

    !insertmacro ArcRho_PrintInstallDetail "Starting Arco data engine components..."
    !insertmacro ArcRho_PrintInstallDetail "Arco Launcher: $0"
    ClearErrors
    Exec '"$0"'
    ${If} ${Errors}
      !insertmacro ArcRho_PrintInstallDetail "Arco Launcher could not be started."
      ${IfNot} ${Silent}
        MessageBox MB_ICONEXCLAMATION|MB_OK "Arco was installed, but the data engine components could not be started. You can start them manually from $0."
      ${EndIf}
    ${Else}
      !insertmacro ArcRho_PrintInstallDetail "Arco Launcher started; it registers itself in the Startup folder and launches the data engine services."
    ${EndIf}
  FunctionEnd

  !macro customInstall
    ${If} $ArcRhoInstallExcelAddIn == "1"
      Call ArcRho_InstallExcelAddIn
    ${Else}
      !insertmacro ArcRho_PrintInstallDetail "Arco Excel add-in installation skipped."
    ${EndIf}
    ${If} $ArcRhoLaunchDataEngine == "1"
      Call ArcRho_LaunchDataEngineComponents
    ${Else}
      !insertmacro ArcRho_PrintInstallDetail "Arco data engine launch skipped."
    ${EndIf}
    Call ArcRho_InstFiles_CompleteProgressText
    !insertmacro ArcRho_PrintInstallDetail "Installation complete."
  !macroend

  ; electron-builder's finish page, with one difference: a setup the app started
  ; for an update relaunches the app and closes on its own instead of waiting
  ; for a click on Finish. Expanded at the page-definition point, after
  ; $launchLink from common.nsh exists.
  ;
  ; The relaunch repeats what common.nsh's StartApp macro does instead of
  ; expanding it. That macro declares a variable of its own and the install
  ; section already expands it once, so a second expansion ends the build with
  ; 'variable "startAppArgs" already declared'.
  !macro customFinishPage
    Function ArcRho_StartApp
      StrCpy $ArcRhoStartAppArgs ""
      ${If} ${isUpdated}
        StrCpy $ArcRhoStartAppArgs "--updated"
      ${EndIf}
      ${StdUtils.ExecShellAsUser} $0 "$launchLink" "open" "$ArcRhoStartAppArgs"
    FunctionEnd

    Function ArcRho_FinishPage_Pre
      ${If} ${isUpdated}
        Call ArcRho_StartApp
        Abort
      ${EndIf}
    FunctionEnd

    !define MUI_PAGE_CUSTOMFUNCTION_PRE ArcRho_FinishPage_Pre
    !define MUI_FINISHPAGE_RUN
    !define MUI_FINISHPAGE_RUN_FUNCTION "ArcRho_StartApp"
    !insertmacro MUI_PAGE_FINISH
  !macroend
!endif

!macro customUnInstall
  SetDetailsPrint both
  SetDetailsView show
  DetailPrint "===== Uninstalling Arco Workspace ====="
!macroend
