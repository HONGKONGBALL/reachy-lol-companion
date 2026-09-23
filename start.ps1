param(
    [ValidateRange(1024,65535)][int]$Port = 8768,
    [switch]$OpenBrowser
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run setup.ps1 first.' }
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $Port is already in use. Use the existing page or choose -Port 8770."
}
$env:REACHY_LOL_PORT = [string]$Port
Write-Host "Frontend and backend: http://127.0.0.1:$Port/"
Write-Host 'Keep this window open. Press Ctrl+C to stop the service.'
if ($OpenBrowser) { Start-Process "http://127.0.0.1:$Port/" }
& $taskPython -m uvicorn reachy_lol.app:app --host 127.0.0.1 --port $Port
if ($LASTEXITCODE -ne 0) { throw 'Backend stopped with an error.' }
