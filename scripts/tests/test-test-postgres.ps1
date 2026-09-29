<#
.SYNOPSIS
Tests test-postgres.ps1 in -DryRun mode: port selection and unique container names.
Starts no containers.
#>
$ErrorActionPreference = 'Stop'
$script = Join-Path (Split-Path -Parent $PSScriptRoot) 'test-postgres.ps1'
$failures = New-Object System.Collections.Generic.List[string]

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { $failures.Add($Message) }
}

function Get-Plan([string[]]$Arguments) {
    $output = & powershell -NoProfile -ExecutionPolicy Bypass -File $script -DryRun @Arguments 2>&1 | Out-String
    $match = [regex]::Match($output, 'container=(\S+) port=(\d+) path=(\S+)')
    if (-not $match.Success) { return $null }
    return [pscustomobject]@{ Name = $match.Groups[1].Value; Port = [int]$match.Groups[2].Value; Path = $match.Groups[3].Value }
}

$saved = $env:GREENLOOP_TEST_DB_PORT
try {
    $env:GREENLOOP_TEST_DB_PORT = $null
    $first = Get-Plan @()
    $second = Get-Plan @()
    Assert-True ($null -ne $first) 'dry run should print a plan'
    Assert-True ($first.Port -eq 55433) "default port should be 55433, got $($first.Port)"
    Assert-True ($first.Name -match '^greenloop-test-db-[0-9a-f]{12}$') "unexpected name $($first.Name)"
    Assert-True ($first.Name -ne $second.Name) 'each run needs a unique container name'
    Assert-True ($first.Path -eq 'tests/integration') 'default path should be tests/integration'

    $env:GREENLOOP_TEST_DB_PORT = '56001'
    Assert-True ((Get-Plan @()).Port -eq 56001) 'GREENLOOP_TEST_DB_PORT should set the port'
    Assert-True ((Get-Plan @('-Port', '56002')).Port -eq 56002) '-Port should win over the env var'
    Assert-True ((Get-Plan @('-Path', 'tests')).Path -eq 'tests') '-Path should pass through'
} finally {
    $env:GREENLOOP_TEST_DB_PORT = $saved
}

$leftovers = docker ps -a --filter 'label=greenloop.purpose=test-db' -q 2>$null
Assert-True (-not $leftovers) 'dry runs must not start containers'

if ($failures.Count -gt 0) {
    $failures | ForEach-Object { Write-Host "FAIL: $_" }
    exit 1
}
Write-Host 'test-postgres: 9 passed'
