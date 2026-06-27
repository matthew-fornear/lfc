# Deobfuscate a fetched DataDome challenge JS bundle
param(
    [Parameter(Mandatory = $true)]
    [string]$InputJs,
    [string]$BundleType = "interstitial"  # interstitial | captcha
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Deob = Join-Path $Root "new-datadome-deobfuscator"
$Out = Join-Path $Root "captures\deobfuscated\$BundleType"

New-Item -ItemType Directory -Force -Path $Out | Out-Null

Push-Location $Deob
node bin/cli.js $InputJs "$Out/" --report "$Out/report.json"
Pop-Location

Write-Host "Report: $Out\report.json"
Write-Host "Extract WASM: node scripts\run_wasm.js `"$Out\report.json`""
