# التحقق من اكتمال تهجيرات Alembic (public + تينانت)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$env:FLASK_APP = "app:create_app"

Write-Host "=== Alembic heads ===" -ForegroundColor Cyan
& .\.venv\Scripts\flask.exe db heads

Write-Host "`n=== Alembic current (DB) ===" -ForegroundColor Cyan
& .\.venv\Scripts\flask.exe db current

Write-Host "`n=== db-verify ===" -ForegroundColor Cyan
& .\.venv\Scripts\flask.exe db-verify

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "`nOK: migrations check passed." -ForegroundColor Green
