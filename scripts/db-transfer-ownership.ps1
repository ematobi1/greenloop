<#
.SYNOPSIS
One-time step for an existing database: moves every object in schema public to
greenloop_orchestrator (ADR 0009, decision B). Run db-bootstrap.ps1 first.

.DESCRIPTION
Runs scripts/db/transfer-public-ownership.sql in one transaction inside the Postgres
container, as the image's superuser over the local socket. No password is involved.
The SQL refuses to commit if any object in public is left with another owner.
Idempotent: a second run changes nothing.

Take a pg_dump backup first. It asks you to type "yes" unless -Yes is given.

.EXAMPLE
.\scripts\db-transfer-ownership.ps1             # compose "db" service
.\scripts\db-transfer-ownership.ps1 -DryRun     # print the plan, touch nothing
#>
param(
    [string]$Container,
    [switch]$Yes,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'db\common.ps1')
$sqlPath = Join-Path $PSScriptRoot 'db\transfer-public-ownership.sql'

if ($DryRun) {
    $target = if ($Container) { $Container } else { 'compose service db' }
    Write-Host "target=$target sql=$sqlPath"
    exit 0
}

if (-not $Yes) {
    $answer = Read-Host 'Move every object in schema public to greenloop_orchestrator? A pg_dump backup should exist. Type yes'
    if ($answer -cne 'yes') { Write-Host 'Nothing changed.'; exit 1 }
}

$ErrorActionPreference = 'Continue'
$target = Resolve-DbContainer $root $Container
$script = @('BEGIN;', (Get-Content -Raw $sqlPath), 'COMMIT;') -join "`n"
$code = Invoke-ContainerPsql $target $script
if ($code -ne 0) { throw 'Ownership transfer failed; nothing was committed.' }
Write-Host 'Every object in public is now owned by greenloop_orchestrator.'
Write-Host 'Next: point DATABASE_URL in .env at greenloop_orchestrator and restart the orchestrator.'
