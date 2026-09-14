#requires -Version 5.1
<#
.SYNOPSIS
  Exporta todo o banco de produção (Supabase) para um arquivo JSON portátil.

.DESCRIPTION
  Lê a conexão de producao do arquivo .env.prod (na raiz do projeto), no
  formato: DATABASE_URL=postgresql://usuario:senha@host:porta/postgres

  Gera backups/fintecpessoal_<AAAAMMDD_HHMMSS>.json usando o proprio Django
  (dumpdata), sem precisar de pg_dump. Nao imprime a senha.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\backup_db.ps1
#>

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root ".env.prod"
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}

if (-not (Test-Path -LiteralPath $envFile)) {
    Write-Host "Arquivo .env.prod nao encontrado em: $envFile" -ForegroundColor Red
    Write-Host "Crie o arquivo com uma linha:" -ForegroundColor Yellow
    Write-Host '  DATABASE_URL=postgresql://postgres.<ref>:<senha>@<host>:5432/postgres' -ForegroundColor Yellow
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

$backupDir = Join-Path $root "backups"
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$out = Join-Path $backupDir "fintecpessoal_$stamp.json"

Write-Host "Exportando banco de producao..." -ForegroundColor Cyan
Push-Location $root
try {
    & $python manage.py dumpdata `
        --natural-foreign --natural-primary `
        --exclude contenttypes --exclude auth.permission --exclude sessions `
        --indent 2 -o "$out"
    if ($LASTEXITCODE -ne 0) { throw "dumpdata falhou (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

$size = (Get-Item -LiteralPath $out).Length
Write-Host ("Backup concluido: {0} ({1:N0} bytes)" -f $out, $size) -ForegroundColor Green
