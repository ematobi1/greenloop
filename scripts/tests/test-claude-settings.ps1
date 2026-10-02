<#
.SYNOPSIS
Guards .claude/settings.json: the safety deny rules stay, bypass mode stays disabled,
and local commits are not gated by an ask rule (Terry, 2026-10-02).
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$settings = Get-Content -Raw (Join-Path $root '.claude\settings.json') | ConvertFrom-Json
$permissions = $settings.permissions
$failures = New-Object System.Collections.Generic.List[string]
$checks = 0

function Assert-True([bool]$Condition, [string]$Message) {
    $script:checks++
    if (-not $Condition) { $failures.Add($Message) }
}

Assert-True ($permissions.disableBypassPermissionsMode -eq 'disable') 'bypass permissions mode must stay disabled'

$requiredDeny = @(
    'Bash(git push:*)', 'Bash(git push)', 'Bash(gh:*)', 'Bash(git reset --hard:*)',
    'Bash(git push --force:*)', 'Bash(rm -rf:*)', 'Bash(cat .env:*)',
    'PowerShell(git push *)', 'PowerShell(git push)', 'PowerShell(gh *)', 'PowerShell(git reset --hard *)',
    'Read(.env)', 'Read(//**/*.pem)', 'Read(~/AppData/Local/GreenLoop/**)', 'Edit(.env)'
)
foreach ($rule in $requiredDeny) {
    Assert-True ($permissions.deny -contains $rule) "deny rule missing: $rule"
}

$commitAsk = @($permissions.ask | Where-Object { $_ -match 'git commit' })
Assert-True ($commitAsk.Count -eq 0) "git commit must not be an ask rule: $($commitAsk -join ', ')"
$commitDeny = @($permissions.deny | Where-Object { $_ -match 'git commit' })
Assert-True ($commitDeny.Count -eq 0) "git commit must not be denied: $($commitDeny -join ', ')"

if ($failures.Count -gt 0) {
    $failures | ForEach-Object { Write-Host "FAIL: $_" }
    Write-Host "claude-settings: $($failures.Count) failed"
    exit 1
}
Write-Host "claude-settings: $checks passed"
