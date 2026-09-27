<#
.SYNOPSIS
Starts one GreenLoop component for local development.

.EXAMPLE
.\scripts\dev.ps1                 # orchestrator on http://localhost:8000
.\scripts\dev.ps1 -Service broker # broker on http://localhost:8100
.\scripts\dev.ps1 -Service web    # web on http://localhost:3000
.\scripts\dev.ps1 -Service db     # Postgres + pgvector in Docker
#>
param(
    [ValidateSet('orchestrator', 'broker', 'web', 'db')]
    [string]$Service = 'orchestrator'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'

function Assert-Venv {
    if (-not (Test-Path $python)) { throw 'Missing .venv. Create it with: py -3.12 -m venv .venv' }
}

switch ($Service) {
    'orchestrator' {
        Assert-Venv
        Set-Location (Join-Path $root 'services\orchestrator')
        & $python -m uvicorn app.main:app --reload --port 8000
    }
    'broker' {
        Assert-Venv
        Set-Location (Join-Path $root 'services\broker')
        & $python -m uvicorn app.main:app --reload --port 8100
    }
    'web' {
        Set-Location (Join-Path $root 'apps\web')
        if (-not (Test-Path 'node_modules')) { npm.cmd ci }
        npm.cmd run dev
    }
    'db' {
        $ErrorActionPreference = 'Continue'
        docker info *> $null
        if ($LASTEXITCODE -ne 0) { throw 'Docker is not running. Start Docker Desktop and retry.' }
        Set-Location $root
        docker compose up -d db
    }
}
