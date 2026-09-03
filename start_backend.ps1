Set-Location -Path $PSScriptRoot
Write-Host "Starting FraudShield Backend on http://localhost:8000..." -ForegroundColor Cyan

$VenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    & $VenvPython run_server.py
} else {
    python run_server.py
}
