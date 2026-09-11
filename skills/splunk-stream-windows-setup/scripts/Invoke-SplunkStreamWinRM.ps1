#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ComputerName,
    [Parameter(Mandatory = $true)]
    [string]$TargetScript,
    [Parameter(Mandatory = $true)]
    [string]$OperationArgumentsJson,
    [string]$PackagePath = '',
    [ValidateSet('Default', 'Kerberos', 'Negotiate', 'Basic', 'CredSSP')]
    [string]$Authentication = 'Default',
    [switch]$UseSSL,
    [int]$Port = 0,
    [string]$CredentialUser = '',
    [string]$CredentialPasswordFile = ''
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $TargetScript -PathType Leaf)) { throw "Target script not found: $TargetScript" }
if ($Authentication -eq 'Basic' -and -not $UseSSL) { throw 'Basic authentication requires -UseSSL.' }

$sessionArguments = @{ ComputerName = $ComputerName; Authentication = $Authentication }
if ($UseSSL) { $sessionArguments.UseSSL = $true }
if ($Port -gt 0) { $sessionArguments.Port = $Port }
if ($CredentialUser) {
    if (-not (Test-Path -LiteralPath $CredentialPasswordFile -PathType Leaf)) { throw 'Credential password file is required.' }
    $secret = [IO.File]::ReadAllText($CredentialPasswordFile).TrimEnd("`r", "`n")
    if ([string]::IsNullOrEmpty($secret)) { throw 'Credential password file is empty.' }
    $secure = ConvertTo-SecureString $secret -AsPlainText -Force
    $sessionArguments.Credential = New-Object Management.Automation.PSCredential($CredentialUser, $secure)
    $secret = $null
}

$session = New-PSSession @sessionArguments
try {
    $remoteRoot = Invoke-Command -Session $session -ScriptBlock {
        $path = Join-Path $env:WINDIR ('Temp\splunk-stream-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $path -Force | Out-Null
        return $path
    }
    $remoteScript = Join-Path $remoteRoot 'Invoke-SplunkStreamWindows.ps1'
    Copy-Item -LiteralPath $TargetScript -Destination $remoteScript -ToSession $session
    $remotePackage = ''
    if ($PackagePath) {
        if (-not (Test-Path -LiteralPath $PackagePath -PathType Leaf)) { throw "Package not found: $PackagePath" }
        $remotePackage = Join-Path $remoteRoot (Split-Path -Leaf $PackagePath)
        Copy-Item -LiteralPath $PackagePath -Destination $remotePackage -ToSession $session
    }
    $arguments = @($OperationArgumentsJson | ConvertFrom-Json)
    for ($index = 0; $index -lt $arguments.Count; $index++) {
        if ([string]$arguments[$index] -eq '__PACKAGE__') { $arguments[$index] = $remotePackage }
    }
    Invoke-Command -Session $session -ScriptBlock {
        param($Script, $Arguments)
        & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script @Arguments
        if ($LASTEXITCODE -ne 0) { throw "Target PowerShell exited with code $LASTEXITCODE." }
    } -ArgumentList $remoteScript, $arguments
}
finally {
    if ($session) {
        if ($remoteRoot) {
            Invoke-Command -Session $session -ScriptBlock { param($Path) Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue } -ArgumentList $remoteRoot -ErrorAction SilentlyContinue
        }
        Remove-PSSession $session
    }
}
