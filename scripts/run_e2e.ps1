# Master script: Restart server + run E2E pipeline test
# Usage: .\scripts\run_e2e.ps1
$root = "C:\Users\ADMIN\e-learning-backend"

# Step 1: Restart server (uses separate script to avoid length limit)
Write-Host "=== RESTARTING SERVER ==="
& "$root\scripts\server_restart.ps1"

# Step 2: Run E2E test
Write-Host "`n=== RUNNING E2E PIPELINE TEST ==="
$env:PYTHONPATH = $root
& "$root\.venv\Scripts\python.exe" "$root\scripts\e2e_pipeline_test.py"
