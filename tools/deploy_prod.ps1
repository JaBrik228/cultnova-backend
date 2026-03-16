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

function Convert-ToManifestRelativePath {
    param(
        [string]$Value,
        [string]$FieldName
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        Fail ("Manifest field {0} is required." -f $FieldName)
    }

    $trimmed = $Value.Trim()
    if ($trimmed.StartsWith("/") -or $trimmed.StartsWith('\')) {
        Fail ("Manifest field {0} must be relative: {1}" -f $FieldName, $Value)
    }
    if ($trimmed -match "^[A-Za-z]:") {
        Fail ("Manifest field {0} must not be drive-rooted: {1}" -f $FieldName, $Value)
    }

    $normalized = $trimmed.Replace('\', "/")
    while ($normalized.StartsWith("./")) {
        $normalized = $normalized.Substring(2)
    }

    $parts = $normalized -split "/"
    if ($parts.Count -eq 0) {
        Fail ("Manifest field {0} is empty after normalization." -f $FieldName)
    }

    foreach ($part in $parts) {
        if ([string]::IsNullOrWhiteSpace($part) -or $part -eq "." -or $part -eq "..") {
            Fail ("Manifest field {0} contains invalid path segments: {1}" -f $FieldName, $Value)
        }
    }

    return ($parts -join "/")
}

function Resolve-RepoRelativePath {
    param(
        [string]$RepoRoot,
        [string]$RelativePath,
        [string]$FieldName
    )

    $normalized = Convert-ToManifestRelativePath -Value $RelativePath -FieldName $FieldName
    $repoFullPath = [System.IO.Path]::GetFullPath($RepoRoot)
    $candidatePath = Join-Path $repoFullPath ($normalized -replace "/", [System.IO.Path]::DirectorySeparatorChar)
    $resolvedPath = [System.IO.Path]::GetFullPath($candidatePath)

    if (
        $resolvedPath -ne $repoFullPath -and
        -not $resolvedPath.StartsWith($repoFullPath + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)
    ) {
        Fail ("Manifest field {0} resolves outside repo root: {1}" -f $FieldName, $RelativePath)
    }

    return [PSCustomObject]@{
        RelativePath = $normalized
        FullPath = $resolvedPath
    }
}

function Test-PublicStaticTargetOverlap {
    param(
        [string]$Left,
        [string]$Right
    )

    return (
        $Left.Equals($Right, [System.StringComparison]::OrdinalIgnoreCase) -or
        $Left.StartsWith($Right + "/", [System.StringComparison]::OrdinalIgnoreCase) -or
        $Right.StartsWith($Left + "/", [System.StringComparison]::OrdinalIgnoreCase)
    )
}

function Join-PosixPath {
    param(
        [string]$Base,
        [string]$Child
    )

    if ([string]::IsNullOrWhiteSpace($Base)) {
        return (Convert-ToManifestRelativePath -Value $Child -FieldName "path")
    }

    $trimmedBase = $Base.TrimEnd("/")
    $trimmedChild = $Child.TrimStart("/")

    if ([string]::IsNullOrWhiteSpace($trimmedChild)) {
        return $trimmedBase
    }

    return "{0}/{1}" -f $trimmedBase, $trimmedChild
}

function Get-PosixDirectoryName {
    param([string]$Path)

    $trimmed = $Path.TrimEnd("/")
    $lastSlash = $trimmed.LastIndexOf("/")

    if ($lastSlash -lt 0) {
        return "."
    }
    if ($lastSlash -eq 0) {
        return "/"
    }

    return $trimmed.Substring(0, $lastSlash)
}

function Get-RelativePathNormalized {
    param(
        [string]$BasePath,
        [string]$ChildPath
    )

    $baseFullPath = [System.IO.Path]::GetFullPath($BasePath)
    $childFullPath = [System.IO.Path]::GetFullPath($ChildPath)

    $baseWithSeparator = $baseFullPath
    if (-not $baseWithSeparator.EndsWith([System.IO.Path]::DirectorySeparatorChar)) {
        $baseWithSeparator += [System.IO.Path]::DirectorySeparatorChar
    }

    $baseUri = [System.Uri]::new($baseWithSeparator)
    $childUri = [System.Uri]::new($childFullPath)
    $relativeUri = $baseUri.MakeRelativeUri($childUri)
    $relativePath = [System.Uri]::UnescapeDataString($relativeUri.ToString())

    return $relativePath.Replace('\', "/")
}

function ConvertTo-ShellSingleQuoted {
    param([string]$Value)

    $escaped = $Value.Replace("'", "'`"`'`"`'")
    return "'" + $escaped + "'"
}

function Assert-PublicStaticManifest {
    param(
        [string]$RepoRoot,
        [string]$ManifestPath,
        $Manifest
    )

    if ($null -eq $Manifest) {
        Fail ("Manifest is empty: {0}" -f $ManifestPath)
    }

    if ($Manifest.version -ne 1) {
        Fail ("Unsupported public static manifest version in {0}: {1}" -f $ManifestPath, $Manifest.version)
    }

    $entries = @($Manifest.entries)
    if ($entries.Count -eq 0) {
        Fail ("Manifest entries list is empty: {0}" -f $ManifestPath)
    }

    $normalizedEntries = @()
    $entryTargets = @()

    foreach ($entry in $entries) {
        $kind = [string]$entry.kind
        if ($kind -ne "file" -and $kind -ne "directory") {
            Fail ("Unsupported manifest entry kind in {0}: {1}" -f $ManifestPath, $kind)
        }

        $sourceInfo = Resolve-RepoRelativePath -RepoRoot $RepoRoot -RelativePath ([string]$entry.source) -FieldName "source"
        $targetPath = Convert-ToManifestRelativePath -Value ([string]$entry.target) -FieldName "target"

        if ($kind -eq "file" -and -not (Test-Path -LiteralPath $sourceInfo.FullPath -PathType Leaf)) {
            Fail ("Manifest source is not a file: {0}" -f $sourceInfo.RelativePath)
        }
        if ($kind -eq "directory" -and -not (Test-Path -LiteralPath $sourceInfo.FullPath -PathType Container)) {
            Fail ("Manifest source is not a directory: {0}" -f $sourceInfo.RelativePath)
        }

        foreach ($existingTarget in $entryTargets) {
            if (Test-PublicStaticTargetOverlap -Left $targetPath -Right $existingTarget) {
                Fail (
                    "Manifest target overlap in {0}: {1} conflicts with {2}" -f
                    $ManifestPath,
                    $targetPath,
                    $existingTarget
                )
            }
        }
        $entryTargets += $targetPath

        $prune = $true
        if ($kind -eq "directory" -and ($entry.PSObject.Properties.Name -contains "prune")) {
            $prune = [bool]$entry.prune
        }

        $deployedFiles = @()
        if ($kind -eq "file") {
            $deployedFiles = @($targetPath)
        }
        else {
            $directoryFiles = Get-ChildItem -LiteralPath $sourceInfo.FullPath -File -Recurse | Sort-Object FullName
            foreach ($file in $directoryFiles) {
                $normalizedRelativeFilePath = Get-RelativePathNormalized -BasePath $sourceInfo.FullPath -ChildPath $file.FullName
                $deployedFiles += (Join-PosixPath -Base $targetPath -Child $normalizedRelativeFilePath)
            }
        }

        $normalizedEntries += [PSCustomObject]@{
            Kind = $kind
            SourceRelativePath = $sourceInfo.RelativePath
            SourceFullPath = $sourceInfo.FullPath
            TargetPath = $targetPath
            Prune = $prune
            DeployedFiles = @($deployedFiles | Sort-Object -Unique)
        }
    }

    $managedFiles = @($normalizedEntries | ForEach-Object { $_.DeployedFiles } | Sort-Object -Unique)
    $prunableFiles = @(
        $normalizedEntries |
        Where-Object { $_.Prune } |
        ForEach-Object { $_.DeployedFiles } |
        Sort-Object -Unique
    )

    return [PSCustomObject]@{
        Version = 1
        ManifestPath = $ManifestPath
        Entries = $normalizedEntries
        ManagedFiles = $managedFiles
        PrunableFiles = $prunableFiles
    }
}

function Read-PublicStaticManifest {
    param(
        [string]$RepoRoot,
        [string]$ManifestPath
    )

    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
        Fail ("Public static manifest not found: {0}" -f $ManifestPath)
    }

    try {
        $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    }
    catch {
        Fail ("Failed to parse public static manifest {0}: {1}" -f $ManifestPath, $_.Exception.Message)
    }

    return Assert-PublicStaticManifest -RepoRoot $RepoRoot -ManifestPath $ManifestPath -Manifest $manifest
}

function Get-RemoteManagedStatePath {
    return "{0}/_deploy_state/public_static_manifest_state.json" -f $script:RemoteCmsRoot.TrimEnd("/")
}

function Read-RemotePublicStaticState {
    param([string]$StatePath)

    $command = "if [ -f {0} ]; then cat {0}; fi" -f (ConvertTo-ShellSingleQuoted -Value $StatePath)
    $result = Invoke-RemoteCapture -Command $command -Description "Deploy: reading previous public static state"

    if ($result.ExitCode -ne 0) {
        Fail "Failed to read previous public static state from server."
    }

    if ([string]::IsNullOrWhiteSpace($result.Output)) {
        return [PSCustomObject]@{
            Version = 1
            ManagedFiles = @()
            PrunableFiles = @()
        }
    }

    try {
        $state = $result.Output | ConvertFrom-Json
    }
    catch {
        Fail ("Failed to parse previous public static state JSON from server: {0}" -f $_.Exception.Message)
    }

    $managedFiles = @()
    if ($state.PSObject.Properties.Name -contains "managed_files") {
        $managedFiles = @($state.managed_files | ForEach-Object { Convert-ToManifestRelativePath -Value ([string]$_) -FieldName "managed_files" } | Sort-Object -Unique)
    }

    $prunableFiles = @()
    if ($state.PSObject.Properties.Name -contains "prunable_files") {
        $prunableFiles = @($state.prunable_files | ForEach-Object { Convert-ToManifestRelativePath -Value ([string]$_) -FieldName "prunable_files" } | Sort-Object -Unique)
    }

    return [PSCustomObject]@{
        Version = 1
        ManagedFiles = $managedFiles
        PrunableFiles = $prunableFiles
    }
}

function Upload-FileViaSftp {
    param(
        [string]$LocalPath,
        [string]$RemotePath,
        [string]$Description
    )

    if (-not (Test-Path -LiteralPath $LocalPath -PathType Leaf)) {
        Fail ("Local file not found for upload: {0}" -f $LocalPath)
    }

    $uploadPy = @'
import os
import sys
import paramiko

host = os.environ["SSH_HOST"]
user = os.environ["SSH_USER"]
password = os.environ["SSH_PASS"]
local_path = sys.argv[1]
remote_path = sys.argv[2]

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

    $uploadScriptPath = [System.IO.Path]::Combine(
        [System.IO.Path]::GetTempPath(),
        ("codex_sftp_upload_{0}.py" -f [System.Guid]::NewGuid().ToString("N"))
    )

    try {
        Set-Content -LiteralPath $uploadScriptPath -Value $uploadPy -Encoding UTF8
        Invoke-ProcessChecked -Exe "python" -ArgumentList @($uploadScriptPath, $LocalPath, $RemotePath) -Description $Description
    }
    finally {
        if (Test-Path -LiteralPath $uploadScriptPath) {
            Remove-Item -LiteralPath $uploadScriptPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Get-PublicStaticSmokeTargets {
    param($ManifestInfo)

    $smokeTargets = @()
    foreach ($entry in $ManifestInfo.Entries) {
        if ($entry.Kind -eq "file") {
            $smokeTargets += $entry.TargetPath
            continue
        }

        if ($entry.DeployedFiles.Count -le 5) {
            $smokeTargets += $entry.DeployedFiles
        }
        else {
            $smokeTargets += $entry.DeployedFiles | Select-Object -First 2
        }
    }

    return @($smokeTargets | Sort-Object -Unique)
}

function Sync-PublicStaticAssets {
    param(
        [string]$PackageDir,
        $ManifestInfo,
        [string]$RemoteAppRoot,
        [string]$RemoteSiteRoot,
        [string]$Timestamp
    )

    $statePath = Get-RemoteManagedStatePath
    $previousState = Read-RemotePublicStaticState -StatePath $statePath
    $currentPrunableSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($path in $ManifestInfo.PrunableFiles) {
        [void]$currentPrunableSet.Add($path)
    }

    $filesToPrune = @()
    foreach ($oldFile in $previousState.PrunableFiles) {
        if (-not $currentPrunableSet.Contains($oldFile)) {
            $filesToPrune += $oldFile
        }
    }
    $filesToPrune = @($filesToPrune | Sort-Object -Unique)

    $copyFiles = @($ManifestInfo.ManagedFiles | Sort-Object -Unique)
    $copyDirectories = @()
    foreach ($copyFile in $copyFiles) {
        $copyDirectories += (Get-PosixDirectoryName -Path (Join-PosixPath -Base $RemoteSiteRoot -Child $copyFile))
    }
    $copyDirectories = @($copyDirectories | Sort-Object -Unique)

    $pruneDirectories = @()
    foreach ($pruneFile in $filesToPrune) {
        $pruneDirectories += (Get-PosixDirectoryName -Path (Join-PosixPath -Base $RemoteSiteRoot -Child $pruneFile))
    }
    $pruneDirectories = @($pruneDirectories | Sort-Object -Unique -Descending)

    $statePayload = [ordered]@{
        version = 1
        manifest_version = $ManifestInfo.Version
        written_at = (Get-Date).ToString("o")
        managed_files = @($ManifestInfo.ManagedFiles | Sort-Object -Unique)
        prunable_files = @($ManifestInfo.PrunableFiles | Sort-Object -Unique)
    }
    $stateJson = $statePayload | ConvertTo-Json -Depth 6

    $syncScriptLines = @(
        "#!/bin/sh",
        "set -e",
        ("trap 'rm -f {0}' EXIT" -f (ConvertTo-ShellSingleQuoted -Value ("{0}/public_static_sync_{1}.sh" -f $script:RemoteTmpDir.TrimEnd("/"), $Timestamp)))
    )

    foreach ($directory in $copyDirectories) {
        $syncScriptLines += ("mkdir -p {0}" -f (ConvertTo-ShellSingleQuoted -Value $directory))
    }

    foreach ($entry in $ManifestInfo.Entries) {
        foreach ($targetFile in $entry.DeployedFiles) {
            $sourcePath = Join-PosixPath -Base $RemoteAppRoot -Child $entry.SourceRelativePath
            if ($entry.Kind -eq "directory") {
                $relativeSourceFile = $targetFile.Substring($entry.TargetPath.Length).TrimStart("/")
                $sourcePath = Join-PosixPath -Base $sourcePath -Child $relativeSourceFile
            }

            $targetPath = Join-PosixPath -Base $RemoteSiteRoot -Child $targetFile
            $syncScriptLines += ("cp {0} {1}" -f (ConvertTo-ShellSingleQuoted -Value $sourcePath), (ConvertTo-ShellSingleQuoted -Value $targetPath))
        }
    }

    foreach ($oldFile in $filesToPrune) {
        $targetPath = Join-PosixPath -Base $RemoteSiteRoot -Child $oldFile
        $syncScriptLines += ("rm -f {0}" -f (ConvertTo-ShellSingleQuoted -Value $targetPath))
    }

    foreach ($directory in $pruneDirectories) {
        $syncScriptLines += ("rmdir -p --ignore-fail-on-non-empty {0} 2>/dev/null || true" -f (ConvertTo-ShellSingleQuoted -Value $directory))
    }

    $stateDirectory = Get-PosixDirectoryName -Path $statePath
    $syncScriptLines += ("mkdir -p {0}" -f (ConvertTo-ShellSingleQuoted -Value $stateDirectory))
    $syncScriptLines += ("cat > {0} <<'PUBLIC_STATIC_STATE_EOF'" -f (ConvertTo-ShellSingleQuoted -Value $statePath))
    $syncScriptLines += $stateJson
    $syncScriptLines += "PUBLIC_STATIC_STATE_EOF"
    $syncScriptLines += "echo PUBLIC_STATIC_SYNCED=1"

    $localScriptPath = Join-Path $PackageDir ("public_static_sync_{0}.sh" -f $Timestamp)
    $remoteScriptPath = "{0}/public_static_sync_{1}.sh" -f $script:RemoteTmpDir.TrimEnd("/"), $Timestamp
    [System.IO.File]::WriteAllText(
        $localScriptPath,
        ($syncScriptLines -join "`n"),
        [System.Text.UTF8Encoding]::new($false)
    )

    Invoke-Remote -Command ("mkdir -p {0}" -f (ConvertTo-ShellSingleQuoted -Value $script:RemoteTmpDir)) -Description "Deploy: ensuring remote tmp directory"
    Upload-FileViaSftp -LocalPath $localScriptPath -RemotePath $remoteScriptPath -Description "Deploy: uploading public static sync script"
    Invoke-Remote -Command ("sh {0}" -f (ConvertTo-ShellSingleQuoted -Value $remoteScriptPath)) -Description "Deploy: syncing public static assets from manifest"
}

function Assert-CommandExists {
    param([string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Fail ("Required command not found in PATH: {0}" -f $Name)
    }
}

function Invoke-ProcessCapture {
    param(
        [string]$Exe,
        [string[]]$ArgumentList,
        [string]$Description
    )

    Write-Step $Description
    $previousErrorActionPreference = $ErrorActionPreference
    $hasNativePreference = $null -ne (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue)
    if ($hasNativePreference) {
        $previousNativePreference = $global:PSNativeCommandUseErrorActionPreference
        $global:PSNativeCommandUseErrorActionPreference = $false
    }

    try {
        $ErrorActionPreference = "Continue"
        $output = & $Exe @ArgumentList 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
        if ($hasNativePreference) {
            $global:PSNativeCommandUseErrorActionPreference = $previousNativePreference
        }
    }

    $text = ($output | Out-String).Trim()
    Write-CommandOutput $text

    return [PSCustomObject]@{
        ExitCode = $exitCode
        Output = $text
    }
}

function Invoke-ProcessChecked {
    param(
        [string]$Exe,
        [string[]]$ArgumentList,
        [string]$Description
    )

    $result = Invoke-ProcessCapture -Exe $Exe -ArgumentList $ArgumentList -Description $Description

    if ($result.ExitCode -ne 0) {
        Fail ("Command failed ({0}): {1} {2}" -f $result.ExitCode, $Exe, ($ArgumentList -join " "))
    }

    return $result.Output
}

function Invoke-RemoteCapture {
    param(
        [string]$Command,
        [string]$Description
    )

    return Invoke-ProcessCapture -Exe "python" -ArgumentList @($script:SshRunPath, $Command) -Description $Description
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
    Write-Host "Run from repo root. ssh_run.py will auto-load .env.deploy by default."
    Write-Host ("python tools/ssh_run.py '{0}'" -f $rollbackCmd)
}

try {
    $repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    $script:SshRunPath = Join-Path $repoRoot "tools\ssh_run.py"
    $publicStaticManifestPath = Join-Path $repoRoot "tools\public_static_manifest.json"
    $timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"

    Write-Step ("Repo root: {0}" -f $repoRoot)

    # A. Preflight
    Assert-CommandExists -Name "python"
    Assert-CommandExists -Name "tar"

    if (-not (Test-Path -LiteralPath $script:SshRunPath)) {
        Fail ("Missing file: {0}" -f $script:SshRunPath)
    }

    $publicStaticManifest = Read-PublicStaticManifest -RepoRoot $repoRoot -ManifestPath $publicStaticManifestPath
    Write-Step (
        "Loaded public static manifest: {0} entries, {1} managed files" -f
        $publicStaticManifest.Entries.Count,
        $publicStaticManifest.ManagedFiles.Count
    )

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
    Invoke-Remote -Command ("mkdir -p {0}" -f (ConvertTo-ShellSingleQuoted -Value $script:RemoteTmpDir)) -Description "Ensuring remote tmp directory"
    Upload-FileViaSftp -LocalPath $packagePath -RemotePath $remotePackagePath -Description "Uploading package via SFTP"

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
    if ($RunMigrations) {
        Write-Step "Migrations are enabled (-RunMigrations)."
    }
    else {
        Write-Step "Migrations will only run when pending migrations are detected and -RunMigrations is provided."
    }

    $extractCmd = 'set -e; pkg="{0}"; app_root="{1}"; test -f "$pkg"; tar -xzf "$pkg" -C "$app_root"; echo EXTRACT_OK=1' -f $remotePackagePath, $remoteAppRoot
    Invoke-Remote -Command $extractCmd -Description "Deploy: extracting package on server"

    $installRequirementsCmd = 'set -e; app_root="{0}"; venv_py="{1}"; "$venv_py" -m pip install --disable-pip-version-check -r "$app_root/requirements.txt"' -f $remoteAppRoot, $remoteVenvPy
    Invoke-Remote -Command $installRequirementsCmd -Description "Deploy: installing python requirements"

    $migrationCheckCmd = 'set -e; app_root="{0}"; venv_py="{1}"; "$venv_py" "$app_root/manage.py" migrate --check --noinput' -f $remoteAppRoot, $remoteVenvPy
    $migrationCheck = Invoke-RemoteCapture -Command $migrationCheckCmd -Description "Deploy: checking pending migrations"

    if ($migrationCheck.ExitCode -ne 0) {
        if (-not $RunMigrations) {
            Fail "Pending migrations detected. Re-run deploy with -RunMigrations. Remote output is shown above."
        }

        $migrateCmd = 'set -e; app_root="{0}"; venv_py="{1}"; "$venv_py" "$app_root/manage.py" migrate --noinput' -f $remoteAppRoot, $remoteVenvPy
        Invoke-Remote -Command $migrateCmd -Description "Deploy: applying migrations"
    }
    else {
        Write-Step "Deploy: no pending migrations detected."
    }

    $collectStaticCmd = 'set -e; app_root="{0}"; venv_py="{1}"; "$venv_py" "$app_root/manage.py" collectstatic --noinput --clear' -f $remoteAppRoot, $remoteVenvPy
    Invoke-Remote -Command $collectStaticCmd -Description "Deploy: collecting Django static files"

    $quotedRemoteVenvPy = ConvertTo-ShellSingleQuoted -Value $remoteVenvPy
    $quotedManagePy = ConvertTo-ShellSingleQuoted -Value ("{0}/manage.py" -f $remoteAppRoot)
    $generatedPagesRootCmd = "set -e; {0} {1} shell -c 'from core.services.build_item_html import get_generated_pages_root; print(get_generated_pages_root())'" -f `
        $quotedRemoteVenvPy, `
        $quotedManagePy
    $generatedPagesRoot = (Invoke-Remote -Command $generatedPagesRootCmd -Description "Deploy: resolving generated pages root").Trim()
    if ([string]::IsNullOrWhiteSpace($generatedPagesRoot)) {
        Fail "Deploy: generated pages root resolved to an empty value."
    }
    $generatedPagesRoot = $generatedPagesRoot.TrimEnd("/")
    Write-Step ("Deploy: generated pages root is {0}" -f $generatedPagesRoot)

    $rebuildArticlesCmd = 'set -e; app_root="{0}"; venv_py="{1}"; "$venv_py" "$app_root/manage.py" rebuild_articles_html --delete-unpublished' -f $remoteAppRoot, $remoteVenvPy
    Invoke-Remote -Command $rebuildArticlesCmd -Description "Deploy: rebuilding article pages"

    $rebuildProjectsCmd = 'set -e; app_root="{0}"; venv_py="{1}"; "$venv_py" "$app_root/manage.py" rebuild_projects_html --delete-unpublished' -f $remoteAppRoot, $remoteVenvPy
    Invoke-Remote -Command $rebuildProjectsCmd -Description "Deploy: rebuilding project pages"

    $rebuildSitemapCmd = 'set -e; app_root="{0}"; venv_py="{1}"; "$venv_py" "$app_root/manage.py" rebuild_sitemap' -f $remoteAppRoot, $remoteVenvPy
    Invoke-Remote -Command $rebuildSitemapCmd -Description "Deploy: rebuilding sitemap.xml"

    if ($generatedPagesRoot -ne $remoteSiteRoot) {
        $copySitemapCmd = 'set -e; generated_root="{0}"; site_root="{1}"; test -f "$generated_root/sitemap.xml"; mkdir -p "$site_root"; cp "$generated_root/sitemap.xml" "$site_root/sitemap.xml"; chmod 644 "$site_root/sitemap.xml"' -f $generatedPagesRoot, $remoteSiteRoot
        Invoke-Remote -Command $copySitemapCmd -Description "Deploy: copying sitemap.xml to public site root"
    }
    else {
        Write-Step "Deploy: sitemap.xml is already generated directly in the public site root."
    }

    $chmodSitemapCmd = 'set -e; site_root="{0}"; test -f "$site_root/sitemap.xml"; chmod 644 "$site_root/sitemap.xml"' -f $remoteSiteRoot
    Invoke-Remote -Command $chmodSitemapCmd -Description "Deploy: setting public permissions on sitemap.xml"

    Sync-PublicStaticAssets -PackageDir $packageDir -ManifestInfo $publicStaticManifest -RemoteAppRoot $remoteAppRoot -RemoteSiteRoot $remoteSiteRoot -Timestamp $timestamp

    $restartCmd = 'set -e; tmp_dir="{0}"; touch "$tmp_dir/restart.txt"; echo RESTART_OK=1' -f $script:RemoteTmpDir
    Invoke-Remote -Command $restartCmd -Description "Deploy: restarting app"

    # F. Smoke-check
    if ($SkipSmoke) {
        Write-Step "Smoke-check skipped (-SkipSmoke)."
    }
    else {
        $apiArticlesUrl = "{0}/api/articles/" -f $remoteDomainCms
        $apiProjectsUrl = "{0}/api/projects/categories" -f $remoteDomainCms
        $sitemapPageUrl = "{0}/sitemap/" -f $remoteDomainSite
        $sitemapUrl = "{0}/sitemap.xml" -f $remoteDomainSite
        $cmsStaticUrls = @(
            "{0}/static/vendor/jodit/es2021/jodit.min.js" -f $remoteDomainCms,
            "{0}/static/vendor/jodit/es2021/jodit.min.css" -f $remoteDomainCms,
            "{0}/static/blog/admin/article_richtext.js" -f $remoteDomainCms,
            "{0}/static/blog/admin/article_richtext.css" -f $remoteDomainCms
        )
        $publicSmokeTargets = Get-PublicStaticSmokeTargets -ManifestInfo $publicStaticManifest

        $articlesResponse = Ensure-Http200 -Url $apiArticlesUrl -Description "Smoke: API articles"
        $corsResponse = Ensure-Http200 -Url $apiProjectsUrl -Headers @{ Origin = "https://cultnova.ru" } -Description "Smoke: API CORS"
        $sitemapPageResponse = Ensure-Http200 -Url $sitemapPageUrl -Description "Smoke: sitemap page"
        $sitemapResponse = Ensure-Http200 -Url $sitemapUrl -Description "Smoke: sitemap.xml"
        foreach ($cmsStaticUrl in $cmsStaticUrls) {
            Ensure-Http200 -Url $cmsStaticUrl -Description "Smoke: CMS static asset" | Out-Null
        }
        foreach ($publicTarget in $publicSmokeTargets) {
            $publicUrl = "{0}/{1}" -f $remoteDomainSite, $publicTarget
            Ensure-Http200 -Url $publicUrl -Description "Smoke: public manifest asset" | Out-Null
        }
        $acao = $corsResponse.Headers["Access-Control-Allow-Origin"]
        if ($acao -ne "https://cultnova.ru") {
            Fail ("CORS check failed. Expected Access-Control-Allow-Origin=https://cultnova.ru, got: {0}" -f $acao)
        }
        Write-Step "CORS header is valid."

        if ($sitemapResponse.Content -notmatch [regex]::Escape("<loc>{0}/</loc>" -f $remoteDomainSite)) {
            Fail ("Sitemap check failed. Home page entry is missing in {0}" -f $sitemapUrl)
        }
        Write-Step "Sitemap contains the home page."

        if (
            $sitemapPageResponse.Content -notmatch [regex]::Escape('data-page="sitemap"') -or
            $sitemapPageResponse.Content -notmatch [regex]::Escape('class="sitemap__section"')
        ) {
            Fail ("Sitemap page check failed. Expected markers are missing in {0}" -f $sitemapPageUrl)
        }
        Write-Step "Sitemap page HTML markers are valid."

        $firstSlug = $null
        $firstProjectSlug = $null
        try {
            $articlesJson = $articlesResponse.Content | ConvertFrom-Json
            if ($articlesJson -and $articlesJson.data -and $articlesJson.data.Count -gt 0) {
                $firstSlug = [string]$articlesJson.data[0].slug
            }
        }
        catch {
            Fail ("Failed to parse /api/articles/ JSON: {0}" -f $_.Exception.Message)
        }

        try {
            $categoriesJson = $corsResponse.Content | ConvertFrom-Json
            foreach ($category in @($categoriesJson)) {
                $categorySlug = [string]$category.slug
                if ([string]::IsNullOrWhiteSpace($categorySlug)) {
                    continue
                }

                $projectsByCategoryUrl = "{0}/api/projects/{1}" -f $remoteDomainCms, $categorySlug
                $projectsResponse = Ensure-Http200 -Url $projectsByCategoryUrl -Description "Smoke: API projects by category"
                $projectsJson = $projectsResponse.Content | ConvertFrom-Json
                if ($projectsJson -and $projectsJson.data -and $projectsJson.data.Count -gt 0) {
                    $firstProjectSlug = [string]$projectsJson.data[0].slug
                    break
                }
            }
        }
        catch {
            Fail ("Failed to parse projects API JSON: {0}" -f $_.Exception.Message)
        }

        if ([string]::IsNullOrWhiteSpace($firstSlug)) {
            Write-Step "Smoke: article page check skipped (no published articles in API)."
        }
        else {
            $articleUrl = "{0}/articles/{1}/" -f $remoteDomainSite, $firstSlug
            Ensure-Http200 -Url $articleUrl -Description "Smoke: public article page" | Out-Null
            if ($sitemapResponse.Content -notmatch [regex]::Escape("<loc>{0}</loc>" -f $articleUrl)) {
                Fail ("Sitemap check failed. Article entry is missing: {0}" -f $articleUrl)
            }
            Write-Step ("Public article page is available: {0}" -f $articleUrl)
        }

        if ([string]::IsNullOrWhiteSpace($firstProjectSlug)) {
            Write-Step "Smoke: project page check skipped (no published projects in API)."
        }
        else {
            $projectUrl = "{0}/projects/{1}/" -f $remoteDomainSite, $firstProjectSlug
            $projectDetailApiUrl = "{0}/api/projects/detail/{1}/full" -f $remoteDomainCms, $firstProjectSlug
            Ensure-Http200 -Url $projectUrl -Description "Smoke: public project page" | Out-Null
            $projectDetailResponse = Ensure-Http200 -Url $projectDetailApiUrl -Description "Smoke: API project detail"
            $projectRobots = ""
            try {
                $projectDetailJson = $projectDetailResponse.Content | ConvertFrom-Json
                if ($null -ne $projectDetailJson.seo -and $null -ne $projectDetailJson.seo.robots) {
                    $projectRobots = [string]$projectDetailJson.seo.robots
                }
            }
            catch {
                Fail ("Failed to parse project detail JSON for sitemap smoke-check: {0}" -f $_.Exception.Message)
            }

            if ($projectRobots.ToLowerInvariant().Contains("noindex")) {
                Write-Step ("Smoke: sitemap check skipped for project {0} because seo_robots is {1}" -f $projectUrl, $projectRobots)
            }
            elseif ($sitemapResponse.Content -notmatch [regex]::Escape("<loc>{0}</loc>" -f $projectUrl)) {
                Fail ("Sitemap check failed. Project entry is missing: {0}" -f $projectUrl)
            }
            Write-Step ("Public project page is available: {0}" -f $projectUrl)
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
