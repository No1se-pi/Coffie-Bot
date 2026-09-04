[CmdletBinding()]
param(
    [string]$HostUrl = "http://localhost:9000",
    [string]$ProjectKey = "Cofie-Bot",
    [switch]$SkipBuild,
    [switch]$SkipCoverage
)

$ErrorActionPreference = "Stop"
$RootDirectory = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$EnvFile = Join-Path $RootDirectory ".env"
$ComposeFile = Join-Path $RootDirectory "compose.yaml"

if ([string]::IsNullOrWhiteSpace($env:SONAR_TOKEN)) {
    throw "Set SONAR_TOKEN in the current shell before running the scan."
}
if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
    throw "Environment file not found: $EnvFile"
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory)][string]$Command,
        [Parameter(Mandatory)][string[]]$Arguments
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code $LASTEXITCODE"
    }
}

function Resolve-PySonar {
    $command = Get-Command pysonar -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }

    # pip --user installs console scripts here on the standard Python 3.11 setup.
    $candidate = Join-Path $env:APPDATA "Python\Python311\Scripts\pysonar.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        return $candidate
    }
    throw "pysonar was not found. Install it with: python -m pip install pysonar"
}

Push-Location $RootDirectory
try {
    $compose = @("compose", "--env-file", $EnvFile, "-f", $ComposeFile)
    if (-not $SkipCoverage) {
        # Reports are disposable artifacts. Removing stale container-owned files
        # avoids Windows bind-mount permission failures on the next run.
        $coverageReports = @(
            (Join-Path $RootDirectory "backend\coverage.xml"),
            (Join-Path $RootDirectory "frontend\coverage\lcov.info")
        )
        foreach ($report in $coverageReports) {
            if (Test-Path -LiteralPath $report -PathType Leaf) {
                Remove-Item -Force -LiteralPath $report
            }
        }

        if (-not $SkipBuild) {
            Invoke-Checked docker ($compose + @("build", "backend"))
        }
        Invoke-Checked docker ($compose + @("up", "-d", "--wait", "db"))

        # Run from the repository root so Cobertura stores backend/app paths
        # that the Windows Sonar scanner can resolve after the container exits.
        $repositoryMount = "${RootDirectory}:/workspace"
        Invoke-Checked docker ($compose + @(
            "run", "--rm", "--no-deps",
            "-e", "APP_ENV=test",
            "-e", "APP_DEBUG=false",
            "-e", "DEV_AUTH_ENABLED=false",
            "-e", "PYTHONPATH=/workspace/backend",
            "-v", $repositoryMount,
            "-w", "/workspace",
            "backend", "pytest", "backend/tests",
            "--cov=backend/app", "--cov-config=.coveragerc",
            "--cov-report=xml:backend/coverage.xml"
        ))

        Invoke-Checked npm @("--prefix", "frontend", "ci")
        Invoke-Checked npm @("--prefix", "frontend", "run", "test:coverage")
    }

    $scanner = Resolve-PySonar
    Invoke-Checked $scanner @(
        "--sonar-host-url", $HostUrl,
        "--sonar-token", $env:SONAR_TOKEN,
        "--sonar-project-key", $ProjectKey,
        "--sonar-project-base-dir", $RootDirectory,
        "--sonar-qualitygate-wait",
        "--sonar-qualitygate-timeout", "300"
    )
}
finally {
    Pop-Location
}
