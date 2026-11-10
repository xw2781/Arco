# Stop or start the deployed ArcRho services, and the build listener, on the
# Server PC.
#
# Two jobs, both of which exist because a deploy and a workspace conversion
# fight with whatever is running:
#
# 1. The persisted JSON conversion (tools/migrate_persisted_json_v4.py)
#    rewrites files the Engine, Bridge and Gateway also write, so they have to
#    be down while it runs, and must not come back up until a build that reads
#    the new format is deployed.
#
# 2. The build listener resets the clone it was started from -- its repository
#    is derived from where its own code lives, not from a setting -- so it must
#    be started from a clone nobody edits. Started from a working clone it
#    reverts uncommitted edits and deletes untracked files on every deploy.
#
# This is narrow enough to grant on its own rather than allowing process
# control in general.
#
#   .\tools\arcrho_service_control.ps1 -Action status
#   .\tools\arcrho_service_control.ps1 -Action stop
#   .\tools\arcrho_service_control.ps1 -Action start
#   .\tools\arcrho_service_control.ps1 -Action listener-stop
#   .\tools\arcrho_service_control.ps1 -Action listener-start
#   .\tools\arcrho_service_control.ps1 -Action clear-stale-heartbeats

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('status', 'stop', 'start', 'listener-stop', 'listener-start', 'clear-stale-heartbeats')]
    [string]$Action,

    [string]$Root = 'E:\Arco Server\apps',

    # The clone the build listener owns. Never a clone anyone edits.
    [string]$ListenerRepo = 'E:\XWSpace\Repos\ArcRho-buildbot',

    [string]$ServerRoot = 'E:\Arco Server',

    # A heartbeat older than this, with no process behind it, is an orphan
    # left by a forced stop. The Engine writes one every few seconds.
    [int]$StaleSeconds = 120
)

$ErrorActionPreference = 'Stop'

# Every action here reads or ends a *local* process, and the workspace drive is
# shared, so the same paths resolve from the Client PC while Get-Process sees
# none of the server's processes. Run from there, `status` would report every
# component stopped while it is serving, and `clear-stale-heartbeats` would
# delete the heartbeats of live components. Refuse rather than answer wrongly.
# The test is the drive itself -- local disk on the Server PC, network drive
# through the share -- so no machine name is hardcoded.
$serverDrive = (Split-Path -Qualifier $ServerRoot)
$driveInfo = Get-CimInstance Win32_LogicalDisk -Filter ("DeviceID='{0}'" -f $serverDrive) -ErrorAction SilentlyContinue
if (-not $driveInfo) {
    Write-Error ("{0} is not available from {1}." -f $serverDrive, $env:COMPUTERNAME)
    exit 2
}
if ($driveInfo.DriveType -ne 3) {
    Write-Error ("{0} is a network drive on {1}, so this machine is not the Server PC. Every action here acts on local processes; run it on the machine that holds the workspace." -f $serverDrive, $env:COMPUTERNAME)
    exit 2
}

# Stop order is the reverse of start order: the Orchestrator supervises the
# rest, so it goes down first and comes up last.
$Components = @(
    @{ Name = 'ArcRho Orchestrator'; Exe = 'ArcRho Orchestrator\ArcRho Orchestrator.exe'; Instance = 'arcrho_orchestrator' },
    @{ Name = 'ArcRho Gateway';      Exe = 'ArcRho Gateway\ArcRho Gateway.exe';           Instance = 'arcrho_gateway' },
    @{ Name = 'ArcRho Bridge';       Exe = 'ArcRho Bridge\ArcRho Bridge.exe';             Instance = 'arcrho_bridge' },
    @{ Name = 'ArcRho Engine';       Exe = 'ArcRho Engine\ArcRho Engine.exe';             Instance = 'arcrho_engine' }
)

$ListenerScript = 'arcrho_build_manager.py'

function Get-Running($name) {
    return @(Get-Process -Name $name -ErrorAction SilentlyContinue)
}

function Get-ListenerProcesses {
    # Matched on the command line, not the process name: the listener runs
    # under a bare pythonw, and killing every pythonw would take unrelated
    # programs with it.
    return @(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='pyw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -like "*$ListenerScript*" })
}

function Show-Status {
    foreach ($component in $Components) {
        $running = Get-Running $component.Name
        if ($running.Count -gt 0) {
            $ids = ($running | ForEach-Object { $_.Id }) -join ', '
            Write-Output ("{0,-22} running  (pid {1})" -f $component.Name, $ids)
        }
        else {
            Write-Output ("{0,-22} stopped" -f $component.Name)
        }
    }
    $listener = Get-ListenerProcesses
    if ($listener.Count -gt 0) {
        $ids = ($listener | ForEach-Object { $_.ProcessId }) -join ', '
        Write-Output ("{0,-22} running  (pid {1})" -f 'Build listener', $ids)
    }
    else {
        Write-Output ("{0,-22} stopped" -f 'Build listener')
    }
}

function Clear-StaleHeartbeats {
    # A forced stop leaves the heartbeat file behind, and the Engine deploy
    # waits on those files to decide the old Engine is gone -- so it waits for
    # something that will never happen and aborts. Only files with no live
    # process and no recent write are removed.
    $removed = 0
    foreach ($component in $Components) {
        if ((Get-Running $component.Name).Count -gt 0) {
            Write-Output ("{0,-22} still running -- heartbeats left alone" -f $component.Name)
            continue
        }
        $folder = Join-Path $ServerRoot ("runtime\instances\" + $component.Instance)
        if (-not (Test-Path $folder)) { continue }
        $cutoff = (Get-Date).AddSeconds(-$StaleSeconds)
        $stale = @(Get-ChildItem -Path $folder -Filter '*.json' -File -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTime -lt $cutoff })
        foreach ($file in $stale) {
            Remove-Item -LiteralPath $file.FullName -Force -Confirm:$false
            $removed++
        }
        if ($stale.Count -gt 0) {
            Write-Output ("{0,-22} removed {1} orphaned heartbeat(s)" -f $component.Name, $stale.Count)
        }
    }
    if ($removed -eq 0) { Write-Output 'No orphaned heartbeats found.' }
}

switch ($Action) {
    'status' {
        Show-Status
    }

    'stop' {
        foreach ($component in $Components) {
            $running = Get-Running $component.Name
            if ($running.Count -eq 0) {
                Write-Output ("{0,-22} already stopped" -f $component.Name)
                continue
            }
            foreach ($process in $running) {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            }
            Write-Output ("{0,-22} stopped {1} process(es)" -f $component.Name, $running.Count)
        }
        Start-Sleep -Seconds 3
        Write-Output ''
        Write-Output '--- after stop ---'
        Show-Status
    }

    'start' {
        # Only the Orchestrator is launched -- it brings up the components it
        # supervises itself.
        $orchestrator = $Components | Where-Object { $_.Name -eq 'ArcRho Orchestrator' }
        $path = Join-Path $Root $orchestrator.Exe
        if (-not (Test-Path $path)) {
            Write-Error ("Not found: {0}" -f $path)
            exit 1
        }
        if ((Get-Running $orchestrator.Name).Count -gt 0) {
            Write-Output 'ArcRho Orchestrator is already running.'
        }
        else {
            Start-Process -FilePath $path | Out-Null
            Write-Output ("Started {0}" -f $path)
        }
        Start-Sleep -Seconds 5
        Write-Output ''
        Write-Output '--- after start ---'
        Show-Status
    }

    'listener-stop' {
        $listener = Get-ListenerProcesses
        if ($listener.Count -eq 0) {
            Write-Output 'Build listener is not running.'
        }
        else {
            foreach ($process in $listener) {
                Write-Output ("stopping build listener pid {0}  ({1})" -f $process.ProcessId, $process.CommandLine)
                Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
            }
            Start-Sleep -Seconds 2
        }
        Write-Output ''
        Show-Status
    }

    'listener-start' {
        $launcher = Join-Path $ListenerRepo 'server-components\build_manager.bat'
        if (-not (Test-Path $launcher)) {
            Write-Error ("Not found: {0}" -f $launcher)
            exit 1
        }
        if ((Get-ListenerProcesses).Count -gt 0) {
            Write-Output 'A build listener is already running. Stop it first.'
            exit 1
        }
        Start-Process -FilePath $launcher -WorkingDirectory (Join-Path $ListenerRepo 'server-components') | Out-Null
        Write-Output ("Started the build listener from {0}" -f $ListenerRepo)
        Start-Sleep -Seconds 6
        Write-Output ''
        Show-Status
    }

    'clear-stale-heartbeats' {
        Clear-StaleHeartbeats
    }
}
