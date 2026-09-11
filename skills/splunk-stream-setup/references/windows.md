# Splunk Stream 8.1.6 on Windows: Deployment Research and Production Design

## Executive determination

Splunk Stream 8.1.6 can capture traffic on 64-bit Windows through
`Splunk_TA_stream`. The reviewed 8.1.6 package includes
`windows_x86_64/bin/streamfwd.exe`, the WinPcap-compatible DLLs that it loads,
and the Npcap 1.55 OEM installer. Splunk's Stream 8.1 deployment requirements
list Windows Server 2012 R2 or later and say that Stream supports only Local
System and Administrator accounts on Windows.^1 The current Stream forwarder
package is published for Splunk platform versions 9.3 through 10.5.^2

Those facts do not make every Windows/Splunk combination safe. Splunk
Enterprise 10.4 no longer permits its Windows service to run as an
Administrator-level user and migrates Local System services to a local service
account during upgrade.^3 That conflicts with Stream's Windows capture account
requirement. Until Splunk publishes a compatible Stream service-identity model,
or Splunk Support approves a specific deployment, this skill must:

- prefer a 64-bit Windows Universal Forwarder running as Local System for
  Windows packet capture;
- refuse Windows-on-ARM, 32-bit Windows, and Independent Stream Forwarder
  installation on Windows;
- refuse to claim support for Stream packet capture on Splunk Enterprise 10.4
  for Windows without a separately recorded vendor exception;
- permit a full Splunk Enterprise instance to remain the Stream search/index
  tier while Windows collection runs on a supported Universal Forwarder; and
- treat a successful package install as incomplete until packet or flow data,
  Stream internal telemetry, and shipped dashboards have all been validated.

The operating-system intersection for a new deployment is narrower than the
historical Stream requirement. Splunk Enterprise 10.4 supports full Enterprise
on Windows Server 2019, 2022, and 2025; Windows Server 2016 is UF-only.^4 A
production plan must use the intersection of the selected Splunk release, the
Stream release, and the Windows release, not the broadest statement from any
one manual.

## Product architecture

A complete managed Stream deployment has three packages:^5

| Component | Placement | Windows relevance |
| --- | --- | --- |
| `splunk_app_stream` | Search tier | Stream management, streams, groups, REST/UI, and dashboards |
| `Splunk_TA_stream_wire_data` | Search tier and indexers | Index/search-time parsing and CIM knowledge objects |
| `Splunk_TA_stream` | Universal or heavy forwarders that capture traffic | Contains the Windows modular input, `streamfwd.exe`, and Npcap OEM installer |

The managed Stream forwarder reads
`Splunk_TA_stream/local/inputs.conf`, contacts the Stream app URL, retrieves its
assigned stream definitions, captures from local NICs or receives flow records,
and emits events through the Splunk forwarding pipeline.^5 An Independent
Stream Forwarder is different: it sends through HEC and is documented as Linux
only, so it is not a Windows installation option.^6

The Stream app URL must be reachable from the Windows host. The conventional
path is:

```text
https://<stream-search-tier>:8000/en-US/custom/splunk_app_stream/
```

TLS verification should remain enabled in production, with `rootCA` and
`sslCommonNameToCheck` set when the certificate chain or name requires an
explicit value. The Stream forwarder's internal status/configuration listener
should bind to `127.0.0.1:8889` unless remote access is explicitly required.

## Investigation before planning

Every Windows run begins with a read-only investigation. It must emit JSON and
a human-readable summary containing the observed values, unresolved findings,
and one recommended plan. Applying from user-supplied assumptions without this
inventory is not a supported path.

### Host and runtime inventory

Collect at least:

- Windows product name, release, build, edition, architecture, pending reboot
  state, hostname, domain/workgroup, time synchronization, and free disk;
- available execution transports and privilege level: local PowerShell,
  Windows OpenSSH, WinRM, AWS Systems Manager, and deployment-client status;
- installed Splunk runtime type, home, version, service name, service state,
  start mode, logon identity, and management port;
- forwarding destinations, deployment server, client name, app deployment
  ownership, and whether `_internal` is forwarded;
- installed versions and enabled state of all three Stream packages;
- existing `local/inputs.conf`, `local/streamfwd.conf`, app ownership, and a
  content digest without printing secrets;
- Npcap/WinPcap products, driver services, versions, registry feature flags,
  pending installer/reboot state, and whether another capture application is
  using the driver;
- enabled physical/virtual NICs, interface GUIDs, Npcap bindings, addresses,
  MTU, link speed, and likely capture interface;
- conflicts on the Stream status port and requested NetFlow/sFlow UDP ports;
- DNS/TLS reachability to the Stream app, Splunk forwarding targets, and any
  remote packet/file server; and
- search-tier package, KV Store, index, stream-definition, dashboard, and
  management-API readiness when credentials are available through protected
  files.

The investigation must not install Npcap, alter a service, open a firewall,
write Splunk configuration, enable streams, or restart anything.

### Plan selection

The plan records:

- runtime prerequisite action (`none`, install/upgrade UF, or blocked);
- transport and package-delivery method;
- package identities, versions, and SHA-256 digests;
- target paths and service identity;
- Npcap action (`none`, install bundled, repair bundled, or blocked);
- Stream app URL, certificate settings, forwarder ID, capture interfaces, flow
  receivers, target indexes, and stream IDs;
- required search-tier/indexer changes;
- expected service restarts, validation traffic, searches, dashboards, and
  rollback artifacts; and
- the exact investigation snapshot hash.

The apply command must present the plan hash and explicit mutation acceptance.
It must re-run the safety-critical inventory under the execution lock and
refuse if runtime version, service identity, installed package version,
configuration digest, Npcap state, or destination paths changed.

## Runtime prerequisite routing

The parent `splunk-stream-setup` workflow owns topology and completion. The
Windows child owns Windows transport, Npcap, Stream forwarder files, and
host-side validation.

If neither Splunk Enterprise nor Universal Forwarder is installed, route to
`splunk-universal-forwarder-setup` to resolve and render the current Windows x64
MSI. A production Windows Stream collector should install the UF as Local
System, seed Splunk credentials only from a protected password file, enroll it
with the deployment server or indexers, validate forwarding, and then return to
the Stream child. Splunk's current Windows UF documentation supports silent MSI
installation from an elevated prompt and documents Local System as an
installation choice.^7

Do not use the deployment server to distribute the UF MSI. Splunk documents
that deployment servers distribute apps and configuration, not the Universal
Forwarder runtime.^8

If a full Windows Splunk Enterprise runtime is requested, investigate its
version and service identity. Existing versions that satisfy both product
support contracts may continue only after explicit compatibility review. A
fresh or upgraded 10.4 Windows Enterprise service cannot be treated as a
supported Stream capture runtime because of the service-account conflict
described above. Use a Windows UF collector or a Linux heavy/independent
forwarder instead.

## Installation and management methods

All methods execute the same target-side PowerShell state machine. Transport
changes how the signed/hashed payload reaches the host and how PowerShell is
invoked; it must not change installation semantics.

| Method | Best use | Required controls |
| --- | --- | --- |
| Local elevated PowerShell | Image build, console/RDP, configuration-management runner | Administrator token, local package hashes, protected secret-file paths |
| Windows OpenSSH + SCP/SFTP | Direct server automation and environments standardized on SSH | Key authentication preferred, pinned host key, administrator principal, constrained staging directory, PowerShell invoked explicitly |
| PowerShell remoting / WinRM | Domain-managed Windows fleets | Kerberos or certificate authentication; HTTPS for non-domain/basic scenarios; no TrustedHosts wildcard |
| AWS Systems Manager Run Command | EC2 Windows without inbound management ports | Online managed node, scoped instance profile, exact instance/tag target, `AWS-RunPowerShellScript`, encrypted/audited output when persisted |
| AWS Systems Manager Distributor | Repeatable AWS fleet deployment | Versioned ZIP, PowerShell install/update/uninstall scripts, SHA-256 manifest, Run Command/State Manager rollout |
| Splunk Agent Management / deployment server | Ongoing TA/config distribution to enrolled UFs | `Splunk_TA_stream` deployment app, explicit Windows server class, `filterType`, controlled restart, client/app readback |
| Splunk REST app endpoint | Search/index tier app install or a host where the package is already server-local | HTTPS management API, protected Splunk credentials, `filename=true`, exact server-local path, install readback |

### Windows OpenSSH

Windows OpenSSH Server is available on supported Windows Server releases and
uses `%ProgramData%\ssh\sshd_config`. The initial default remote shell is
`cmd.exe`; PowerShell can be configured as the default, but the skill must not
assume that it has been.^9 Invoke PowerShell explicitly with a staged `.ps1`
path and `-File` so quoting does not depend on the default shell.

Production SSH requirements:

- verify the target against a reviewed `known_hosts` file or exact host-key
  fingerprint; TOFU is lab-only;
- prefer a private-key file protected by local filesystem permissions; support
  password input only through an existing protected credential mechanism, never
  argv or generated scripts;
- require an administrator account because driver installation and service
  control need elevation;
- stage into a unique directory under `%ProgramData%\SplunkStreamSetup` with
  restrictive ACLs, verify hashes on the host, and remove transient payloads on
  success; and
- support both `scp`/SFTP package transfer and a pre-staged server-local package
  path.

For administrator accounts, Windows OpenSSH normally uses
`%ProgramData%\ssh\administrators_authorized_keys`, whose ACL should be limited
to SYSTEM and Administrators.^10 Enabling or changing OpenSSH itself is an
independent host-management action and must appear in the plan rather than
being silently performed by Stream setup.

### PowerShell remoting / WinRM

Windows Server 2012 R2 and later normally has PowerShell remoting available.
WinRM uses ports 5985 (HTTP) and 5986 (HTTPS), restricts the default endpoint to
Administrators, and encrypts remoting messages after authentication.^11 In a
domain, use Kerberos. Across workgroups or untrusted domains, use HTTPS with
certificate validation; do not add `*` to TrustedHosts. Copy the payload through
a `PSSession`, validate hashes remotely, and call the same target-side script.

### AWS Systems Manager

Run Command can execute `AWS-RunPowerShellScript` on an online managed Windows
node without opening SSH, WinRM, or RDP.^12 Prefer instance IDs or tightly
controlled tags, set bounded timeout/error/concurrency values, and never place
secrets in the command document or command parameters. If output is persisted
to CloudWatch Logs or S3, use an encrypted destination and remember that
CloudTrail records the API call while session/command logging records the
target-side content.

For repeatable AWS fleet deployment, Distributor supports versioned Windows
ZIP packages containing `install.ps1`, `update.ps1`, and `uninstall.ps1`, with
SHA-256 values in its manifest.^13 Distributor is optional; one-host validation
can use Run Command with a pre-staged package.

### Splunk Agent Management / deployment server

The deployment server is the preferred ongoing fleet distribution path once a
Windows UF exists. Put the complete `Splunk_TA_stream` app under
`$SPLUNK_HOME/etc/deployment-apps`, create an explicit Windows-only server
class, enable the app, and set `restartSplunkd=true` for the initial binary/
modular-input activation. Deployed apps land under the client's
`$SPLUNK_HOME/etc/apps` directory.^14

The server class must avoid matching indexers or search-head-cluster members,
must set app-level `filterType` explicitly on current Splunk releases, and must
be validated by client check-in, app hash/version readback, restart completion,
and host-side Stream checks. Package removal through deployment server has had
historical Windows cleanup defects; uninstall must verify absence and report
residual files rather than assuming server-class removal deleted the app.^15

## Windows target-side transaction

### Preflight

1. Require 64-bit Windows and a supported runtime/OS intersection.
2. Require an elevated administrator execution token.
3. Require a supported Splunk service identity; default to UF under Local
   System.
4. Reject a package with unsafe archive paths, multiple top-level directories,
   a mismatched `[package] id`, version mismatch, or SHA-256 mismatch.
5. Confirm the selected NIC and requested ports still exist and are available.
6. Confirm the Stream app URL and forwarding path are reachable.
7. Detect pending reboot, pending MSI installation, capture-driver consumers,
   and app ownership by deployment server or another configuration manager.

### Backup and install

Create a timestamped, ACL-protected transaction directory. Record the service
state, runtime version, app inventory, package hashes, config hashes, Npcap
state, and rollback command. Back up the existing `Splunk_TA_stream` directory
and local configuration before replacement.

For a direct install, stop the Splunk service cleanly, extract the reviewed
`Splunk_TA_stream` archive into `%SPLUNK_HOME%\etc\apps`, and verify the
installed `app.conf`, `streamfwd.exe`, DLLs, and Npcap installer before editing
configuration. Splunk also supports installing an app from a server-local
`.tgz` through `POST /services/apps/local` with `filename=true`; use that path
only when protected Splunk authentication is already available.^16

Do not overwrite deployment-server-owned content locally. Update the deployment
app and redeploy it, or explicitly transfer ownership in the plan.

### Npcap

The 8.1.6 TA contains `npcap-1.55-oem.exe`. Run the bundled installer, rather
than downloading an unreviewed moving version, unless a separate compatibility
decision approves another version. Npcap OEM supports unattended `/S`
installation. Start it with `Start-Process -Wait` because the installer is
backgrounded even in silent mode; handle success, reboot-required (`3010`),
retry-after-reboot (`350`), concurrent-install (`1618`), and unsupported-
platform (`1633`) outcomes explicitly.^17

Use WinPcap API-compatible mode because the TA ships and expects the WinPcap
API surface. Detect existing Npcap/WinPcap first. Do not silently downgrade a
newer Npcap, uninstall a shared capture driver, or terminate other capture
applications. If existing features differ, stop with a reviewed repair plan.
After installation, validate the `npcap` service/driver and the
`WinPcapCompatible` registry value; an installer exit code alone is not proof.^17

Npcap licensing matters. Silent installation is an OEM feature, and fleet use
must stay within the license attached to the vendor-bundled installer or the
organization's own Npcap OEM entitlement.^18 Do not extract and republish the
bundled Npcap installer as an independent package.

### Configuration

Write only `local` configuration, atomically, with CRLF-safe text and a final
newline. At minimum:

```ini
[streamfwd://streamfwd]
splunk_stream_app_location = https://stream.example.com:8000/en-US/custom/splunk_app_stream/
stream_forwarder_id = win-collector-01
sslVerifyServerCert = true
rootCA = C:\ProgramData\Splunk\certs\stream-ca.pem
sslCommonNameToCheck = stream.example.com
disabled = false
```

```ini
[streamfwd]
ipAddr = 127.0.0.1
port = 8889
```

Optional capture-interface and NetFlow/sFlow stanzas belong in
`local/streamfwd.conf`. A flow receiver must use a specific requested UDP port,
validate that Windows Firewall and upstream security controls allow only the
required exporters, and prefer `netflowReceiver.<N>.filter` for exporter
allowlisting. Never expose the internal 8889 listener merely to receive flow
records.

Start the Splunk service and wait for both the runtime and modular input. If
Npcap requests a reboot, the transaction must stop in a resumable
`reboot-required` state and must not report success.

## Validation and completion evidence

Validation must cover the Windows host, transport/control plane, Stream data
plane, search/index tier, and content layer.

### Host evidence

- Splunk service is running under the planned identity and survived a controlled
  restart.
- Installed TA version/build and package digest match the plan.
- Authenticode signatures for the Npcap installer and Stream executable are
  recorded; a missing/invalid signature is a failure unless vendor package
  evidence explicitly explains it.
- Npcap driver is installed/running with the planned compatibility mode.
- `streamfwd.exe` is running as the modular input, its local status port is
  listening, and it reports the expected version/interfaces.
- Stream app TLS/HTTP reachability succeeds and no requested flow port conflict
  exists.
- Recent `streamfwd.log`, `splunkd.log`, and Windows service/driver events show
  no capture, configuration-fetch, TLS, queue, or forwarding errors.

### Data evidence

Generate deterministic, labeled validation traffic without sensitive payloads:

- DNS and HTTP(S) connections from the Windows host for NIC packet capture;
- a minimal valid NetFlow v5 datagram sent to the configured receiver when
  NetFlow is enabled; and
- Stream's built-in stats/log events.

Search with a bounded time window and validation marker. Stream event searches
use `source=stream:<stream-id>` and `sourcetype=stream:<protocol>` syntax.^19
Evidence must include host, source, sourcetype, index, event count, earliest/
latest time, selected protocol fields, and the absence of relevant recent
errors. A running process or open UDP port without indexed data is not success.

### Dashboard evidence

`splunk_app_stream` ships informational dashboards such as Analytics Overview,
Flow Visualization, HTTP, DNS, SSL, and Database Activity, plus admin dashboards
for data volumes, network metrics, forwarder status, and forwarder logs.^20 The
admin dashboards depend on `stream:stats` and `stream:log` data in `_internal`,
so `_internal` from the Windows forwarder must reach the indexers.^21

Completion requires:

- Stream app visible on the search tier;
- shipped views discoverable and not disabled;
- macros and saved searches resolving against the configured indexes;
- Stream Forwarder Status showing the Windows forwarder;
- at least one protocol dashboard returning the generated validation data; and
- NetFlow dashboard/search evidence when flow receiving is part of the plan.

### Feature coverage matrix

| Capability | Windows workflow obligation |
| --- | --- |
| Managed NIC metadata capture | Configure, generate representative DNS/HTTP traffic, and prove indexed events |
| Protocol streams | Permit every package-defined protocol; validate selected protocols and reject unknown IDs |
| NetFlow v5/v9, IPFIX, jFlow, sFlow | Render receiver/filter settings; run a v5 smoke event; validate each production exporter format during rollout |
| Stream filters and forwarder groups | Configure through the Stream app/API; prove the Windows forwarder is assigned and receives the revision |
| Aggregation and estimate mode | Preserve Stream definitions and validate stats for selected streams |
| Content/hash extraction | Support through Stream definitions; test only with approved non-sensitive sample traffic |
| Targeted packet capture | Enterprise-only plan with an approved remote file server, privacy review, write/read test, and packet workflow evidence |
| File extraction | Enterprise-only; requires storage, privacy, malware-handling, and retrieval controls |
| Offline PCAP ingestion/upload | Unsupported in Stream 8.1.5 and later; the skill must not advertise or test it as available^22 |
| Independent Stream Forwarder | Linux-only; route away from Windows^6 |
| Splunk Cloud | Windows managed UF is customer-controlled; search-tier package provisioning and unsupported Cloud packet/file features remain separate gates |

“Supports all protocols” means the workflow accepts and validates every stream
definition shipped by the exact package. It does not mean one smoke test can
prove every parser. A production rollout should select the protocols and flow
formats actually present, generate or replay approved representative traffic,
and retain per-capability evidence.

## Rollback, rerun, and failure handling

The transaction is idempotent. A same-version, same-config rerun must report a
no-op and still validate. An upgrade must preserve `local` configuration, stop
capture before package replacement, and never merge stale `default` files into
the new package.

Rollback must:

1. stop the Splunk service cleanly;
2. restore the complete prior TA directory and local configuration from the
   transaction backup;
3. restore the prior service start state;
4. avoid uninstalling Npcap automatically when it predated the transaction or
   is shared with another product;
5. restart and validate the prior runtime; and
6. retain a private evidence journal if compensation is incomplete.

Do not automatically roll back after data has begun flowing if rollback would
remove a shared driver, discard a newer deployment-server app, or cross a
runtime upgrade boundary. Stop and emit exact recovery commands instead.

The historical Windows capture failure after NIC reconfiguration should be
part of operational validation: re-detect/reapply a stream configuration or
restart the Splunk Forwarder service, then prove capture resumes.^15 Windows
Feature Updates can also disturb Npcap; validate the `npcapwatchdog` task and
driver health after OS servicing.^17

## Sources

1. Splunk. “[Deployment requirements — Splunk Stream 8.1](https://help.splunk.com/en/splunk-enterprise/collect-stream-data/install-and-configure-splunk-stream/8.1/install-splunk-stream-in-a-single-instance-deployment-configuration/deployment-requirements).” Updated August 28, 2025.
2. Splunkbase. “[Splunk Add-on for Stream Forwarders](https://splunkbase.splunk.com/app/5238).” Version 8.1.6, released March 3, 2026.
3. Splunk. “[About upgrading to 10.4: Windows administrator-level service account change](https://help.splunk.com/en/splunk-enterprise/administer/install-and-upgrade/10.4/upgrade-or-migrate-splunk-enterprise/about-upgrading-to-10.4-read-this-first).” Updated May 19, 2026.
4. Splunk. “[System requirements for Splunk Enterprise on-premises 10.4](https://help.splunk.com/en/splunk-enterprise/administer/install-and-upgrade/10.4/plan-your-splunk-enterprise-installation/system-requirements-for-use-of-splunk-enterprise-on-premises).” Updated May 17, 2026.
5. Splunk. “[Splunk Stream on-premise deployment architecture](https://help.splunk.com/en/splunk-enterprise/collect-stream-data/install-and-configure-splunk-stream/8.1/splunk-stream-architecture/splunk-stream-on-premise-deployment-architecture).” Updated August 28, 2025.
6. Splunk. “[Install an Independent Stream Forwarder](https://help.splunk.com/en/data-management/collect-stream-data/install-and-configure-splunk-stream/8.0/install-and-configure-your-splunk-stream-forwarder/install-an-independent-stream-forwarder).” Updated July 23, 2025.
7. Splunk. “[Install a Windows universal forwarder 10.4](https://help.splunk.com/en/splunk-enterprise/forward-and-process-data/universal-forwarder-manual/10.4/install-the-universal-forwarder/install-a-windows-universal-forwarder).” Updated May 17, 2026.
8. Splunk. “[Upgrade the universal forwarder](https://help.splunk.com/en/data-management/forward-data/universal-forwarder-manual/10.4/upgrade-or-uninstall-the-universal-forwarder/upgrade-the-universal-forwarder).” Updated May 17, 2026.
9. Microsoft. “[OpenSSH Server configuration for Windows Server and Windows](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh-server-configuration).” Updated August 5, 2025.
10. Microsoft. “[Key-Based Authentication in OpenSSH for Windows](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_keymanagement).” Updated October 3, 2025.
11. Microsoft. “[Security considerations for PowerShell Remoting using WinRM](https://learn.microsoft.com/en-us/powershell/scripting/security/remoting/winrm-security).” Updated December 9, 2025.
12. Amazon Web Services. “[AWS Systems Manager Run Command](https://docs.aws.amazon.com/systems-manager/latest/userguide/run-command.html).” Accessed September 10, 2026.
13. Amazon Web Services. “[Create a package in Systems Manager Distributor](https://docs.aws.amazon.com/systems-manager/latest/userguide/distributor-working-with-packages-create.html).” Accessed September 10, 2026.
14. Splunk. “[Create deployment apps](https://help.splunk.com/en/splunk-enterprise/administer/update-your-deployment/10.4/configure-the-agent-management-system/create-deployment-apps/create-the-app-directories).” Updated May 11, 2026.
15. Splunk. “[Splunk Stream 8.0 known issues](https://help.splunk.com/ja-jp/splunk-enterprise/collect-stream-data/release-notes/8.0/release-notes/known-issues).” Updated August 28, 2025.
16. Splunk. “[Application endpoint descriptions: apps/local](https://help.splunk.com/en/splunk-enterprise/leverage-rest-apis/rest-api-reference/9.1/application-endpoints/application-endpoint-descriptions).” Updated July 4, 2025.
17. Nmap Project. “[Npcap Users’ Guide](https://npcap.com/guide/npcap-users-guide.html).” Accessed September 10, 2026.
18. Nmap Project. “[Npcap OEM](https://npcap.com/oem/).” Accessed September 10, 2026.
19. Splunk. “[Splunk Stream search syntax](https://help.splunk.com/en/data-management/collect-stream-data/install-and-configure-splunk-stream/8.0/reference/splunk-stream-search-syntax).” Updated July 23, 2025.
20. Splunk. “[Stream Informational Dashboards](https://help.splunk.com/en/data-management/collect-stream-data/use-splunk-stream/8.0/dashboards/stream-informational-dashboards).” Updated July 23, 2025.
21. Splunk. “[Stream Admin dashboards](https://help.splunk.com/en/splunk-cloud-platform/collect-stream-data/use-splunk-stream/8.1/dashboards/stream-admin-dashboards).” Updated July 23, 2025.
22. Splunk. “[What’s New — Splunk Stream 8.1](https://help.splunk.com/en/splunk-cloud-platform/collect-stream-data/release-notes/8.1/release-notes/whats-new).” Updated March 2, 2026.

## Reviewed package evidence

The repository's original 8.1.6 vendor archives were inspected directly on
September 10, 2026:

| Archive | SHA-256 | Material evidence |
| --- | --- | --- |
| `splunk-app-for-stream_816.tgz` | `f9436b71f0bc791b6b74384d23e741e077f61b4852f2133c2bad7edab49fc399` | App version/build, default streams, macros, saved searches, 19 XML views |
| `splunk-add-on-for-stream-forwarders_816.tgz` | `1ac54c5bc6424cabf1b3fe9480f82ccb6348fb74e3af109ea8dbcbf88fa9a068` | Windows x64 Stream executable/DLLs and Npcap 1.55 OEM installer |
| `splunk-add-on-for-stream-wire-data_816.tgz` | `206100a732cedbee90af4c9412301a2a5d894cbf561f05cfad2ace19be14f1d9` | Wire-data knowledge objects; no shipped user-facing views |
