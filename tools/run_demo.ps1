# Start the open-ended demo with its own save database.
param(
    [switch]$Stub,
    [switch]$BackendOnly,
    [int]$Port = 8767,
    [string]$GodotPath = $env:GODOT
)
$ErrorActionPreference = 'Stop'
$demoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $demoRoot 'backend/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Backend dependencies are missing. Run: uv sync --native-tls --project backend'
}
if (-not $GodotPath) {
    $GodotPath = 'C:\Users\Burry\Downloads\Godot_v4.7.2-stable_win64.exe\Godot_v4.7.2-stable_win64_console.exe'
}
if (-not $BackendOnly -and -not (Test-Path -LiteralPath $GodotPath)) {
    throw 'Set GODOT or pass -GodotPath with the path to your Godot executable.'
}
$server = "http://127.0.0.1:$Port"
$health = $null
try { $health = Invoke-RestMethod "$server/health" -TimeoutSec 2 } catch {}
if ($health -and ($health.seed_version -ne 14 -or $health.rules_revision -ne 'D-62')) {
    throw "Port $Port is running a different simulation. Choose another port with -Port."
}
if (-not $health) {
    $savedDatabase = $env:DATABASE_PATH
    $savedMode = $env:AI_MODE
    try {
        $env:DATABASE_PATH = Join-Path $demoRoot 'data/open-ended-demo.sqlite3'
        $env:AI_MODE = if ($Stub) { 'stub' } else { 'live' }
        Remove-Item Env:SSLKEYLOGFILE -ErrorAction SilentlyContinue
        $backend = Join-Path $demoRoot 'backend'
        $process = Start-Process -FilePath $python -WorkingDirectory $demoRoot -WindowStyle Hidden -PassThru `
            -ArgumentList @('-m', 'uvicorn', 'app:app', '--app-dir', "`"$backend`"", '--host', '127.0.0.1', '--port', "$Port") `
            -RedirectStandardOutput (Join-Path $demoRoot "data/demo-$Port.log") `
            -RedirectStandardError (Join-Path $demoRoot "data/demo-$Port-errors.log")
        Set-Content -LiteralPath (Join-Path $demoRoot "data/demo-$Port.pid") -Value $process.Id
    } finally {
        $env:DATABASE_PATH = $savedDatabase
        $env:AI_MODE = $savedMode
    }
    for ($try = 0; $try -lt 40 -and -not $health; $try++) {
        Start-Sleep -Milliseconds 250
        try { $health = Invoke-RestMethod "$server/health" -TimeoutSec 2 } catch {}
        if ($process.HasExited) { break }
    }
}
if (-not $health) { throw "Backend failed to start. Read data/demo-$Port-errors.log." }
$wantedMode = if ($Stub) { 'stub' } else { 'live' }
if ($health.ai.mode -ne $wantedMode -or -not $health.ai.judge) {
    throw "The demo needs AI mode '$wantedMode'. Configure OPENAI_API_KEY in backend/.env for live play, or use -Stub for pipeline checks. Restart this launcher-owned backend after changing its configuration."
}
if (-not $Stub) {
    $readiness = Invoke-RestMethod "$server/health/ai" -TimeoutSec 7
    if (-not $readiness.ready) {
        throw "Live AI is unavailable: $($readiness.reason). Update backend/.env and restart this launcher-owned backend. Use -Stub for offline verification."
    }
}
Write-Output "Demo backend ready at $server ($wantedMode, rules D-62, seed 14)."
Write-Output 'Demo saves: data/open-ended-demo.sqlite3; your original data/demo.sqlite3 is preserved.'
if (-not $BackendOnly) {
    # The game is the interactive application the user requested.
    Start-Process -FilePath $GodotPath -WorkingDirectory $demoRoot `
        -ArgumentList @('--path', "`"$demoRoot`"", '--', "--server=$server") | Out-Null
}
