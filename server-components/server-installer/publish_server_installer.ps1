param(
    [Parameter(Mandatory = $true)]
    [string]$InstallerPath,

    [string]$Repo = "xw2781/ArcRho",

    [string]$FeedDir = "E:\Arco Server\releases\server-installers"
)

$ErrorActionPreference = "Stop"
Get-Command gh -ErrorAction Stop | Out-Null

$installer = Get-Item -LiteralPath (Resolve-Path -LiteralPath $InstallerPath)
$match = [regex]::Match($installer.Name, '^ArcRho-Server-Setup-(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?)\.exe$')
if (-not $match.Success) {
    throw "Installer must be named ArcRho-Server-Setup-<version>.exe."
}
$version = $match.Groups[1].Value
$tag = "ArcRho-v$version"
$hash = (Get-FileHash -LiteralPath $installer.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
$hashFile = "$($installer.FullName).sha256"
"$hash  $($installer.Name)" | Set-Content -LiteralPath $hashFile -Encoding ASCII

gh release view $tag --repo $Repo | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "The matching frontend release $tag does not exist in $Repo. Publish ArcRho first."
}
gh release upload $tag $installer.FullName $hashFile --repo $Repo --clobber
if ($LASTEXITCODE -ne 0) {
    throw "Could not upload ArcRho Server Components to $tag."
}

New-Item -ItemType Directory -Path $FeedDir -Force | Out-Null
$target = Join-Path $FeedDir $installer.Name
Copy-Item -LiteralPath $installer.FullName -Destination $target -Force
Copy-Item -LiteralPath $hashFile -Destination "$target.sha256" -Force
$manifest = [ordered]@{
    version = $version
    installer = $installer.Name
    sha256 = $hash
    publishedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
}
$manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $FeedDir "latest.json") -Encoding UTF8

Write-Host "Published ArcRho Server Components $version beside $tag and to $FeedDir."
