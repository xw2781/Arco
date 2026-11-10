param(
    [string]$OutputPath = "E:\Arco Server\Excel Add-ins\Arco Add-in Setup.exe"
)

# Compiles excel-addin/setup_app into the small installer that sits beside
# Arco.xlam on the share. Uses the C# compiler that ships with Windows.

$ErrorActionPreference = "Stop"

$sourcePath = Join-Path $PSScriptRoot "..\setup_app\ArcoAddinSetup.cs"
$compilerPath = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"

& $compilerPath /nologo /target:winexe /optimize+ /platform:anycpu `
    /r:System.Windows.Forms.dll /r:System.Drawing.dll `
    "/out:$OutputPath" $sourcePath
if ($LASTEXITCODE -ne 0) {
    throw "Arco Add-in Setup did not compile."
}

Write-Host "Built $OutputPath"
