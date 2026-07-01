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

1. Marks UID and `centralized_rbac` as `not_applicable`. The Discover app
   remains available when the Cloud version supports its Configurations REST
   surface, and service-account pairing owns its access-token write.
2. Renders a `support-tickets/fedramp-il5-readiness.md` template if the
   operator wants UID enforcement on a FedRAMP/IL5 stack.
3. On Splunk Cloud Platform, falls back to Discover-app API-token pairing
   where that public workflow is available. Splunk Enterprise uses the
   separate Log Observer Connect service-account workflow.

## How the Skill Detects the Region

The renderer validates only the declared realm against this static map. Before
live apply, the operator must verify Splunk Cloud stack metadata/region through
an approved ACS workflow. For Splunk Enterprise the operator sets
`target: enterprise`; Enterprise has no UID path.

The skill compares the detected AWS region to the spec's `realm` value
using the table above. Mismatch + same-table-row produces a WARN
(cross-region carve-out); mismatch + outside the table (e.g., GovCloud,
GCP) produces a FAIL.
