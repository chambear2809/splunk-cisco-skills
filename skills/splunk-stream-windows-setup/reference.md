# Splunk Stream Windows operator reference

The comprehensive, cited design and product research is maintained with the
parent skill at
[`../splunk-stream-setup/references/windows.md`](../splunk-stream-setup/references/windows.md).
Use it for:

- the Splunk Stream and Splunk platform support matrix;
- the Windows Enterprise 10.4 service-identity conflict;
- package placement across search, index, and capture tiers;
- local, OpenSSH, WinRM, SSM Run Command, Distributor, and Deployment Server
  method details;
- Npcap OEM silent-install exit codes and licensing boundaries;
- required host, data, `_internal`, macro, and dashboard evidence;
- feature coverage, upgrade, rollback, and known-issue behavior; and
- direct links to the official Splunk, Microsoft, AWS, and Npcap sources.

## Manual/RDP target entry point

When remote automation is unavailable, copy these two files to a private local
staging directory on the Windows host:

- `scripts/Invoke-SplunkStreamWindows.ps1`
- the hash-verified ZIP produced by `setup.sh plan`

Run `Investigate` first from elevated PowerShell and retain its compact JSON:

```powershell
.\Invoke-SplunkStreamWindows.ps1 -Operation Investigate `
  -StreamAppUrl 'https://splunk.example.com:8000/en-US/custom/splunk_app_stream'
```

Use the controller-generated `plan.json` values for Apply. Do not invent a plan
hash or bypass the controller's inventory-drift check. Manual apply is an
operator handoff and cannot make a production-completion claim until the same
host and parent completion validation have passed.

## WinRM controller notes

`scripts/Invoke-SplunkStreamWinRM.ps1` creates one PSSession, copies the target
script and optional package with `Copy-Item -ToSession`, invokes Windows
PowerShell remotely, and removes staging in `finally`. The Python controller
uses it automatically for `--transport winrm`.

- Domain path: prefer Kerberos with the caller's signed-in identity.
- Workgroup path: use WinRM HTTPS with a validated certificate and a narrowly
  scoped host trust decision.
- Basic authentication is rejected without `--winrm-use-ssl`.
- If a password is unavoidable, create a mode-600 file with the shared secret
  helper and pass only its path.

## Deployment Server boundary

Deployment Server and Agent Management distribute Splunk apps/configuration;
they do not install the Windows UF MSI and should not silently take ownership of
a shared packet-capture driver. Use this child once per Windows host (or a
reviewed Systems Manager Distributor package) to establish Npcap. Then publish
the unchanged `Splunk_TA_stream` payload plus reviewed `local` configuration
through `splunk-agent-management-setup`, backed by
`splunk-deployment-server-setup`. Canary one server class before broad rollout.
