# Splunk Universal Forwarder Setup Reference

This skill handles the Universal Forwarder runtime layer. Fleet policy, server
classes, deployment apps, and input app delivery remain the responsibility of
`splunk-agent-management-setup` or product-specific skills.

## Research Basis

The v1 surface follows the current Splunk Universal Forwarder 10.2 manual and
download page:

- <https://www.splunk.com/en_us/download/universal-forwarder.html>
- <https://help.splunk.com/en/data-management/forward-data/universal-forwarder-manual/10.2/deploy-the-universal-forwarder/installation-overview>
- <https://help.splunk.com/en/data-management/forward-data/universal-forwarder-manual/10.2/install-the-universal-forwarder/install-a-nix-universal-forwarder>
- <https://help.splunk.com/en/data-management/forward-data/universal-forwarder-manual/10.2/install-the-universal-forwarder/install-a-windows-universal-forwarder>
- <https://help.splunk.com/en/data-management/forward-data/universal-forwarder-manual/10.2/configure-the-universal-forwarder/configure-the-universal-forwarder-using-configuration-files>
- <https://help.splunk.com/en/data-management/forward-data/universal-forwarder-manual/10.2/configure-the-universal-forwarder/enable-a-receiver-for-the-splunk-cloud-platform>

## Package Matrix

The latest resolver parses Splunk's official download page and recognizes the
full current UF matrix:

| OS family | Architectures / variants | Package types | v1 apply |
|-----------|--------------------------|---------------|----------|
| Linux | `amd64`, `arm64`, `ppc64le`, `s390x` | `.tgz`, `.rpm`, `.deb` where published | local/SSH |
| macOS | `intel`, `universal2` | `.tgz`, `.dmg`, `.pkg` | `.tgz` local/SSH; `.dmg` and `.pkg` download/verify only (operator runs the package installer manually) |
| Windows | `x64`, `x86` | `.msi` | rendered PowerShell only |
| FreeBSD | `freebsd14-amd64`, `freebsd13-amd64` | `.tgz`, `.txz` | unsupported in v1 |
| Solaris | `amd64`, `sparc` | `.tar.Z`, `.p5p` | unsupported in v1 |
| AIX | `powerpc` | `.tgz` | unsupported in v1 |

Official latest downloads verify Splunk's published SHA512 checksum before the
package is accepted. Live metadata is cached under `splunk-ta/` with names such
as `.latest-splunk-universal-forwarder-linux-amd64-tgz.json`. Stale cache
fallback is available only when `--allow-stale-latest` is passed and the cache
is younger than 30 days.

## Phases

| Phase | Behavior |
|-------|----------|
| `render` | Render reviewable assets. Windows uses this as the normal v1 handoff. |
| `download` | Resolve/download/cache/verify the package. |
| `install` | Fresh install, upgrade, or same-version no-op. |
| `enroll` | Apply deployment-server, indexer, or Splunk Cloud enrollment. |
| `status` | Check binary, version, service state, and selected enrollment config. |
| `all` | Unix-like targets run download, install, enroll, and status; Windows renders. |

Render and dry-run phases remain available for download-only or unsupported v1
targets so operators can inspect exact package metadata and handoff notes without
attempting an apply.

## Install Safety

- The skill rejects packages that are not named like official Universal
  Forwarder packages.
- Existing installs are inspected before upgrade. If the target appears to be
  full Splunk Enterprise, the script refuses to install UF over it.
- `.tgz` extraction rejects absolute paths, parent traversal, device files,
  FIFOs, and unsafe link targets before extracting.
- First-start credentials use `user-seed.conf` written from
  `--admin-password-file`; seed files and backups are removed after startup.
- Same-version package requests succeed as no-ops.

## Enrollment Files

Deployment server enrollment renders and applies:

```ini
[deployment-client]
phoneHomeIntervalInSecs = 60
clientName = optional-name

[target-broker:deploymentServer]
targetUri = ds01.example.com:8089
```

Enterprise indexer enrollment renders and applies:

```ini
[tcpout]
defaultGroup = default-autolb-group

[tcpout:default-autolb-group]
server = idx01.example.com:9997,idx02.example.com:9997
useACK = true
autoLBFrequency = 30
forceTimebasedAutoLB = true
```

Splunk Cloud enrollment installs the operator-provided `splunkclouduf.spl`
credentials package with stdin-fed authentication and restarts the forwarder.

## Boundaries

- Do not use this skill for heavy forwarders. Heavy forwarders are full Splunk
  Enterprise runtimes and belong in `splunk-enterprise-host-setup`.
- Do not use this skill to manage server classes or deployment apps. Use
  `splunk-agent-management-setup`.
- Do not render data-input policy here except for minimal future starter
  config. Product inputs should come through Agent Management or the relevant
  product-specific skill.
