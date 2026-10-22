# Publishes the small file the desktop app reads to find its next update.
#
# The app used to list releases through the GitHub API, which allows 60 requests an
# hour per internet address; every office user shares one address, so update checks
# failed until the hour reset. The file is a release asset on a fixed prerelease tag,
# downloaded like any other asset, which that limit does not apply to. It is rebuilt
# from the published releases on every run, so it holds no state of its own and
# running it again only rewrites the same file.
param(
    [ValidateSet("Arco", "Arcode")]
    [string]$ProductName = "Arco",

    [string]$Repo = "",

    [string]$ReleaseChannelFile = ""
)

$ErrorActionPreference = "Stop"

# Enough notes for a user who skipped several releases, without making a slow
# connection download the whole release history on every check.
$MAX_RELEASES_IN_MANIFEST = 10

Get-Command gh -ErrorAction Stop | Out-Null

$channelPath = if ($ReleaseChannelFile) { $ReleaseChannelFile } else { Join-Path $PSScriptRoot "release_channel.json" }
$channel = Get-Content -LiteralPath $channelPath -Raw | ConvertFrom-Json
if (-not $Repo) { $Repo = [string]$channel.githubRepo }
$tagFormat = [string]$channel.tagFormat
$feedTag = [string]$channel.updateFeedTag
$feedAssetName = ([string]$channel.updateFeedAsset).Replace("{product}", $ProductName)
if (-not $Repo -or -not $feedTag -or -not $feedAssetName) {
    throw "Release channel needs 'githubRepo', 'updateFeedTag' and 'updateFeedAsset' values: $channelPath"
}

$tagPattern = "^" + [regex]::Escape($tagFormat).Replace("\{product}", [regex]::Escape($ProductName)).Replace("\{version}", "(\d+\.\d+\.\d+)") + "$"

$releasesJson = gh api "repos/$Repo/releases?per_page=100"
if ($LASTEXITCODE -ne 0) { throw "gh api could not list the releases of $Repo (exit code $LASTEXITCODE)." }
# Windows PowerShell passes a parsed JSON array down the pipeline as one object,
# so it is unrolled here into one entry per release.
$releases = @($releasesJson | Out-String | ConvertFrom-Json | ForEach-Object { $_ })

$entries = foreach ($release in $releases) {
    if ($release.draft -or $release.prerelease) { continue }
    $match = [regex]::Match([string]$release.tag_name, $tagPattern)
    if (-not $match.Success) { continue }
    $version = $match.Groups[1].Value
    $installerName = "$ProductName-Setup-$version.exe"
    $installer = @($release.assets | Where-Object { $_.name -eq $installerName })[0]
    $checksum = @($release.assets | Where-Object { $_.name -eq "$installerName.sha256" })[0]
    if (-not $installer -or -not $checksum) { continue }
    [pscustomobject]@{
        Version = [version]$version
        Tag = [string]$release.tag_name
        Installer = $installer
        ChecksumName = [string]$checksum.name
        PublishedAt = [string]$release.published_at
        Body = [string]$release.body
    }
}
$entries = @($entries | Sort-Object Version -Descending | Select-Object -First $MAX_RELEASES_IN_MANIFEST)
if ($entries.Count -eq 0) { throw "No published $ProductName release with an installer and checksum was found in $Repo." }

$latest = $entries[0]
$workDir = Join-Path ([System.IO.Path]::GetTempPath()) "arco-update-manifest-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $workDir | Out-Null
try {
    gh release download $latest.Tag --repo $Repo --pattern $latest.ChecksumName --dir $workDir
    if ($LASTEXITCODE -ne 0) { throw "Could not download $($latest.ChecksumName) from $($latest.Tag)." }
    $sha256 = [regex]::Match((Get-Content -LiteralPath (Join-Path $workDir $latest.ChecksumName) -Raw), "\b[a-fA-F0-9]{64}\b").Value.ToLowerInvariant()
    if (-not $sha256) { throw "$($latest.ChecksumName) in $($latest.Tag) holds no SHA-256 value." }

    $manifest = [ordered]@{
        product = $ProductName
        version = $latest.Version.ToString()
        installer = [string]$latest.Installer.name
        url = [string]$latest.Installer.browser_download_url
        sha256 = $sha256
        releases = @($entries | ForEach-Object {
            [ordered]@{ version = $_.Version.ToString(); publishedAt = $_.PublishedAt; body = $_.Body }
        })
    }
    $manifestPath = Join-Path $workDir $feedAssetName
    [System.IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 5), (New-Object System.Text.UTF8Encoding $false))

    gh release view $feedTag --repo $Repo | Out-Null
    if ($LASTEXITCODE -ne 0) {
        # A prerelease is never "latest" and is skipped by clients that still scan the
        # release list, so the feed never looks like a version anyone could install.
        gh release create $feedTag $manifestPath --repo $Repo --prerelease --title "Update feed" `
            --notes "Holds the files the desktop apps read to find their next update. Rewritten on every release; not an installable version."
        if ($LASTEXITCODE -ne 0) { throw "gh release create failed for $feedTag with exit code $LASTEXITCODE." }
    } else {
        gh release upload $feedTag $manifestPath --repo $Repo --clobber
        if ($LASTEXITCODE -ne 0) { throw "gh release upload failed for $feedTag with exit code $LASTEXITCODE." }
    }
} finally {
    Remove-Item -LiteralPath $workDir -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "Published the $ProductName update feed ($($latest.Version), $($entries.Count) releases of notes) to https://github.com/$Repo/releases/download/$feedTag/$feedAssetName"
