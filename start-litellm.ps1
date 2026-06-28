# Start LiteLLM proxy for local LLM setup
# This script must run WITHOUT the app's DATABASE_URL env var

$env:PYTHONIOENCODING = "utf-8"
$env:DATABASE_URL = ""
$env:DATABASE_URL_SYNC = ""

# Activate venv
. "$PSScriptRoot\.venv-1\Scripts\Activate.ps1"

Write-Host "Starting LiteLLM proxy on http://localhost:4000"
Write-Host "Ollama backend: http://localhost:11434"
Write-Host "Press Ctrl+C to stop"
Write-Host ""

litellm --config D:\litellm_config.yaml --port 4000
