param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,

    [string]$ReleaseNotes = "",

    [string]$ReleaseNotesPath = "",

    [ValidateSet("Arco", "Arcode")]
    [string]$ProductName = "Arco",

    [string]$Repo = "",

    [string]$ReleaseChannelFile = "",

    [switch]$Mandatory,

    [switch]$Prerelease
)

$ErrorActionPreference = "Stop"

# GitHub's hard cap on a release body. The truncation target leaves room for the
# pointer paragraph and the mandatory marker appended after truncation.
$GITHUB_RELEASE_BODY_LIMIT = 125000
$NOTES_TRUNCATION_LENGTH = 124000

Get-Command gh -ErrorAction Stop | Out-Null

$channelPath = if ($ReleaseChannelFile) { $ReleaseChannelFile } else { Join-Path $PSScriptRoot "release_channel.json" }
if (-not (Test-Path -LiteralPath $channelPath -PathType Leaf)) {
    throw "Missing release channel definition: $channelPath"
}
$channel = Get-Content -LiteralPath $channelPath -Raw | ConvertFrom-Json
if (-not $Repo) { $Repo = [string]$channel.githubRepo }
$tagFormat = [string]$channel.tagFormat
if (-not $Repo) { throw "Release channel is missing a 'githubRepo' value: $channelPath" }
if ($tagFormat -notlike "*{product}*" -or $tagFormat -notlike "*{version}*") {
    throw "Release channel 'tagFormat' must contain both {product} and {version}: $channelPath"
}

$resolvedInstaller = Resolve-Path -LiteralPath $InstallerPath
$installerFile = Get-Item -LiteralPath $resolvedInstaller.Path
if (-not $installerFile.Name.StartsWith("$ProductName-Setup-") -or -not $installerFile.Name.EndsWith(".exe")) {
    throw "Installer must be named like $ProductName-Setup-<version>.exe."
}

$escapedProductName = [regex]::Escape($ProductName)
$versionMatch = [regex]::Match($installerFile.Name, "^$escapedProductName-Setup-(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?)\.exe$")
if (-not $versionMatch.Success) {
    throw "Could not infer a semantic version from $($installerFile.Name)."
}

$version = $versionMatch.Groups[1].Value
$tag = $tagFormat.Replace("{product}", $ProductName).Replace("{version}", $version)

if ($ReleaseNotesPath) {
    $resolvedReleaseNotes = Resolve-Path -LiteralPath $ReleaseNotesPath
    $ReleaseNotes = Get-Content -LiteralPath $resolvedReleaseNotes.Path -Raw
}

$hash = (Get-FileHash -LiteralPath $installerFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
$hashFile = Join-Path ([System.IO.Path]::GetTempPath()) "$($installerFile.Name).sha256"
"$hash  $($installerFile.Name)" | Set-Content -LiteralPath $hashFile -Encoding ASCII

$notesText = if ($ReleaseNotes) { $ReleaseNotes } else { "$ProductName $version" }

# GitHub rejects a release body over 125000 characters. When the notes exceed that,
# attach them in full as a release asset and publish a truncated body that points at it,
# so a long release never blocks publication and nothing is silently lost.
$fullNotesAsset = $null
if ($notesText.Length -gt $GITHUB_RELEASE_BODY_LIMIT) {
    $fullNotesAsset = Join-Path ([System.IO.Path]::GetTempPath()) "$ProductName-$version-release-notes.md"
    $notesText | Set-Content -LiteralPath $fullNotesAsset -Encoding UTF8

    $truncated = $notesText.Substring(0, $NOTES_TRUNCATION_LENGTH)
    $lastBreak = $truncated.LastIndexOf("`n")
    if ($lastBreak -gt 0) { $truncated = $truncated.Substring(0, $lastBreak) }
    $assetName = [System.IO.Path]::GetFileName($fullNotesAsset)
    $notesText = @"
$truncated

---

These release notes were truncated to fit the GitHub release body limit of $GITHUB_RELEASE_BODY_LIMIT characters.
The complete notes are attached to this release as ``$assetName``.
"@
    Write-Host "Release notes exceed the GitHub body limit; attaching the full notes as $assetName."
}

if ($Mandatory) {
    $notesText = "$notesText`n`nmandatory: true"
}

$notesFile = Join-Path ([System.IO.Path]::GetTempPath()) "$($installerFile.Name).notes.md"
$notesText | Set-Content -LiteralPath $notesFile -Encoding UTF8

$releaseAssets = @($installerFile.FullName, $hashFile)
if ($fullNotesAsset) { $releaseAssets += $fullNotesAsset }

Write-Host "Publishing $ProductName $version to GitHub Releases:"
Write-Host "  Repo:      $Repo"
Write-Host "  Tag:       $tag"
Write-Host "  Installer: $($installerFile.FullName)"
Write-Host "  Checksum:  $hashFile"
if ($fullNotesAsset) { Write-Host "  Notes:     $fullNotesAsset" }

# gh is a native executable, so a missing release sets $LASTEXITCODE instead of throwing.
# A try/catch here would leave $releaseExists true and upload into a tag that does not exist.
gh release view $tag --repo $Repo | Out-Null
$releaseExists = ($LASTEXITCODE -eq 0)

if (-not $releaseExists) {
    $createArgs = @(
        "release", "create", $tag
    ) + $releaseAssets + @(
        "--repo", $Repo,
        "--title", "$ProductName $version",
        "--notes-file", $notesFile
    )
    if ($Prerelease) { $createArgs += "--prerelease" }
    gh @createArgs
    if ($LASTEXITCODE -ne 0) { throw "gh release create failed with exit code $LASTEXITCODE." }
} else {
    gh release upload $tag @releaseAssets --repo $Repo --clobber
    if ($LASTEXITCODE -ne 0) { throw "gh release upload failed with exit code $LASTEXITCODE." }
    gh release edit $tag --repo $Repo --title "$ProductName $version" --notes-file $notesFile
    if ($LASTEXITCODE -ne 0) { throw "gh release edit failed with exit code $LASTEXITCODE." }
}

$temporaryFiles = @($hashFile, $notesFile)
if ($fullNotesAsset) { $temporaryFiles += $fullNotesAsset }
Remove-Item -LiteralPath $temporaryFiles -Force -ErrorAction SilentlyContinue

Write-Host "Published $ProductName $version to https://github.com/$Repo/releases/tag/$tag"

# Installed apps find this release through the update feed, not the release list.
& (Join-Path $PSScriptRoot "publish_update_manifest.ps1") -ProductName $ProductName -Repo $Repo -ReleaseChannelFile $channelPath
