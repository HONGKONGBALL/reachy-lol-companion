# Alternative to the official Reachy Mini Control daemon; do not run both.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run setup.ps1 first.' }
if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Port 8000 is in use. Keep the existing Reachy Mini Control daemon; do not start another.'
}
& $taskPython -m reachy_mini.daemon.app.main --no-media --serialport auto --fastapi-host 127.0.0.1 --no-wake-up-on-start
