param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,

    [string]$FeedDir = "E:\Arco Server\releases\installers",

    [string]$ReleaseNotes = "",

    [string]$ReleaseNotesPath = "",

    [ValidateSet("Arco", "Arcode")]
    [string]$ProductName = "Arco",

    [switch]$Mandatory
)

$ErrorActionPreference = "Stop"

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
New-Item -ItemType Directory -Path $FeedDir -Force | Out-Null

if ($ReleaseNotesPath) {
    $resolvedReleaseNotes = Resolve-Path -LiteralPath $ReleaseNotesPath
    $ReleaseNotes = Get-Content -LiteralPath $resolvedReleaseNotes.Path -Raw
}

# Hash the local source. Hashing the published copy instead re-reads the whole installer
# across the network in 4 KB chunks, which cost 17+ minutes per publish on a 362 MB build.
$hash = (Get-FileHash -LiteralPath $installerFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant()

$targetInstaller = Join-Path $FeedDir $installerFile.Name
Copy-Item -LiteralPath $installerFile.FullName -Destination $targetInstaller -Force
$publishedLength = (Get-Item -LiteralPath $targetInstaller).Length
if ($publishedLength -ne $installerFile.Length) {
    throw "Published installer is $publishedLength bytes but the source is $($installerFile.Length) bytes: $targetInstaller"
}

$hashFile = "$targetInstaller.sha256"
"$hash  $($installerFile.Name)" | Set-Content -LiteralPath $hashFile -Encoding ASCII

$manifest = [ordered]@{
    version = $version
    installer = $installerFile.Name
    sha256 = $hash
    releaseNotes = $ReleaseNotes
    mandatory = [bool]$Mandatory
    publishedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
}

$manifestPath = Join-Path $FeedDir "latest.json"
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Write-Host "Published $ProductName $version update feed:"
Write-Host "  $targetInstaller"
Write-Host "  $hashFile"
Write-Host "  $manifestPath"
