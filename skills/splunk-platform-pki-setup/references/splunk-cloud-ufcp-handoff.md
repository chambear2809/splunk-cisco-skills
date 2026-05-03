# Splunk Cloud Handoff — UFCP and BYOC

This skill targets **self-managed Splunk Enterprise**. For
Splunk Cloud Platform (SCP), Splunk owns the indexer / search-head
trust anchor and you cannot mint your own certs for it. This doc
captures the two related Splunk Cloud handoffs.

## Forwarders sending to Splunk Cloud — UFCP

For Universal / Heavy Forwarders sending data to a Splunk Cloud
Platform stack, do NOT use this skill to issue a forwarder cert.
Splunk Cloud rotates its indexer certs on its own schedule and
your forwarder must trust whatever Splunk presents.

Use the
[Universal Forwarder Credentials Package (UFCP)](https://help.splunk.com/?resourceId=Forwarder_Forwarder_ConfigSCUFCredentials)
which Splunk auto-generates for your stack:

1. In Splunk Cloud Platform, go to **Apps → Universal Forwarder**.
2. Download the credentials package for your stack. The package
   contains:
   - `100_<stack>_app_for_splunkcloud/local/server.conf`
   - `100_<stack>_app_for_splunkcloud/local/outputs.conf`
   - `100_<stack>_app_for_splunkcloud/local/inputs.conf`
   - `100_<stack>_app_for_splunkcloud/auth/server.pem` (forwarder
     client cert, signed by Splunk Cloud)
   - `100_<stack>_app_for_splunkcloud/auth/cacert.pem` (Splunk
     Cloud root CA the forwarder trusts)
3. Install the package into `$SPLUNK_HOME/etc/apps/` on every
   forwarder.
4. Restart the forwarder.

`splunk-universal-forwarder-setup` automates step 3 and step 4.
This PKI skill **refuses** when the operator passes
`--target uf-fleet --destination splunk-cloud`, and emits this
handoff document so the operator runs UFCP instead.

The `server.pem` in UFCP is unique per stack. Splunk Cloud
rotates it; the operator periodically downloads a fresh UFCP
package and redistributes it via `splunk-agent-management-setup`.

## HEC custom-domain BYOC on Splunk Cloud

If the operator wants their HEC endpoint to be reachable as
`hec.example.com` (not `<stack>.splunkcloud.com`) with a cert
matching `hec.example.com`, this is **not currently a self-service
ACS operation**.

The
[Splunk Cloud ACS HEC token doc](https://help.splunk.com/splunk-cloud-platform/administer/admin-config-service-manual/10.1.2507/administer-splunk-cloud-platform-using-the-admin-config-service-acs-api/manage-http-event-collector-hec-tokens-in-splunk-cloud-platform)
covers HEC token management but does NOT expose endpoints to
upload a custom-domain certificate. Operators have two options:

### Option A — Splunk Support ticket

Open a Splunk Support ticket requesting a custom HEC domain.
Splunk provisions the cert on their side. Plan for several
business days.

### Option B — Custom inputs.conf-in-app with operator cert

Build a Splunk Cloud-installable app that includes the operator's
cert chain in `local/inputs.conf [http]`. Splunk Cloud's app
review process accepts this for many tenants but the workflow is
not as clean as ACS-driven HEC management.

This skill emits a handoff document at
`handoff/splunk-cloud-byoc.md` with the contact / process info but
does NOT mint the cert. The operator's Splunk Support engagement
governs the procedure.

## Splunk Cloud federated search

If a Splunk Cloud stack federates from a self-managed Splunk
Enterprise federation provider, the FSS2S provider trust IS in
scope of this skill. See
[`splunk-federated-search-setup`](../../splunk-federated-search-setup/SKILL.md)
for the wiring; this skill emits the per-provider client cert.

## Splunk Cloud forwarder-tier mTLS

If the operator wants forwarder→Splunk-Cloud connections to use
mTLS (where the forwarder presents a client cert that Splunk
Cloud validates), again this is a Splunk Support engagement.
UFCP handles the simple case where the forwarder validates Splunk
Cloud's cert; mutual auth requires Splunk-side configuration on
the SCP indexer cluster.

## Summary

| Use case | Handled by | This skill |
|---|---|---|
| UF / HF → SCP forwarding cert trust | UFCP (download + install) | refuses, emits handoff |
| HEC custom-domain BYOC on SCP | Splunk Support / inputs.conf-in-app | refuses, emits handoff |
| SCP search-head / indexer cert | Splunk owns it | not in scope |
| FSS2S provider on self-managed SE | this skill | mints provider cert |
| FSS2S provider on SCP | Splunk owns it | not in scope |

For a clean separation: this skill targets self-managed Splunk
Enterprise. Splunk Cloud is Splunk's responsibility.
