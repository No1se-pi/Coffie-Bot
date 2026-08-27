[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$BackupPath,
    [switch]$Force,
    [string]$EnvFile,
    [string]$ComposeFile
)

$ErrorActionPreference = "Stop"
$RootDirectory = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))

function Resolve-ProjectPath {
    param([string]$Path, [string]$Default)

    $value = if ([string]::IsNullOrWhiteSpace($Path)) { $Default } else { $Path }
    if (-not [IO.Path]::IsPathRooted($value)) {
        $value = Join-Path $RootDirectory $value
    }
    return [IO.Path]::GetFullPath($value)
}

function Invoke-Docker {
    param([Parameter(Mandatory)][string[]]$Arguments)

    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Invoke-Compose {
    param([Parameter(Mandatory)][string[]]$Arguments)

    Invoke-Docker -Arguments ($script:ComposePrefix + $Arguments)
}

function Get-DotEnvValue {
    param([Parameter(Mandatory)][string]$Name)

    $prefix = "$Name="
    $line = Get-Content -LiteralPath $script:ResolvedEnvFile -Encoding UTF8 |
        Where-Object { $_.StartsWith($prefix, [StringComparison]::Ordinal) } |
        Select-Object -Last 1
    if ($null -eq $line) { return $null }
    $value = $line.Substring($prefix.Length).Trim()
    if ($value.Length -ge 2 -and (($value[0] -eq '"' -and $value[-1] -eq '"') -or ($value[0] -eq "'" -and $value[-1] -eq "'"))) {
        return $value.Substring(1, $value.Length - 2)
    }
    return $value
}

if (-not $Force) {
    throw "Restore replaces the current database and media. Re-run with -Force."
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI is required"
}

$BackupPath = Resolve-ProjectPath -Path $BackupPath -Default ""
$ResolvedEnvFile = Resolve-ProjectPath -Path $EnvFile -Default ".env"
$ResolvedComposeFile = Resolve-ProjectPath -Path $ComposeFile -Default "compose.yaml"
$databaseDump = Join-Path $BackupPath "database.dump"
$mediaArchive = Join-Path $BackupPath "media.tar.gz"
$manifestPath = Join-Path $BackupPath "manifest.txt"

if (-not (Test-Path -LiteralPath $BackupPath -PathType Container)) { throw "Backup directory not found: $BackupPath" }
if (-not (Test-Path -LiteralPath $databaseDump -PathType Leaf)) { throw "database.dump is missing from $BackupPath" }
if (-not (Test-Path -LiteralPath $mediaArchive -PathType Leaf)) { throw "media.tar.gz is missing from $BackupPath" }
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw "manifest.txt is missing from $BackupPath" }
if (-not (Test-Path -LiteralPath $ResolvedEnvFile -PathType Leaf)) { throw "Environment file not found: $ResolvedEnvFile" }
if (-not (Test-Path -LiteralPath $ResolvedComposeFile -PathType Leaf)) { throw "Compose file not found: $ResolvedComposeFile" }

# Verify both artifacts before stopping any application process or replacing data.
$manifest = @{}
foreach ($line in Get-Content -LiteralPath $manifestPath -Encoding UTF8) {
    $separator = $line.IndexOf("=", [StringComparison]::Ordinal)
    if ($separator -gt 0) {
        $manifest[$line.Substring(0, $separator)] = $line.Substring($separator + 1).Trim()
    }
}
$expectedDatabaseHash = $manifest["database_sha256"]
$expectedMediaHash = $manifest["media_sha256"]
if ($expectedDatabaseHash -notmatch "^[a-f0-9]{64}$" -or $expectedMediaHash -notmatch "^[a-f0-9]{64}$") {
    throw "Backup manifest contains invalid SHA256 values"
}
$actualDatabaseHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $databaseDump).Hash.ToLowerInvariant()
$actualMediaHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $mediaArchive).Hash.ToLowerInvariant()
if ($actualDatabaseHash -ne $expectedDatabaseHash) {
    throw "database.dump checksum does not match manifest.txt"
}
if ($actualMediaHash -ne $expectedMediaHash) {
    throw "media.tar.gz checksum does not match manifest.txt"
}

$ComposePrefix = @("compose", "--env-file", $ResolvedEnvFile, "-f", $ResolvedComposeFile)
Invoke-Compose -Arguments @("config", "--quiet")

$timestamp = [DateTime]::UtcNow.ToString("yyyyMMdd'T'HHmmss'Z'")
$containerDump = "/tmp/coffie-restore-$timestamp.dump"
$completed = $false
try {
    Write-Host "Stopping application processes before restore..."
    Invoke-Compose -Arguments @("stop", "frontend", "backend", "bot", "worker")
    Invoke-Compose -Arguments @("up", "--detach", "--wait", "db")
    Invoke-Compose -Arguments @("cp", $databaseDump, "db:${containerDump}")
    Invoke-Compose -Arguments @(
        "exec", "-T", "db", "sh", "-eu", "-c",
        'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore --host 127.0.0.1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges --single-transaction --exit-on-error "$1"',
        "sh", $containerDump
    )

    $mediaVolume = [Environment]::GetEnvironmentVariable("MEDIA_VOLUME_NAME")
    if ([string]::IsNullOrWhiteSpace($mediaVolume)) { $mediaVolume = Get-DotEnvValue -Name "MEDIA_VOLUME_NAME" }
    if ([string]::IsNullOrWhiteSpace($mediaVolume)) { $mediaVolume = "coffie-bot-media" }

    $helperImage = [Environment]::GetEnvironmentVariable("BACKUP_HELPER_IMAGE")
    if ([string]::IsNullOrWhiteSpace($helperImage)) { $helperImage = Get-DotEnvValue -Name "BACKUP_HELPER_IMAGE" }
    if ([string]::IsNullOrWhiteSpace($helperImage)) { $helperImage = "postgres:17-alpine" }

    Invoke-Docker -Arguments @("volume", "inspect", $mediaVolume)
    # Native Windows argument quoting can corrupt the regular expressions in an
    # inline `sh -c` script. Base64 keeps the shell program opaque until it is
    # decoded inside the trusted helper container.
    $mediaRestoreScript = @'
if tar -tzf /backup/media.tar.gz | grep -Eq "(^/|(^|/)\.\.(/|$))"; then
    echo "Unsafe path in media archive" >&2
    exit 1
fi
if tar -tvzf /backup/media.tar.gz | grep -Eq "^[lh]"; then
    echo "Links are not allowed in media archive" >&2
    exit 1
fi
find /target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
tar -xzf /backup/media.tar.gz -C /target
'@
    $encodedMediaRestoreScript = [Convert]::ToBase64String(
        [Text.Encoding]::UTF8.GetBytes($mediaRestoreScript)
    )
    Invoke-Docker -Arguments @(
        "run", "--rm",
        "--volume", "${mediaVolume}:/target",
        "--volume", "${BackupPath}:/backup:ro",
        $helperImage,
        "sh", "-eu", "-c",
        "echo $encodedMediaRestoreScript | base64 -d | sh -eu"
    )

    Invoke-Compose -Arguments @("run", "--rm", "migrate")
    Invoke-Compose -Arguments @("up", "--detach", "backend", "bot", "worker", "frontend")
    $completed = $true
} finally {
    try {
        Invoke-Compose -Arguments @("exec", "-T", "db", "rm", "-f", $containerDump)
    } catch {
        Write-Warning "Could not remove temporary database dump from the db container: $_"
    }
    if (-not $completed) {
        Write-Warning "Restore failed; application services were left stopped. Inspect the error before restarting them."
    }
}

Write-Host "Restore completed from: $BackupPath"
