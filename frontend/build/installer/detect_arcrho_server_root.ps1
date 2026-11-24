$ErrorActionPreference = "Stop"

# The app's settings folder was renamed from ArcRho to Arco, and the app moves
# it on its first start after the update. Setup runs before that start, so an
# upgrade still finds the configured root only in the old folder.
foreach ($folder in @("Arco", "ArcRho")) {
    $configPath = Join-Path $env:APPDATA "$folder\workspace_paths.json"
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        continue
    }
    try {
        $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
        $root = [string]$config.workspace_root
        if (-not $root -or -not (Test-Path -LiteralPath $root -PathType Container)) {
            continue
        }
        [Console]::Out.Write((Resolve-Path -LiteralPath $root).Path)
        exit 0
    } catch {
        continue
    }
}
exit 1
