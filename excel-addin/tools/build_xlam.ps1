param(
    [string]$SourceDir = (Join-Path $PSScriptRoot "..\src_vba"),
    [string]$TargetPath = (Join-Path $PSScriptRoot "..\beta\ARCRHO_BETA.xlam"),
    [string]$CustomUIPath = (Join-Path $PSScriptRoot "customUI.xml"),
    [string]$NotesPath = (Join-Path $SourceDir "..\RELEASE_NOTES.md")
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "xlam_package_helpers.ps1")

function Resolve-FullPath([string]$Path) {
    $executionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path)
}

function Get-VbaComponentName([System.IO.FileInfo]$File) {
    $name = [System.IO.Path]::GetFileNameWithoutExtension($File.Name)
    $name = $name -replace '[^A-Za-z0-9_]', '_'
    if ($name -notmatch '^[A-Za-z]') {
        $name = "M_$name"
    }
    $name
}

function Get-VbaComponentOrNull([object]$VBProject, [string]$Name) {
    try {
        return $VBProject.VBComponents.Item($Name)
    }
    catch {
        return $null
    }
}

function Get-CodeTextFromExportedComponent([string]$Path) {
    $text = Get-Content -LiteralPath $Path -Raw
    $lines = [regex]::Split($text, "\r?\n")
    $startIndex = 0

    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^Attribute VB_Exposed\s*=') {
            $startIndex = $i + 1
            break
        }
    }

    if ($startIndex -ge $lines.Count) {
        return ""
    }

    ($lines[$startIndex..($lines.Count - 1)] -join [Environment]::NewLine).TrimStart()
}

function Replace-CodeModuleFromText([object]$Component, [string]$CodeText) {
    $codeModule = $Component.CodeModule
    if ($null -eq $codeModule) {
        Write-Warning "Could not replace code for $($Component.Name) because Excel returned no CodeModule."
        return
    }

    if ($codeModule.CountOfLines -gt 0) {
        $codeModule.DeleteLines(1, $codeModule.CountOfLines)
    }

    if (-not [string]::IsNullOrWhiteSpace($CodeText)) {
        $codeModule.AddFromString($CodeText)
    }
}

function Remove-ExcelTempFiles([string]$Directory) {
    if (-not (Test-Path -LiteralPath $Directory -PathType Container)) {
        return
    }

    Get-ChildItem -LiteralPath $Directory -File -Force |
        Where-Object {
            ($_.Name -match '^[0-9A-Fa-f]{8}$' -and [string]::IsNullOrEmpty($_.Extension)) -or
            ($_.Name -like '~$*.xls*')
        } |
        ForEach-Object {
            try {
                Remove-Item -LiteralPath $_.FullName -Force
                Write-Host "Removed Excel temp file $($_.Name)"
            }
            catch {
                Write-Warning "Could not remove Excel temp file $($_.FullName): $($_.Exception.Message)"
            }
        }
}

function Get-ExcelMacroName([object]$Workbook, [string]$ProcedureName) {
    $workbookName = $Workbook.Name -replace "'", "''"
    "'$workbookName'!$ProcedureName"
}

function Invoke-WorkbookMacro([object]$Excel, [object]$Workbook, [string]$ProcedureName) {
    $macroName = Get-ExcelMacroName $Workbook $ProcedureName
    Write-Host "Running workbook macro: $macroName"
    $Excel.Run($macroName) | Out-Null
}

function Update-WorkbookCoreProperties([string]$WorkbookPath, [string]$Title) {
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    # The share can refuse the second open for a few seconds after the first
    # update was written; retry the file-in-use failure instead of stopping.
    $zip = Invoke-FileOperationWithRetry "Open package for update: $WorkbookPath" {
        [System.IO.Compression.ZipFile]::Open($WorkbookPath, [System.IO.Compression.ZipArchiveMode]::Update)
    }
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

function Update-CustomUIXml([string]$WorkbookPath, [string]$RibbonXmlPath) {
    if (-not (Test-Path -LiteralPath $RibbonXmlPath -PathType Leaf)) {
        Write-Warning "Ribbon XML not found: $RibbonXmlPath"
        return
    }

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    $workbookDirectory = [System.IO.Path]::GetDirectoryName([System.IO.Path]::GetFullPath($WorkbookPath))
    $tempRibbonXmlPath = New-CustomUIXmlForWorkbook $RibbonXmlPath $WorkbookPath $workbookDirectory
    # The share can refuse the second open for a few seconds after the first
    # update was written; retry the file-in-use failure instead of stopping.
    $zip = Invoke-FileOperationWithRetry "Open package for update: $WorkbookPath" {
        [System.IO.Compression.ZipFile]::Open($WorkbookPath, [System.IO.Compression.ZipArchiveMode]::Update)
    }
    try {
        $entryPath = "customUI/customUI.xml"
        $entriesToDelete = @($zip.Entries | Where-Object { ($_.FullName -replace '\\', '/') -ieq $entryPath })
        foreach ($entry in $entriesToDelete) {
            $entry.Delete()
        }

        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $zip,
            $tempRibbonXmlPath,
            $entryPath,
            [System.IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null

        Write-Host "Updated ribbon XML: $RibbonXmlPath"
    }
    finally {
        $zip.Dispose()
        if ($null -ne $tempRibbonXmlPath -and (Test-Path -LiteralPath $tempRibbonXmlPath -PathType Leaf)) {
            Remove-Item -LiteralPath $tempRibbonXmlPath -Force
        }
    }
}

$sourceDirFull = Resolve-FullPath $SourceDir
$targetPathFull = Resolve-FullPath $TargetPath
$customUIPathFull = Resolve-FullPath $CustomUIPath

if (-not (Test-Path -LiteralPath $sourceDirFull -PathType Container)) {
    throw "Source VBA folder not found: $sourceDirFull"
}

if (-not (Test-Path -LiteralPath $targetPathFull -PathType Leaf)) {
    throw "Target XLAM not found: $targetPathFull"
}

# A build carries release notes whose newest entry is the version it builds.
$notesPathFull = Resolve-FullPath $NotesPath
$coreText = Get-Content -LiteralPath (Join-Path $sourceDirFull "Core.bas") -Raw
$version = [regex]::Match($coreText, 'ARCRHO_VERSION As String = "([^"]+)"').Groups[1].Value
if ((Get-ReleaseNotesVersion $notesPathFull) -ne $version) {
    throw "Add a '## $version - <date>' entry at the top of $notesPathFull before building."
}

$targetName = Split-Path -Leaf $targetPathFull
if ([string]::Compare($targetName, "Arco.xlam", $true) -eq 0) {
    throw "Refusing to update Arco.xlam. This script updates ARCRHO_BETA.xlam only."
}

$targetDir = Split-Path -Parent $targetPathFull
Remove-ExcelTempFiles $targetDir
Update-CustomUIXml $targetPathFull $customUIPathFull
Update-WorkbookCoreProperties $targetPathFull (Get-RibbonLabelForWorkbook $targetPathFull $customUIPathFull)

$excel = $null
$workbook = $null
$tempTargetPath = Join-Path $targetDir ("_ARCRHO_BETA_build_{0}.xlam" -f ([Guid]::NewGuid().ToString("N")))

try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.EnableEvents = $false
    $excel.ScreenUpdating = $false

    $workbook = $excel.Workbooks.Open($targetPathFull)
    $vbProject = $workbook.VBProject

    # Remove imported modules/classes from the target. Preserve UserForms so
    # their MSForms designer binaries do not get re-imported and DPI-scaled.
    # Document modules such as ThisWorkbook and worksheet modules cannot be
    # removed.
    $toRemove = @()
    foreach ($component in $vbProject.VBComponents) {
        if ($component.Type -ne 100 -and $component.Type -ne 3) {
            $toRemove += $component
        }
    }

    foreach ($component in $toRemove) {
        $vbProject.VBComponents.Remove($component)
    }

    # Replace ThisWorkbook code from the exported document module, if present.
    $thisWorkbookPath = Join-Path $sourceDirFull "ThisWorkbook.cls"
    if (Test-Path -LiteralPath $thisWorkbookPath -PathType Leaf) {
        $thisWorkbook = $vbProject.VBComponents.Item("ThisWorkbook")
        $codeModule = $thisWorkbook.CodeModule
        if ($null -ne $codeModule) {
            if ($codeModule.CountOfLines -gt 0) {
                $codeModule.DeleteLines(1, $codeModule.CountOfLines)
            }
            $codeModule.AddFromFile($thisWorkbookPath)
        }
        else {
            Write-Warning "Could not replace ThisWorkbook code because Excel returned no CodeModule."
        }
    }

    # Import standard modules and class modules first. Existing UserForms are
    # code-refreshed below while preserving their designer state.
    $importPatterns = @("*.bas", "*.cls")
    foreach ($pattern in $importPatterns) {
        Get-ChildItem -LiteralPath $sourceDirFull -Filter $pattern -File |
            Where-Object { $_.Name -ne "ThisWorkbook.cls" } |
            Sort-Object Name |
            ForEach-Object {
                $componentName = Get-VbaComponentName $_
                Write-Host "Importing $($_.Name) as $componentName"
                $component = $vbProject.VBComponents.Import($_.FullName)
                $component.Name = $componentName
            }
    }

    Get-ChildItem -LiteralPath $sourceDirFull -Filter "*.frm" -File |
        Sort-Object Name |
        ForEach-Object {
            $componentName = Get-VbaComponentName $_
            $component = Get-VbaComponentOrNull $vbProject $componentName
            if ($null -eq $component) {
                Write-Warning "Importing new UserForm $($_.Name) as $componentName. Existing forms are preserved, but new forms still rely on Excel's importer."
                $component = $vbProject.VBComponents.Import($_.FullName)
                $component.Name = $componentName
            }
            else {
                Write-Host "Updating UserForm code $($_.Name) as $componentName"
                Replace-CodeModuleFromText $component (Get-CodeTextFromExportedComponent $_.FullName)
            }
        }

    Invoke-WorkbookMacro $excel $workbook "RegisterArcoFunctionHelp"

    $workbook.IsAddin = $true
    $workbook.SaveAs($tempTargetPath, 55)
    $workbook.Close($true)
    $workbook = $null

    Copy-Item -LiteralPath $tempTargetPath -Destination $targetPathFull -Force
    Remove-Item -LiteralPath $tempTargetPath -Force
    Assert-XlamPackage $targetPathFull
    Copy-Item -LiteralPath $notesPathFull -Destination (Get-ReleaseNotesPath $targetPathFull) -Force

    Write-Host "Updated XLAM: $targetPathFull (version $version)"
}
finally {
    if ($null -ne $workbook) {
        $workbook.Close($false)
    }
    if ($null -ne $excel) {
        $excel.Quit()
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null
    }
    if (Test-Path -LiteralPath $tempTargetPath -PathType Leaf) {
        Remove-Item -LiteralPath $tempTargetPath -Force
    }
    Remove-ExcelTempFiles $targetDir
}


