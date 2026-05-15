---
name: splunk-universal-forwarder-setup
description: >-
  Bootstrap Splunk Universal Forwarder runtimes on Linux, macOS, and Windows,
  resolve official UF downloads, render first-class enrollment assets for
  deployment servers, static Enterprise indexers, or Splunk Cloud credentials
  packages, and validate installed forwarders. Use when the user asks to
  install, upgrade, enroll, or check Universal Forwarders separately from full
  Splunk Enterprise host bootstrap or Agent Management server-class work.
---

# Splunk Universal Forwarder Setup

Bootstraps **Universal Forwarder runtime clients**. Use this skill for endpoint
or server forwarders that should run the lightweight UF package, not a full
Splunk Enterprise heavy forwarder.

## Scope

- Linux: local and SSH apply for `.rpm`, `.deb`, and `.tgz`; default
  `SPLUNK_HOME=/opt/splunkforwarder`; default service user `splunkfwd`.
- macOS: local and SSH apply for `.tgz`; default
  `SPLUNK_HOME=/Applications/splunkforwarder`.
- Windows: render an administrator-run PowerShell/MSI bootstrap script. WinRM
  execution is out of scope in v1.
- FreeBSD, Solaris, and AIX: recognized by latest-resolution metadata and smoke
  checks, but install/apply is unsupported in v1.

The skill intentionally delegates server classes and deployment apps to
`splunk-agent-management-setup`. This workflow installs or upgrades the UF
runtime and enrolls the client only.

## Credential Rules

Never ask for passwords in chat and never pass password values as argv or
environment-variable prefixes.

Use a local password file for first-start admin seeding and Splunk Cloud
credentials-package installs:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/uf_admin_password
```

Then pass only the file path:

```bash
--admin-password-file /tmp/uf_admin_password
```

Windows rendering follows the same rule. The PowerShell script installs MSI
packages with `LAUNCHSPLUNK=0`, writes `user-seed.conf` from the password file
before first start, and removes seed artifacts after startup. It never renders
or runs `SPLUNKPASSWORD=...`.

## Main Script

```bash
bash skills/splunk-universal-forwarder-setup/scripts/setup.sh \
  --phase render|download|install|enroll|status|all \
  --target-os auto|linux|macos|windows|freebsd|solaris|aix \
  --execution local|ssh|render \
  --source auto|splunk-auth|remote|local \
  --url latest|URL \
  --file PATH \
  --package-type auto|tgz|rpm|deb|msi|dmg|pkg|txz|p5p|tar-z
```

Useful additions:

- `--target-arch auto|amd64|arm64|ppc64le|s390x|x64|x86|intel|universal2|freebsd13-amd64|freebsd14-amd64|sparc|powerpc`
- `--allow-stale-latest`
- `--output-dir PATH`
- `--dry-run --json`

## Enrollment Modes

- `--enroll none`: install or upgrade only.
- `--enroll deployment-server --deployment-server HOST:PORT`: writes
  `deploymentclient.conf` using the same client semantics as Agent Management.
- `--enroll enterprise-indexers --server-list HOST:9997[,HOST:9997...]`:
  writes `outputs.conf` with static load-balanced indexers and `useACK=true`.
- `--enroll splunk-cloud --cloud-credentials-package PATH`: installs the
  user-supplied `splunkclouduf.spl` package and restarts the forwarder.

## Examples

Linux install and deployment-server enrollment:

```bash
bash skills/splunk-universal-forwarder-setup/scripts/setup.sh \
  --phase all \
  --target-os linux \
  --source remote \
  --url latest \
  --enroll deployment-server \
  --deployment-server ds01.example.com:8089 \
  --client-name web01 \
  --admin-password-file /tmp/uf_admin_password
```

Windows MSI handoff:

```bash
bash skills/splunk-universal-forwarder-setup/scripts/setup.sh \
  --phase render \
  --target-os windows \
  --execution render \
  --source local \
  --file /tmp/splunkforwarder.msi \
  --enroll enterprise-indexers \
  --server-list idx01.example.com:9997,idx02.example.com:9997 \
  --admin-password-file C:\\Temp\\uf_admin_password.txt
```

Latest-resolution smoke without downloading a package:

```bash
bash skills/splunk-universal-forwarder-setup/scripts/smoke_latest_resolution.sh \
  --target-os all \
  --package-type all
```

## Validate

```bash
bash skills/splunk-universal-forwarder-setup/scripts/validate.sh \
  --target-os linux \
  --execution ssh \
  --enroll deployment-server
```

## Hand-off Contracts

- **DS runtime** (bootstrap, `phoneHome` tuning, HA pair, client migration): see [`splunk-deployment-server-setup`](../splunk-deployment-server-setup/SKILL.md). This skill handles UF enrollment; `splunk-deployment-server-setup` owns the DS runtime side.
- **Server class authoring**: see [`splunk-agent-management-setup`](../splunk-agent-management-setup/SKILL.md) for `serverclass.conf` and `deploymentclient.conf` rendering.

## References

- [reference.md](reference.md) for package matrix, phases, and operational notes
- [template.example](template.example) for non-secret intake
