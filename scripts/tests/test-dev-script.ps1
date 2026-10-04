<#
.SYNOPSIS
Tests dev.ps1 through -DryRun only: nothing starts, no container is touched.
#>
$ErrorActionPreference = 'Stop'
$script = Join-Path (Split-Path -Parent $PSScriptRoot) 'dev.ps1'
$failures = New-Object System.Collections.Generic.List[string]
$passed = 0

function Assert-True([bool]$Condition, [string]$Message) {
    if ($Condition) { $script:passed++ } else { $failures.Add($Message) }
}

# Running dev.ps1 without -DryRun starts a server, so refuse to test a script that lacks it.
if (-not (Get-Command $script).Parameters.ContainsKey('DryRun')) {
    throw 'dev.ps1 has no -DryRun switch; refusing to run it.'
}

function Invoke-DryRun([string]$Service) {
    $output = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -Service $Service -DryRun
    return @{ Code = $LASTEXITCODE; Text = ($output | Out-String).Trim() }
}

$stack = Invoke-DryRun 'stack'
Assert-True ($stack.Code -eq 0) "stack dry run exited $($stack.Code)"
Assert-True ($stack.Text -eq 'dir=. command=docker compose up -d --build --wait') "stack command was: $($stack.Text)"
Assert-True ($stack.Text -notmatch 'force-recreate') 'stack must rebuild, not only recreate'

$db = Invoke-DryRun 'db'
Assert-True ($db.Text -eq 'dir=. command=docker compose up -d db') "db command was: $($db.Text)"

$orchestrator = Invoke-DryRun 'orchestrator'
Assert-True ($orchestrator.Text -eq 'dir=services\orchestrator command=python.exe -m uvicorn app.main:app --reload --port 8000') "orchestrator command was: $($orchestrator.Text)"

$broker = Invoke-DryRun 'broker'
Assert-True ($broker.Text -eq 'dir=services\broker command=python.exe -m uvicorn app.main:app --reload --port 8100') "broker command was: $($broker.Text)"

$web = Invoke-DryRun 'web'
Assert-True ($web.Text -eq 'dir=apps\web command=npm.cmd run dev') "web command was: $($web.Text)"

if ($failures.Count -gt 0) {
    $failures | ForEach-Object { Write-Host "FAIL: $_" }
    exit 1
}
Write-Host "dev-script: $passed passed"
