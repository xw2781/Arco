$ErrorActionPreference = "Stop"

$configPath = Join-Path $env:APPDATA "Arco\workspace_paths.json"
if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
    exit 1
}

try {
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    $root = [string]$config.workspace_root
    if (-not $root -or -not (Test-Path -LiteralPath $root -PathType Container)) {
        exit 1
    }
    [Console]::Out.Write((Resolve-Path -LiteralPath $root).Path)
    exit 0
} catch {
    exit 1
}
