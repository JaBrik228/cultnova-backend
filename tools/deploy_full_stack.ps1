[CmdletBinding()]
param(
    [string]$BackendConfigPath = ".\.env.deploy",
    [switch]$RunBackendMigrations,
    [switch]$SkipFrontend,
    [switch]$SkipFrontendSmoke,
    [switch]$SkipBackend,
    [switch]$SkipBackendSmoke
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)

    Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Message)
}

function Fail {
    param([string]$Message)

    throw [System.Exception]::new($Message)
}

function Resolve-ConfigPath {
    param(
        [string]$RepoRoot,
        [string]$InputPath
    )

    if ([System.IO.Path]::IsPathRooted($InputPath)) {
        return $InputPath
    }

    return Join-Path $RepoRoot $InputPath
}

function Read-KeyValueConfig {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        Fail ("Config file not found: {0}" -f $Path)
    }

    $config = @{}
    foreach ($rawLine in Get-Content -LiteralPath $Path) {
        $line = $rawLine.Trim()
        if ($line.Length -eq 0 -or $line.StartsWith("#")) {
            continue
        }

        $eqIndex = $line.IndexOf("=")
        if ($eqIndex -lt 1) {
            continue
        }

        $key = $line.Substring(0, $eqIndex).Trim()
        $value = $line.Substring($eqIndex + 1).Trim()

        if (
            ($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))
        ) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        $config[$key] = $value
    }

    return $config
}

function Invoke-ProcessChecked {
    param(
        [string]$Exe,
        [string[]]$ArgumentList,
        [string]$Description,
        [string]$WorkingDirectory
    )

    Write-Step $Description
    Push-Location $WorkingDirectory
    try {
        $output = & $Exe @ArgumentList 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }

    $text = ($output | Out-String).Trim()
    if (-not [string]::IsNullOrWhiteSpace($text)) {
        Write-Host $text
    }

    if ($exitCode -ne 0) {
        Fail ("Command failed ({0}): {1} {2}" -f $exitCode, $Exe, ($ArgumentList -join " "))
    }
}

try {
    $backendRepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    $resolvedBackendConfigPath = Resolve-ConfigPath -RepoRoot $backendRepoRoot -InputPath $BackendConfigPath
    if (Test-Path -LiteralPath $resolvedBackendConfigPath) {
        $resolvedBackendConfigPath = (Resolve-Path -LiteralPath $resolvedBackendConfigPath).Path
    }

    $backendConfig = Read-KeyValueConfig -Path $resolvedBackendConfigPath
    $frontendRepoPath = ""
    if ($backendConfig.ContainsKey("FRONTEND_REPO_PATH")) {
        $frontendRepoPath = [string]$backendConfig["FRONTEND_REPO_PATH"]
    }
    if ([string]::IsNullOrWhiteSpace($frontendRepoPath)) {
        Fail "FRONTEND_REPO_PATH must be configured in backend .env.deploy for full-stack deploy."
    }

    if (-not (Test-Path -LiteralPath $frontendRepoPath -PathType Container)) {
        Fail ("Frontend repo path does not exist: {0}" -f $frontendRepoPath)
    }

    $frontendSiteConfigPath = Join-Path $frontendRepoPath ".env.deploy.site"
    $frontendMailConfigPath = Join-Path $frontendRepoPath ".env.deploy.mail"
    $frontendDeployScriptPath = Join-Path $frontendRepoPath "tools\deploy_prod_site.ps1"
    $backendDeployScriptPath = Join-Path $backendRepoRoot "tools\deploy_prod.ps1"

    if (-not $SkipFrontend) {
        $frontendArgs = @(
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            $frontendDeployScriptPath,
            "-ConfigPath",
            $frontendSiteConfigPath,
            "-MailConfigPath",
            $frontendMailConfigPath
        )
        if ($SkipFrontendSmoke) {
            $frontendArgs += "-SkipSmoke"
        }

        Invoke-ProcessChecked `
            -Exe "powershell" `
            -ArgumentList $frontendArgs `
            -Description "Deploying frontend site" `
            -WorkingDirectory $frontendRepoPath
    }
    else {
        Write-Step "Frontend deploy skipped (-SkipFrontend)."
    }

    if (-not $SkipBackend) {
        $backendArgs = @(
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            $backendDeployScriptPath,
            "-ConfigPath",
            $resolvedBackendConfigPath
        )
        if ($RunBackendMigrations) {
            $backendArgs += "-RunMigrations"
        }
        if ($SkipBackendSmoke) {
            $backendArgs += "-SkipSmoke"
        }

        Invoke-ProcessChecked `
            -Exe "powershell" `
            -ArgumentList $backendArgs `
            -Description "Deploying backend CMS" `
            -WorkingDirectory $backendRepoRoot
    }
    else {
        Write-Step "Backend deploy skipped (-SkipBackend)."
    }

    Write-Step "Full-stack deploy completed successfully."
    exit 0
}
catch {
    Write-Host ""
    Write-Host ("FULL-STACK DEPLOY FAILED: {0}" -f $_.Exception.Message)
    exit 1
}
