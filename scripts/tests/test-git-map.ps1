<#
.SYNOPSIS
Tests git-map.ps1 against a synthetic folder tree in the temp directory.
Never touches the real greenloop-* folders.
#>
$ErrorActionPreference = 'Stop'
$script = Join-Path (Split-Path -Parent $PSScriptRoot) 'git-map.ps1'
$failures = New-Object System.Collections.Generic.List[string]

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { $failures.Add($Message) }
}

$sandbox = Join-Path ([System.IO.Path]::GetTempPath()) ("git-map-test-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $sandbox | Out-Null
try {
    $alpha = Join-Path $sandbox 'greenloop-alpha'
    New-Item -ItemType Directory -Path $alpha | Out-Null
    $ErrorActionPreference = 'Continue'
    git -C $alpha -c init.defaultBranch=main init -q 2>$null
    Set-Content -Path (Join-Path $alpha 'README.md') -Value 'alpha'
    git -C $alpha add README.md 2>$null
    git -C $alpha -c user.name=test -c user.email=test@example.invalid commit -q -m 'first | commit' 2>$null
    Set-Content -Path (Join-Path $alpha 'untracked.txt') -Value 'x'
    $ErrorActionPreference = 'Stop'

    New-Item -ItemType Directory -Path (Join-Path $sandbox 'greenloop-beta') | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $sandbox 'unrelated') | Out-Null
    Set-Content -Path (Join-Path $sandbox 'greenloop-file.txt') -Value 'not a folder'

    $map = Join-Path $sandbox 'map.md'
    Set-Content -Path $map -Value @(
        '| Old folder | New path | Notes | Status |',
        '|---|---|---|---|',
        '| greenloop-alpha | `services/alpha` | | not started |'
    )

    $report = (& $script -Root $sandbox -MigrationMap $map | Out-String)
    $lines = $report -split "`r?`n"
    $alphaRow = $lines | Where-Object { $_ -like '| greenloop-alpha *' }
    $betaRow = $lines | Where-Object { $_ -like '| greenloop-beta *' }

    Assert-True ($null -ne $alphaRow) 'alpha row missing'
    Assert-True ($alphaRow -match '\| yes \| main \|') 'alpha should be a git repo on main'
    Assert-True ($alphaRow -match 'first \\\| commit') 'commit subject pipe should be escaped'
    Assert-True ($alphaRow -match '\| 1 \| no \| 2 \| services/alpha \|') 'alpha dirty/remote/entries/target wrong'
    Assert-True ($betaRow -match '\| greenloop-beta \| no \| - \| - \| - \| - \| 0 \| - \|') 'beta row wrong'
    Assert-True ($report -notmatch 'unrelated') 'non-greenloop folder should be excluded'
    Assert-True ($report -notmatch 'greenloop-file') 'files should be excluded'
    Assert-True ($report -match '2 folder\(s\)') 'folder count wrong'

    $refused = $false
    try { & $script -Root (Join-Path $env:LOCALAPPDATA 'GreenLoop\child') | Out-Null } catch { $refused = $_.Exception.Message -match 'Refusing' }
    Assert-True $refused 'protected location must be refused'
} finally {
    Remove-Item -LiteralPath $sandbox -Recurse -Force
}

if ($failures.Count -gt 0) {
    $failures | ForEach-Object { Write-Host "FAIL: $_" }
    Write-Host "git-map: $($failures.Count) failed"
    exit 1
}
Write-Host 'git-map: 9 passed'
