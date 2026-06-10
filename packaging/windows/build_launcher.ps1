$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Resolve-Path (Join-Path $scriptDir "..\..")
$source = Join-Path $scriptDir "AutoTitrationLauncher.cs"
$outDir = Join-Path $root "dist\release"
$outExe = Join-Path $outDir "AutoTitration.exe"

New-Item -ItemType Directory -Force -Path $outDir | Out-Null

Add-Type `
  -TypeDefinition (Get-Content $source -Raw) `
  -ReferencedAssemblies System.Windows.Forms `
  -OutputAssembly $outExe `
  -OutputType WindowsApplication

Write-Host "Built $outExe"
