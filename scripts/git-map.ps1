<#
.SYNOPSIS
Read-only map of the old greenloop-* folders next to this repository.

.DESCRIPTION
For each top-level greenloop-* directory under -Root it reports whether it is a
Git repository, its branch, last commit, uncommitted change count, whether any
remote is configured (never the URL, which can embed tokens), top-level entry
count, and the migration target from docs/migration-map.md.

It reads names and Git metadata only: no file contents, no recursion, and Git
runs with --no-optional-locks so nothing is written to the old repositories.
It refuses to run against %LOCALAPPDATA%\GreenLoop.

.EXAMPLE
.\scripts\git-map.ps1
.\scripts\git-map.ps1 -OutFile $env:TEMP\greenloop-map.md
#>
param(
    [string]$Root = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$MigrationMap = (Join-Path (Split-Path -Parent $PSScriptRoot) 'docs\migration-map.md'),
    [string]$OutFile
)

$ErrorActionPreference = 'Stop'

$forbidden = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'GreenLoop')).TrimEnd('\')
$target = [System.IO.Path]::GetFullPath($Root).TrimEnd('\')
if ($target -ieq $forbidden -or $target.StartsWith("$forbidden\", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to map $target (protected location)."
}

function Get-MigrationTargets([string]$Path) {
    $targets = @{}
    if (-not (Test-Path $Path)) { return $targets }
    foreach ($line in Get-Content $Path) {
        if ($line -match '^\|\s*(greenloop-[\w-]+)\s*\|\s*([^|]+?)\s*\|') {
            $targets[$Matches[1]] = $Matches[2].Replace('`', '')
        }
    }
    return $targets
}

function Invoke-GitRead([string]$Path, [string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $output = & git -C $Path --no-optional-locks @Arguments 2>$null
    $ErrorActionPreference = $previous
    if ($LASTEXITCODE -ne 0) { return $null }
    return $output
}

function Format-Cell([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return '-' }
    return $Value.Replace('|', '\|').Trim()
}

$targets = Get-MigrationTargets $MigrationMap
$rows = New-Object System.Collections.Generic.List[string]
$rows.Add('| Folder | Git | Branch | Last commit | Uncommitted | Remote | Entries | Migration target |')
$rows.Add('|---|---|---|---|---|---|---|---|')

$folders = Get-ChildItem -LiteralPath $target -Directory -Filter 'greenloop-*' |
    Where-Object { -not ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) } |
    Sort-Object Name

foreach ($folder in $folders) {
    $path = $folder.FullName
    $entries = @(Get-ChildItem -LiteralPath $path -Force -Name | Where-Object { $_ -ne '.git' }).Count
    $isGit = Test-Path -LiteralPath (Join-Path $path '.git')
    $branch = $last = $dirty = $remote = $null
    if ($isGit) {
        $branch = Invoke-GitRead $path @('rev-parse', '--abbrev-ref', 'HEAD')
        $last = Invoke-GitRead $path @('log', '-1', '--format=%h %cs %s')
        $status = Invoke-GitRead $path @('status', '--porcelain')
        $dirty = "$(@($status | Where-Object { $_ }).Count)"
        $remotes = Invoke-GitRead $path @('remote')
        $remote = if (@($remotes | Where-Object { $_ }).Count -gt 0) { 'yes' } else { 'no' }
    }
    $cells = @(
        $folder.Name,
        $(if ($isGit) { 'yes' } else { 'no' }),
        "$branch", "$last", "$dirty", "$remote", "$entries",
        "$($targets[$folder.Name])"
    ) | ForEach-Object { Format-Cell $_ }
    $rows.Add('| ' + ($cells -join ' | ') + ' |')
}

$report = ($rows -join "`n") + "`n`n$($folders.Count) folder(s) under $target`n"
if ($OutFile) {
    $report | Out-File -FilePath $OutFile -Encoding utf8
    Write-Host "Wrote $OutFile"
} else {
    $report
}
