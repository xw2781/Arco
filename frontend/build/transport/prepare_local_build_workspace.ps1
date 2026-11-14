param(
    [Parameter(Mandatory = $true)]
    [string]$Destination,

    [string]$SourceRoot = "",

    [switch]$SkipNodeModules,

    [ValidateRange(1, 128)]
    [int]$CopyThreads = 32,

    [switch]$NoProgress,

    [switch]$CleanDestination
)

$ErrorActionPreference = "Stop"

function Resolve-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    $executionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path)
}

function Test-ExcludedDirectory {
    param(
        [Parameter(Mandatory = $true)][System.IO.DirectoryInfo]$Directory,
        [string[]]$ExcludeDirs = @()
    )

    $fullName = $Directory.FullName.TrimEnd("\", "/")
    foreach ($exclude in $ExcludeDirs) {
        if ([string]::IsNullOrWhiteSpace($exclude)) {
            continue
        }

        if ([System.IO.Path]::IsPathRooted($exclude)) {
            $excludeFullName = $exclude.TrimEnd("\", "/")
            if ($fullName.Equals($excludeFullName, [System.StringComparison]::OrdinalIgnoreCase)) {
                return $true
            }
            if ($fullName.StartsWith("$excludeFullName\", [System.StringComparison]::OrdinalIgnoreCase)) {
                return $true
            }
            continue
        }

        if ($Directory.Name -like $exclude) {
            return $true
        }
    }

    return $false
}

function Test-ExcludedFile {
    param(
        [Parameter(Mandatory = $true)][System.IO.FileInfo]$File,
        [string[]]$ExcludeFiles = @()
    )

    foreach ($exclude in $ExcludeFiles) {
        if (-not [string]::IsNullOrWhiteSpace($exclude) -and $File.Name -like $exclude) {
            return $true
        }
    }

    return $false
}

function Get-DirectoryByteSize {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string[]]$ExcludeDirs = @(),
        [string[]]$ExcludeFiles = @()
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        return 0
    }

    $total = [int64]0
    $pending = New-Object "System.Collections.Generic.Stack[string]"
    $pending.Push($Path)

    while ($pending.Count -gt 0) {
        $current = $pending.Pop()
        foreach ($item in Get-ChildItem -LiteralPath $current -Force -ErrorAction SilentlyContinue) {
            if ($item.PSIsContainer) {
                if (-not (Test-ExcludedDirectory -Directory $item -ExcludeDirs $ExcludeDirs)) {
                    $pending.Push($item.FullName)
                }
                continue
            }

            if (-not (Test-ExcludedFile -File $item -ExcludeFiles $ExcludeFiles)) {
                $total += [int64]$item.Length
            }
        }
    }

    return $total
}

function ConvertTo-ProcessArgument {
    param([Parameter(Mandatory = $true)][string]$Value)

    if ($Value -notmatch '[\s"]') {
        return $Value
    }

    return '"' + $Value.Replace('"', '\"') + '"'
}

function Invoke-RobocopyChecked {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Target,
        [string[]]$ExcludeDirs = @(),
        [string[]]$ExcludeFiles = @()
    )

    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        throw "Source directory not found: $Source"
    }

    New-Item -ItemType Directory -Force -Path $Target | Out-Null

    $args = @(
        $Source,
        $Target,
        "/E",
        "/DCOPY:DAT",
        "/COPY:DAT",
        "/R:2",
        "/W:2",
        "/MT:$CopyThreads",
        "/NFL",
        "/NDL",
        "/NP"
    )

    if ($ExcludeDirs.Count -gt 0) {
        $args += "/XD"
        $args += $ExcludeDirs
    }

    if ($ExcludeFiles.Count -gt 0) {
        $args += "/XF"
        $args += $ExcludeFiles
    }

    Write-Host "Copying $Source -> $Target"
    if ($NoProgress) {
        & robocopy @args
        $code = $LASTEXITCODE
    } else {
        Write-Host "Estimating copy size for progress..."
        $totalBytes = Get-DirectoryByteSize -Path $Source -ExcludeDirs $ExcludeDirs -ExcludeFiles $ExcludeFiles
        $processArgs = ($args | ForEach-Object { ConvertTo-ProcessArgument $_ }) -join " "
        $process = Start-Process -FilePath "robocopy.exe" -ArgumentList $processArgs -NoNewWindow -PassThru

        while (-not $process.HasExited) {
            if ($totalBytes -gt 0) {
                $copiedBytes = Get-DirectoryByteSize -Path $Target
                $percent = [Math]::Min(100, [Math]::Floor(($copiedBytes / $totalBytes) * 100))
                $status = "{0:N1} MB of {1:N1} MB" -f ($copiedBytes / 1MB), ($totalBytes / 1MB)
                Write-Progress -Id 1 -Activity "Copying ArcRho build workspace" -Status $status -PercentComplete $percent
            }
            Start-Sleep -Seconds 1
        }

        $process.WaitForExit()
        Write-Progress -Id 1 -Activity "Copying ArcRho build workspace" -Completed
        $code = $process.ExitCode
    }

    if ($code -ge 8) {
        throw "Robocopy failed with exit code $code while copying $Source"
    }
}

function Copy-FileChecked {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Target
    )

    if (Test-Path -LiteralPath $Source -PathType Leaf) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Target) | Out-Null
        Copy-Item -LiteralPath $Source -Destination $Target -Force
    }
}

function Convert-BatchFileLineEndings {
    param([Parameter(Mandatory = $true)][string]$Root)

    # cmd.exe resolves `call :label` by byte offset, and that search fails on a
    # batch file saved with LF-only line endings once the label sits past a
    # certain position, so a build dies with "cannot find the batch label
    # specified" even though the label is present. The repository keeps batch
    # files CRLF through .gitattributes; normalize the workspace copies too so an
    # editor that rewrote a batch file with LF endings cannot break packaging.
    # -Include is ignored when the source is given as -LiteralPath, so filter by
    # extension with -Filter, once per extension. -Filter also matches short 8.3
    # names, so confirm the real extension before rewriting a file.
    $normalizedCount = 0
    $batchFiles = @(
        @("*.bat", "*.cmd") | ForEach-Object {
            Get-ChildItem -LiteralPath $Root -Recurse -File -Force -Filter $_ -ErrorAction SilentlyContinue
        } | Where-Object {
            $_.Extension -match '^\.(?:bat|cmd)$' -and
            $_.FullName -notmatch '\\(?:node_modules|node-portable|venvs)\\'
        }
    )

    foreach ($batchFile in $batchFiles) {
        # Rewrite bytes rather than decoded text so the file keeps whatever
        # single-byte encoding it already uses.
        $bytes = [System.IO.File]::ReadAllBytes($batchFile.FullName)
        $normalized = New-Object System.Collections.Generic.List[byte]
        for ($index = 0; $index -lt $bytes.Length; $index++) {
            $current = $bytes[$index]
            if ($current -eq 13 -and ($index + 1) -lt $bytes.Length -and $bytes[$index + 1] -eq 10) {
                continue
            }
            if ($current -eq 10) {
                $normalized.Add([byte]13)
            }
            $normalized.Add($current)
        }

        if ($normalized.Count -ne $bytes.Length) {
            [System.IO.File]::WriteAllBytes($batchFile.FullName, $normalized.ToArray())
            Write-Host "Normalized batch line endings: $($batchFile.FullName.Substring($Root.Length).TrimStart('\'))"
            $normalizedCount++
        }
    }

    Write-Host "Batch files normalized to CRLF: $normalizedCount"
}

if ([string]::IsNullOrWhiteSpace($SourceRoot)) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $SourceRoot = Resolve-FullPath (Join-Path $scriptDir "..\..\..")
} else {
    $SourceRoot = Resolve-FullPath $SourceRoot
}

$Destination = Resolve-FullPath $Destination

if (-not (Test-Path -LiteralPath (Join-Path $SourceRoot "frontend\build\build_app_via_local_workspace.bat") -PathType Leaf)) {
    throw "SourceRoot does not look like the ArcRho repository root: $SourceRoot"
}

if ($Destination.TrimEnd("\", "/").Equals($SourceRoot.TrimEnd("\", "/"), [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Destination must be different from SourceRoot."
}

if ($CleanDestination -and (Test-Path -LiteralPath $Destination)) {
    $destinationInfo = Get-Item -LiteralPath $Destination -Force
    if (-not $destinationInfo.PSIsContainer) {
        throw "Destination exists but is not a directory: $Destination"
    }

    $destinationRoot = [System.IO.Path]::GetPathRoot($destinationInfo.FullName).TrimEnd("\", "/")
    $destinationFullName = $destinationInfo.FullName.TrimEnd("\", "/")
    if (
        $destinationFullName.Equals($destinationRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
        $destinationFullName.Length -lt 10
    ) {
        throw "Refusing to clean unsafe destination: $Destination"
    }

    Write-Host "Deleting existing local build workspace: $Destination"
    Remove-Item -LiteralPath $Destination -Recurse -Force
}

Write-Host "Preparing local ArcRho build workspace"
Write-Host "Source:      $SourceRoot"
Write-Host "Destination: $Destination"
Write-Host ""

New-Item -ItemType Directory -Force -Path $Destination | Out-Null

foreach ($file in @("AGENT_GUIDELINES.md", "CLAUDE.md", "README.md", ".gitignore")) {
    Copy-FileChecked -Source (Join-Path $SourceRoot $file) -Target (Join-Path $Destination $file)
}

$frontendExcludeDirs = @(
    (Join-Path $SourceRoot "frontend\dist"),
    (Join-Path $SourceRoot "frontend\python_dist"),
    (Join-Path $SourceRoot "frontend\python_build"),
    (Join-Path $SourceRoot "frontend\build\log"),
    (Join-Path $SourceRoot "frontend\build\local_workspace_log"),
    (Join-Path $SourceRoot "frontend\build\python_packages"),
    (Join-Path $SourceRoot "frontend\build\__pycache__"),
    (Join-Path $SourceRoot "frontend\build\generated"),
    (Join-Path $SourceRoot "frontend\logs"),
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    ".git",
    ".agents",
    ".codex",
    ".claude",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "venv_*",
    "node-v*-win-x64"
)

if ($SkipNodeModules) {
    $frontendExcludeDirs += "node_modules"
}

Invoke-RobocopyChecked `
    -Source (Join-Path $SourceRoot "frontend") `
    -Target (Join-Path $Destination "frontend") `
    -ExcludeDirs $frontendExcludeDirs `
    -ExcludeFiles @("*.pyc", "*.pyo", "*.log", "*.tmp", "*.ipynb")

New-Item -ItemType Directory -Force -Path (Join-Path $Destination "python-api") | Out-Null
foreach ($file in @("pyproject.toml", "README.md")) {
    Copy-FileChecked -Source (Join-Path $SourceRoot "python-api\$file") -Target (Join-Path $Destination "python-api\$file")
}

Invoke-RobocopyChecked `
    -Source (Join-Path $SourceRoot "python-api\src") `
    -Target (Join-Path $Destination "python-api\src") `
    -ExcludeDirs @("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache") `
    -ExcludeFiles @("*.pyc", "*.pyo", "*.log", "*.tmp")

Invoke-RobocopyChecked `
    -Source (Join-Path $SourceRoot "python-api\tools") `
    -Target (Join-Path $Destination "python-api\tools") `
    -ExcludeDirs @("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache") `
    -ExcludeFiles @("*.pyc", "*.pyo", "*.log", "*.tmp")

Convert-BatchFileLineEndings -Root $Destination

Write-Host ""
Write-Host "Local build workspace is ready."
Write-Host "Start packaging through E:\XWSpace\Build ArcRho App\build_app_one_click.bat."
Write-Host "It requests a fresh ZIP and recreates the local workspace automatically."
