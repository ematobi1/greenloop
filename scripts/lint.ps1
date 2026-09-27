<#
.SYNOPSIS
Runs every linter: Ruff (check + format), PowerShell syntax, web lint and
typecheck, terraform fmt. Exits 1 if any check fails.
#>
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$ruff = Join-Path $root '.venv\Scripts\ruff.exe'
$failures = New-Object System.Collections.Generic.List[string]

function Invoke-Check([string]$Name, [scriptblock]$Command) {
    Write-Host "== $Name"
    & $Command
    if ($LASTEXITCODE -ne 0) { $failures.Add($Name) }
}

Push-Location $root
try {
    Invoke-Check 'ruff check' { & $ruff check packages services }
    Invoke-Check 'ruff format' { & $ruff format --check packages services }

    Write-Host '== powershell syntax'
    foreach ($script in Get-ChildItem (Join-Path $root 'scripts') -Recurse -Filter '*.ps1') {
        $errors = $null
        [System.Management.Automation.Language.Parser]::ParseFile($script.FullName, [ref]$null, [ref]$errors) | Out-Null
        if ($errors.Count -gt 0) {
            $errors | ForEach-Object { Write-Host "$($script.Name): $($_.Message)" }
            $failures.Add("powershell syntax: $($script.Name)")
        }
    }

    if (Test-Path 'apps\web\node_modules') {
        Invoke-Check 'web lint' { npm.cmd --prefix apps/web run lint --silent }
        Invoke-Check 'web typecheck' { npm.cmd --prefix apps/web run typecheck --silent }
    } else {
        Write-Host '== web lint: skipped (run npm ci in apps/web)'
    }

    if (Get-Command terraform -ErrorAction SilentlyContinue) {
        Invoke-Check 'terraform fmt' { terraform fmt -check -recursive infra/terraform }
    } else {
        Write-Host '== terraform fmt: skipped (terraform not installed)'
    }
} finally {
    Pop-Location
}

if ($failures.Count -gt 0) {
    Write-Host "FAILED: $($failures -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host 'All lint checks passed.' -ForegroundColor Green
