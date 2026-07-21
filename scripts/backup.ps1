[CmdletBinding()]
param(
    [string]$Destination,
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
    if ($null -eq $line) {
        return $null
    }
    $value = $line.Substring($prefix.Length).Trim()
    if ($value.Length -ge 2 -and (($value[0] -eq '"' -and $value[-1] -eq '"') -or ($value[0] -eq "'" -and $value[-1] -eq "'"))) {
        return $value.Substring(1, $value.Length - 2)
    }
    return $value
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI is required"
}

$ResolvedEnvFile = Resolve-ProjectPath -Path $EnvFile -Default ".env"
$ResolvedComposeFile = Resolve-ProjectPath -Path $ComposeFile -Default "compose.yaml"
if (-not (Test-Path -LiteralPath $ResolvedEnvFile -PathType Leaf)) {
    throw "Environment file not found: $ResolvedEnvFile (copy .env.example to .env)"
}
if (-not (Test-Path -LiteralPath $ResolvedComposeFile -PathType Leaf)) {
    throw "Compose file not found: $ResolvedComposeFile"
}

$timestamp = [DateTime]::UtcNow.ToString("yyyyMMdd'T'HHmmss'Z'")
if ([string]::IsNullOrWhiteSpace($Destination)) {
    $Destination = Join-Path $RootDirectory "backups\$timestamp"
}
$Destination = Resolve-ProjectPath -Path $Destination -Default "backups\$timestamp"
if (Test-Path -LiteralPath $Destination) {
    if (Get-ChildItem -Force -LiteralPath $Destination | Select-Object -First 1) {
        throw "Backup destination is not empty: $Destination"
    }
} else {
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
}

$ComposePrefix = @("compose", "--env-file", $ResolvedEnvFile, "-f", $ResolvedComposeFile)
Invoke-Compose -Arguments @("config", "--quiet")
Invoke-Compose -Arguments @("up", "--detach", "--wait", "db")

$containerDump = "/tmp/coffie-backup-$timestamp.dump"
try {
    Invoke-Compose -Arguments @(
        "exec", "-T", "db", "sh", "-eu", "-c",
        'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump --host 127.0.0.1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --format custom --compress 6 --no-owner --no-privileges --file "$1"',
        "sh", $containerDump
    )
    Invoke-Compose -Arguments @("cp", "db:${containerDump}", (Join-Path $Destination "database.dump"))

    $mediaVolume = [Environment]::GetEnvironmentVariable("MEDIA_VOLUME_NAME")
    if ([string]::IsNullOrWhiteSpace($mediaVolume)) { $mediaVolume = Get-DotEnvValue -Name "MEDIA_VOLUME_NAME" }
    if ([string]::IsNullOrWhiteSpace($mediaVolume)) { $mediaVolume = "coffie-bot-media" }

    $helperImage = [Environment]::GetEnvironmentVariable("BACKUP_HELPER_IMAGE")
    if ([string]::IsNullOrWhiteSpace($helperImage)) { $helperImage = Get-DotEnvValue -Name "BACKUP_HELPER_IMAGE" }
    if ([string]::IsNullOrWhiteSpace($helperImage)) { $helperImage = "postgres:17-alpine" }

    Invoke-Docker -Arguments @("volume", "inspect", $mediaVolume)
    Invoke-Docker -Arguments @(
        "run", "--rm",
        "--volume", "${mediaVolume}:/source:ro",
        "--volume", "${Destination}:/backup",
        $helperImage,
        "sh", "-eu", "-c", "tar -czf /backup/media.tar.gz -C /source ."
    )

    $databaseHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $Destination "database.dump")).Hash.ToLowerInvariant()
    $mediaHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $Destination "media.tar.gz")).Hash.ToLowerInvariant()
    @(
        "created_at_utc=$timestamp"
        "database_file=database.dump"
        "database_format=postgresql_custom"
        "database_sha256=$databaseHash"
        "media_file=media.tar.gz"
        "media_format=tar_gzip"
        "media_sha256=$mediaHash"
        "media_volume=$mediaVolume"
        "compose_file=$ResolvedComposeFile"
    ) | Set-Content -LiteralPath (Join-Path $Destination "manifest.txt") -Encoding UTF8
} finally {
    try {
        Invoke-Compose -Arguments @("exec", "-T", "db", "rm", "-f", $containerDump)
    } catch {
        Write-Warning "Could not remove temporary database dump from the db container: $_"
    }
}

Write-Host "Backup created: $Destination"

