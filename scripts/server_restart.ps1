# Permanently solves PowerShell 5.1 965-byte command limit
# Usage: .\scripts\server_restart.ps1
$root = "C:\Users\ADMIN\e-learning-backend"

Write-Host "Killing Python..."
Get-Process -Name python -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
Start-Sleep 3

Write-Host "Clearing all .pyc and __pycache__..."
Get-ChildItem -Path $root -Recurse -Include *.pyc -EA SilentlyContinue | Remove-Item -Force -EA SilentlyContinue
Get-ChildItem -Path $root -Recurse -Directory -Filter __pycache__ -EA SilentlyContinue | Remove-Item -Recurse -Force -EA SilentlyContinue

Write-Host "Starting server..."
$env:PYTHONPATH = $root
Start-Process -FilePath "$root\.venv\Scripts\python.exe" `
  -ArgumentList "$root\scripts\run_server.py" `
  -NoNewWindow -PassThru `
  -RedirectStandardOutput "$root\server_stdout.log" `
  -RedirectStandardError "$root\server_stderr.log"

Write-Host "Waiting for server..."
$maxWait = 30
for ($i = 1; $i -le $maxWait; $i++) {
    Start-Sleep 2
    try {
        $r = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/health" -TimeoutSec 3
        Write-Host "Server UP after $($i*2)s"
        break
    } catch {
        if ($i -eq $maxWait) {
            Write-Host "Server failed to start after ${maxWait}s"
            Get-Content "$root\server_stderr.log" -Tail 10 -EA SilentlyContinue
        }
    }
}
