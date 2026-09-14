#requires -Version 5.1
<#
.SYNOPSIS
  Restaura um backup JSON em um banco (ex.: nova conta Supabase).

.DESCRIPTION
  Le a conexao de destino de .env.prod, aplica as migracoes e carrega o JSON
  indicado. Nao imprime a senha.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\restore_db.ps1 -Backup backups\fintecpessoal_20260101_120000.json
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$Backup
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root ".env.prod"
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) { $python = "python" }
if (-not (Test-Path -LiteralPath $envFile)) {
    Write-Host "Arquivo .env.prod nao encontrado em: $envFile" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path -LiteralPath $Backup)) {
    Write-Host "Backup nao encontrado: $Backup" -ForegroundColor Red
    exit 1
}

$dbUrl = (Get-Content -LiteralPath $envFile | Where-Object { $_ -match '^\s*DATABASE_URL\s*=' } | Select-Object -First 1)
if (-not $dbUrl) {
    Write-Host "DATABASE_URL nao encontrada dentro de .env.prod" -ForegroundColor Red
    exit 1
}
$dbUrl = ($dbUrl -replace '^\s*DATABASE_URL\s*=\s*', '').Trim().Trim('"').Trim("'")

$env:DATABASE_URL = $dbUrl
$env:DJANGO_SETTINGS_MODULE = "config.settings.production"

Push-Location $root
try {
    Write-Host "Aplicando migracoes no banco de destino..." -ForegroundColor Cyan
    & $python manage.py migrate --noinput
    if ($LASTEXITCODE -ne 0) { throw "migrate falhou (exit $LASTEXITCODE)" }

    Write-Host "Carregando dados do backup..." -ForegroundColor Cyan
    & $python manage.py loaddata "$Backup"
    if ($LASTEXITCODE -ne 0) { throw "loaddata falhou (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

Write-Host "Restauracao concluida." -ForegroundColor Green
