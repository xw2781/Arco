[CmdletBinding()]
param(
    [string]$SourceRoot = "",
    [string]$OutputZip = "",
    [switch]$Check
)

$ErrorActionPreference = "Stop"

function Resolve-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    $executionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path)
}

function New-StreamedZipArchive {
    param(
        [Parameter(Mandatory = $true)][string]$SourceDirectory,
        [Parameter(Mandatory = $true)][string]$ArchivePath
    )

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    $sourceRoot = [System.IO.Path]::GetFullPath($SourceDirectory).TrimEnd("\", "/") + "\"
    $archiveRootName = Split-Path -Leaf $SourceDirectory
    $sourceFiles = @(Get-ChildItem -LiteralPath $SourceDirectory -Recurse -Force -File)
    $fileStream = [System.IO.File]::Open(
        $ArchivePath,
        [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::None
    )

    try {
        $archive = New-Object System.IO.Compression.ZipArchive(
            $fileStream,
            [System.IO.Compression.ZipArchiveMode]::Create,
            $false
        )
        try {
            for ($index = 0; $index -lt $sourceFiles.Count; $index++) {
                $sourceFile = $sourceFiles[$index]
                $relativePath = $sourceFile.FullName.Substring($sourceRoot.Length).Replace("\", "/")
                $entryName = "$archiveRootName/$relativePath"
                $entry = $archive.CreateEntry(
                    $entryName,
                    [System.IO.Compression.CompressionLevel]::Optimal
                )

                $lastWriteTime = $sourceFile.LastWriteTime
                if ($lastWriteTime.Year -lt 1980) {
                    $lastWriteTime = [DateTime]::new(1980, 1, 1)
                }
                elseif ($lastWriteTime.Year -gt 2107) {
                    $lastWriteTime = [DateTime]::new(2107, 12, 31, 23, 59, 58)
                }
                $entry.LastWriteTime = [DateTimeOffset]$lastWriteTime

                $inputStream = $null
                $outputStream = $null
                try {
                    $inputStream = [System.IO.File]::Open(
                        $sourceFile.FullName,
                        [System.IO.FileMode]::Open,
                        [System.IO.FileAccess]::Read,
                        [System.IO.FileShare]::Read
                    )
                    $outputStream = $entry.Open()
                    $inputStream.CopyTo($outputStream, 1MB)
                }
                catch {
                    throw "Failed to add ZIP entry '$entryName': $($_.Exception.Message)"
                }
                finally {
                    if ($outputStream) {
                        $outputStream.Dispose()
                    }
                    if ($inputStream) {
                        $inputStream.Dispose()
                    }
                }

                $completedCount = $index + 1
                if ($completedCount -eq $sourceFiles.Count -or $completedCount % 500 -eq 0) {
                    $percent = if ($sourceFiles.Count -gt 0) {
                        [Math]::Floor(($completedCount * 100.0) / $sourceFiles.Count)
                    }
                    else {
                        100
                    }
                    Write-Host "  Archived $completedCount / $($sourceFiles.Count) files ($percent%)"
                }
            }
        }
        finally {
            $archive.Dispose()
        }
    }
    finally {
        $fileStream.Dispose()
    }

    return $sourceFiles.Count
}

function Test-ArchiveEntrySuffix {
    param(
        [Parameter(Mandatory = $true)][System.Collections.Generic.HashSet[string]]$EntryNames,
        [Parameter(Mandatory = $true)][string]$Suffix
    )

    foreach ($entryName in $EntryNames) {
        if (
            $entryName.Equals($Suffix, [System.StringComparison]::OrdinalIgnoreCase) -or
            $entryName.EndsWith("/$Suffix", [System.StringComparison]::OrdinalIgnoreCase)
        ) {
            return $true
        }
    }

    return $false
}

function Assert-BuildArchive {
    param([Parameter(Mandatory = $true)][string]$ArchivePath)

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    $requiredFiles = @(
        "BUILD_SOURCE_MANIFEST.json",
        "frontend/build/build_app_via_local_workspace.bat",
        "frontend/build/transport/prepare_local_build_workspace_from_zip.ps1",
        "frontend/package.json",
        "frontend/package-lock.json",
        "frontend/electron/main.js",
        "frontend/ui/index.html",
        "frontend/icons/icon.png",
        "frontend/build/transport/run_with_log.ps1",
        "frontend/build/release/release_notes.py",
        "frontend/build/release/release_workflow.py",
        "frontend/build/release/version_manager.py",
        "frontend/build/helpers/build_python_api_wheel.js",
        "frontend/build/build_python_server.bat",
        "frontend/build/build_arcode_python_server.bat",
        "frontend/build/helpers/convert_icon.js",
        "frontend/build/check_python_build_env.py",
        "frontend/build/server.spec",
        "frontend/build/server_entry.py",
        "frontend/build/arcode_server.spec",
        "frontend/build/arcode_server_entry.py",
        "frontend/build/installer/patch_nsis_installer_progress.js",
        "frontend/build/arcbot_runtime/refresh_bundled_codex_runtime.ps1",
        "frontend/build/arcbot_runtime/validate_bundled_codex_runtime.js",
        "frontend/electron/arcbot_runtime_contract.json",
        "frontend/build/installer/installer_progress_helper.cs",
        "frontend/build/installer/installer.nsh",
        "frontend/build/installer/detect_arcrho_server_root.ps1",
        "frontend/build/installer/arcode_installer.nsh",
        "frontend/electron-builder.arcode.json",
        "frontend/icons/icon_wing_geo_v8.svg",
        "frontend/build/installer/install_arcrho_excel_addin.ps1",
        "frontend/build/release/publish_update_feed.ps1",
        "frontend/build/release/publish_github_release.ps1",
        "frontend/build/release/publish_update_manifest.ps1",
        "frontend/build/release/release_channel.json",
        "frontend/build/release/request_release_sync.ps1",
        "frontend/node-portable/node.exe",
        "frontend/node-portable/npm.cmd",
        "frontend/node-portable/node_modules/npm/bin/npm-cli.js",
        "frontend/node-portable/node_modules/npm/package.json",
        "frontend/node-portable/codex.cmd",
        "frontend/node-portable/node_modules/@openai/codex/bin/codex.js",
        "frontend/node-portable/node_modules/@openai/codex/package.json",
        "node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe",
        "frontend/node_modules/electron-builder/cli.js",
        "frontend/node_modules/app-builder-bin/win/x64/app-builder.exe",
        "python-api/pyproject.toml",
        "python-api/tools/build_wheel.py"
    )

    $archive = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        $entryNames = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
        foreach ($entry in $archive.Entries) {
            $normalizedName = $entry.FullName.Replace("\", "/").TrimStart("/")
            if (-not $entryNames.Add($normalizedName)) {
                throw "Build ZIP contains a duplicate entry: $normalizedName"
            }
        }

        foreach ($requiredFile in $requiredFiles) {
            if (-not (Test-ArchiveEntrySuffix -EntryNames $entryNames -Suffix $requiredFile)) {
                throw "Build ZIP is missing required file: $requiredFile"
            }
        }

        $hasPythonApiSource = $false
        foreach ($entryName in $entryNames) {
            if ($entryName -match '(^|/)python-api/src/.+') {
                $hasPythonApiSource = $true
                break
            }
        }
        if (-not $hasPythonApiSource) {
            throw "Build ZIP is missing python-api/src content."
        }

        $forbiddenPatterns = @(
            '^(?:[^/]+/)?\.(?:git|agents|codex)(?:/|$)',
            '^(?:[^/]+/)?frontend/(?:dist|python_dist|python_build)(?:/|$)',
            '^(?:[^/]+/)?frontend/build/(?:generated|log|local_workspace_log|python_packages|__pycache__)(?:/|$)'
        )
        foreach ($entryName in $entryNames) {
            foreach ($pattern in $forbiddenPatterns) {
                if ($entryName -match $pattern) {
                    throw "Build ZIP contains excluded content: $entryName"
                }
            }
        }

        return $archive.Entries.Count
    }
    finally {
        $archive.Dispose()
    }
}

function Publish-FileAtomically {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$DestinationPath,
        [Parameter(Mandatory = $true)][string]$BackupPath
    )

    if (Test-Path -LiteralPath $DestinationPath -PathType Leaf) {
        if (Test-Path -LiteralPath $BackupPath) {
            throw "Atomic replacement backup path already exists: $BackupPath"
        }
        [System.IO.File]::Replace($SourcePath, $DestinationPath, $BackupPath, $true)
    }
    else {
        [System.IO.File]::Move($SourcePath, $DestinationPath)
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($SourceRoot)) {
    $SourceRoot = Resolve-FullPath (Join-Path $scriptDir "..\..\..")
}
else {
    $SourceRoot = Resolve-FullPath $SourceRoot
}

if ([string]::IsNullOrWhiteSpace($OutputZip)) {
    $OutputZip = "E:\XWSpace\Build ArcRho App\ArcRho.zip"
}
$OutputZip = Resolve-FullPath $OutputZip

if (-not $OutputZip.EndsWith(".zip", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputZip must use the .zip extension: $OutputZip"
}

$outputDirectory = Split-Path -Parent $OutputZip
if (-not (Test-Path -LiteralPath $outputDirectory -PathType Container)) {
    if ($Check) {
        Write-Host "Output directory will be created: $outputDirectory"
    }
    else {
        New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
    }
}
$sourceRootWithSeparator = [System.IO.Path]::GetFullPath($SourceRoot).TrimEnd("\", "/") + "\"
$outputDirectoryFullName = [System.IO.Path]::GetFullPath($outputDirectory).TrimEnd("\", "/")
if (
    $outputDirectoryFullName.Equals($sourceRootWithSeparator.TrimEnd("\"), [System.StringComparison]::OrdinalIgnoreCase) -or
    $outputDirectoryFullName.StartsWith($sourceRootWithSeparator, [System.StringComparison]::OrdinalIgnoreCase)
) {
    throw "OutputZip must be outside the source repository: $OutputZip"
}

$prepareScript = Join-Path $SourceRoot "frontend\build\transport\prepare_local_build_workspace.ps1"
$requiredSourcePaths = @(
    "frontend\build\build_app_via_local_workspace.bat",
    "frontend\build\transport\prepare_local_build_workspace_from_zip.ps1",
    "frontend\package.json",
    "frontend\package-lock.json",
    "frontend\electron\main.js",
    "frontend\ui\index.html",
    "frontend\icons\icon.png",
    "frontend\app_server\default_preferences",
    "frontend\changes\unreleased",
    "frontend\docs\releases",
    "frontend\build\transport\run_with_log.ps1",
    "frontend\build\release\release_notes.py",
    "frontend\build\release\release_workflow.py",
    "frontend\build\release\version_manager.py",
    "frontend\build\helpers\build_python_api_wheel.js",
    "frontend\build\build_python_server.bat",
    "frontend\build\build_arcode_python_server.bat",
    "frontend\build\helpers\convert_icon.js",
    "frontend\build\check_python_build_env.py",
    "frontend\build\server.spec",
    "frontend\build\server_entry.py",
    "frontend\build\arcode_server.spec",
    "frontend\build\arcode_server_entry.py",
    "frontend\build\installer\patch_nsis_installer_progress.js",
    "frontend\build\arcbot_runtime\refresh_bundled_codex_runtime.ps1",
    "frontend\build\arcbot_runtime\validate_bundled_codex_runtime.js",
    "frontend\electron\arcbot_runtime_contract.json",
    "frontend\build\installer\installer_progress_helper.cs",
    "frontend\build\installer\installer.nsh",
    "frontend\build\installer\detect_arcrho_server_root.ps1",
    "frontend\build\installer\arcode_installer.nsh",
    "frontend\electron-builder.arcode.json",
    "frontend\icons\icon_wing_geo_v8.svg",
    "frontend\build\installer\install_arcrho_excel_addin.ps1",
    "frontend\build\release\publish_update_feed.ps1",
    "frontend\build\release\publish_github_release.ps1",
    "frontend\build\release\publish_update_manifest.ps1",
    "frontend\build\release\release_channel.json",
    "frontend\build\release\request_release_sync.ps1",
    "frontend\node-portable\node.exe",
    "frontend\node-portable\npm.cmd",
    "frontend\node-portable\node_modules\npm\bin\npm-cli.js",
    "frontend\node-portable\node_modules\npm\package.json",
    "frontend\node-portable\codex.cmd",
    "frontend\node-portable\node_modules\@openai\codex\bin\codex.js",
    "frontend\node-portable\node_modules\@openai\codex\package.json",
    "frontend\node_modules\electron-builder\cli.js",
    "frontend\node_modules\app-builder-bin\win\x64\app-builder.exe",
    "python-api\pyproject.toml",
    "python-api\src",
    "python-api\tools\build_wheel.py"
)

if (-not (Test-Path -LiteralPath $prepareScript -PathType Leaf)) {
    throw "Missing workspace preparation helper: $prepareScript"
}
foreach ($relativePath in $requiredSourcePaths) {
    $fullPath = Join-Path $SourceRoot $relativePath
    if (-not (Test-Path -LiteralPath $fullPath)) {
        throw "Source repository is missing required build input: $relativePath"
    }
}

$bundledRuntimeRoot = Join-Path $SourceRoot "frontend\node-portable"
$bundledRuntimeValidator = Join-Path $SourceRoot "frontend\build\arcbot_runtime\validate_bundled_codex_runtime.js"
$bundledNode = Join-Path $bundledRuntimeRoot "node.exe"
& $bundledNode $bundledRuntimeValidator --runtime-root $bundledRuntimeRoot --inventory-only
if ($LASTEXITCODE -ne 0) {
    throw "Bundled Node/npm/Codex runtime inventory validation failed."
}

$readyFlagPath = "$OutputZip.ready"
Write-Host "ArcRho clean build ZIP creator"
Write-Host "Source repository: $SourceRoot"
Write-Host "Output ZIP:        $OutputZip"
Write-Host "Completion flag:   $readyFlagPath"
Write-Host ""

if ($Check) {
    Write-Host "Source ZIP creation prerequisites passed."
    exit 0
}

if (Test-Path -LiteralPath $readyFlagPath) {
    Remove-Item -LiteralPath $readyFlagPath -Force
}

$computerName = if ([string]::IsNullOrWhiteSpace($env:COMPUTERNAME)) { "unknown-pc" } else { $env:COMPUTERNAME }
$logDirectory = Join-Path $outputDirectory ("logs\" + $computerName)
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$logStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = Join-Path $logDirectory "create_build_source_zip_$logStamp.log"
$transcriptStarted = $false
Start-Transcript -LiteralPath $logPath -Force | Out-Null
$transcriptStarted = $true
Write-Host "ZIP creation log: $logPath"
Write-Host ""

$runId = [Guid]::NewGuid().ToString("N")
$shortRunId = $runId.Substring(0, 8)
$stagingContainer = Join-Path $outputDirectory ".arczip-$shortRunId"
$stagingRepository = Join-Path $stagingContainer "ArcRho"
$temporaryZip = Join-Path $outputDirectory "ArcRho.building-$runId.zip"
$temporaryHash = Join-Path $outputDirectory "ArcRho.building-$runId.sha256"
$temporaryReadyFlag = Join-Path $outputDirectory "ArcRho.building-$runId.ready"
$zipBackup = Join-Path $outputDirectory "ArcRho.backup-$runId.zip"
$hashBackup = Join-Path $outputDirectory "ArcRho.backup-$runId.sha256"
$hashPath = "$OutputZip.sha256"
$startedAt = Get-Date

try {
    Write-Host "Preparing curated staging tree..."
    & $prepareScript `
        -SourceRoot $SourceRoot `
        -Destination $stagingRepository `
        -CleanDestination `
        -NoProgress

    $gitCommit = $null
    $gitDirty = $null
    if (Get-Command git -ErrorAction SilentlyContinue) {
        $gitCommitOutput = @(& git -C $SourceRoot rev-parse HEAD 2>$null)
        if ($LASTEXITCODE -eq 0 -and $gitCommitOutput.Count -gt 0) {
            $gitCommit = $gitCommitOutput[0].Trim()
            $gitStatusOutput = @(& git -C $SourceRoot status --porcelain 2>$null)
            if ($LASTEXITCODE -eq 0) {
                $gitDirty = $gitStatusOutput.Count -gt 0
            }
        }
    }

    $stagedFiles = @(Get-ChildItem -LiteralPath $stagingRepository -Recurse -Force -File)
    $manifest = [ordered]@{
        schemaVersion = 1
        purpose = "ArcRho local-workspace application build source"
        createdAtUtc = [DateTime]::UtcNow.ToString("o")
        sourceCommit = $gitCommit
        sourceDirty = $gitDirty
        stagedFileCount = $stagedFiles.Count + 1
        stagedFileBytesBeforeManifest = [int64](($stagedFiles | Measure-Object -Property Length -Sum).Sum)
    }
    $manifestPath = Join-Path $stagingRepository "BUILD_SOURCE_MANIFEST.json"
    $manifestJson = ($manifest | ConvertTo-Json -Depth 4) + [Environment]::NewLine
    [System.IO.File]::WriteAllText(
        $manifestPath,
        $manifestJson,
        (New-Object System.Text.UTF8Encoding($false))
    )

    Write-Host "Creating compressed archive..."
    $writtenFileCount = New-StreamedZipArchive `
        -SourceDirectory $stagingRepository `
        -ArchivePath $temporaryZip

    Write-Host "Validating archive contents..."
    $entryCount = Assert-BuildArchive -ArchivePath $temporaryZip
    if ($entryCount -ne $writtenFileCount) {
        throw "Build ZIP entry count mismatch: wrote $writtenFileCount files but validated $entryCount entries."
    }

    Write-Host "Publishing archive atomically..."
    Publish-FileAtomically `
        -SourcePath $temporaryZip `
        -DestinationPath $OutputZip `
        -BackupPath $zipBackup

    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $OutputZip).Hash.ToLowerInvariant()
    $hashLine = "$hash  $([System.IO.Path]::GetFileName($OutputZip))" + [Environment]::NewLine
    [System.IO.File]::WriteAllText(
        $temporaryHash,
        $hashLine,
        [System.Text.Encoding]::ASCII
    )
    Publish-FileAtomically `
        -SourcePath $temporaryHash `
        -DestinationPath $hashPath `
        -BackupPath $hashBackup

    if (Test-Path -LiteralPath $zipBackup) {
        Remove-Item -LiteralPath $zipBackup -Force
    }
    if (Test-Path -LiteralPath $hashBackup) {
        Remove-Item -LiteralPath $hashBackup -Force
    }

    $outputInfo = Get-Item -LiteralPath $OutputZip
    $elapsed = (Get-Date) - $startedAt
    [System.IO.File]::WriteAllText(
        $temporaryReadyFlag,
        $runId + [Environment]::NewLine,
        [System.Text.Encoding]::ASCII
    )
    [System.IO.File]::Move($temporaryReadyFlag, $readyFlagPath)

    Write-Host ""
    Write-Host "Clean ArcRho build ZIP created successfully."
    Write-Host "ZIP:        $OutputZip"
    Write-Host "SHA-256:    $hashPath"
    Write-Host "Ready flag: $readyFlagPath"
    Write-Host "Entries:    $entryCount"
    Write-Host "Size:       $([Math]::Round($outputInfo.Length / 1MB, 1)) MB"
    Write-Host "Elapsed:    $($elapsed.ToString('hh\:mm\:ss'))"
}
catch {
    Write-Host ""
    Write-Host "ZIP creation failed:" -ForegroundColor Red
    Write-Host ($_ | Out-String) -ForegroundColor Red
    throw
}
finally {
    if (Test-Path -LiteralPath $temporaryZip) {
        Remove-Item -LiteralPath $temporaryZip -Force
    }
    if (Test-Path -LiteralPath $temporaryHash) {
        Remove-Item -LiteralPath $temporaryHash -Force
    }
    if (Test-Path -LiteralPath $temporaryReadyFlag) {
        Remove-Item -LiteralPath $temporaryReadyFlag -Force
    }
    if (Test-Path -LiteralPath $stagingContainer) {
        $stagingFullName = [System.IO.Path]::GetFullPath($stagingContainer)
        $outputFullName = [System.IO.Path]::GetFullPath($outputDirectory).TrimEnd("\", "/") + "\"
        if (
            -not $stagingFullName.StartsWith($outputFullName, [System.StringComparison]::OrdinalIgnoreCase) -or
            -not (Split-Path -Leaf $stagingFullName).StartsWith(".arczip-", [System.StringComparison]::OrdinalIgnoreCase)
        ) {
            throw "Refusing to clean unexpected staging path: $stagingFullName"
        }
        Remove-Item -LiteralPath $stagingFullName -Recurse -Force
    }
    if (Test-Path -LiteralPath $zipBackup) {
        Write-Warning "ZIP replacement backup retained after failure: $zipBackup"
    }
    if (Test-Path -LiteralPath $hashBackup) {
        Write-Warning "Checksum replacement backup retained after failure: $hashBackup"
    }
    if ($transcriptStarted) {
        Stop-Transcript | Out-Null
    }
}
