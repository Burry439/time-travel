# Every automatic check in one command (GDD D-58).
#   ./tools/check.ps1          lint (ruff, gdlint), compile every GDScript, backend tests. About a minute.
#   ./tools/check.ps1 -Full    also every Godot smoke test, against a throwaway stub backend on port 8766 with its
#                              own database (your game on 8765 and data/demo.sqlite3 are never touched).
# The pre-commit hook (.githooks/pre-commit) runs the fast part. Set GODOT to your Godot console executable if it
# isn't at the default path below.
param([switch]$Full)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$bin = Join-Path $root 'backend/.venv/Scripts'
$godot = if ($env:GODOT) { $env:GODOT } else { 'C:\Users\Burry\Downloads\Godot_v4.7.2-stable_win64.exe\Godot_v4.7.2-stable_win64_console.exe' }
$failed = @()

function Step([string]$name, [scriptblock]$run) {
    Write-Output "== $name"
    & $run
    if ($LASTEXITCODE -ne 0) { $script:failed += $name; Write-Output "   FAILED: $name" }
}

Push-Location $root
try {
    Step 'ruff check' { & (Join-Path $bin 'ruff.exe') check backend --quiet }
    Step 'ruff format' { & (Join-Path $bin 'ruff.exe') format --check backend 2>&1 | Select-Object -Last 2 }
    Step 'gdlint' { & (Join-Path $bin 'gdlint.exe') scripts tools 2>&1 | Select-Object -Last 3 }
    Step 'GDScript compiles' { & $godot --headless --path $root --script res://tools/check_scripts.gd 2>&1 |
        Select-String 'CHECK SCRIPTS' }
    Push-Location (Join-Path $root 'backend')
    try { Step 'backend tests' { & (Join-Path $bin 'python.exe') -m pytest -q -p no:cacheprovider 2>&1 | Select-Object -Last 2 } }
    finally { Pop-Location }

    if ($Full) {
        $port = 8766
        $db = Join-Path ([IO.Path]::GetTempPath()) "time-travel-check-$PID.sqlite3"
        $env:AI_MODE = 'stub'
        $env:DATABASE_PATH = $db
        $env:GAME_SERVER = "http://127.0.0.1:$port"
        Remove-Item Env:SSLKEYLOGFILE -ErrorAction SilentlyContinue
        $uv = (Get-Command uv -ErrorAction Stop).Source
        $backend = Start-Process -FilePath $uv -PassThru -WindowStyle Hidden -WorkingDirectory $root -ArgumentList @(
            'run', '--native-tls', '--project', (Join-Path $root 'backend'), 'uvicorn', 'app:app',
            '--app-dir', (Join-Path $root 'backend'), '--host', '127.0.0.1', '--port', "$port")
        try {
            $ready = $false
            for ($i = 0; $i -lt 40 -and -not $ready; $i++) {
                Start-Sleep -Milliseconds 500
                try { $ready = (Invoke-RestMethod "http://127.0.0.1:$port/health" -TimeoutSec 2).status -eq 'ok' } catch {}
            }
            if (-not $ready) { throw "The stub backend on port $port didn't start." }
            foreach ($smoke in Get-ChildItem (Join-Path $root 'tools') -Filter 'smoke_*.gd' | Sort-Object Name) {
                $name = $smoke.BaseName
                $out = Join-Path ([IO.Path]::GetTempPath()) "check-$name.txt"
                $proc = Start-Process -FilePath $godot -NoNewWindow -Wait -PassThru -RedirectStandardOutput $out `
                    -RedirectStandardError "$out.err" -ArgumentList @('--path', $root, '--script', "res://tools/$($smoke.Name)")
                if ($proc.ExitCode -eq 0) { Write-Output "   $name passed" }
                else {
                    $failed += $name
                    Write-Output "   FAILED: $name"
                    Get-Content "$out.err" | Select-String 'FAILED|SCRIPT ERROR' | Select-Object -First 3
                }
            }
        }
        finally {
            & taskkill /PID $backend.Id /T /F *> $null
            Remove-Item Env:AI_MODE, Env:DATABASE_PATH, Env:GAME_SERVER -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 500
            Remove-Item $db, "$db-wal", "$db-shm" -ErrorAction SilentlyContinue
        }
    }
}
finally { Pop-Location }

if ($failed.Count -gt 0) {
    Write-Output "CHECK FAILED: $($failed -join ', ')"
    exit 1
}
Write-Output 'CHECK PASSED'
exit 0
