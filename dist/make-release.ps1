# Cut a new Smiteless release so your brother's copy can update itself.
#
#   powershell -ExecutionPolicy Bypass -File dist\make-release.ps1 -Version 1.1.0 [-Notes "what changed"]
#
# It bumps VERSION, builds SmitelessSetup.exe, commits, tags, and publishes a GitHub Release
# with the installer attached. The installed app checks that release and offers the update.
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Notes = "",
    [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent
$ver  = $Version.TrimStart('v')

Write-Host "==> set VERSION = $ver" -ForegroundColor Cyan
[IO.File]::WriteAllText((Join-Path $repo "VERSION"), $ver)

Write-Host "==> build" -ForegroundColor Cyan
& (Join-Path $PSScriptRoot "build.ps1") -Python $Python
$setup = Join-Path $repo "build\SmitelessSetup.exe"
if (-not (Test-Path $setup)) { throw "build did not produce SmitelessSetup.exe" }

Write-Host "==> commit + push VERSION" -ForegroundColor Cyan
git -C $repo add VERSION
git -C $repo commit -m "Release v$ver"
git -C $repo push origin main

Write-Host "==> publish GitHub release v$ver" -ForegroundColor Cyan
if (-not $Notes) { $Notes = "Smiteless v$ver" }
gh release create "v$ver" $setup --repo bobbyroylee/smiteless --title "Smiteless v$ver" --notes $Notes

Write-Host "`nReleased v$ver. Installed copies will offer the update on next launch." -ForegroundColor Green
