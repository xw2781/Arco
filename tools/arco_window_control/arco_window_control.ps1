<#
.SYNOPSIS
Lets an agent look at and drive one Arco window, and nothing outside it.

.DESCRIPTION
Talks to the running Arco desktop app, which publishes a loopback endpoint in
%APPDATA%\Arco\agent_window_control.json. Input goes straight into Arco's page, so the real
mouse pointer never moves and nothing outside Arco can be clicked. While an agent is in
control, the window shows an edge glow, the agent's own pointer, and a banner. A click, key
press, or wheel turn in the window, or Ctrl+Alt+Esc anywhere, pauses the agent; only the
banner's Resume button lets it continue. See README.md beside this script.

Exit codes: 0 done, 2 not started or bad arguments, 3 the user paused or ended control,
4 refused or failed.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet('windows', 'screenshot', 'start', 'stop', 'status', 'action', 'move', 'click', 'drag', 'scroll', 'type', 'key', 'demo')]
    [string]$Command,

    [string]$Window,
    [string]$Out,
    [Nullable[double]]$X,
    [Nullable[double]]$Y,
    [Nullable[double]]$Width,
    [Nullable[double]]$Height,
    [double]$Zoom = 1,
    [switch]$ShowOverlay,

    [string]$Agent,
    [string]$Action,
    [ValidateSet('TopCenter', 'TopRight', 'BottomCenter', 'BottomRight')]
    [string]$Position = 'TopCenter',
    [switch]$NoPointer,
    [double]$IdleExitMinutes = 20,

    [Nullable[double]]$ToX,
    [Nullable[double]]$ToY,
    [ValidateSet('Left', 'Right', 'Double')]
    [string]$Button = 'Left',
    [double]$Delta,
    [string]$Text,
    [string]$Key,

    [ValidateSet('Arco', 'Arcode')]
    [string]$App = 'Arco',
    [int]$AppPid,
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'

function Get-Endpoint {
    $file = Join-Path $env:APPDATA "$App\agent_window_control.json"
    if (-not (Test-Path -LiteralPath $file)) {
        Write-Warning "Arco is not running, or it is a version without agent window control ($file is missing)."
        exit 2
    }
    $payload = Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json
    $entries = @($payload.apps)
    if (-not $entries.Count) { $entries = @($payload) }
    foreach ($entry in $entries) {
        if ($AppPid -and [int]$entry.pid -ne $AppPid) { continue }
        if (Get-Process -Id ([int]$entry.pid) -ErrorAction SilentlyContinue) { return $entry }
    }
    if ($AppPid) { Write-Warning "No running Arco with process id $AppPid published an endpoint." }
    else { Write-Warning 'No running Arco published an endpoint. Start Arco and try again.' }
    exit 2
}

function Invoke-Arco([hashtable]$Body) {
    $endpoint = Get-Endpoint
    $json = $Body | ConvertTo-Json -Compress -Depth 5
    try {
        return Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$($endpoint.port)/command" `
            -Headers @{ 'X-Agent-Control-Token' = [string]$endpoint.token } `
            -ContentType 'application/json; charset=utf-8' `
            -Body ([Text.Encoding]::UTF8.GetBytes($json)) -TimeoutSec $TimeoutSeconds
    } catch {
        Write-Warning "Arco did not answer: $($_.Exception.Message)"
        exit 4
    }
}

function Add-IfSet([hashtable]$Body, [string]$Name, $Value) {
    if ($null -ne $Value -and "$Value" -ne '') { $Body[$Name] = $Value }
}

function Write-Hit($Answer) {
    if (-not $Answer.hit -or -not $Answer.hit.element) { return }
    $frames = @($Answer.hit.frames) | Where-Object { $_ }
    if ($frames) { Write-Host "Hit: $($Answer.hit.element) (inside $($frames -join ' > '))" }
    else { Write-Host "Hit: $($Answer.hit.element)" }
}

function Complete([object]$Answer) {
    if ($Answer.code -ne 0) {
        Write-Warning $Answer.message
        exit ([int]$Answer.code)
    }
    exit 0
}

# Messages go to the host so the function returns only the answer.
function Send-Command([hashtable]$Body) {
    $answer = Invoke-Arco $Body
    if ($answer.code -eq 0) { Write-Host $answer.message }
    Write-Hit $answer
    return $answer
}

$body = @{ command = $Command }
switch ($Command) {
    'windows' {
        $answer = Invoke-Arco $body
        $answer.windows | ForEach-Object {
            $flags = @()
            if ($_.focused) { $flags += 'focused' }
            if ($_.minimized) { $flags += 'minimized' }
            if (-not $_.visible) { $flags += 'hidden' }
            [pscustomobject]@{
                Id     = $_.id
                Role   = $_.role
                Title  = $_.title
                Size   = "$($_.content.width) x $($_.content.height)"
                Screen = "$($_.content.x), $($_.content.y)"
                State  = $flags -join ', '
            }
        } | Format-Table -AutoSize | Out-String -Width 200 | Write-Output
        Complete $answer
    }
    'screenshot' {
        if (-not $Out) { Write-Warning 'screenshot needs -Out <png>.'; exit 2 }
        $body.out = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Out)
        $body.zoom = $Zoom
        Add-IfSet $body 'window' $Window
        if ($Width -or $Height) {
            $body.x = if ($null -ne $X) { $X } else { 0 }
            $body.y = if ($null -ne $Y) { $Y } else { 0 }
            Add-IfSet $body 'width' $Width
            Add-IfSet $body 'height' $Height
        }
        if ($ShowOverlay) { $body.showOverlay = $true }
        $answer = Invoke-Arco $body
        if ($answer.code -eq 0) {
            Write-Output "$($answer.message) $($answer.path)"
            Write-Output ("Window {0} ({1}). Origin ({2}, {3}), zoom {4}: image point (px, py) is window point ({2} + px / {4}, {3} + py / {4})." -f `
                $answer.window.id, $answer.window.title, $answer.origin.x, $answer.origin.y, $answer.zoom)
        }
        Complete $answer
    }
    'start' {
        $body.agent = if ($Agent) { $Agent } else { 'Agent' }
        $body.position = $Position
        $body.idleExitMinutes = $IdleExitMinutes
        Add-IfSet $body 'action' $Action
        Add-IfSet $body 'window' $Window
        if ($NoPointer) { $body.noPointer = $true }
        Complete (Send-Command $body)
    }
    'status' {
        $answer = Invoke-Arco $body
        if ($answer.agent) {
            $state = if ($answer.ended) { 'ended by the user' } elseif ($answer.paused) { 'paused by the user' } else { 'in control' }
            Write-Output "$($answer.agent): $state for $($answer.seconds) s. Action: $($answer.action)"
            if ($answer.reason) { Write-Output "Reason: $($answer.reason)" }
            if ($answer.window) { Write-Output "Window $($answer.window.id) ($($answer.window.title)), $($answer.window.content.width) x $($answer.window.content.height)." }
            if ($answer.stopKey) { Write-Output "Stop key: $($answer.stopKey)" }
        }
        Complete $answer
    }
    'demo' {
        $body = @{ command = 'start'; agent = $(if ($Agent) { $Agent } else { 'Demo' }); action = 'Showing the agent pointer'; position = $Position; idleExitMinutes = 2 }
        Add-IfSet $body 'window' $Window
        $answer = Send-Command $body
        if ($answer.code -ne 0) { Complete $answer }
        $size = $answer.window.content
        $points = @(@(0.25, 0.3), @(0.7, 0.35), @(0.55, 0.7), @(0.3, 0.6), @(0.5, 0.5))
        foreach ($point in $points) {
            $answer = Invoke-Arco @{ command = 'move'; x = [math]::Round($size.width * $point[0]); y = [math]::Round($size.height * $point[1]); action = 'Gliding around the window' }
            if ($answer.code -ne 0) { break }
            Start-Sleep -Milliseconds 900
        }
        $final = $answer
        Invoke-Arco @{ command = 'stop' } | Out-Null
        Complete $final
    }
    default {
        Add-IfSet $body 'action' $Action
        Add-IfSet $body 'x' $X
        Add-IfSet $body 'y' $Y
        switch ($Command) {
            'click' { $body.button = $Button }
            'drag' { Add-IfSet $body 'toX' $ToX; Add-IfSet $body 'toY' $ToY }
            'scroll' { $body.delta = $Delta }
            'type' { $body.text = $Text }
            'key' { $body.key = $Key }
        }
        Complete (Send-Command $body)
    }
}
