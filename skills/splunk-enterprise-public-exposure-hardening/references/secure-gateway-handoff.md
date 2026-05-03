# Splunk Secure Gateway Handoff

Splunk Secure Gateway (SG) is the search-head app that bridges Splunk
Mobile, Splunk Edge Hub, and Mission Control to the SH. v1 of this
skill said SG was "out of scope". v2 brings it in scope as a
clarification-and-floor-enforcement target — not a configuration
target — because the SH-side network surface is already covered by
this skill's `web.conf` and `server.conf` hardening.

## Outbound-only architecture (verified)

SG runs in the search head and connects **outbound only** to:

- Default: `prod.spacebridge.spl.mobi:443`
- Regional: `http.<region>.spacebridge.splunkcx.com:443`
  (e.g., `http.us-east-1.spacebridge.splunkcx.com:443`)

These outbound destinations must be allowlisted in the egress
firewall when Splunk Mobile, Edge Hub, or Mission Control (standalone
ES 7) are in use.

**SG opens NO inbound ports of its own** beyond the existing Splunk
Web (8000) and splunkd (8089) surfaces.

## End-to-end auth model (corrected)

Mobile clients authenticate **end-to-end to the SG app**, not to
spacebridge:

- ECC keypairs pinned per device.
- Libsodium ECIES encryption inside TLS 1.2.
- Spacebridge **cannot decrypt** the channel — it is an encrypted
  relay only.

This is the single most-misunderstood part of SG. The previous
"mobile clients authenticate to spacebridge" framing is wrong.

## Search-head-side surfaces

| Path | Already covered by |
|---|---|
| Splunk Web 8000: `/en-US/app/splunk_secure_gateway/` (admin UI) | `web.conf` admin-path lockdown to bastion CIDR |
| splunkd 8089: `/services/ssg/` (REST surface) | `server.conf [httpServer] acceptFrom` |

No new proxy or firewall rules are required when SG is deployed.

## SG-app SVD floor

Splunk Secure Gateway has its own SVD class. The skill's preflight
refuses outdated SG installs. Per-branch floor (in
`references/cve-svd-floor.json`):

| Branch | Floor version |
|---|---|
| 3.9.x | `3.9.10` |
| 3.8.x | `3.8.58` |
| 3.7.x | `3.7.28` |
| 4.x   | (assumed past floor) |

Cited advisories:

- SVD-2025-0302 (HIGH 7.1)
- SVD-2025-1208
- SVD-2025-1202
- SVD-2025-0307
- SVD-2024-1005
- SVD-2023-0212

Preflight step 24 reads `$SPLUNK_HOME/etc/apps/splunk_secure_gateway/
default/app.conf` and refuses to mark the deployment ready when the
version is below the floor.

## Disabling SG

Splunk's documented SG mitigation is "disable the app". The renderer
does NOT do this for you — operator decision — but documents the
side effects:

- Splunk Mobile becomes unavailable to all users.
- Splunk Edge Hub becomes unavailable.
- Mission Control (standalone ES 7) becomes unavailable. ES 8.4 has
  Mission Control bundled differently and is less affected.

To disable:

```bash
splunk disable app splunk_secure_gateway
splunk restart
```

Then re-run the rendered preflight to confirm Step 24 reports
"splunk_secure_gateway not installed".

## Compliance carve-out

Spacebridge is **NOT** FIPS 140-2 / GovCloud / FedRAMP-bound. Sites
operating under FedRAMP (or planning to) MUST either:

1. Disable SG entirely, OR
2. Deploy **Private Spacebridge** via Splunk's Helm chart for an
   on-prem encrypted relay. Note: Private Spacebridge has no push
   notifications.

The skill does not configure Private Spacebridge — that is its own
deployment (separate chart, separate threat model). The skill simply
flags the FIPS / FedRAMP / GovCloud incompatibility so the operator
makes an informed call before exposing publicly.

## Operator-side egress allowlist

```
prod.spacebridge.spl.mobi:443       # default
http.us-east-1.spacebridge.splunkcx.com:443
http.us-west-2.spacebridge.splunkcx.com:443
http.eu-central-1.spacebridge.splunkcx.com:443
# Add the regional endpoints relevant to your deployment.
```

These are the ONLY outbound URLs SG uses. No call-home telemetry
goes to other Splunk-owned domains beyond the standard Splunkbase /
update-checker endpoints which the operator already controls via
`updateCheckerBaseURL`.
