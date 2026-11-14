<#
.SYNOPSIS
    Shows an on-screen presence indicator while an agent drives the mouse and keyboard, and
    moves the agent's own pointer.

.DESCRIPTION
    An agent calls `start` before it touches the screen, `action` before each step, and
    `stop` when it is finished. A hidden helper process draws a soft glow along the screen
    edges, the agent's own pointer, and an always-on-top panel naming the agent and its
    current action.

    The agent's pointer is separate from the real one. `move`, `click`, and `drag` glide it
    to the target; for a click the real pointer jumps there only for the instant of the
    click and then returns to where the person left it. Coordinates are real screen pixels,
    the same pixels `screenshot` saves.

    `screenshot` and `windows` let an agent see the screen: a PNG of the screen, a region, or
    one window, and the list of visible windows with their positions, front to back.

    Everything except the panel's Release button is click-through, so the overlay cannot
    intercept a click meant for ResQ or ArcRho.

.EXAMPLE
    .\agent_screen_control.ps1 windows -Window 'ResQ'
    .\agent_screen_control.ps1 screenshot -Window 'ResQ' -Out temp\resq.png
    .\agent_screen_control.ps1 start -Agent 'Claude Opus 5' -Action 'Opening the ResQ project list'
    .\agent_screen_control.ps1 click -X 812 -Y 440 -Window 'ResQ' -Action 'Clicking Open Project'
    .\agent_screen_control.ps1 click -X 812 -Y 520 -Button Double
    .\agent_screen_control.ps1 drag -X 300 -Y 200 -ToX 600 -ToY 200
    .\agent_screen_control.ps1 stop

.EXAMPLE
    .\agent_screen_control.ps1 demo
    Moves the agent's pointer around the screen and taps without clicking anything.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'action', 'move', 'click', 'drag', 'stop', 'status', 'screenshot',
        'windows', 'demo', 'overlay')]
    [string]$Command = 'status',

    [string]$Action = '',
    [string]$Agent = 'Agent',
    [string]$Color = '#FF9A1F',
    [ValidateSet('TopCenter', 'TopRight', 'BottomCenter', 'BottomRight')]
    [string]$Position = 'TopCenter',
    [int]$X = [int]::MinValue,
    [int]$Y = [int]::MinValue,
    [int]$ToX = [int]::MinValue,
    [int]$ToY = [int]::MinValue,
    [ValidateSet('Left', 'Right', 'Double')]
    [string]$Button = 'Left',
    [string]$Window = '',
    [int]$TimeoutSeconds = 15,
    [string]$Out = '',
    [int]$Width = 0,
    [int]$Height = 0,
    [double]$Zoom = 1.0,
    [int]$Thickness = 0,
    [int]$IdleExitMinutes = 20,
    [switch]$NoCursor,
    [switch]$NoEdges
)

$ErrorActionPreference = 'Stop'

$stateDir = Join-Path $env:APPDATA 'Arco\agent_screen_control'
$statePath = Join-Path $stateDir 'state.json'
$ackPath = Join-Path $stateDir 'cursor_ack.json'
$pidPath = Join-Path $stateDir 'overlay.pid'
$logPath = Join-Path $stateDir 'overlay.log'

# Compiles the overlay source once per process; screenshot, windows, demo, and the overlay share it.
function Import-ScreenControl {
    if (-not ('ArcRho.ScreenControl.Native' -as [type])) {
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
        $source = Get-Content -Path (Join-Path $PSScriptRoot 'AgentScreenControl.cs') -Raw
        Add-Type -TypeDefinition $source -Language CSharp `
            -ReferencedAssemblies 'System.Windows.Forms', 'System.Drawing'
    }
    [ArcRho.ScreenControl.Native]::UseRealPixels()
}

function Ensure-StateDir {
    if (-not (Test-Path $stateDir)) { New-Item -ItemType Directory -Path $stateDir -Force | Out-Null }
}

function Read-JsonFile([string]$path) {
    if (-not (Test-Path $path)) { return $null }
    try { return Get-Content -Path $path -Raw -ErrorAction Stop | ConvertFrom-Json }
    catch { return $null }
}

function Read-State { return Read-JsonFile $statePath }

function Write-State($state) {
    Ensure-StateDir
    $json = $state | ConvertTo-Json
    # A partial read by the overlay is harmless, but a torn file is not: write then move.
    $tmp = "$statePath.tmp"
    Set-Content -Path $tmp -Value $json -Encoding UTF8
    Move-Item -Path $tmp -Destination $statePath -Force
}

function Set-Field($state, [string]$name, $value) {
    $state | Add-Member -NotePropertyName $name -NotePropertyValue $value -Force
}

function Get-OverlayProcess {
    if (-not (Test-Path $pidPath)) { return $null }
    $raw = (Get-Content -Path $pidPath -Raw).Trim()
    $overlayPid = 0
    if (-not [int]::TryParse($raw, [ref]$overlayPid)) { return $null }
    try { $proc = Get-Process -Id $overlayPid -ErrorAction Stop } catch { return $null }
    if ($proc.ProcessName -notmatch 'powershell') { return $null }
    return $proc
}

function Start-Overlay {
    if (Get-OverlayProcess) { return $true }
    Ensure-StateDir
    $launchArgs = @(
        '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass',
        '-File', ('"{0}"' -f $PSCommandPath), 'overlay',
        '-IdleExitMinutes', $IdleExitMinutes
    )
    $proc = Start-Process -FilePath 'powershell.exe' -ArgumentList $launchArgs `
        -WindowStyle Hidden -PassThru
    Set-Content -Path $pidPath -Value $proc.Id -Encoding ASCII
    # Add-Type compiles the overlay on first run; give it a moment, then confirm it lived.
    Start-Sleep -Milliseconds 2500
    if ($proc.HasExited) {
        Remove-Item -Path $pidPath -Force -ErrorAction SilentlyContinue
        Write-Warning "The overlay process exited immediately. Run it in the foreground to see why:"
        Write-Warning "  powershell -NoProfile -STA -File `"$PSCommandPath`" overlay"
        return $false
    }
    return $true
}

function Stop-Overlay {
    $state = Read-State
    if ($state) {
        $state.active = $false
        # The request has been honoured, so it must not colour the next session's status.
        $state.release_requested = $false
        $state.heartbeat = Now-Iso
        Write-State $state
    }
    $proc = Get-OverlayProcess
    if ($proc) {
        if (-not $proc.WaitForExit(4000)) { $proc | Stop-Process -Force -ErrorAction SilentlyContinue }
    }
    Remove-Item -Path $pidPath -Force -ErrorAction SilentlyContinue
}

function Now-Iso { return (Get-Date).ToString('o') }

function New-State {
    return [ordered]@{
        active            = $true
        agent             = $Agent
        action            = $Action
        started           = Now-Iso
        heartbeat         = Now-Iso
        release_requested = $false
        color             = $Color
        thickness         = $Thickness
        show_cursor       = (-not $NoCursor)
        show_edges        = (-not $NoEdges)
        panel_position    = $Position
        cursor_seq        = 0
        cursor_action     = ''
        cursor_x          = 0
        cursor_y          = 0
        cursor_to_x       = 0
        cursor_to_y       = 0
        cursor_window     = ''
        cursor_issued     = ''
    }
}

function Result([int]$code, [string]$message) {
    return [pscustomobject]@{ Code = $code; Message = $message }
}

<#
    Hands one pointer command to the overlay and waits for it to finish.
    Code 0 = done (Message names the window hit), 2 = not started, 3 = release requested,
    4 = the overlay refused or failed (Message says why).
#>
function Invoke-Pointer([string]$kind, [int]$px, [int]$py, [int]$qx, [int]$qy, [string]$say) {
    $state = Read-State
    if (-not $state -or -not $state.active) { return Result 2 "Not started. Run 'start' first." }
    if ($state.release_requested) {
        return Result 3 'Release was requested from the overlay panel. Stop driving the screen.'
    }
    if (-not (Get-OverlayProcess)) {
        if (-not (Start-Overlay)) { return Result 2 'The overlay is not running and could not be started.' }
        $state = Read-State
    }

    $seq = 1 + [int]$state.cursor_seq
    Set-Field $state 'cursor_seq' $seq
    Set-Field $state 'cursor_action' $kind
    Set-Field $state 'cursor_x' $px
    Set-Field $state 'cursor_y' $py
    Set-Field $state 'cursor_to_x' $qx
    Set-Field $state 'cursor_to_y' $qy
    Set-Field $state 'cursor_window' $Window
    Set-Field $state 'cursor_issued' (Now-Iso)
    Set-Field $state 'heartbeat' (Now-Iso)
    if ($say) { Set-Field $state 'action' $say }
    Write-State $state

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $ack = Read-JsonFile $ackPath
        if ($ack -and [int]$ack.seq -eq $seq) {
            if ($ack.ok) { return Result 0 $ack.window }
            if ($ack.released) { return Result 3 $ack.message }
            return Result 4 $ack.message
        }
        Start-Sleep -Milliseconds 40
    }
    return Result 4 ("The overlay did not confirm the $kind within $TimeoutSeconds seconds. It may " +
        'still have happened, so take a screenshot before trying again; overlay.log beside the state ' +
        'file shows how far it got.')
}

switch ($Command) {

    'start' {
        Write-State (New-State)
        # The log traces one control session only, so it never accumulates.
        Remove-Item -Path $ackPath, $logPath -Force -ErrorAction SilentlyContinue
        if (Start-Overlay) { Write-Output "agent screen control: on ($Agent)" }
        break
    }

    'action' {
        $state = Read-State
        if (-not $state -or -not $state.active) {
            Write-Warning "Not started. Run 'start' first."
            break
        }
        $state.action = $Action
        $state.heartbeat = Now-Iso
        Write-State $state
        if (-not (Get-OverlayProcess)) { [void](Start-Overlay) }
        if ($state.release_requested) {
            Write-Warning "Release was requested from the overlay panel. Stop driving the screen."
            exit 3
        }
        exit 0
    }

    { $_ -in 'move', 'click', 'drag' } {
        if ($X -eq [int]::MinValue -or $Y -eq [int]::MinValue) {
            Write-Warning '-X and -Y are required, in physical screen pixels.'
            exit 2
        }
        $qx = 0; $qy = 0
        if ($Command -eq 'drag') {
            if ($ToX -eq [int]::MinValue -or $ToY -eq [int]::MinValue) {
                Write-Warning 'drag needs -ToX and -ToY as well.'
                exit 2
            }
            $qx = $ToX; $qy = $ToY
        }
        $kind = $Command
        if ($Command -eq 'click') {
            $kind = @{ Left = 'click'; Right = 'right'; Double = 'double' }[$Button]
        }
        $r = Invoke-Pointer $kind $X $Y $qx $qy $Action
        if ($r.Code -ne 0) {
            Write-Warning $r.Message
            exit $r.Code
        }
        $where = if ($r.Message) { " in $($r.Message)" } else { '' }
        Write-Output ('{0} {1},{2}{3}' -f $kind, $X, $Y, $where)
        # Explicit, so a caller never reads a stale code from an earlier failure.
        exit 0
    }

    'demo' {
        Import-ScreenControl
        $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds

        $state = New-State
        $state.action = 'Demo: the agent pointer moves and taps, but nothing is clicked'
        Write-State $state
        Remove-Item -Path $ackPath, $logPath -Force -ErrorAction SilentlyContinue
        if (-not (Start-Overlay)) { exit 2 }
        $stops = @(
            @(0.30, 0.35, 'point', 'Tapping a spot on the left'),
            @(0.72, 0.28, 'point', 'Crossing to the right'),
            @(0.66, 0.72, 'point', 'Down to the lower right'),
            @(0.24, 0.66, 'move', 'Moving without a tap, then resting'),
            @(0.50, 0.50, 'point', 'Back to the middle')
        )
        try {
            Start-Sleep -Milliseconds 1500
            foreach ($s in $stops) {
                $px = [int]($b.Left + $b.Width * $s[0])
                $py = [int]($b.Top + $b.Height * $s[1])
                $r = Invoke-Pointer $s[2] $px $py 0 0 ('Demo: ' + $s[3])
                if ($r.Code -ne 0) { Write-Warning $r.Message; break }
                Write-Output ('{0} {1},{2}' -f $s[2], $px, $py)
                # Rest so the idle sway shows between moves.
                Start-Sleep -Milliseconds 2200
            }
        }
        finally {
            Stop-Overlay
        }
        Write-Output 'agent screen control: demo finished'
        break
    }

    'stop' {
        Stop-Overlay
        Write-Output 'agent screen control: off'
        break
    }

    'status' {
        $state = Read-State
        $running = [bool](Get-OverlayProcess)
        if (-not $state) {
            [pscustomobject]@{ Active = $false; OverlayRunning = $running }
            break
        }
        $ack = Read-JsonFile $ackPath
        $last = ''
        if ($ack) {
            $last = if ($ack.ok) { "done: $($state.cursor_action) in $($ack.window)" } else { "failed: $($ack.message)" }
        }
        [pscustomobject]@{
            Active           = [bool]$state.active
            Agent            = $state.agent
            CurrentAction    = $state.action
            LastPointer      = $last
            ReleaseRequested = [bool]$state.release_requested
            OverlayRunning   = $running
            LastHeartbeat    = $state.heartbeat
        }
        if ($state.active -and $state.release_requested) { exit 3 }
        break
    }

    'windows' {
        Import-ScreenControl
        $found = [ArcRho.ScreenControl.ScreenTools]::Windows($Window)
        if ($found.Count -eq 0) {
            Write-Warning "No visible window matches '$Window'."
            exit 4
        }
        $found | ForEach-Object { $_.ToString() }
        exit 0
    }

    'screenshot' {
        if (-not $Out) {
            Write-Warning '-Out is required: the PNG path to write (scratch paths belong under temp\).'
            exit 2
        }
        Import-ScreenControl
        $path = [System.IO.Path]::GetFullPath($Out)
        $rx = 0; $ry = 0; $rw = 0; $rh = 0
        if ($Window) {
            # The frontmost matching window that is on screen.
            $w = [ArcRho.ScreenControl.ScreenTools]::Windows($Window) |
                Where-Object { -not $_.Minimized } | Select-Object -First 1
            if (-not $w) {
                Write-Warning "No window on screen matches '$Window'. Run 'windows' to see what is there."
                exit 4
            }
            $rx = $w.Bounds.Left; $ry = $w.Bounds.Top; $rw = $w.Bounds.Width; $rh = $w.Bounds.Height
            # A screenshot shows what is on screen, so name anything in front of the window.
            $cover = [ArcRho.ScreenControl.ScreenTools]::Windows('') |
                Where-Object { $_.Order -lt $w.Order -and -not $_.Minimized -and $_.Bounds.IntersectsWith($w.Bounds) }
            foreach ($o in $cover) {
                Write-Warning "'$($o.Title)' [$($o.Process)] is in front of '$($w.Title)' and shows in the screenshot."
            }
        }
        elseif ($Width -gt 0 -and $Height -gt 0) {
            if ($X -eq [int]::MinValue -or $Y -eq [int]::MinValue) {
                Write-Warning 'A region needs -X and -Y with -Width and -Height.'
                exit 2
            }
            $rx = $X; $ry = $Y; $rw = $Width; $rh = $Height
        }
        [ArcRho.ScreenControl.ScreenTools]::Capture($path, $rx, $ry, $rw, $rh, $Zoom)
        exit 0
    }

    'overlay' {
        Import-ScreenControl
        [ArcRho.ScreenControl.Overlay]::Run($statePath, $IdleExitMinutes)
        break
    }
}
