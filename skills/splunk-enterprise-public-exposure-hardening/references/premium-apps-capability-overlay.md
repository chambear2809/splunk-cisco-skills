# Premium Apps Capability Overlay

When ES, SOAR, ITSI, UBA, ARI, AA, Mission Control, Content Packs,
or SSE are installed on a public-facing search head, those apps add
capabilities to `authorize.conf` that the base `role_public_reader`
hardening does not know about. The skill's preflight scans for them
in two tiers.

## Tier A — embedded list

These apps publish a canonical Splunk-side capability reference, so
the overlay ships an embedded list (JSON) with pinned doc versions:

| App | Pinned version | Source |
|---|---|---|
| Splunk Enterprise Security 8.x | 8.4 | https://help.splunk.com/en/splunk-enterprise-security-8/install/8.4/installation/capability-reference-for-splunk-enterprise-security |
| Splunk Enterprise Security 7.x | 7.3 | https://help.splunk.com/splunk-enterprise-security-7/install/7.3/installation/capability-reference-for-splunk-enterprise-security |
| `splunk_app_soar` (Splunkbase 6361) | 1.0.74 | Splunkbase + app's `default/authorize.conf` |
| Splunk IT Service Intelligence (`SA-ITOA`) | 4.21 | https://docs.splunk.com/Documentation/ITSI/4.21.0/Configure/itsi-roles |
| `Splunk_TA_ueba` (UEBA SH-side) | latest | UEBA TA spec |
| Splunk Asset and Risk Intelligence | 1.2 | https://help.splunk.com/en/splunk-asset-and-risk-intelligence |
| Mission Control (ES 7 standalone OR ES 8.4 bundled) | bundled | (handled by ES 8.4 entry) |

Avoid these stale URLs (404):
- `Documentation/ES/latest/Install/Capabilityreference`
- `Documentation/ARI/latest/Install/RolesAndCapabilities`

## Tier B — WARN-only (runtime scan)

These apps do NOT publish a public capability reference. The overlay
scans `default/authorize.conf` of the installed app at preflight time
and warns on any custom capability granted to a non-admin role:

- Splunk App for SOAR Export (Splunkbase 3411)
- `Splunk_TA_SAA` + `Splunk_App_SAA` (Attack Analyzer)
- Splunk App for Content Packs
- Splunk Security Essentials

## Special-case rules

### `list_inputs` is MUST-NOT-REMOVE (ERROR not WARN)

In ES 8.4 Splunk explicitly warns that `list_inputs` MUST NOT be
removed from any role. Removing it breaks data-input visibility
across the platform. Preflight raises an **ERROR** if the capability
is missing from any non-admin role that previously had it.

### `splunk_app_soar` role on 1.0.71+ is deprecated

If the app is at 1.0.71 or above AND the legacy `splunk_app_soar`
role still exists, preflight WARNs and recommends deletion (Splunk's
own upgrade guidance).

### De-dup in ES 8.4

Splunk's own ES 8.4 capability table lists these capabilities twice
(once per related feature). The embedded list de-dups to one entry
per capability:

- `edit_notable_events`
- `schedule_search`
- `edit_managed_configurations`
- `edit_lookups`

## How the overlay is consumed

`references/premium-apps-capability-overlay.json` is the machine-
readable form. The schema:

```json
{
  "<app_id>": {
    "verified_version": "<doc-pinned version>",
    "source_url": "<canonical URL>",
    "capabilities_to_disable_on_public_reader": [
      {
        "name": "...",
        "default_role": "...",
        "risk": "admin-only|ops-only|read-only-safe|MUST-NOT-REMOVE",
        "removal_breaks": true|false
      }
    ],
    "must_not_remove": ["list_inputs"]
  }
}
```

The rendered `preflight.sh` step 23 enumerates installed apps in
`$SPLUNK_HOME/etc/apps/` and matches them against this JSON.

## Operator review checklist

When preflight reports a Tier-A app:

1. Read the cited Splunk capability reference at the pinned version.
2. List capabilities on `role_public_reader` via:
   ```
   splunk btool authorize list role_public_reader
   ```
3. Disable each capability in the overlay's
   `capabilities_to_disable_on_public_reader` array that is currently
   `enabled` on `role_public_reader`.
4. Re-run preflight to confirm.

When preflight reports a Tier-B app:

1. Run:
   ```
   cat $SPLUNK_HOME/etc/apps/<app>/default/authorize.conf \
     | grep -E '^\[role_|^\[capability::|^.*= enabled$'
   ```
2. Audit each capability in the output. Disable on `role_public_reader`
   anything that grants write or execute permissions.
3. File a security-review ticket if the app's behavior is unclear.

## When NOT to install a premium app on a public-facing SH

Some premium apps are not designed for public-facing exposure at all:

- **Splunk SOAR** (the platform, not the Splunk-side app): runs its
  own UI on a separate host with its own threat model. Do NOT
  consolidate onto a public-facing SH.
- **Splunk UBA**: the appliance is its own deployment. Only the
  `Splunk_TA_ueba` integration TA goes on the SH; UBA's own ports
  must remain internal.
- **Splunk Mission Control**: standalone Mission Control (ES 7)
  shares the SH's auth surface; bundled-in-ES 8.4 inherits the ES
  posture. Either way, audit per the overlay.

## Update cadence

Splunk publishes new app versions regularly; capability lists shift.
The overlay JSON pins doc versions explicitly so an audit failure
points to a specific `verified_version`. To update:

1. Fetch the new capability reference from the URL in the overlay.
2. Diff against the embedded list.
3. Bump the `verified_version` in the JSON.
4. Re-run pytest + smoke.
