<#
.SYNOPSIS
Starts one GreenLoop component for local development.

.EXAMPLE
.\scripts\dev.ps1                 # orchestrator on http://localhost:8000
.\scripts\dev.ps1 -Service broker # broker on http://localhost:8100
.\scripts\dev.ps1 -Service web    # web on http://localhost:3000
.\scripts\dev.ps1 -Service db     # Postgres + pgvector in Docker
.\scripts\dev.ps1 -Service stack  # rebuild images, start the compose stack, wait for health
.\scripts\dev.ps1 -Service stack -DryRun  # print the command, run nothing

.NOTES
-Service stack always passes --build. `docker compose up --force-recreate` alone
recreates containers from the old image, so code pulled from main never runs.
--wait makes it fail when a service exits at startup, for example on the database
startup check (docs/database-roles.md, Troubleshooting).
#>
param(
    [ValidateSet('orchestrator', 'broker', 'web', 'db', 'stack')]
    [string]$Service = 'orchestrator',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'

$commands = @{
    orchestrator = @{ Dir = 'services\orchestrator'; Exe = $python; Args = @('-m', 'uvicorn', 'app.main:app', '--reload', '--port', '8000') }
    broker       = @{ Dir = 'services\broker'; Exe = $python; Args = @('-m', 'uvicorn', 'app.main:app', '--reload', '--port', '8100') }
    web          = @{ Dir = 'apps\web'; Exe = 'npm.cmd'; Args = @('run', 'dev') }
    db           = @{ Dir = '.'; Exe = 'docker'; Args = @('compose', 'up', '-d', 'db') }
    stack        = @{ Dir = '.'; Exe = 'docker'; Args = @('compose', 'up', '-d', '--build', '--wait') }
}
$command = $commands[$Service]

if ($DryRun) {
    Write-Host "dir=$($command.Dir) command=$(Split-Path -Leaf $command.Exe) $($command.Args -join ' ')"
    exit 0
}

if ($command.Exe -eq $python -and -not (Test-Path $python)) {
    throw 'Missing .venv. Create it with: py -3.12 -m venv .venv'
}
if ($command.Exe -eq 'docker') {
    $ErrorActionPreference = 'Continue'
    docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Docker is not running. Start Docker Desktop and retry.' }
}

Set-Location (Join-Path $root $command.Dir)
if ($Service -eq 'web' -and -not (Test-Path 'node_modules')) { npm.cmd ci }
$arguments = $command.Args
& $command.Exe @arguments
if ($Service -eq 'stack' -and $LASTEXITCODE -ne 0) {
    throw 'The stack did not come up healthy. See why with: docker compose logs orchestrator broker'
}
