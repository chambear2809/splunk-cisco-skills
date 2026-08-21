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
| Splunk Enterprise Security 7.x | 7.3 | https://help.splunk.com/en/splunk-enterprise-security-7/install/7.3/installation/configure-users-and-roles |
| `splunk_app_soar` (Splunkbase 6361) | 1.0.74 | https://help.splunk.com/en/splunk-soar/splunk-app-for-soar/install-and-configure/1.0.74/install-splunk-app-for-soar/assign-roles-for-splunk-app-for-soar |
| Splunk IT Service Intelligence (`SA-ITOA`) | 4.21 | https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/administer/4.21/permissions/itsi-capabilities-reference |
| `Splunk_TA_ueba` (UEBA SH-side) | 5.4.5 | https://help.splunk.com/en/security-offerings/splunk-user-behavior-analytics/send-and-receive-data-from-the-splunk-platform/5.4.5/introduction/about-the-splunk-add-on-for-splunk-uba |
| Splunk Asset and Risk Intelligence | 1.2 | https://help.splunk.com/en/security-offerings/splunk-asset-and-risk-intelligence/install-and-upgrade/1.2/install-splunk-asset-and-risk-intelligence/set-up-roles-and-capabilities-for-splunk-asset-and-risk-intelligence |
| Mission Control (ES 7 standalone OR ES 8.4 bundled) | bundled | (handled by ES 8.4 entry) |

ES 7 publishes no standalone capability-reference topic; its capability
table lives inside the 7.3 "Configure users and roles" installation
topic, which is why that row points at a differently-named page than the
8.x row.

Avoid these stale URLs (404):
- `Documentation/ES/latest/Install/Capabilityreference`
- `Documentation/ARI/latest/Install/RolesAndCapabilities`
- `docs.splunk.com/Documentation/ITSI/4.21.0/Configure/itsi-roles` —
  ITSI moved off `docs.splunk.com`; `latest` now redirects to the docs
  home page rather than to the ITSI manual.
- `help.splunk.com/splunk-enterprise-security-7/...` (no `/en/` segment)

## Capability naming conventions (verified against the tables above)

The names in the JSON are matched literally against the installed
`authorize.conf`, so a name that no longer exists silently matches
nothing and the capability stays enabled. Two families are easy to get
wrong, and one that was wrong in every entry:

- **ES** uses plural, suffixed names: `edit_notable_events`,
  `edit_threat_intel_collections`, `edit_log_review_settings`. Singular
  forms (`edit_notable_event`, `edit_threat_intel`, `edit_log_review`)
  and the `edit_glasstable_*` family do not appear in either the 7.3 or
  the 8.4 table.
- **ITSI** uses `read_` / `write_` / `delete_` / `interact_with_`
  prefixes. There is no `edit_itsi_*` or `configure_itsi_*` family; the
  RBAC capability is the unprefixed `configure_perms`. `itoa_admin` and
  `neap_admin` are *roles*, not capabilities, and matching them as
  capabilities finds nothing.
- **ARI** prefixes every capability with `ari_`. None of the
  `edit_assets` / `edit_risk_*` / `edit_classifications` /
  `edit_exposure_analytics` / `manage_collections` / `configure_ari` /
  `view_ari_dashboards` / `edit_ari_alerts` names exists, and
  `ari_admin` / `ari_analyst` are *roles*, not capabilities. ARI 1.0
  additionally shipped `ari_manage_posture_settings` and called its
  least-privilege role `user`; 1.1 renamed that role to `ari_analyst`
  and 1.2 dropped `ari_manage_posture_settings`, so neither should be
  carried forward against a 1.2 install.

ARI's capability table was previously recorded as non-existent. It does
exist — the old `Documentation/ARI/latest/Install/RolesAndCapabilities`
URL 404s because the topic migrated to `help.splunk.com`, not because
the topic was withdrawn. All eight ARI names are now taken from the
live 1.2 table.

### ARI requires `admin_all_objects`

ARI documents `admin_all_objects` as a hard prerequisite for
`ari_manage_data_source_settings` and `ari_manage_metric_settings` to
function, and instructs operators to satisfy it by assigning `sc_admin`
or `admin`. A working ARI deployment is therefore likely to have
`admin_all_objects` granted somewhere reachable from a public-facing
search head. The ARI entry lists it in its own right rather than
leaning on the ES entry, because ARI can be installed without ES — in
which case the ES entry never applies and the capability would go
unswept.

### ARI has no must-not-remove capability

Verified, not assumed. `ari_analyst` gets its read access from the
`ari_asset` index rather than from any capability, so no ARI capability
is needed for read-only investigation. All eight are writes:
`ari_edit_table_fields` and `ari_save_filters` read as reader-adjacent
but only change which columns display and persist a filter, and
Discovery / Metrics / Investigation browsing works without either. This
is the opposite of the ITSI case, where `write_itsi_deep_dive_context`
genuinely backs a reader drill-down and must survive the
`write_itsi_*` wildcard. Every ARI name is listed literally, so no
wildcard can over-match one.

### Platform capabilities carried per app, not inherited from ES

The dangerous capability is often the *platform* one an app quietly
requires, not the app's own — and an app installed without ES leaves it
unswept. Every Tier-A entry is therefore checked against
`admin_all_objects` and `list_storage_passwords` in its own right. Where
an entry omits one, the omission is a recorded verified negative, not an
oversight.

| App | `admin_all_objects` | `list_storage_passwords` | Basis |
| --- | --- | --- | --- |
| ES 8.x / 7.x | listed | listed | ES capability reference |
| `SA-ITOA` | verified negative | **listed** | "Splunk Admin capabilities and ITSI roles" table |
| `splunk_app_soar` | **listed** | verified negative | admin role capability list in "Assign roles for Splunk App for SOAR" |
| `SplunkAssetRiskIntelligence` | listed | verified negative | ARI roles-and-capabilities prerequisite |
| `Splunk_TA_ueba` | verified negative | verified negative | ships only with ES; see below |

ITSI is the widest of these. Its "Configure users and roles in ITSI"
topic has a section headed **Splunk Admin capabilities and ITSI roles**,
opening "Some ITSI roles inherit capabilities that are typically only
available to Splunk administration roles," and its table grants six
platform capabilities to non-admin ITSI roles: `edit_token_http` (all
four roles), `list_storage_passwords` (`itoa_analyst`,
`itoa_team_admin`), `list_search_head_clustering` and
`dispatch_rest_to_indexers` (`itoa_team_admin`, `itoa_admin`), and
`list_settings` and `edit_monitor` (`itoa_team_admin`). ITSI's own
shipped `[role_itoa_admin]` stanza, quoted on the same page, confirms
`list_storage_passwords = enabled` under the comment "Capabilities
copied from Splunk admin role to enable write permissions." All six are
now swept. `edit_monitor` is the sharpest: it permits adding file
monitor inputs, which becomes arbitrary local file read on a
public-facing search head. Of the six, only `edit_token_http` is held by
`itoa_user`, and ITSI grants it "For event management" rather than for
reading, so removing it from a purpose-built public reader breaks no
read path — and none of the six is matched by the `write_itsi_*` or
`delete_itsi_*` wildcards.

`Splunk_TA_ueba` is a verified negative on stronger grounds than "not
documented." Splunk states "The Splunk Add-on for UBA is not available
for download on Splunkbase. The add-on is installed by default with
Splunk Enterprise Security (ES)." The install-without-ES argument that
justifies the ARI and SOAR entries cannot apply, because ES is present
by construction and its entry already carries both capabilities.
Duplicating them here would add noise, not coverage.

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
