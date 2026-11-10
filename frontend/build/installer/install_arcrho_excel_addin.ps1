param(
    [string]$AddInPath = "E:\Arco Server\Excel Add-ins\Arco.xlam",
    [string]$UserGuidePath = ""
)

$ErrorActionPreference = "Stop"

function Release-ComObject($Object) {
    if ($null -ne $Object -and [System.Runtime.InteropServices.Marshal]::IsComObject($Object)) {
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($Object)
    }
}

if (-not (Test-Path -LiteralPath $AddInPath -PathType Leaf)) {
    throw "Arco Excel add-in was not found: $AddInPath"
}

$resolvedAddInPath = [System.IO.Path]::GetFullPath($AddInPath)
if ([string]::IsNullOrWhiteSpace($UserGuidePath)) {
    $UserGuidePath = Join-Path ([System.IO.Path]::GetDirectoryName($resolvedAddInPath)) "User Guide.xlsm"
}

if (-not (Test-Path -LiteralPath $UserGuidePath -PathType Leaf)) {
    throw "Arco Excel add-in installer workbook was not found: $UserGuidePath"
}

$resolvedUserGuidePath = [System.IO.Path]::GetFullPath($UserGuidePath)
$excel = $null
$workbooks = $null
$userGuideWorkbook = $null
$addIns = $null
$candidate = $null
$previousDisplayAlerts = $null
$previousEnableEvents = $null
$previousAutomationSecurity = $null

try {
    # Always use an isolated Excel instance. Attaching to an existing or stale
    # instance can make AddIns.Add fail and can interfere with a user's workbooks.
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false

    $previousDisplayAlerts = $excel.DisplayAlerts
    $previousEnableEvents = $excel.EnableEvents
    $previousAutomationSecurity = $excel.AutomationSecurity
    $excel.DisplayAlerts = $false
    $excel.EnableEvents = $false

    # Respect Excel's configured Trust Center policy. The installer does not
    # lower macro security or attempt to bypass a blocked workbook.
    $msoAutomationSecurityByUI = 2
    $excel.AutomationSecurity = $msoAutomationSecurityByUI

    $workbooks = $excel.Workbooks
    $userGuideWorkbook = $workbooks.Open($resolvedUserGuidePath, 0, $true)
    Release-ComObject $workbooks
    $workbooks = $null

    $escapedWorkbookName = $userGuideWorkbook.Name.Replace("'", "''")
    $macroName = "'$escapedWorkbookName'!InstallNetworkXLAM"
    Write-Host "Running trusted Excel add-in installer macro: $macroName"

    try {
        $excel.Run($macroName, $resolvedAddInPath) | Out-Null
    }
    catch {
        throw "Excel could not run the Arco add-in installer macro from '$resolvedUserGuidePath'. Ensure the workbook is trusted and its macros are permitted. $($_.Exception.Message)"
    }

    $addIns = $excel.AddIns
    # The add-in was ArcRho.xlam until 2026-11-09; its registration points at
    # a file that no longer exists, so Excel would report it on every start.
    for ($index = 1; $index -le $addIns.Count; $index++) {
        $candidate = $null
        try {
            $candidate = $addIns.Item($index)
            if ([string]::Equals([string]$candidate.Name, "ArcRho.xlam", [System.StringComparison]::OrdinalIgnoreCase) -and $candidate.Installed) {
                $candidate.Installed = $false
                Write-Host "Turned off the old ArcRho.xlam add-in registration."
            }
        }
        catch {
            Write-Warning "Could not turn off the old ArcRho.xlam add-in registration: $($_.Exception.Message)"
        }
        finally {
            Release-ComObject $candidate
            $candidate = $null
        }
    }

    $installedAddInPath = $null
    $registeredButDisabledPath = $null
    for ($index = 1; $index -le $addIns.Count; $index++) {
        $candidate = $null
        try {
            $candidate = $addIns.Item($index)
            $candidatePath = [System.IO.Path]::GetFullPath([string]$candidate.FullName)
            if ([string]::Equals($candidatePath, $resolvedAddInPath, [System.StringComparison]::OrdinalIgnoreCase)) {
                if ($candidate.Installed) {
                    $installedAddInPath = $candidatePath
                }
                else {
                    $registeredButDisabledPath = $candidatePath
                }
                break
            }
        }
        catch {
            Write-Warning "Skipped an Excel add-in entry that could not be inspected: $($_.Exception.Message)"
        }
        finally {
            Release-ComObject $candidate
            $candidate = $null
        }
    }

    if ([string]::IsNullOrWhiteSpace($installedAddInPath)) {
        if (-not [string]::IsNullOrWhiteSpace($registeredButDisabledPath)) {
            throw "Excel registered the Arco add-in but did not mark it as installed: $registeredButDisabledPath"
        }
        throw "The Arco installer macro completed, but Excel did not report the add-in as installed: $resolvedAddInPath"
    }

    Write-Host "Installed Arco Excel add-in through Excel VBA: $installedAddInPath"
}
finally {
    Release-ComObject $candidate
    Release-ComObject $addIns

    if ($null -ne $userGuideWorkbook) {
        try {
            $userGuideWorkbook.Close($false)
        }
        catch {
            Write-Warning "Could not close the Arco add-in installer workbook: $($_.Exception.Message)"
        }
    }
    Release-ComObject $userGuideWorkbook
    Release-ComObject $workbooks

    if ($null -ne $excel) {
        if ($null -ne $previousDisplayAlerts) {
            try {
                $excel.DisplayAlerts = $previousDisplayAlerts
            }
            catch {
                Write-Warning "Could not restore Excel DisplayAlerts: $($_.Exception.Message)"
            }
        }
        if ($null -ne $previousEnableEvents) {
            try {
                $excel.EnableEvents = $previousEnableEvents
            }
            catch {
                Write-Warning "Could not restore Excel EnableEvents: $($_.Exception.Message)"
            }
        }
        if ($null -ne $previousAutomationSecurity) {
            try {
                $excel.AutomationSecurity = $previousAutomationSecurity
            }
            catch {
                Write-Warning "Could not restore Excel AutomationSecurity: $($_.Exception.Message)"
            }
        }

        try {
            $excel.Quit()
        }
        catch {
            Write-Warning "Could not close the installer-created Excel instance: $($_.Exception.Message)"
        }
    }

    Release-ComObject $excel
    [System.GC]::Collect()
    [System.GC]::WaitForPendingFinalizers()
}
