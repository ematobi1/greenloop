<#
.SYNOPSIS
Runs every test suite (Python packages, web, scripts) and prints a summary.
Exits 1 if any suite fails.
#>
param([switch]$SkipWeb)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Error "Missing .venv. Create it with: py -3.12 -m venv .venv (see README.md)"
    exit 1
}

$results = New-Object System.Collections.Generic.List[object]

function Add-Result([string]$Suite, [string]$Summary, [int]$ExitCode) {
    $results.Add([pscustomobject]@{ Suite = $Suite; Result = $Summary; Passed = ($ExitCode -eq 0) })
}

foreach ($suite in 'packages/contracts', 'services/orchestrator', 'services/broker', 'services/self-improvement') {
    Push-Location (Join-Path $root $suite)
    $output = & $python -m pytest -q 2>&1 | Out-String
    $code = $LASTEXITCODE
    Pop-Location
    $summary = ($output -split "`r?`n" | Where-Object { $_ -match '\d+ (passed|failed|error)' } | Select-Object -Last 1)
    if ($code -ne 0) { Write-Host $output }
    Add-Result $suite ("$summary".Trim()) $code
}

$web = Join-Path $root 'apps\web'
if ($SkipWeb) {
    Add-Result 'apps/web' 'skipped (-SkipWeb)' 0
} elseif (-not (Test-Path (Join-Path $web 'node_modules'))) {
    Add-Result 'apps/web' 'skipped (run npm ci in apps/web)' 0
} else {
    Push-Location $web
    $output = & npm.cmd test 2>&1 | Out-String
    $code = $LASTEXITCODE
    Pop-Location
    $pass = [regex]::Match($output, '# pass (\d+)').Groups[1].Value
    $fail = [regex]::Match($output, '# fail (\d+)').Groups[1].Value
    if ($code -ne 0) { Write-Host $output }
    Add-Result 'apps/web' "$pass passed, $fail failed" $code
}

foreach ($test in Get-ChildItem (Join-Path $PSScriptRoot 'tests') -Filter 'test-*.ps1') {
    $output = & powershell -NoProfile -ExecutionPolicy Bypass -File $test.FullName 2>&1 | Out-String
    $code = $LASTEXITCODE
    if ($code -ne 0) { Write-Host $output }
    $last = ($output.Trim() -split "`r?`n" | Select-Object -Last 1)
    Add-Result "scripts/tests/$($test.Name)" $last $code
}

$results | Format-Table -AutoSize | Out-String -Width 200 | Write-Host
if ($results | Where-Object { -not $_.Passed }) {
    Write-Host 'FAILED' -ForegroundColor Red
    exit 1
}
Write-Host 'All suites passed.' -ForegroundColor Green
