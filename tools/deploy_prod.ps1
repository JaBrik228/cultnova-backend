[CmdletBinding()]
param(
    [string]$ConfigPath = ".\.env.deploy",
    [switch]$RunMigrations,
    [switch]$SkipSmoke
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:LogFile = $null
$script:BackupPath = $null
$script:SshRunPath = $null
$script:RemoteCmsRoot = $null
$script:RemoteTmpDir = $null

function Write-Step {
    param([string]$Message)

    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Message
    Write-Host $line

    if ($script:LogFile) {
        Add-Content -LiteralPath $script:LogFile -Value $line
    }
}

function Write-CommandOutput {
    param([string]$Text)

    if (-not [string]::IsNullOrWhiteSpace($Text)) {
        Write-Host $Text
        if ($script:LogFile) {
            Add-Content -LiteralPath $script:LogFile -Value $Text
        }
    }
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
    $lines = Get-Content -LiteralPath $Path
    foreach ($rawLine in $lines) {
        $line = $rawLine.Trim()
        if ($line.Length -eq 0) { continue }
        if ($line.StartsWith("#")) { continue }

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

function Assert-CommandExists {
    param([string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Fail ("Required command not found in PATH: {0}" -f $Name)
    }
}

function Invoke-ProcessChecked {
    param(
        [string]$Exe,
        [string[]]$ArgumentList,
        [string]$Description
    )

    Write-Step $Description
    $output = & $Exe @ArgumentList 2>&1
    $exitCode = $LASTEXITCODE
    $text = ($output | Out-String).Trim()
    Write-CommandOutput $text

    if ($exitCode -ne 0) {
        Fail ("Command failed ({0}): {1} {2}" -f $exitCode, $Exe, ($ArgumentList -join " "))
    }

    return $text
}

function Invoke-Remote {
    param(
        [string]$Command,
        [string]$Description
    )

    return Invoke-ProcessChecked -Exe "python" -ArgumentList @($script:SshRunPath, $Command) -Description $Description
}

function ConvertTo-HeadersHashtable {
    param([string[]]$HeaderLines)

    $headers = @{}
    foreach ($line in $HeaderLines) {
        if ($line -match "^\s*([^:]+)\s*:\s*(.*)$") {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            if ($headers.ContainsKey($name)) {
                $headers[$name] = "{0}, {1}" -f $headers[$name], $value
            }
            else {
                $headers[$name] = $value
            }
        }
    }
    return $headers
}

function Get-LastHttpHeaderBlock {
    param([string]$HeadersText)

    $lines = $HeadersText -split "`r?`n"
    $blocks = @()
    $current = @()

    foreach ($lineRaw in $lines) {
        $line = $lineRaw.TrimEnd("`r")
        if ($line -match "^HTTP/\S+\s+\d{3}\b") {
            if ($current.Count -gt 0) {
                $blocks += ,$current
            }
            $current = @($line)
            continue
        }

        if ($current.Count -gt 0) {
            if ([string]::IsNullOrWhiteSpace($line)) {
                $blocks += ,$current
                $current = @()
            }
            else {
                $current += $line
            }
        }
    }

    if ($current.Count -gt 0) {
        $blocks += ,$current
    }

    if ($blocks.Count -eq 0) {
        throw [System.Exception]::new("No HTTP header blocks were parsed from curl output.")
    }

    return $blocks[$blocks.Count - 1]
}

function Invoke-HttpViaCurl {
    param(
        [string]$Url,
        [hashtable]$Headers = @{}
    )

    $curlCmd = Get-Command "curl.exe" -ErrorAction SilentlyContinue
    if (-not $curlCmd) {
        throw [System.Exception]::new("curl.exe is not available in PATH.")
    }

    $headersFile = [System.IO.Path]::GetTempFileName()
    $bodyFile = [System.IO.Path]::GetTempFileName()

    try {
        $args = @(
            "-sS",
            "-L",
            "--connect-timeout", "10",
            "--max-time", "30",
            "-D", $headersFile,
            "-o", $bodyFile,
            "-w", "%{http_code}"
        )

        foreach ($key in $Headers.Keys) {
            $args += "-H"
            $args += ("{0}: {1}" -f $key, [string]$Headers[$key])
        }

        $args += $Url

        $rawOutput = & $curlCmd.Source @args 2>&1
        $exitCode = $LASTEXITCODE
        $outputText = ($rawOutput | Out-String).Trim()

        if ($exitCode -ne 0) {
            throw [System.Exception]::new(
                ("curl.exe failed with exit code {0}: {1}" -f $exitCode, $outputText)
            )
        }

        $headersText = ""
        if (Test-Path -LiteralPath $headersFile) {
            $headersText = Get-Content -LiteralPath $headersFile -Raw
        }
        if ([string]::IsNullOrWhiteSpace($headersText)) {
            throw [System.Exception]::new("curl.exe response headers are empty.")
        }

        $finalBlock = Get-LastHttpHeaderBlock -HeadersText $headersText
        $statusLine = [string]$finalBlock[0]
        if (-not ($statusLine -match "^HTTP/\S+\s+(\d{3})\b")) {
            throw [System.Exception]::new(("Unable to parse HTTP status from line: {0}" -f $statusLine))
        }
        $statusCode = [int]$matches[1]

        $statusFromWriteOut = 0
        if ($outputText -match "(\d{3})\s*$") {
            $statusFromWriteOut = [int]$matches[1]
        }
        if ($statusFromWriteOut -ne 0 -and $statusFromWriteOut -ne $statusCode) {
            throw [System.Exception]::new(
                ("curl.exe status mismatch: headers={0}, write-out={1}" -f $statusCode, $statusFromWriteOut)
            )
        }

        $body = ""
        if (Test-Path -LiteralPath $bodyFile) {
            $body = Get-Content -LiteralPath $bodyFile -Raw
        }

        $headersHash = ConvertTo-HeadersHashtable -HeaderLines $finalBlock
        return [PSCustomObject]@{
            StatusCode = $statusCode
            Content = [string]$body
            Headers = $headersHash
            Transport = "curl"
        }
    }
    finally {
        if (Test-Path -LiteralPath $headersFile) {
            Remove-Item -LiteralPath $headersFile -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path -LiteralPath $bodyFile) {
            Remove-Item -LiteralPath $bodyFile -Force -ErrorAction SilentlyContinue
        }
    }
}

function Invoke-HttpViaInvokeWebRequest {
    param(
        [string]$Url,
        [hashtable]$Headers = @{}
    )

    try {
        $response = Invoke-WebRequest -Uri $Url -Method GET -Headers $Headers -TimeoutSec 30 -UseBasicParsing
        $headersHash = @{}
        if ($response.Headers) {
            foreach ($name in $response.Headers.Keys) {
                $headersHash[$name] = [string]$response.Headers[$name]
            }
        }
        return [PSCustomObject]@{
            StatusCode = [int]$response.StatusCode
            Content = [string]$response.Content
            Headers = $headersHash
            Transport = "Invoke-WebRequest"
        }
    }
    catch {
        $webResponse = $_.Exception.Response
        if ($null -ne $webResponse) {
            $statusCode = 0
            try {
                $statusCode = [int]$webResponse.StatusCode
            }
            catch {
                $statusCode = 0
            }

            $headersHash = @{}
            try {
                if ($webResponse.Headers) {
                    foreach ($name in $webResponse.Headers.AllKeys) {
                        if (-not [string]::IsNullOrWhiteSpace([string]$name)) {
                            $headersHash[$name] = [string]$webResponse.Headers[$name]
                        }
                    }
                }
            }
            catch { }

            $content = ""
            try {
                $stream = $webResponse.GetResponseStream()
                if ($null -ne $stream) {
                    $reader = New-Object System.IO.StreamReader($stream)
                    try {
                        $content = $reader.ReadToEnd()
                    }
                    finally {
                        $reader.Close()
                        $stream.Close()
                    }
                }
            }
            catch { }

            return [PSCustomObject]@{
                StatusCode = $statusCode
                Content = [string]$content
                Headers = $headersHash
                Transport = "Invoke-WebRequest"
            }
        }

        throw [System.Exception]::new(
            ("Invoke-WebRequest failed for {0}: {1}" -f $Url, $_.Exception.Message)
        )
    }
}

function Invoke-HttpWithFallback {
    param(
        [string]$Url,
        [hashtable]$Headers = @{}
    )

    $primaryTransport = "Invoke-WebRequest"
    $fallbackTransport = $null
    if (Get-Command "curl.exe" -ErrorAction SilentlyContinue) {
        $primaryTransport = "curl"
        $fallbackTransport = "Invoke-WebRequest"
    }

    $primaryError = $null
    try {
        if ($primaryTransport -eq "curl") {
            return Invoke-HttpViaCurl -Url $Url -Headers $Headers
        }
        return Invoke-HttpViaInvokeWebRequest -Url $Url -Headers $Headers
    }
    catch {
        $primaryError = $_.Exception.Message
    }

    if ([string]::IsNullOrWhiteSpace($fallbackTransport)) {
        throw [System.Exception]::new(
            ("HTTP request failed for {0}. Primary {1} error: {2}" -f $Url, $primaryTransport, $primaryError)
        )
    }

    Write-Step ("Primary transport failed, fallback to {0}: {1}" -f $fallbackTransport, $primaryError)

    try {
        return Invoke-HttpViaInvokeWebRequest -Url $Url -Headers $Headers
    }
    catch {
        $fallbackError = $_.Exception.Message
        throw [System.Exception]::new(
            ("HTTP request failed for {0}. Primary {1} error: {2}. Fallback {3} error: {4}" -f $Url, $primaryTransport, $primaryError, $fallbackTransport, $fallbackError)
        )
    }
}

function Ensure-Http200 {
    param(
        [string]$Url,
        [hashtable]$Headers = @{},
        [string]$Description = "HTTP check"
    )

    Write-Step ("{0}: {1}" -f $Description, $Url)

    $response = $null
    try {
        $response = Invoke-HttpWithFallback -Url $Url -Headers $Headers
    }
    catch {
        Fail ("HTTP request failed for {0}: {1}" -f $Url, $_.Exception.Message)
    }

    Write-Step ("{0} via {1}: HTTP {2}" -f $Description, $response.Transport, $response.StatusCode)

    if ([int]$response.StatusCode -ne 200) {
        Fail ("Unexpected HTTP status for {0}: {1}" -f $Url, $response.StatusCode)
    }

    return $response
}

function Show-RollbackHint {
    if (-not $script:BackupPath) {
        return
    }

    Write-Host ""
    Write-Host "Rollback command:"
    $rollbackCmd = "set -e; tar -xzf `"{0}`" -C `"{1}`"; touch `"{2}/restart.txt`"" -f $script:BackupPath, $script:RemoteCmsRoot, $script:RemoteTmpDir
    Write-Host ("python tools/ssh_run.py '{0}'" -f $rollbackCmd)
}

try {
    $repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    $script:SshRunPath = Join-Path $repoRoot "tools\ssh_run.py"
    $timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"

    Write-Step ("Repo root: {0}" -f $repoRoot)

    # A. Preflight
    Assert-CommandExists -Name "python"
    Assert-CommandExists -Name "tar"

    if (-not (Test-Path -LiteralPath $script:SshRunPath)) {
        Fail ("Missing file: {0}" -f $script:SshRunPath)
    }

    $resolvedConfigPath = Resolve-ConfigPath -RepoRoot $repoRoot -InputPath $ConfigPath
    if (Test-Path -LiteralPath $resolvedConfigPath) {
        $resolvedConfigPath = (Resolve-Path -LiteralPath $resolvedConfigPath).Path
    }
    Write-Step ("Using config: {0}" -f $resolvedConfigPath)

    $config = Read-KeyValueConfig -Path $resolvedConfigPath
    $defaults = @{
        SSH_HOST = "31.31.196.108"
        SSH_USER = "u1995576"
        REMOTE_APP_ROOT = "/var/www/u1995576/data/www/cms.cultnova.ru/app"
        REMOTE_SITE_ROOT = "/var/www/u1995576/data/www/cultnova.ru"
        REMOTE_TMP_DIR = "/var/www/u1995576/data/www/cms.cultnova.ru/tmp"
        REMOTE_VENV_PY = "/var/www/u1995576/data/www/cms.cultnova.ru/venv/bin/python"
        REMOTE_DOMAIN_CMS = "https://cms.cultnova.ru"
        REMOTE_DOMAIN_SITE = "https://cultnova.ru"
    }

    foreach ($key in $defaults.Keys) {
        if (-not $config.ContainsKey($key) -or [string]::IsNullOrWhiteSpace([string]$config[$key])) {
            $config[$key] = $defaults[$key]
            Write-Step ("Config key {0} is missing, using default: {1}" -f $key, $defaults[$key])
        }
    }

    if (-not $config.ContainsKey("SSH_PASS") -or [string]::IsNullOrWhiteSpace([string]$config["SSH_PASS"])) {
        Fail "Config key SSH_PASS is required."
    }

    $env:SSH_HOST = [string]$config["SSH_HOST"]
    $env:SSH_USER = [string]$config["SSH_USER"]
    $env:SSH_PASS = [string]$config["SSH_PASS"]

    $remoteAppRoot = ([string]$config["REMOTE_APP_ROOT"]).TrimEnd("/")
    $remoteSiteRoot = ([string]$config["REMOTE_SITE_ROOT"]).TrimEnd("/")
    $script:RemoteTmpDir = ([string]$config["REMOTE_TMP_DIR"]).TrimEnd("/")
    $remoteVenvPy = [string]$config["REMOTE_VENV_PY"]
    $remoteDomainCms = ([string]$config["REMOTE_DOMAIN_CMS"]).TrimEnd("/")
    $remoteDomainSite = ([string]$config["REMOTE_DOMAIN_SITE"]).TrimEnd("/")

    if ($remoteAppRoot -notmatch "/app$") {
        Fail ("REMOTE_APP_ROOT must end with /app: {0}" -f $remoteAppRoot)
    }

    $script:RemoteCmsRoot = $remoteAppRoot.Substring(0, $remoteAppRoot.Length - 4)

    Invoke-ProcessChecked -Exe "python" -ArgumentList @("-c", "import paramiko") -Description "Checking local python dependency: paramiko"
    Invoke-Remote -Command "echo connected && whoami" -Description "Checking SSH connectivity"

    # B. Package
    $packageDir = Join-Path $repoRoot ("server_backups\deploy_pkg_{0}" -f $timestamp)
    New-Item -ItemType Directory -Path $packageDir -Force | Out-Null

    $script:LogFile = Join-Path $packageDir ("deploy_{0}.log" -f $timestamp)
    New-Item -ItemType File -Path $script:LogFile -Force | Out-Null

    Write-Step ("Deploy log: {0}" -f $script:LogFile)

    $packagePath = Join-Path $packageDir ("cultnova_cms_deploy_{0}.tar.gz" -f $timestamp)
    $packageIncludes = @(
        "blog",
        "core",
        "cultnova",
        "projects",
        "static",
        "templates",
        "manage.py",
        "requirements.txt"
    )

    Push-Location $repoRoot
    try {
        Invoke-ProcessChecked -Exe "tar" -ArgumentList (@("-czf", $packagePath) + $packageIncludes) -Description "Building deploy package"
    }
    finally {
        Pop-Location
    }

    if (-not (Test-Path -LiteralPath $packagePath)) {
        Fail ("Package was not created: {0}" -f $packagePath)
    }
    Write-Step ("Package created: {0}" -f $packagePath)

    # C. Upload
    $remotePackagePath = "{0}/cultnova_cms_deploy_{1}.tar.gz" -f $script:RemoteTmpDir, $timestamp
    $env:DEPLOY_LOCAL_PKG = $packagePath
    $env:DEPLOY_REMOTE_PKG = $remotePackagePath

    $uploadPy = @'
import os
import paramiko

host = os.environ["SSH_HOST"]
user = os.environ["SSH_USER"]
password = os.environ["SSH_PASS"]
local_path = os.environ["DEPLOY_LOCAL_PKG"]
remote_path = os.environ["DEPLOY_REMOTE_PKG"]

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(hostname=host, username=user, password=password, timeout=20)
try:
    sftp = client.open_sftp()
    try:
        sftp.put(local_path, remote_path)
    finally:
        sftp.close()
finally:
    client.close()

print(remote_path)
'@

    Write-Step "Uploading package via SFTP"
    $uploadOut = $uploadPy | python - 2>&1
    $uploadExit = $LASTEXITCODE
    $uploadText = ($uploadOut | Out-String).Trim()
    Write-CommandOutput $uploadText
    if ($uploadExit -ne 0) {
        Fail "SFTP upload failed."
    }

    Invoke-Remote -Command ("test -f `"{0}`" && echo PACKAGE_OK=1" -f $remotePackagePath) -Description "Verifying uploaded package on server"

    # D. Backup
    $backupCmd = 'set -e; ts="{0}"; cms_root="{1}"; backup_dir="$cms_root/_deploy_backups"; mkdir -p "$backup_dir"; tar -czf "$backup_dir/cms_full_before_$ts.tar.gz" -C "$cms_root" app passenger_wsgi.py; echo "BACKUP_PATH=$backup_dir/cms_full_before_$ts.tar.gz"' -f $timestamp, $script:RemoteCmsRoot
    $backupOutput = Invoke-Remote -Command $backupCmd -Description "Creating pre-deploy backup on server"
    $backupMatch = [regex]::Match($backupOutput, "BACKUP_PATH=(.+)")
    if (-not $backupMatch.Success) {
        Fail "Cannot parse backup path from remote output."
    }

    $script:BackupPath = $backupMatch.Groups[1].Value.Trim()
    Write-Step ("Backup created: {0}" -f $script:BackupPath)

    # E. Deploy
    $migratePart = ""
    if ($RunMigrations) {
        $migratePart = '"$venv_py" "$app_root/manage.py" migrate --noinput;'
        Write-Step "Migrations are enabled (-RunMigrations)."
    }
    else {
        Write-Step "Migrations are skipped (default)."
    }

    $deployCmd = 'set -e; pkg="{0}"; app_root="{1}"; tmp_dir="{2}"; venv_py="{3}"; test -f "$pkg"; tar -xzf "$pkg" -C "$app_root"; touch "$tmp_dir/restart.txt"; {4} "$venv_py" "$app_root/manage.py" rebuild_articles_html --delete-unpublished; echo DEPLOY_OK=1' -f $remotePackagePath, $remoteAppRoot, $script:RemoteTmpDir, $remoteVenvPy, $migratePart
    Invoke-Remote -Command $deployCmd -Description "Deploying package and rebuilding article pages"

    # F. Smoke-check
    if ($SkipSmoke) {
        Write-Step "Smoke-check skipped (-SkipSmoke)."
    }
    else {
        $apiArticlesUrl = "{0}/api/articles/" -f $remoteDomainCms
        $apiProjectsUrl = "{0}/api/projects/categories" -f $remoteDomainCms

        $articlesResponse = Ensure-Http200 -Url $apiArticlesUrl -Description "Smoke: API articles"
        $corsResponse = Ensure-Http200 -Url $apiProjectsUrl -Headers @{ Origin = "https://cultnova.ru" } -Description "Smoke: API CORS"
        $acao = $corsResponse.Headers["Access-Control-Allow-Origin"]
        if ($acao -ne "https://cultnova.ru") {
            Fail ("CORS check failed. Expected Access-Control-Allow-Origin=https://cultnova.ru, got: {0}" -f $acao)
        }
        Write-Step "CORS header is valid."

        $firstSlug = $null
        try {
            $articlesJson = $articlesResponse.Content | ConvertFrom-Json
            if ($articlesJson -and $articlesJson.data -and $articlesJson.data.Count -gt 0) {
                $firstSlug = [string]$articlesJson.data[0].slug
            }
        }
        catch {
            Fail ("Failed to parse /api/articles/ JSON: {0}" -f $_.Exception.Message)
        }

        if ([string]::IsNullOrWhiteSpace($firstSlug)) {
            Write-Step "Smoke: article page check skipped (no published articles in API)."
        }
        else {
            $articleUrl = "{0}/articles/{1}/" -f $remoteDomainSite, $firstSlug
            Ensure-Http200 -Url $articleUrl -Description "Smoke: public article page" | Out-Null
            Write-Step ("Public article page is available: {0}" -f $articleUrl)
        }
    }

    Write-Step "Deploy completed successfully."
    exit 0
}
catch {
    Write-Host ""
    Write-Host ("DEPLOY FAILED: {0}" -f $_.Exception.Message)
    Show-RollbackHint
    exit 1
}
