#requires -Version 4.0
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Investigate', 'Apply', 'Validate', 'Rollback')]
    [string]$Operation,
    [string]$SplunkHome = '',
    [string]$PackagePath = '',
    [string]$StreamAppUrl = '',
    [string]$BindIp = 'auto',
    [ValidateRange(1, 65535)]
    [int]$Port = 8889,
    [ValidateSet('true', 'false')]
    [string]$SslVerify = 'true',
    [string]$NetflowIp = '',
    [ValidateRange(0, 65535)]
    [int]$NetflowPort = 0,
    [ValidateSet('netflow', 'sflow')]
    [string]$NetflowDecoder = 'netflow',
    [string]$ExpectedPackageSha256 = '',
    [string]$PlanHash = '',
    [string]$TransactionId = '',
    [ValidateSet('install-if-missing', 'preserve', 'upgrade')]
    [string]$NpcapPolicy = 'install-if-missing',
    [switch]$AcceptMutation,
    [string]$TransactionRoot = "$env:ProgramData\SplunkStreamSetup\transactions"
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Write-JsonResult([object]$Value) {
    Write-Output ($Value | ConvertTo-Json -Depth 12 -Compress)
}

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Run this workflow under a local Administrator or LocalSystem execution identity.'
    }
}

function Get-DirectAdministratorMembership([string]$StartName) {
    if ([string]::IsNullOrWhiteSpace($StartName)) { return $false }
    if ($StartName -in @('LocalSystem', 'NT AUTHORITY\SYSTEM', '.\Administrator')) { return $true }
    $parts = $StartName -split '\\', 2
    $wantedDomain = ''
    $wantedName = $parts[-1]
    if ($parts.Count -eq 2) { $wantedDomain = $parts[0] }
    if ($wantedDomain -eq '.') { $wantedDomain = $env:COMPUTERNAME }
    try {
        $group = [ADSI]'WinNT://./Administrators,group'
        foreach ($member in @($group.psbase.Invoke('Members'))) {
            $type = $member.GetType()
            $name = [string]$type.InvokeMember('Name', 'GetProperty', $null, $member, $null)
            $path = [string]$type.InvokeMember('AdsPath', 'GetProperty', $null, $member, $null)
            $domain = ''
            if ($path -match '^WinNT://([^/]+)/') { $domain = $Matches[1] }
            if ($name -ieq $wantedName -and ([string]::IsNullOrWhiteSpace($wantedDomain) -or $domain -ieq $wantedDomain)) {
                return $true
            }
        }
    }
    catch {
        return $false
    }
    return $false
}

function Get-SplunkRuntime([string]$RequestedHome) {
    $service = $null
    foreach ($name in @('SplunkForwarder', 'Splunkd')) {
        $candidate = Get-CimInstance Win32_Service -Filter "Name='$name'" -ErrorAction SilentlyContinue
        if ($null -ne $candidate) { $service = $candidate; break }
    }

    $runtimeHome = $RequestedHome
    if ([string]::IsNullOrWhiteSpace($runtimeHome) -and $null -ne $service) {
        $image = [string]$service.PathName
        $executable = ''
        if ($image -match '^\s*"([^"]+)"') { $executable = $Matches[1] }
        elseif ($image -match '^\s*([^\s]+\.exe)') { $executable = $Matches[1] }
        if ($executable) { $runtimeHome = Split-Path -Parent (Split-Path -Parent $executable) }
    }
    if ([string]::IsNullOrWhiteSpace($runtimeHome)) {
        foreach ($candidateHome in @(
            "$env:ProgramFiles\SplunkUniversalForwarder",
            "$env:ProgramFiles\Splunk",
            "${env:ProgramFiles(x86)}\SplunkUniversalForwarder"
        )) {
            if ($candidateHome -and (Test-Path -LiteralPath (Join-Path $candidateHome 'bin\splunk.exe') -PathType Leaf)) {
                $runtimeHome = $candidateHome
                break
            }
        }
    }

    $runtimeType = 'absent'
    if ($runtimeHome) {
        if (($null -ne $service -and $service.Name -eq 'SplunkForwarder') -or $runtimeHome -match 'SplunkUniversalForwarder') {
            $runtimeType = 'universal-forwarder'
        }
        else { $runtimeType = 'enterprise' }
    }
    $version = ''
    $splunkExe = if ($runtimeHome) { Join-Path $runtimeHome 'bin\splunk.exe' } else { '' }
    if ($splunkExe -and (Test-Path -LiteralPath $splunkExe -PathType Leaf)) {
        $version = [string](Get-Item -LiteralPath $splunkExe).VersionInfo.ProductVersion
    }
    $startName = if ($null -ne $service) { [string]$service.StartName } else { '' }
    $isLocalSystem = $startName -in @('LocalSystem', 'NT AUTHORITY\SYSTEM')
    $isDirectAdmin = if ($startName) { Get-DirectAdministratorMembership $startName } else { $false }
    $serviceRecord = [ordered]@{
        name = if ($null -ne $service) { [string]$service.Name } else { '' }
        state = if ($null -ne $service) { [string]$service.State } else { 'Absent' }
        start_mode = if ($null -ne $service) { [string]$service.StartMode } else { '' }
        start_name = $startName
        local_system = $isLocalSystem
        direct_local_administrator = $isDirectAdmin
        stream_account_supported = ($isLocalSystem -or $isDirectAdmin)
    }
    return [ordered]@{
        home = $runtimeHome
        runtime_type = $runtimeType
        version = $version
        executable_present = [bool]($splunkExe -and (Test-Path -LiteralPath $splunkExe -PathType Leaf))
        service = $serviceRecord
    }
}

function Get-AppVersion([string]$AppPath) {
    foreach ($relative in @('local\app.conf', 'default\app.conf')) {
        $path = Join-Path $AppPath $relative
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
        $inLauncher = $false
        foreach ($line in Get-Content -LiteralPath $path -ErrorAction SilentlyContinue) {
            if ($line -match '^\s*\[([^]]+)\]') { $inLauncher = $Matches[1] -ieq 'launcher'; continue }
            if ($inLauncher -and $line -match '^\s*version\s*=\s*(.+?)\s*$') { return $Matches[1] }
        }
    }
    return ''
}

function Get-ConfStanza([string]$Path, [string]$Stanza) {
    $result = [ordered]@{}
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $result }
    $inside = $false
    foreach ($line in Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue) {
        if ($line -match '^\s*\[([^]]+)\]\s*$') { $inside = $Matches[1] -ieq $Stanza; continue }
        if ($inside -and $line -match '^\s*([^#;][^=]*?)\s*=\s*(.*?)\s*$') {
            $result[$Matches[1].Trim()] = $Matches[2]
        }
    }
    return $result
}

function Get-EffectiveStreamConfig([string]$RuntimeHome) {
    $empty = [ordered]@{ inputs = [ordered]@{}; streamfwd = [ordered]@{} }
    if ([string]::IsNullOrWhiteSpace($RuntimeHome)) { return $empty }
    $app = Join-Path $RuntimeHome 'etc\apps\Splunk_TA_stream'
    if (-not (Test-Path -LiteralPath $app -PathType Container)) { return $empty }
    foreach ($layer in @('default', 'local')) {
        $inputs = Get-ConfStanza (Join-Path $app "$layer\inputs.conf") 'streamfwd://streamfwd'
        foreach ($key in $inputs.Keys) { $empty.inputs[$key] = $inputs[$key] }
        $streamfwd = Get-ConfStanza (Join-Path $app "$layer\streamfwd.conf") 'streamfwd'
        foreach ($key in $streamfwd.Keys) { $empty.streamfwd[$key] = $streamfwd[$key] }
    }
    return $empty
}

function Get-NpcapState {
    $service = Get-Service -Name 'npcap' -ErrorAction SilentlyContinue
    $version = ''
    foreach ($registryPath in @('HKLM:\SOFTWARE\Npcap', 'HKLM:\SOFTWARE\WOW6432Node\Npcap')) {
        if (Test-Path -LiteralPath $registryPath) {
            $record = Get-ItemProperty -LiteralPath $registryPath -ErrorAction SilentlyContinue
            foreach ($property in @('Version', 'CurrentVersion')) {
                if ($record.$property) { $version = [string]$record.$property; break }
            }
        }
        if ($version) { break }
    }
    $watchdog = $null
    if (Get-Command Get-ScheduledTask -ErrorAction SilentlyContinue) {
        $watchdog = Get-ScheduledTask -TaskName 'npcapwatchdog' -ErrorAction SilentlyContinue
    }
    $parameters = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Npcap' -ErrorAction SilentlyContinue
    return [ordered]@{
        installed = [bool]($null -ne $service)
        service_state = if ($null -ne $service) { [string]$service.Status } else { 'Absent' }
        version = $version
        winpcap_compatible = [bool]($null -ne $parameters -and [int]$parameters.WinPcapCompatible -eq 1)
        watchdog_task_present = [bool]($null -ne $watchdog)
    }
}

function Get-NetworkInventory {
    $records = @()
    if (Get-Command Get-NetAdapter -ErrorAction SilentlyContinue) {
        foreach ($adapter in @(Get-NetAdapter -ErrorAction SilentlyContinue | Sort-Object ifIndex)) {
            $addresses = @()
            if (Get-Command Get-NetIPAddress -ErrorAction SilentlyContinue) {
                $addresses = @(Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4, IPv6 -ErrorAction SilentlyContinue |
                    Where-Object { $_.IPAddress -notmatch '^(127\.|::1$|fe80:)' } | Select-Object -ExpandProperty IPAddress)
            }
            $records += [ordered]@{
                name = [string]$adapter.Name
                description = [string]$adapter.InterfaceDescription
                interface_index = [int]$adapter.ifIndex
                status = [string]$adapter.Status
                mac_address = [string]$adapter.MacAddress
                addresses = @($addresses)
            }
        }
    }
    else {
        foreach ($adapter in @(Get-CimInstance Win32_NetworkAdapterConfiguration -Filter 'IPEnabled=True')) {
            $records += [ordered]@{
                name = [string]$adapter.Description
                description = [string]$adapter.Description
                interface_index = [int]$adapter.InterfaceIndex
                status = 'Up'
                mac_address = [string]$adapter.MACAddress
                addresses = @($adapter.IPAddress | Where-Object { $_ -notmatch '^(127\.|::1$|fe80:)' })
            }
        }
    }
    return @($records)
}

function Test-Endpoint([string]$Url) {
    $result = [ordered]@{ tested = $false; host = ''; port = 0; tcp_succeeded = $false; http_succeeded = $false; http_status = 0; error = '' }
    if ([string]::IsNullOrWhiteSpace($Url)) { return $result }
    try { $uri = [Uri]$Url }
    catch { $result.tested = $true; $result.error = 'Invalid URL'; return $result }
    $result.tested = $true
    $result.host = $uri.DnsSafeHost
    $result.port = if ($uri.IsDefaultPort) { if ($uri.Scheme -eq 'https') { 443 } else { 80 } } else { $uri.Port }
    $client = New-Object Net.Sockets.TcpClient
    try {
        $pending = $client.BeginConnect($result.host, $result.port, $null, $null)
        if ($pending.AsyncWaitHandle.WaitOne(5000, $false)) {
            $client.EndConnect($pending)
            $result.tcp_succeeded = $true
        }
        else { $result.error = 'TCP connection timed out' }
    }
    catch { $result.error = $_.Exception.Message }
    finally { $client.Close() }
    if ($result.tcp_succeeded) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -Method Head -TimeoutSec 15
            $result.http_status = [int]$response.StatusCode
            $result.http_succeeded = $true
        }
        catch {
            if ($null -ne $_.Exception.Response) {
                $result.http_status = [int]$_.Exception.Response.StatusCode
                $result.http_succeeded = $true
            }
            elseif (-not $result.error) { $result.error = $_.Exception.Message }
        }
    }
    return $result
}

function Get-Inventory([string]$RequestedHome, [string]$Endpoint) {
    $os = Get-CimInstance Win32_OperatingSystem
    $computer = Get-CimInstance Win32_ComputerSystem
    $runtime = Get-SplunkRuntime $RequestedHome
    $appPath = if ($runtime.home) { Join-Path $runtime.home 'etc\apps\Splunk_TA_stream' } else { '' }
    $configuration = Get-EffectiveStreamConfig $runtime.home
    $process = Get-Process -Name 'streamfwd' -ErrorAction SilentlyContinue
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return [ordered]@{
        schema_version = 1
        checked_at = (Get-Date).ToUniversalTime().ToString('o')
        computer_name = [string]$env:COMPUTERNAME
        execution_identity = [string]$identity.Name
        is_administrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        os = [ordered]@{
            caption = [string]$os.Caption
            version = [string]$os.Version
            build_number = [string]$os.BuildNumber
            architecture = [string]$os.OSArchitecture
            product_type = [int]$os.ProductType
            is_server = [bool]([int]$os.ProductType -ne 1)
            manufacturer = [string]$computer.Manufacturer
            model = [string]$computer.Model
        }
        splunk = $runtime
        npcap = Get-NpcapState
        network_adapters = @(Get-NetworkInventory)
        stream = [ordered]@{
            app_path = $appPath
            installed = [bool]($appPath -and (Test-Path -LiteralPath $appPath -PathType Container))
            version = if ($appPath) { Get-AppVersion $appPath } else { '' }
            process_running = [bool]($null -ne $process)
            configuration = $configuration
        }
        transport_services = [ordered]@{
            openssh = [string]((Get-Service -Name 'sshd' -ErrorAction SilentlyContinue).Status)
            winrm = [string]((Get-Service -Name 'WinRM' -ErrorAction SilentlyContinue).Status)
            ssm = [string]((Get-Service -Name 'AmazonSSMAgent' -ErrorAction SilentlyContinue).Status)
        }
        reachability = Test-Endpoint $Endpoint
    }
}

function Resolve-BindAddress([string]$Requested, [object[]]$Adapters) {
    if ($Requested -and $Requested -ne 'auto') { return $Requested }
    foreach ($adapter in @($Adapters | Where-Object { $_.status -eq 'Up' } | Sort-Object interface_index)) {
        foreach ($address in @($adapter.addresses)) {
            if ($address -match '^\d+\.\d+\.\d+\.\d+$' -and $address -notmatch '^169\.254\.') { return [string]$address }
        }
    }
    throw 'Could not resolve an active non-link-local IPv4 bind address. Supply -BindIp explicitly.'
}

function Set-ConfStanza([string]$Path, [string]$Stanza, [Collections.IDictionary]$Values) {
    $lines = @()
    if (Test-Path -LiteralPath $Path -PathType Leaf) { $lines = @(Get-Content -LiteralPath $Path) }
    $output = New-Object Collections.Generic.List[string]
    $inside = $false
    $found = $false
    $managed = @{}
    foreach ($key in $Values.Keys) { $managed[$key.ToLowerInvariant()] = $true }
    foreach ($line in $lines) {
        if ($line -match '^\s*\[([^]]+)\]\s*$') {
            if ($inside) {
                foreach ($key in $Values.Keys) { $output.Add("$key = $($Values[$key])") }
                $output.Add('')
            }
            $inside = $Matches[1] -ieq $Stanza
            if ($inside) { $found = $true }
            $output.Add($line)
            continue
        }
        if ($inside -and $line -match '^\s*([^#;][^=]*?)\s*=') {
            if ($managed.ContainsKey($Matches[1].Trim().ToLowerInvariant())) { continue }
        }
        $output.Add($line)
    }
    if ($inside) {
        foreach ($key in $Values.Keys) { $output.Add("$key = $($Values[$key])") }
        $output.Add('')
    }
    elseif (-not $found) {
        if ($output.Count -gt 0 -and $output[$output.Count - 1] -ne '') { $output.Add('') }
        $output.Add("[$Stanza]")
        foreach ($key in $Values.Keys) { $output.Add("$key = $($Values[$key])") }
        $output.Add('')
    }
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    [IO.File]::WriteAllLines($Path, $output.ToArray(), [Text.Encoding]::ASCII)
}

function Protect-TransactionDirectory([string]$Path) {
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
    & icacls.exe $Path '/inheritance:r' '/grant:r' '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not restrict transaction directory ACLs: $Path" }
}

function Save-Journal([string]$Path, [Collections.IDictionary]$Journal) {
    $Journal.updated_at = (Get-Date).ToUniversalTime().ToString('o')
    [IO.File]::WriteAllText($Path, ($Journal | ConvertTo-Json -Depth 10), (New-Object Text.UTF8Encoding($false)))
}

function Install-Npcap([string]$Installer, [string]$Policy, [Collections.IDictionary]$Journal) {
    $before = Get-NpcapState
    if ($before.installed -and $Policy -ne 'upgrade') { return $before }
    if (-not $before.installed -and $Policy -eq 'preserve') {
        throw 'Npcap is absent and the reviewed policy is preserve. Choose install-if-missing and re-plan.'
    }
    if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) { throw "Bundled Npcap installer is missing: $Installer" }
    $process = Start-Process -FilePath $Installer -ArgumentList '/S /winpcap_mode=yes' -Wait -PassThru
    $Journal.npcap_exit_code = [int]$process.ExitCode
    if ($process.ExitCode -eq 350) { throw 'Npcap requires a reboot before installation can be retried (exit 350).' }
    if ($process.ExitCode -eq 3010) { $Journal.reboot_required = $true }
    elseif ($process.ExitCode -notin @(0)) {
        throw "Npcap silent installation failed with exit code $($process.ExitCode)."
    }
    if (-not $before.installed) { $Journal.npcap_installed_by_transaction = $true }
    Start-Sleep -Seconds 2
    $after = Get-NpcapState
    if (-not $after.installed) { throw 'Npcap installer returned success but the npcap driver service is absent.' }
    return $after
}

function Get-Validation([string]$RuntimeHome, [string]$Endpoint, [string]$ExpectedBindIp, [int]$ExpectedPort, [string]$ExpectedSsl) {
    $inventory = Get-Inventory $RuntimeHome $Endpoint
    $checks = New-Object Collections.Generic.List[object]
    $warnings = New-Object Collections.Generic.List[string]
    function Add-Check([string]$Name, [bool]$Passed, [string]$Detail) {
        $checks.Add([ordered]@{ name = $Name; passed = $Passed; detail = $Detail })
    }
    Add-Check 'windows_server_x64' ([bool]($inventory.os.is_server -and $inventory.os.architecture -match '64')) "$($inventory.os.caption) $($inventory.os.architecture)"
    Add-Check 'splunk_service_running' ([bool]($inventory.splunk.service.state -eq 'Running')) "$($inventory.splunk.service.name): $($inventory.splunk.service.state)"
    Add-Check 'supported_service_account' ([bool]$inventory.splunk.service.stream_account_supported) "$($inventory.splunk.service.start_name)"
    Add-Check 'npcap_driver_present' ([bool]$inventory.npcap.installed) "Npcap $($inventory.npcap.version), $($inventory.npcap.service_state)"
    Add-Check 'stream_ta_installed' ([bool]$inventory.stream.installed) "Splunk_TA_stream $($inventory.stream.version)"
    Add-Check 'streamfwd_process_running' ([bool]$inventory.stream.process_running) "streamfwd process running=$($inventory.stream.process_running)"
    $inputConfig = $inventory.stream.configuration.inputs
    $forwarderConfig = $inventory.stream.configuration.streamfwd
    Add-Check 'stream_input_enabled' ([bool]($inputConfig.disabled -in @('0', 'false'))) "disabled=$($inputConfig.disabled)"
    Add-Check 'stream_app_location' ([bool](([string]$inputConfig.splunk_stream_app_location).TrimEnd('/') -ieq $Endpoint.TrimEnd('/'))) "$($inputConfig.splunk_stream_app_location)"
    Add-Check 'stream_tls_policy' ([bool]($inputConfig.sslVerifyServerCert -ieq $ExpectedSsl)) "sslVerifyServerCert=$($inputConfig.sslVerifyServerCert)"
    Add-Check 'stream_bind_address' ([bool]($forwarderConfig.ipAddr -ieq $ExpectedBindIp)) "ipAddr=$($forwarderConfig.ipAddr)"
    Add-Check 'stream_management_port' ([bool]([string]$forwarderConfig.port -eq [string]$ExpectedPort)) "port=$($forwarderConfig.port)"
    Add-Check 'stream_app_tcp_reachable' ([bool]$inventory.reachability.tcp_succeeded) "$($inventory.reachability.host):$($inventory.reachability.port)"
    $logPath = Join-Path $inventory.splunk.home 'var\log\splunk\streamfwd.log'
    if (Test-Path -LiteralPath $logPath -PathType Leaf) {
        $recentErrors = @(Get-Content -LiteralPath $logPath -Tail 200 -ErrorAction SilentlyContinue | Where-Object { $_ -match '\b(ERROR|FATAL)\b' })
        if ($recentErrors.Count -gt 0) { $warnings.Add("streamfwd.log contains $($recentErrors.Count) ERROR/FATAL line(s) in its last 200 lines; inspect $logPath") }
    }
    else { $warnings.Add("streamfwd.log is not present yet: $logPath") }
    $failed = @($checks | Where-Object { -not $_.passed })
    return [ordered]@{
        schema_version = 1
        operation = 'Validate'
        success = [bool]($failed.Count -eq 0)
        checked_at = (Get-Date).ToUniversalTime().ToString('o')
        computer_name = $inventory.computer_name
        checks = @($checks)
        warnings = @($warnings)
        failed_checks = @($failed | Select-Object -ExpandProperty name)
        inventory = $inventory
    }
}

function Invoke-Apply {
    Assert-Administrator
    if (-not $AcceptMutation) { throw 'Apply requires -AcceptMutation with a reviewed plan hash.' }
    if ([string]::IsNullOrWhiteSpace($PlanHash) -or [string]::IsNullOrWhiteSpace($TransactionId)) {
        throw 'Apply requires non-empty -PlanHash and -TransactionId values.'
    }
    if (-not (Test-Path -LiteralPath $PackagePath -PathType Leaf)) { throw "Staged package not found: $PackagePath" }
    $actualHash = (Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $ExpectedPackageSha256.ToLowerInvariant()) {
        throw "Staged package SHA-256 mismatch. Expected $ExpectedPackageSha256, got $actualHash."
    }
    $inventory = Get-Inventory $SplunkHome $StreamAppUrl
    if ($inventory.splunk.runtime_type -eq 'absent') { throw 'A Splunk runtime is required before Stream can be installed.' }
    if (-not $inventory.splunk.service.stream_account_supported) { throw "Unsupported Splunk service account: $($inventory.splunk.service.start_name)" }
    if ($inventory.splunk.runtime_type -eq 'enterprise') {
        $versionMatch = [regex]::Match([string]$inventory.splunk.version, '^(\d+)\.(\d+)')
        if ($versionMatch.Success -and (([int]$versionMatch.Groups[1].Value -gt 10) -or
            ([int]$versionMatch.Groups[1].Value -eq 10 -and [int]$versionMatch.Groups[2].Value -ge 4))) {
            throw 'Splunk Enterprise 10.4+ on Windows conflicts with the service identity required by Splunk Stream.'
        }
    }
    $resolvedBindIp = Resolve-BindAddress $BindIp $inventory.network_adapters
    $desiredUrl = $StreamAppUrl.TrimEnd('/') + '/'
    $currentInputs = $inventory.stream.configuration.inputs
    $currentForwarder = $inventory.stream.configuration.streamfwd
    $sameConfig = [bool](
        $inventory.stream.version -eq '8.1.6' -and
        $currentInputs.disabled -in @('0', 'false') -and
        ([string]$currentInputs.splunk_stream_app_location).TrimEnd('/') -ieq $desiredUrl.TrimEnd('/') -and
        $currentInputs.sslVerifyServerCert -ieq $SslVerify -and
        $currentForwarder.ipAddr -ieq $resolvedBindIp -and
        [string]$currentForwarder.port -eq [string]$Port -and
        ($inventory.npcap.installed -or $NpcapPolicy -eq 'preserve')
    )
    if ($sameConfig -and $inventory.splunk.service.state -eq 'Running' -and $inventory.stream.process_running -and $NpcapPolicy -ne 'upgrade') {
        $validation = Get-Validation $inventory.splunk.home $desiredUrl $resolvedBindIp $Port $SslVerify
        $validation.operation = 'Apply'
        $validation.no_op = $true
        $validation.plan_hash = $PlanHash
        $validation.transaction_id = $TransactionId
        return $validation
    }

    $transaction = Join-Path $TransactionRoot $TransactionId
    Protect-TransactionDirectory $transaction
    $journalPath = Join-Path $transaction 'journal.json'
    if (Test-Path -LiteralPath $journalPath -PathType Leaf) {
        $existing = Get-Content -LiteralPath $journalPath -Raw | ConvertFrom-Json
        if ($existing.status -eq 'complete') {
            $validation = Get-Validation $inventory.splunk.home $desiredUrl $resolvedBindIp $Port $SslVerify
            $validation.operation = 'Apply'
            $validation.no_op = $true
            $validation.plan_hash = $PlanHash
            $validation.transaction_id = $TransactionId
            return $validation
        }
        throw "Transaction already exists but is not complete: $transaction"
    }
    $appParent = Join-Path $inventory.splunk.home 'etc\apps'
    $appPath = Join-Path $appParent 'Splunk_TA_stream'
    $backupPath = Join-Path $transaction 'Splunk_TA_stream.before'
    $extractRoot = Join-Path $transaction 'expanded'
    $journal = [ordered]@{
        schema_version = 1
        transaction_id = $TransactionId
        plan_hash = $PlanHash
        status = 'started'
        splunk_home = $inventory.splunk.home
        service_name = $inventory.splunk.service.name
        prior_service_state = $inventory.splunk.service.state
        app_path = $appPath
        backup_path = $backupPath
        prior_app_present = [bool](Test-Path -LiteralPath $appPath -PathType Container)
        npcap_installed_before = [bool]$inventory.npcap.installed
        npcap_installed_by_transaction = $false
        npcap_exit_code = $null
        reboot_required = $false
        resolved_bind_ip = $resolvedBindIp
        created_at = (Get-Date).ToUniversalTime().ToString('o')
        updated_at = ''
    }
    Save-Journal $journalPath $journal

    $serviceName = $inventory.splunk.service.name
    $serviceWasStopped = $false
    $oldAppMoved = $false
    $newAppMoved = $false
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        New-Item -ItemType Directory -Path $extractRoot -Force | Out-Null
        [IO.Compression.ZipFile]::ExtractToDirectory($PackagePath, $extractRoot)
        $stagedApp = Join-Path $extractRoot 'Splunk_TA_stream'
        $streamExe = Join-Path $stagedApp 'windows_x86_64\bin\streamfwd.exe'
        $npcapInstaller = Join-Path $stagedApp 'windows_x86_64\bin\npcap-1.55-oem.exe'
        if (-not (Test-Path -LiteralPath $streamExe -PathType Leaf)) { throw 'Staged package is missing windows_x86_64\bin\streamfwd.exe.' }
        if ((Get-AppVersion $stagedApp) -ne '8.1.6') { throw 'Staged package version is not the reviewed Stream 8.1.6 build.' }
        Install-Npcap $npcapInstaller $NpcapPolicy $journal | Out-Null
        Save-Journal $journalPath $journal

        if (Test-Path -LiteralPath (Join-Path $appPath 'local') -PathType Container) {
            Copy-Item -LiteralPath (Join-Path $appPath 'local') -Destination (Join-Path $stagedApp 'local') -Recurse -Force
        }
        $inputs = [ordered]@{
            disabled = '0'
            source = 'stream'
            splunk_stream_app_location = $desiredUrl
            sslVerifyServerCert = $SslVerify
        }
        $forwarder = [ordered]@{ ipAddr = $resolvedBindIp; port = [string]$Port }
        if ($NetflowPort -gt 0) {
            $forwarder['netflowReceiver.0.ip'] = $NetflowIp
            $forwarder['netflowReceiver.0.port'] = [string]$NetflowPort
            $forwarder['netflowReceiver.0.decoder'] = $NetflowDecoder
        }
        Set-ConfStanza (Join-Path $stagedApp 'local\inputs.conf') 'streamfwd://streamfwd' $inputs
        Set-ConfStanza (Join-Path $stagedApp 'local\streamfwd.conf') 'streamfwd' $forwarder

        if ($inventory.splunk.service.state -eq 'Running') {
            Stop-Service -Name $serviceName -Force
            (Get-Service -Name $serviceName).WaitForStatus('Stopped', (New-TimeSpan -Seconds 60))
            $serviceWasStopped = $true
        }
        if (Test-Path -LiteralPath $appPath -PathType Container) {
            Move-Item -LiteralPath $appPath -Destination $backupPath
            $oldAppMoved = $true
        }
        Move-Item -LiteralPath $stagedApp -Destination $appPath
        $newAppMoved = $true
        $journal.status = 'installed'
        Save-Journal $journalPath $journal

        Start-Service -Name $serviceName
        (Get-Service -Name $serviceName).WaitForStatus('Running', (New-TimeSpan -Seconds 60))
        $deadline = (Get-Date).AddSeconds(90)
        do {
            if (Get-Process -Name 'streamfwd' -ErrorAction SilentlyContinue) { break }
            Start-Sleep -Seconds 3
        } while ((Get-Date) -lt $deadline)
        $validation = Get-Validation $inventory.splunk.home $desiredUrl $resolvedBindIp $Port $SslVerify
        if (-not $validation.success) { throw "Post-install validation failed: $($validation.failed_checks -join ', ')" }
        $journal.status = 'complete'
        $journal.completed_at = (Get-Date).ToUniversalTime().ToString('o')
        Save-Journal $journalPath $journal
        $validation.operation = 'Apply'
        $validation.no_op = $false
        $validation.plan_hash = $PlanHash
        $validation.transaction_id = $TransactionId
        $validation.journal_path = $journalPath
        $validation.reboot_required = [bool]$journal.reboot_required
        return $validation
    }
    catch {
        $failure = $_.Exception.Message
        try {
            if ((Get-Service -Name $serviceName -ErrorAction SilentlyContinue).Status -eq 'Running') { Stop-Service -Name $serviceName -Force }
            if ($newAppMoved -and (Test-Path -LiteralPath $appPath -PathType Container)) {
                Move-Item -LiteralPath $appPath -Destination (Join-Path $transaction 'Splunk_TA_stream.failed')
            }
            if ($oldAppMoved -and (Test-Path -LiteralPath $backupPath -PathType Container)) {
                Move-Item -LiteralPath $backupPath -Destination $appPath
            }
            if ($serviceWasStopped -or $inventory.splunk.service.state -eq 'Running') { Start-Service -Name $serviceName }
            $journal.status = 'compensated'
            $journal.failure = $failure
            Save-Journal $journalPath $journal
        }
        catch {
            $journal.status = 'compensation-failed'
            $journal.failure = $failure
            $journal.compensation_failure = $_.Exception.Message
            Save-Journal $journalPath $journal
        }
        throw "Splunk Stream apply failed: $failure. Transaction journal: $journalPath"
    }
}

function Invoke-Rollback {
    Assert-Administrator
    if (-not $AcceptMutation) { throw 'Rollback requires -AcceptMutation.' }
    if ([string]::IsNullOrWhiteSpace($TransactionId) -or [string]::IsNullOrWhiteSpace($PlanHash)) {
        throw 'Rollback requires -TransactionId and -PlanHash.'
    }
    $transaction = Join-Path $TransactionRoot $TransactionId
    $journalPath = Join-Path $transaction 'journal.json'
    if (-not (Test-Path -LiteralPath $journalPath -PathType Leaf)) { throw "Transaction journal not found: $journalPath" }
    $journal = Get-Content -LiteralPath $journalPath -Raw | ConvertFrom-Json
    if ($journal.plan_hash -ne $PlanHash) { throw 'Transaction plan hash does not match the reviewed plan.' }
    if ($journal.status -eq 'rolled-back') {
        return [ordered]@{ schema_version = 1; operation = 'Rollback'; success = $true; no_op = $true; transaction_id = $TransactionId; journal_path = $journalPath }
    }
    $service = Get-Service -Name $journal.service_name -ErrorAction Stop
    if ($service.Status -eq 'Running') {
        Stop-Service -Name $journal.service_name -Force
        (Get-Service -Name $journal.service_name).WaitForStatus('Stopped', (New-TimeSpan -Seconds 60))
    }
    $currentRecovery = Join-Path $transaction 'Splunk_TA_stream.rolled_back_from'
    if (Test-Path -LiteralPath $journal.app_path -PathType Container) {
        if (Test-Path -LiteralPath $currentRecovery) { throw "Rollback recovery path already exists: $currentRecovery" }
        Move-Item -LiteralPath $journal.app_path -Destination $currentRecovery
    }
    if ($journal.prior_app_present) {
        if (-not (Test-Path -LiteralPath $journal.backup_path -PathType Container)) { throw "Prior app backup is missing: $($journal.backup_path)" }
        Move-Item -LiteralPath $journal.backup_path -Destination $journal.app_path
    }
    if ($journal.prior_service_state -eq 'Running') {
        Start-Service -Name $journal.service_name
        (Get-Service -Name $journal.service_name).WaitForStatus('Running', (New-TimeSpan -Seconds 60))
    }
    $journal.status = 'rolled-back'
    $journal.rolled_back_at = (Get-Date).ToUniversalTime().ToString('o')
    $journal | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $journalPath -Encoding UTF8
    $restored = if ($journal.prior_app_present) { Test-Path -LiteralPath $journal.app_path -PathType Container } else { -not (Test-Path -LiteralPath $journal.app_path) }
    return [ordered]@{
        schema_version = 1
        operation = 'Rollback'
        success = [bool]$restored
        no_op = $false
        prior_app_restored = [bool]$restored
        npcap_retained = [bool]$journal.npcap_installed_by_transaction
        transaction_id = $TransactionId
        journal_path = $journalPath
    }
}

try {
    switch ($Operation) {
        'Investigate' { Write-JsonResult (Get-Inventory $SplunkHome $StreamAppUrl) }
        'Apply' { Write-JsonResult (Invoke-Apply) }
        'Validate' {
            $inventory = Get-Inventory $SplunkHome $StreamAppUrl
            $resolved = Resolve-BindAddress $BindIp $inventory.network_adapters
            Write-JsonResult (Get-Validation $inventory.splunk.home $StreamAppUrl $resolved $Port $SslVerify)
        }
        'Rollback' { Write-JsonResult (Invoke-Rollback) }
    }
}
catch {
    Write-Error $_
    exit 1
}
