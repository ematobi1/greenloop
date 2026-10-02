<#
.SYNOPSIS
Creates the greenloop_orchestrator and greenloop_broker login roles and their schemas
(ADR 0009). Running it again rotates both passwords.

.DESCRIPTION
Runs scripts/db/bootstrap-roles.sql in one transaction inside the Postgres container,
as the image's superuser over the local socket, so no superuser password is needed.

Each role password comes from ORCHESTRATOR_DB_PASSWORD / BROKER_DB_PASSWORD when set,
otherwise from a hidden prompt (asked twice). Passwords must be at least 16
characters. They reach psql through `docker exec -e NAME` and psql's :'variable'
quoting, so they never appear on a command line, in the SQL text, in psql output or
in the server log.

After a rotation, update the matching values in your .env and restart the services.

.EXAMPLE
.\scripts\db-bootstrap.ps1                          # compose "db" service, prompts
.\scripts\db-bootstrap.ps1 -DryRun                  # print the plan, touch nothing
#>
param(
    [string]$Container,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'db\common.ps1')
$sqlPath = Join-Path $PSScriptRoot 'db\bootstrap-roles.sql'
$passwordVariables = 'ORCHESTRATOR_DB_PASSWORD', 'BROKER_DB_PASSWORD'
$minimumLength = 16

function ConvertFrom-Secure([Security.SecureString]$Value) {
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Read-RolePassword([string]$Label) {
    $plain = ConvertFrom-Secure (Read-Host "Password for $Label (hidden)" -AsSecureString)
    $repeat = ConvertFrom-Secure (Read-Host "Repeat the password for $Label" -AsSecureString)
    if ($plain -cne $repeat) { throw "The two passwords for $Label do not match." }
    return $plain
}

$sources = @{}
foreach ($name in $passwordVariables) {
    $sources[$name] = if ([Environment]::GetEnvironmentVariable($name)) { 'environment' } else { 'prompt' }
}

if ($DryRun) {
    $target = if ($Container) { $Container } else { 'compose service db' }
    Write-Host "target=$target sql=$sqlPath"
    foreach ($name in $passwordVariables) { Write-Host "$name=$($sources[$name])" }
    exit 0
}

$saved = @{}
foreach ($name in $passwordVariables) { $saved[$name] = [Environment]::GetEnvironmentVariable($name) }
try {
    foreach ($name in $passwordVariables) {
        if ($sources[$name] -eq 'prompt') {
            $role = if ($name -like 'ORCHESTRATOR*') { 'greenloop_orchestrator' } else { 'greenloop_broker' }
            Set-Item "env:$name" (Read-RolePassword $role)
        }
        if ([Environment]::GetEnvironmentVariable($name).Length -lt $minimumLength) {
            throw "$name must be at least $minimumLength characters."
        }
    }

    $ErrorActionPreference = 'Continue'
    $target = Resolve-DbContainer $root $Container
    # psql interpolates :'variable' client side, so the set_config statements carry the
    # password: logging goes off first. \o /dev/null hides set_config's echoed result.
    $script = @(
        'BEGIN;'
        "SET log_statement = 'none';"
        'SET log_min_duration_statement = -1;'
        "SET log_min_error_statement = 'panic';"
        "SET log_min_messages = 'panic';"
        '\getenv orchestrator_password ORCHESTRATOR_DB_PASSWORD'
        '\getenv broker_password BROKER_DB_PASSWORD'
        '\o /dev/null'
        "SELECT set_config('greenloop.orchestrator_password', :'orchestrator_password', false);"
        "SELECT set_config('greenloop.broker_password', :'broker_password', false);"
        '\o'
        '\unset orchestrator_password'
        '\unset broker_password'
        (Get-Content -Raw $sqlPath)
        'COMMIT;'
    ) -join "`n"
    $code = Invoke-ContainerPsql $target $script $passwordVariables
    if ($code -ne 0) { throw 'Bootstrap failed; nothing was committed.' }
    Write-Host 'Roles greenloop_orchestrator and greenloop_broker are ready; schemas public and broker are owned by them.'
} finally {
    foreach ($name in $passwordVariables) {
        if ($saved[$name]) { Set-Item "env:$name" $saved[$name] } else { Remove-Item "env:$name" -ErrorAction SilentlyContinue }
    }
}
