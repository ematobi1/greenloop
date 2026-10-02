<#
.SYNOPSIS
Tests db-bootstrap.ps1 and db-transfer-ownership.ps1 in -DryRun mode, plus static
checks that passwords never go on a command line. Starts no containers.
The real runs are exercised by test-postgres.ps1 against a throwaway container.
#>
$ErrorActionPreference = 'Stop'
$scripts = Split-Path -Parent $PSScriptRoot
$bootstrap = Join-Path $scripts 'db-bootstrap.ps1'
$transfer = Join-Path $scripts 'db-transfer-ownership.ps1'
$failures = New-Object System.Collections.Generic.List[string]
$passed = 0

function Assert-True([bool]$Condition, [string]$Message) {
    if ($Condition) { $script:passed++ } else { $failures.Add($Message) }
}

function Invoke-DryRun([string]$Script, [string[]]$Arguments) {
    return & powershell -NoProfile -ExecutionPolicy Bypass -File $Script -DryRun @Arguments 2>&1 | Out-String
}

$names = 'ORCHESTRATOR_DB_PASSWORD', 'BROKER_DB_PASSWORD'
$saved = @{}
foreach ($name in $names) { $saved[$name] = [Environment]::GetEnvironmentVariable($name) }
try {
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $null, 'Process') }
    $plan = Invoke-DryRun $bootstrap @()
    Assert-True ($plan -match 'target=compose service db') 'bootstrap should default to the compose db service'
    Assert-True ($plan -match 'ORCHESTRATOR_DB_PASSWORD=prompt') 'unset orchestrator password should be prompted for'
    Assert-True ($plan -match 'BROKER_DB_PASSWORD=prompt') 'unset broker password should be prompted for'

    $marker = 'dry-run-marker-' + [guid]::NewGuid().ToString('N')
    [Environment]::SetEnvironmentVariable('ORCHESTRATOR_DB_PASSWORD', $marker, 'Process')
    $plan = Invoke-DryRun $bootstrap @('-Container', 'some-container')
    Assert-True ($plan -match 'target=some-container') '-Container should pass through'
    Assert-True ($plan -match 'ORCHESTRATOR_DB_PASSWORD=environment') 'a set password should come from the environment'
    Assert-True (-not $plan.Contains($marker)) 'the dry run must not print a password'

    $plan = Invoke-DryRun $transfer @()
    Assert-True ($plan -match 'target=compose service db') 'transfer should default to the compose db service'
    Assert-True ($plan -match 'transfer-public-ownership\.sql') 'transfer should name its SQL file'
} finally {
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
}

$common = Get-Content -Raw (Join-Path $scripts 'db\common.ps1')
Assert-True ($common -match "foreach \(\`$name in \`$PassEnv\) \{ '-e'; \`$name \}") 'docker exec must get -e NAME only, never NAME=value'
$bootstrapText = Get-Content -Raw $bootstrap
Assert-True ($bootstrapText.IndexOf("SET log_statement = 'none'") -lt $bootstrapText.IndexOf('set_config(')) 'logging must be off before set_config carries a password'
Assert-True ($bootstrapText -match '\\o /dev/null') 'set_config output must be hidden'

$leftovers = docker ps -a --filter 'label=greenloop.purpose=test-db' -q 2>$null
Assert-True (-not $leftovers) 'dry runs must not start containers'

if ($failures.Count -gt 0) {
    $failures | ForEach-Object { Write-Host "FAIL: $_" }
    exit 1
}
Write-Host "db-scripts: $passed passed"
