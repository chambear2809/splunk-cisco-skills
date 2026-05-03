# CLI Trust — `cacert.pem` Alignment

A frequently-missed step in Splunk cert rotation: the local
`splunk` CLI uses a separate trust anchor file from inter-Splunk
TLS. After rotation, this file must be aligned or local CLI
calls fail.

## The file

```
$SPLUNK_HOME/etc/auth/cacert.pem
```

This is what the Splunk CLI uses when it makes REST calls to its
own splunkd (e.g. `splunk show cluster-status`,
`splunk apply cluster-bundle`). It's NOT controlled by
`server.conf [sslConfig] sslRootCAPath` — it has its own location.

## Symptoms of misalignment

After installing a new splunkd cert without aligning
`cacert.pem`:

```bash
$ splunk show cluster-status
SSL Error: Couldn't connect to server: certificate verify failed
```

```bash
$ splunk apply cluster-bundle -auth admin:<pw>
SSLError: HTTPSConnectionPool(host='localhost', port=8089): Max retries exceeded with url: /services/cluster/manager/control/default/apply ...
[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed
```

Even though the new cert is valid and other Splunk hosts can
talk to splunkd, the local CLI can't because it doesn't trust
the new CA.

## The fix

`pki/install/align-cli-trust.sh` copies the new CA bundle to
`cacert.pem`:

```bash
#!/usr/bin/env bash
set -euo pipefail

NEW_CA_BUNDLE="${1:?usage: $0 <new-ca-bundle.pem>}"
DEST="$SPLUNK_HOME/etc/auth/cacert.pem"

# Backup the old one
if [[ -f "$DEST" ]]; then
  cp "$DEST" "${DEST}.pki-backup-$(date -u +%Y%m%dT%H%M%SZ)"
fi

# Install the new one
cp "$NEW_CA_BUNDLE" "$DEST"
chown "$(stat -c %U: "$SPLUNK_HOME")" "$DEST"
chmod 0644 "$DEST"

# Verify
if openssl verify -CAfile "$DEST" "$NEW_CA_BUNDLE" >/dev/null 2>&1; then
  echo "OK: cacert.pem aligned to new CA bundle"
else
  echo "WARN: openssl verify of $DEST failed; restore backup if local CLI breaks"
  exit 1
fi
```

The `install-leaf.sh --target splunkd` helper calls
`align-cli-trust.sh` automatically.

## When the operator must run it manually

Out-of-band cert installs (e.g. operator scp's a new cert to a
peer without going through the install helper) require an
explicit `align-cli-trust.sh` run.

## Why Splunk has a separate `cacert.pem`

Splunk historically used `cacert.pem` for the CLI's REST calls
back when `sslRootCAPath` didn't yet exist as a setting. Modern
Splunk versions still honor `cacert.pem` as the CLI's default
trust anchor for backwards compatibility.

The `splunk btool server list sslConfig` output usually shows
both:

```
sslRootCAPath = /opt/splunk/etc/auth/myssl/cabundle.pem
caCertFile    = /opt/splunk/etc/auth/cacert.pem        # legacy, deprecated
```

Best practice: keep `cacert.pem` aligned with the active
`sslRootCAPath` content. The install helper enforces this.

## Splunk CLI verify-disable (debugging only)

For one-off debugging when CLI is broken but the cluster is up:

```bash
splunk --no-verify-cert <command>
```

NEVER use this in scripts or as a workaround. The fix is always
to align `cacert.pem`.

## Splunk REST callers (third-party tooling)

Tools like the Splunk MCP server, monitoring agents, and custom
REST clients often have their own trust-store alignment story:

| Tool | Trust store |
|---|---|
| Splunk MCP server | `mcp.conf [server] ssl_verify=true` + system CA store |
| `curl` from operator workstation | system CA store + `--cacert` flag |
| Splunk Python SDK | system CA store + `splunklib`'s `verify=True` |
| Splunk Java SDK | JVM `cacerts` keystore |
| `splunk btool` | reads from disk; no TLS |

The PKI skill aligns the on-Splunk-host `cacert.pem` only.
External tool trust alignment is operator-driven via:

```
align-cli-trust.sh --include-system-store
```

This appends the new CA bundle to the OS trust store
(`/etc/pki/ca-trust/source/anchors/` on RHEL, `/usr/local/share/ca-certificates/`
on Debian) and runs `update-ca-trust` / `update-ca-certificates`.
Off by default to avoid mutating the OS trust store
unexpectedly.
