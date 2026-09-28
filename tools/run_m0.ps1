$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$healthUrl = 'http://127.0.0.1:8765/health'
try {
    $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
    if ($health.status -eq 'ok') {
        Write-Output 'Game backend is already healthy on http://127.0.0.1:8765.'
        exit 0
    }
} catch {}

$uvExecutable = (Get-Command uv -ErrorAction Stop).Source
$dataDir = Join-Path $projectRoot 'data'
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
$backendPath = Join-Path $projectRoot 'backend'
$arguments = @('run', '--native-tls', '--project', $backendPath,
               'uvicorn', 'app:app', '--app-dir', $backendPath,
               '--host', '127.0.0.1', '--port', '8765')
# A TLS key-log pipe inherited from some shells breaks every HTTPS call the backend makes.
Remove-Item Env:SSLKEYLOGFILE -ErrorAction SilentlyContinue
$process = Start-Process -FilePath $uvExecutable -ArgumentList $arguments `
    -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $dataDir 'backend.log') `
    -RedirectStandardError (Join-Path $dataDir 'backend-errors.log')
Set-Content -LiteralPath (Join-Path $dataDir 'backend.pid') -Value $process.Id
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Milliseconds 500
    try {
        $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
        if ($health.status -eq 'ok') {
            Write-Output "Game backend ready on http://127.0.0.1:8765 (PID $($process.Id))."
            exit 0
        }
    } catch {}
    if ($process.HasExited) { break }
}
throw "Backend did not become healthy. Read data/backend-errors.log."
