param(
    [string]$BetaPath = (Join-Path $PSScriptRoot "..\beta\ARCRHO_BETA.xlam"),
    [string]$ReleasePath = "E:\Arco Server\Excel Add-ins\Arco.xlam",
    [string]$CustomUIPath = (Join-Path $PSScriptRoot "customUI.xml"),
    [string]$ArchiveDir = (Join-Path $PSScriptRoot "..\beta\Archive"),
    [string]$ExtractDir = (Join-Path $PSScriptRoot "..\beta\_release_unpack")
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "xlam_package_helpers.ps1")

function Resolve-FullPath([string]$Path) {
    $executionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path)
}

function Clear-ReadOnly([string]$Path) {
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        $item = Get-Item -LiteralPath $Path
        if (($item.Attributes -band [System.IO.FileAttributes]::ReadOnly) -ne 0) {
            $item.Attributes = $item.Attributes -band (-bnot [System.IO.FileAttributes]::ReadOnly)
        }
    }
}

function Update-WorkbookCoreProperties([string]$WorkbookPath, [string]$Title) {
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    $zip = [System.IO.Compression.ZipFile]::Open($WorkbookPath, [System.IO.Compression.ZipArchiveMode]::Update)
    try {
        $entry = $zip.Entries | Where-Object { ($_.FullName -replace '\\', '/') -ieq 'docProps/core.xml' } | Select-Object -First 1
        if ($null -eq $entry) {
            Write-Warning "Workbook core properties not found: $WorkbookPath"
            return
        }

        $reader = New-Object System.IO.StreamReader($entry.Open())
        try {
            [xml]$xml = $reader.ReadToEnd()
        }
        finally {
            $reader.Dispose()
        }

        $ns = New-Object System.Xml.XmlNamespaceManager($xml.NameTable)
        $ns.AddNamespace('dc', 'http://purl.org/dc/elements/1.1/')
        $titleNode = $xml.SelectSingleNode('//dc:title', $ns)
        if ($null -eq $titleNode) {
            $titleNode = $xml.CreateElement('dc', 'title', 'http://purl.org/dc/elements/1.1/')
            [void]$xml.DocumentElement.AppendChild($titleNode)
        }
        $titleNode.InnerText = $Title

        $descriptionNode = $xml.SelectSingleNode('//dc:description', $ns)
        if ($null -eq $descriptionNode) {
            $descriptionNode = $xml.CreateElement('dc', 'description', 'http://purl.org/dc/elements/1.1/')
            [void]$xml.DocumentElement.AppendChild($descriptionNode)
        }
        $descriptionNode.InnerText = 'Arco actuarial data and analytics system'

        $entry.Delete()
        $newEntry = $zip.CreateEntry('docProps/core.xml', [System.IO.Compression.CompressionLevel]::Optimal)
        $writer = New-Object System.IO.StreamWriter($newEntry.Open(), (New-Object System.Text.UTF8Encoding($false)))
        try {
            $xml.Save($writer)
        }
        finally {
            $writer.Dispose()
        }
        Write-Host "Updated workbook title: $Title"
    }
    finally {
        $zip.Dispose()
    }
}

function New-CustomUIXmlForWorkbook([string]$RibbonXmlPath, [string]$WorkbookPath, [string]$WorkingDir) {
    if (-not (Test-Path -LiteralPath $WorkingDir -PathType Container)) {
        New-Item -ItemType Directory -Path $WorkingDir | Out-Null
    }

    $label = Get-RibbonLabelForWorkbook $WorkbookPath $RibbonXmlPath
    [xml]$xml = Get-Content -LiteralPath $RibbonXmlPath -Raw

    $namespaceUri = $xml.DocumentElement.NamespaceURI
    if ([string]::IsNullOrEmpty($namespaceUri)) {
        $tab = $xml.SelectSingleNode("//tab")
    }
    else {
        $namespaceManager = New-Object System.Xml.XmlNamespaceManager($xml.NameTable)
        $namespaceManager.AddNamespace("ui", $namespaceUri)
        $tab = $xml.SelectSingleNode("//ui:tab", $namespaceManager)
    }

    if ($null -eq $tab) {
        throw "Ribbon XML does not contain a tab element: $RibbonXmlPath"
    }

    $tab.SetAttribute("label", $label)

    $tempPath = Join-Path $WorkingDir ("customUI.{0}.xml" -f [System.Guid]::NewGuid().ToString("N"))
    $settings = New-Object System.Xml.XmlWriterSettings
    $settings.Indent = $true
    $settings.OmitXmlDeclaration = $true
    $settings.Encoding = New-Object System.Text.UTF8Encoding($false)

    $writer = [System.Xml.XmlWriter]::Create($tempPath, $settings)
    try {
        $xml.Save($writer)
    }
    finally {
        $writer.Close()
    }

    Write-Host "Using ribbon tab label: $label"
    $tempPath
}

function Update-XlamPackageFromUnpackedFiles(
    [string]$WorkbookPath,
    [string]$RibbonXmlPath,
    [string]$WorkingDir,
    [string]$LabelWorkbookPath = $WorkbookPath
) {
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    if (Test-Path -LiteralPath $WorkingDir) {
        Remove-Item -LiteralPath $WorkingDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $WorkingDir | Out-Null

    $zipPath = [System.IO.Path]::ChangeExtension($WorkbookPath, ".zip")
    try {
        [System.IO.Compression.ZipFile]::ExtractToDirectory($WorkbookPath, $WorkingDir)

        $customUIDir = Join-Path $WorkingDir "customUI"
        if (-not (Test-Path -LiteralPath $customUIDir -PathType Container)) {
            New-Item -ItemType Directory -Path $customUIDir | Out-Null
        }

        $tempRibbonXmlPath = New-CustomUIXmlForWorkbook $RibbonXmlPath $LabelWorkbookPath $WorkingDir
        try {
            Copy-Item -LiteralPath $tempRibbonXmlPath -Destination (Join-Path $customUIDir "customUI.xml") -Force
        }
        finally {
            if (Test-Path -LiteralPath $tempRibbonXmlPath -PathType Leaf) {
                Remove-Item -LiteralPath $tempRibbonXmlPath -Force
            }
        }
        Write-Host "Updated ribbon XML: $RibbonXmlPath"

        if (Test-Path -LiteralPath $zipPath -PathType Leaf) {
            Remove-Item -LiteralPath $zipPath -Force
        }

        Compress-XlamPackage $WorkingDir $zipPath
        Assert-XlamPackage $zipPath

        Clear-ReadOnly $WorkbookPath
        Move-Item -LiteralPath $zipPath -Destination $WorkbookPath -Force
    }
    finally {
        if (Test-Path -LiteralPath $zipPath -PathType Leaf) {
            Remove-Item -LiteralPath $zipPath -Force
        }
        if (Test-Path -LiteralPath $WorkingDir -PathType Container) {
            Remove-Item -LiteralPath $WorkingDir -Recurse -Force
        }
    }
}

$betaPathFull = Resolve-FullPath $BetaPath
$releasePathFull = Resolve-FullPath $ReleasePath
$customUIPathFull = Resolve-FullPath $CustomUIPath
$archiveDirFull = Resolve-FullPath $ArchiveDir
$extractDirFull = Resolve-FullPath $ExtractDir

if (-not (Test-Path -LiteralPath $betaPathFull -PathType Leaf)) {
    throw "Beta XLAM not found: $betaPathFull"
}

if (-not (Test-Path -LiteralPath $customUIPathFull -PathType Leaf)) {
    throw "Ribbon XML not found: $customUIPathFull"
}

if (-not (Test-Path -LiteralPath $archiveDirFull -PathType Container)) {
    New-Item -ItemType Directory -Path $archiveDirFull | Out-Null
}

Update-XlamPackageFromUnpackedFiles $betaPathFull $customUIPathFull $extractDirFull $betaPathFull
Update-WorkbookCoreProperties $betaPathFull (Get-RibbonLabelForWorkbook $betaPathFull $customUIPathFull)
Assert-XlamPackage $betaPathFull

# Build the finished release package locally, next to the beta add-in, so the
# share is touched only twice at the end (archive the old file, copy the new
# one). Editing the package in place on the share used to fail whenever the
# server still held the file after a write ("being used by another process").
# The staged file carries the release file name because the ribbon label and
# the workbook title are derived from it.
$stageDirFull = Join-Path (Split-Path -Parent $extractDirFull) "_release_stage"
$stagePathFull = Join-Path $stageDirFull ([System.IO.Path]::GetFileName($releasePathFull))
if (Test-Path -LiteralPath $stageDirFull) {
    Remove-Item -LiteralPath $stageDirFull -Recurse -Force
}
New-Item -ItemType Directory -Path $stageDirFull | Out-Null

try {
    Copy-Item -LiteralPath $betaPathFull -Destination $stagePathFull -Force
    Update-XlamPackageFromUnpackedFiles $stagePathFull $customUIPathFull $extractDirFull $stagePathFull
    Update-WorkbookCoreProperties $stagePathFull (Get-RibbonLabelForWorkbook $stagePathFull $customUIPathFull)
    Assert-XlamPackage $stagePathFull

    $archivePath = $null
    if (Test-Path -LiteralPath $releasePathFull -PathType Leaf) {
        $timestamp = Get-Date -Format "yy.MM.dd-HH.mm.ss"
        $milliseconds = (Get-Date).Millisecond
        $archiveName = "ArcRho v.$timestamp ($milliseconds).xlam"
        $archivePath = Join-Path $archiveDirFull $archiveName
        Invoke-FileOperationWithRetry "Archive existing XLAM: $releasePathFull" {
            Clear-ReadOnly $releasePathFull
            Move-Item -LiteralPath $releasePathFull -Destination $archivePath -Force
        } | Out-Null
        Write-Host "Archived existing XLAM: $archivePath"
    }

    try {
        Invoke-FileOperationWithRetry "Copy release XLAM: $releasePathFull" {
            Copy-Item -LiteralPath $stagePathFull -Destination $releasePathFull -Force
        } | Out-Null
    }
    catch {
        if ($null -ne $archivePath) {
            Write-Warning "The previous release was archived but the new one could not be copied. Restore it from: $archivePath"
        }
        throw
    }

    Invoke-FileOperationWithRetry "Validate release XLAM: $releasePathFull" {
        Assert-XlamPackage $releasePathFull
    } | Out-Null
    Set-FileReadOnlyWithRetry $releasePathFull
}
finally {
    if (Test-Path -LiteralPath $stageDirFull -PathType Container) {
        Remove-Item -LiteralPath $stageDirFull -Recurse -Force
    }
}

Write-Host "Released XLAM: $releasePathFull"

