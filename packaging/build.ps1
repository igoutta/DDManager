#Requires -Version 5.1
<#
.SYNOPSIS
  Build the frozen "DD Manager" app and the portable release zip.

.DESCRIPTION
  Ported from the v0.2.x build.ps1 (same output layout and zip naming), minus the Tcl/Tk
  bundling. Steps: render the Windows version resource, run PyInstaller with
  packaging/ddmanager.spec, self-test the frozen exe, assemble "release/DD Manager Portable/",
  and zip it as "release/DD Manager Portable <version>.zip".

  Run from the repo root (or via `just build`). Requires uv with the build group synced:
      uv sync --group dev --group build
#>

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$appName = "DD Manager"
$distRoot = Join-Path $root "dist"
$distAppDir = Join-Path $distRoot $appName
$buildRoot = Join-Path $root "build"
$releaseRoot = Join-Path $root "release"
$portableName = "$appName Portable"
$portableDir = Join-Path $releaseRoot $portableName
$portableDataDir = Join-Path $portableDir "$appName Data"
$iconCacheDir = Join-Path $portableDataDir "icon_cache"
$zipAttemptCount = 5

# ---- version --------------------------------------------------------------------------
$appVersion = (uv run python -c "from src.__about__ import __version__; print(__version__)").Trim()
if ([string]::IsNullOrWhiteSpace($appVersion)) { throw "Could not read src/__about__.py version." }

$releaseVersion = $env:GITHUB_REF_NAME
if ([string]::IsNullOrWhiteSpace($releaseVersion)) {
    try { $releaseVersion = (git describe --tags --exact-match 2>$null).Trim() } catch { $releaseVersion = "" }
}
if ([string]::IsNullOrWhiteSpace($releaseVersion)) { $releaseVersion = "v$appVersion" }

$portableZip = Join-Path $releaseRoot "$portableName $releaseVersion.zip"

# numeric parts for VERSIONINFO (pre-release suffixes like 0.3.0a1 are stripped)
$numeric = ($appVersion -replace '[^0-9.].*$', '').Split('.')
while ($numeric.Count -lt 3) { $numeric += "0" }
New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
$template = Get-Content -LiteralPath (Join-Path $PSScriptRoot "version_info.tmpl") -Raw
$rendered = $template.Replace("{major}", $numeric[0]).Replace("{minor}", $numeric[1]).Replace("{patch}", $numeric[2]).Replace("{version}", $appVersion)
Set-Content -LiteralPath (Join-Path $buildRoot "version_info.txt") -Value $rendered -Encoding UTF8

# ---- PyInstaller ----------------------------------------------------------------------
if (Test-Path $distAppDir) { Remove-Item -LiteralPath $distAppDir -Recurse -Force }
uv run pyinstaller --noconfirm --clean --distpath $distRoot --workpath (Join-Path $buildRoot "pyinstaller") (Join-Path $PSScriptRoot "ddmanager.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE." }
if (-not (Test-Path $distAppDir)) { throw "Build finished but could not find $distAppDir." }

# ---- self-test the frozen exe ---------------------------------------------------------
$selfTestData = Join-Path $env:TEMP "ddm-selftest"
if (Test-Path $selfTestData) { Remove-Item -LiteralPath $selfTestData -Recurse -Force }
& (Join-Path $distAppDir "$appName.exe") --self-test --data-dir $selfTestData
if ($LASTEXITCODE -ne 0) { throw "Frozen self-test failed with exit code $LASTEXITCODE." }

# ---- portable folder + zip (same layout as v0.2.x) ------------------------------------
if (Test-Path $portableDir) { Remove-Item -LiteralPath $portableDir -Recurse -Force }
if (Test-Path $portableZip) { Remove-Item -LiteralPath $portableZip -Force }
New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
Copy-Item -LiteralPath $distAppDir -Destination $portableDir -Recurse
New-Item -ItemType Directory -Path $iconCacheDir -Force | Out-Null

Copy-Item -LiteralPath (Join-Path $root "README.md") -Destination (Join-Path $portableDir "README.md") -Force
Set-Content -LiteralPath (Join-Path $portableDataDir "README.txt") -Value @(
    "This folder holds DD Manager's portable local data (state, profiles, backups, logs)."
    ""
    "Extracting a newer release over this folder keeps your data: the zip never contains mod_state.json."
)
Set-Content -LiteralPath (Join-Path $iconCacheDir ".keep") -Value ""

$stateLeak = Get-ChildItem -LiteralPath $portableDir -Recurse -Filter "mod_state*.json" -ErrorAction SilentlyContinue
if ($stateLeak) { throw "Refusing to package user state: $($stateLeak.FullName -join ', ')" }

$zipComplete = $false
for ($attempt = 1; $attempt -le $zipAttemptCount; $attempt++) {
    try {
        Compress-Archive -LiteralPath $portableDir -DestinationPath $portableZip -CompressionLevel Optimal
        $zipComplete = $true
        break
    }
    catch {
        if (Test-Path $portableZip) { Remove-Item -LiteralPath $portableZip -Force -ErrorAction SilentlyContinue }
        if ($attempt -eq $zipAttemptCount) { throw }
        Start-Sleep -Seconds 2
    }
}
if (-not $zipComplete) { throw "Failed to create $portableZip." }

Write-Host ""
Write-Host "Build complete:"
Write-Host "  app:      $distAppDir"
Write-Host "  portable: $portableDir"
Write-Host "  zip:      $portableZip"
