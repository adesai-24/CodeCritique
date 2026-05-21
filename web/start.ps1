# Start the CodeCritique web server
# Run from the repo root:  .\web\start.ps1

$venv = Join-Path $PSScriptRoot ".." ".venv" "Scripts" "python.exe"
$venv = (Resolve-Path $venv).Path

& $venv -m uvicorn web.main:app --reload --port 8000 --app-dir (Split-Path $PSScriptRoot)
