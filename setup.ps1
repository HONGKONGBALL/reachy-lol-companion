$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    & py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 x64 with the Python launcher first.' }
}
& $taskPython -m pip install -e '.[dev]'
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the error above.' }
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
if (-not (Test-Path -LiteralPath 'preferences.json')) { Copy-Item -LiteralPath 'preferences.example.json' -Destination 'preferences.json' }
New-Item -ItemType Directory -Force -Path 'evidence' | Out-Null
Write-Host 'Setup complete. Fill API keys in .env locally, connect Reachy Mini, then run start.ps1.'
