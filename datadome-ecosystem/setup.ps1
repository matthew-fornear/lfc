# One-time setup for the glizzykingdreko DataDome RE ecosystem
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

Write-Host "=== DataDome ecosystem setup ===" -ForegroundColor Cyan

Push-Location "$Root\new-datadome-deobfuscator"
npm install
Pop-Location

Push-Location "$Root\datadome-encryption"
npm install
Pop-Location

pip install -e "$Root\datadome-encryption-python"
pip install -r "$Root\requirements.txt"

Write-Host "`nVerifying..." -ForegroundColor Cyan
Push-Location "$Root\datadome-wasm"
node wasm.js
Pop-Location

Push-Location "$Root\datadome-encryption-python\tests"
python test.py
Pop-Location

Push-Location "$Root\datadome-encryption"
npm test
Pop-Location

Write-Host "`nSetup complete. Run: python scripts\pipeline.py --help" -ForegroundColor Green
