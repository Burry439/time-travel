$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendPath = Join-Path $projectRoot 'backend'
$listener = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $listener) {
    Write-Output 'Game backend is already stopped.'
    exit 0
}
$processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
if (-not $processInfo -or -not $processInfo.CommandLine.Contains($backendPath) -or -not $processInfo.CommandLine.Contains('uvicorn')) {
    throw 'Port 8765 belongs to an unrecognized process; no process was stopped.'
}
Stop-Process -Id $listener.OwningProcess
Write-Output "Stopped game backend (PID $($listener.OwningProcess))."
