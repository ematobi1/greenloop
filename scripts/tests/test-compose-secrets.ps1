<#
.SYNOPSIS
Checks docker-compose.yml gives each service only its own secrets (ADR 0009 rule 1):
no env_file, the orchestrator never gets the broker's or the superuser's database
password, the broker never gets the orchestrator's secrets, and the broker has no
host port. Reads the file only; starts nothing.
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $root '.venv\Scripts\python.exe'
$compose = Join-Path $root 'docker-compose.yml'

$check = Join-Path $PSScriptRoot 'check_compose_secrets.py'

$output = & $python $check $compose 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) {
    $output.Trim() -split "`r?`n" | ForEach-Object { Write-Host "FAIL: $_" }
    exit 1
}
Write-Host 'compose-secrets: 1 passed'
