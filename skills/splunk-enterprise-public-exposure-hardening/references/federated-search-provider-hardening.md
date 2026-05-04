# Federated Search Provider Hardening

When a public-facing search head IS a federated-search provider —
i.e., other (consumer) SHs reach inbound to run searches against
this SH — the inbound surface must be hardened separately from the
browser/HEC surface.

## Auth model — IMPORTANT correction

A common misconception is that federated search uses
`pass4SymmKey` (the cluster-style shared secret). **It does not.**

Per the `federated.conf` spec and the official "Service accounts
and security for Federated Search for Splunk" doc:

- Federation authenticates with a **per-provider service account**:
  a native Splunk username + password.
- The credential lives in `federated.conf [provider://<name>]` on
  the **CONSUMER** SH.
- The service account is a **native Splunk user** (NOT LDAP, NOT
  AD, NOT SAML). This is by design — federation has its own
  credential isolation.

The existing `splunk/rotate-pass4symmkey.sh` does NOT touch
federation credentials. Use the new
`splunk/rotate-federation-service-account.sh` helper instead.

## Inbound transport

| Property | Value |
|---|---|
| Port | splunkd `mgmtHostPort` (default 8089) |
| Protocol | HTTPS over TLS 1.2+ (inherits `[sslConfig]` from `server.conf`) |
| mTLS | Supported in Splunk Enterprise 10.0+ via `requireClientCert`; recommended for public-exposure providers |
| Allowlist | `server.conf [httpServer] acceptFrom` — must include consumer SH IPs/CIDR |
| Separate federation port | None — federation reuses splunkd 8089 |

## Provider-side hardening checklist

1. **Service account**: dedicate a Splunk-native user with
   minimum-required search permissions on the federated indexes
   (e.g., `srchIndexesAllowed = main;summary` only; no admin caps).
2. **`acceptFrom`**: add the consumer SH IPs/CIDR to
   `server.conf [httpServer] acceptFrom`. The skill's existing
   acceptFrom rendering already includes a slot for this CIDR.
   Pass the consumer CIDR via `--bastion-cidr`; if an operator needs
   separate federation-only granularity, add a dedicated
   `--federation-consumer-cidr` renderer flag in the same acceptFrom
   allowlist path.
3. **mTLS** (Splunk Enterprise 10.0+): set
   `[sslConfig] requireClientCert = true` on the provider and
   distribute a client cert to each consumer. This adds a layer of
   auth beyond the service-account password.
4. **Service-account lockout awareness**: Splunk auto-locks the
   federation service account if a transparent-mode provider
   definition is saved with bad creds (default 30-minute timeout).
   Pre-validate with the "Test connection" REST call before saving
   on each consumer.

## Consumer-side rotation procedure

When the provider rotates the service-account password (via the
rendered `rotate-federation-service-account.sh`):

1. Provider runs:
   ```
   bash splunk/rotate-federation-service-account.sh \
       fed_svc_acct /path/to/new_password_file
   ```
2. For each CONSUMER SH:
   - Pre-validate with "Test connection" against the new password.
   - Update `etc/system/local/federated.conf [provider://<name>]`
     with the new password (Splunk re-encrypts via the consumer's
     own `splunk.secret`).
   - Save the provider definition. Do NOT save bad creds — that
     triggers the 30-min lockout.
   - Restart Splunk on the consumer.

## What NOT to do

- Do NOT use the LDAP / SAML service tokens for federation. They
  are not supported, and Splunk falls back to the native auth check.
- Do NOT share the federation service account across providers.
  Per-provider isolation is the documented best practice.
- Do NOT publish federation listening on a non-8089 port — Splunk
  does not document a separate federation port.
- Do NOT route federation through the reverse proxy that fronts
  Splunk Web. Federation traffic goes directly to splunkd 8089.

## Validation

The rendered `validate.sh` does not directly probe federation auth
(it would require operator-side credentials). Recommended runtime
validation:

- `splunk list federated-search-config` on the consumer.
- The "Test connection" REST call:
  ```
  curl -k -u admin:* \
       "https://<provider>:8089/services/federated/connect/<provider_name>"
  ```
- Look for `_audit` events on the provider showing successful
  federation searches.

## Related advisories

As of catalog version v2026.05.01, no federated-search-specific
SVDs are tracked. Federation generally inherits the splunkd SVD
floor (already enforced by step 3 of preflight).
