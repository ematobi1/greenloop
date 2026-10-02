<#
.SYNOPSIS
Runs the orchestrator's Postgres tests against a throwaway pgvector container.

.DESCRIPTION
Starts a uniquely named pgvector/pgvector:pg16 container with a random password
on 127.0.0.1:<port>, runs pytest against it, and always removes it in a finally
block, including after a failure or Ctrl+C. A hard kill (closed window,
Stop-Process) skips finally, so each run first removes test containers whose
owning PowerShell process is gone, or that started more than an hour ago. It never touches the dev database (docker compose "db"
on GREENLOOP_DB_PORT, default 5432).

The port comes from -Port, else GREENLOOP_TEST_DB_PORT, else 55433.

.EXAMPLE
.\scripts\test-postgres.ps1                     # tests/integration
.\scripts\test-postgres.ps1 -Path tests         # the whole orchestrator suite
.\scripts\test-postgres.ps1 -DryRun             # print the plan, start nothing
#>
param(
    [int]$Port = 0,
    [string]$Path = 'tests/integration',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$image = 'pgvector/pgvector:pg16'
$label = 'greenloop.purpose=test-db'
$staleAfterSeconds = 3600

function Remove-StaleTestDbs {
    # {{.Labels}} needs no inner quotes; Windows PowerShell 5.1 strips them from native arguments.
    $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $rows = docker ps -a --filter "label=$label" --format '{{.ID}} {{.Labels}}'
    if ($LASTEXITCODE -ne 0) { Write-Warning 'Could not list test containers; skipping the stale sweep.'; return }
    foreach ($row in @($rows)) {
        $id, $labelText = "$row".Split(' ', 2)
        if (-not $id) { continue }
        $labels = @{}
        foreach ($pair in "$labelText".Split(',')) {
            $key, $value = $pair.Split('=', 2)
            $labels[$key] = $value
        }
        $startedAt = 0
        $ownerId = 0
        $tooOld = -not [long]::TryParse("$($labels['greenloop.started'])", [ref]$startedAt) -or
            $now - $startedAt -gt $staleAfterSeconds
        $ownerGone = -not [int]::TryParse("$($labels['greenloop.owner-pid'])", [ref]$ownerId) -or
            -not (Get-Process -Id $ownerId -ErrorAction SilentlyContinue)
        if ($tooOld -or $ownerGone) {
            docker rm -f $id 2>$null | Out-Null
            Write-Host "Removed stale test container $id."
        }
    }
}

# Runs the real db-bootstrap.ps1 and db-transfer-ownership.ps1 against the throwaway
# container with synthetic passwords, and checks that no password reaches the output.
function Test-DbScripts([string]$Container) {
    $passwords = @{
        ORCHESTRATOR_DB_PASSWORD = 'synthetic-' + [guid]::NewGuid().ToString('N')
        BROKER_DB_PASSWORD = 'synthetic-' + [guid]::NewGuid().ToString('N')
    }
    $saved = @{}
    foreach ($key in $passwords.Keys) { $saved[$key] = [Environment]::GetEnvironmentVariable($key) }
    try {
        foreach ($key in $passwords.Keys) { [Environment]::SetEnvironmentVariable($key, $passwords[$key], 'Process') }
        $output = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'db-bootstrap.ps1') -Container $Container 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) { throw "db-bootstrap.ps1 failed:`n$output" }
        $output += & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'db-transfer-ownership.ps1') -Container $Container -Yes 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) { throw "db-transfer-ownership.ps1 failed:`n$output" }
        foreach ($value in $passwords.Values) {
            if ($output.Contains($value)) { throw 'A role password appeared in the db script output.' }
        }
        $logs = docker logs $Container 2>&1 | Out-String
        foreach ($value in $passwords.Values) {
            if ($logs.Contains($value)) { throw 'A role password appeared in the Postgres server log.' }
        }
        Write-Host 'db-bootstrap.ps1 and db-transfer-ownership.ps1 ran cleanly; no password in output or server log.'
    } finally {
        foreach ($key in $passwords.Keys) { [Environment]::SetEnvironmentVariable($key, $saved[$key], 'Process') }
    }
}

function Resolve-TestDbPort([int]$Requested) {
    if ($Requested -gt 0) { return $Requested }
    if ($env:GREENLOOP_TEST_DB_PORT) { return [int]$env:GREENLOOP_TEST_DB_PORT }
    return 55433
}

$Port = Resolve-TestDbPort $Port
$name = 'greenloop-test-db-' + [guid]::NewGuid().ToString('N').Substring(0, 12)

if ($DryRun) {
    Write-Host "container=$name port=$Port path=$Path"
    exit 0
}

if (-not (Test-Path $python)) { throw 'Missing .venv. Create it with: py -3.12 -m venv .venv' }
$password = [guid]::NewGuid().ToString('N')
$exitCode = 1
$previousUrl = $env:TEST_DATABASE_URL

try {
    $ErrorActionPreference = 'Continue'
    Remove-StaleTestDbs
    $started = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    docker run -d --rm --name $name --label $label --label "greenloop.started=$started" --label "greenloop.owner-pid=$PID" `
        -e POSTGRES_USER=greenloop_test -e "POSTGRES_PASSWORD=$password" -e POSTGRES_DB=greenloop_test `
        -p "127.0.0.1:${Port}:5432" $image postgres -c log_statement=all | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not start $name on port $Port (is Docker running, or is the port taken?)" }

    # -h 127.0.0.1 waits for the final server; the init-time server listens on the socket only.
    $deadline = (Get-Date).AddSeconds(90)
    do {
        docker exec $name pg_isready -h 127.0.0.1 -U greenloop_test -d greenloop_test -q 2>$null
        $ready = $LASTEXITCODE -eq 0
        if (-not $ready) { Start-Sleep -Milliseconds 500 }
    } until ($ready -or (Get-Date) -gt $deadline)
    if (-not $ready) { throw "$name did not become ready within 90s" }

    Test-DbScripts $name

    $env:TEST_DATABASE_URL = "postgresql+psycopg://greenloop_test:$password@127.0.0.1:$Port/greenloop_test"
    Write-Host "Postgres tests on $name (127.0.0.1:$Port): $Path"
    Push-Location (Join-Path $root 'services\orchestrator')
    try {
        & $python -m pytest -q $Path
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
} finally {
    $env:TEST_DATABASE_URL = $previousUrl
    docker rm -f $name 2>$null | Out-Null
    Write-Host "Removed $name."
}
exit $exitCode
