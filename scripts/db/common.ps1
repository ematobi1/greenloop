# Shared by db-bootstrap.ps1 and db-transfer-ownership.ps1. Dot-source only.

function Resolve-DbContainer([string]$Root, [string]$Container) {
    if ($Container) { return $Container }
    Push-Location $Root
    try {
        $id = docker compose ps -q db 2>$null
    } finally {
        Pop-Location
    }
    if ($LASTEXITCODE -ne 0 -or -not $id) {
        throw 'The compose "db" service is not running. Start it with: .\scripts\dev.ps1 -Service db'
    }
    return "$id".Trim()
}

# Pipes a psql script into the container on stdin, as the image's superuser over the
# local socket. Values listed in -PassEnv go through `docker exec -e NAME`, which copies
# them from this process's environment, so they never appear on a command line.
function Invoke-ContainerPsql([string]$Container, [string]$Script, [string[]]$PassEnv = @()) {
    $envArgs = foreach ($name in $PassEnv) { '-e'; $name }
    $previousEncoding = $OutputEncoding
    $OutputEncoding = New-Object System.Text.UTF8Encoding $false
    try {
        $Script | docker exec -i @envArgs $Container sh -c 'psql -X -q -v ON_ERROR_STOP=1 -U $POSTGRES_USER -d $POSTGRES_DB' | Out-Host
        return $LASTEXITCODE
    } finally {
        $OutputEncoding = $previousEncoding
    }
}
