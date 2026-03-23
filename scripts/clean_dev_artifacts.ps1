# Remove Python caches, pytest cache, stray artifacts, and generated pipeline outputs.
# Run:  powershell -File backend/scripts/clean_dev_artifacts.ps1  (from repo root)
# Or:   powershell -File scripts/clean_dev_artifacts.ps1            (from backend/)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "Cleaning under: $root"

Get-ChildItem -Path $root -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Get-ChildItem -Path $root -Recurse -Include "*.pyc","*.pyo" -File -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

$pytestCache = Join-Path $root ".pytest_cache"
if (Test-Path $pytestCache) {
    Remove-Item -Recurse -Force $pytestCache
    Write-Host "Removed .pytest_cache"
}

$outputs = Join-Path $root "data\outputs"
if (Test-Path $outputs) {
    Get-ChildItem -Path $outputs -File -ErrorAction SilentlyContinue | Remove-Item -Force
    Write-Host "Emptied data/outputs"
}

$junk = @(
    (Join-Path $root "0.0.9"),
    (Join-Path $root "agent_logs.txt")
)
foreach ($f in $junk) {
    if (Test-Path $f) {
        Remove-Item -Force $f
        Write-Host "Removed $f"
    }
}

Write-Host "Done."
