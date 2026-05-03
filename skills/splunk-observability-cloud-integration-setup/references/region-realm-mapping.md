# Region <-> Realm Mapping Reference

The Splunk Cloud Platform <-> Splunk Observability Cloud Unified Identity
pairing has a fixed AWS region <-> Splunk Observability Cloud realm map.
Cross-region pairing requires Splunk Account team approval and produces a
`support-tickets/cross-region-pairing.md` template at render time.

## Default In-Region Pairings

| AWS Region                       | Splunk Observability Cloud Realm |
| -------------------------------- | -------------------------------- |
| `us-east-1` (US East Virginia)   | `us0`                            |
| `us-west-2` (US West Oregon)     | `us1`                            |
| `eu-west-1` (EU Dublin)          | `eu0`                            |
| `eu-central-1` (EU Frankfurt)    | `eu1`                            |
| `eu-west-2` (EU London)          | `eu2`                            |
| `ap-southeast-2` (AP Sydney)     | `au0`                            |
| `ap-northeast-1` (AP Tokyo)      | `jp0`                            |
| `ap-southeast-1` (AP Singapore)  | `sg0`                            |

Special note: both `us0` and `us1` realms can map to AWS US East Virginia
(`us-east-1`) and to AWS US West Oregon (`us-west-2`). Cross-region pairing
inside this US pair (e.g., `us0` realm to `us-west-2` region) still
requires Splunk Account team approval — the skill renders a WARN, not a
FAIL, in that case.

## Excluded Regions

Unified Identity is NOT supported in:

- GovCloud (any AWS GovCloud region).
- GCP regions (including the GCP `us2` Splunk Observability Cloud realm).
- FedRAMP / IL5 deployments — Splunk Cloud Platform itself is FedRAMP
  Moderate authorized and DoD IL5 provisionally authorized, but Splunk
  Observability Cloud is not separately listed in the public FedRAMP / IL5
  documentation as of this skill's authoring.

When the skill detects any of these gates it:

1. Marks the `pairing` UID + `centralized_rbac` + `discover_app`
   Configurations sections as `not_applicable` (or `deeplink` where the
   UI surface still exists for SA mode).
2. Renders a `support-tickets/fedramp-il5-readiness.md` template if the
   operator wants UID enforcement on a FedRAMP/IL5 stack.
3. Falls back to Service Account pairing for the `pairing` section so the
   integration still works without UID.

## How the Skill Detects the Region

For Splunk Cloud Platform the skill calls ACS to read the stack metadata
(`acs config show-stack` returns the AWS region). For Splunk Enterprise
the operator must set `target: enterprise` in the spec; Splunk Enterprise
has no UID path so the region check is informational only.

The skill compares the detected AWS region to the spec's `realm` value
using the table above. Mismatch + same-table-row produces a WARN
(cross-region carve-out); mismatch + outside the table (e.g., GovCloud,
GCP) produces a FAIL.
