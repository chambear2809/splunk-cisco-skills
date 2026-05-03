# RBAC Reference

## Splunk Observability Cloud Roles (provisioned by `enable-capabilities`)

`acs observability enable-capabilities` provisions four prepackaged Splunk
Observability Cloud roles on Splunk Cloud Platform. Propagation can take
about 30 minutes.

| Role             | Capability set                                              |
| ---------------- | ----------------------------------------------------------- |
| `o11y_admin`     | Full Splunk Observability Cloud administration.             |
| `o11y_power`     | Create / edit dashboards, charts, detectors; no admin ops.  |
| `o11y_read_only` | Read-only access to all Splunk Observability Cloud objects. |
| `o11y_usage`     | Usage / billing data only.                                  |

After provisioning, the four roles appear in the Splunk Cloud Platform
Roles UI and can be assigned to users like any other Splunk role.

## The Gate Role: `o11y_access`

The custom role `o11y_access` is the gate role that every UID-mapped user
must hold to access Splunk Observability Cloud. Missing it produces the
"You do not have access to Splunk Observability Cloud. Contact your Splunk
Cloud Platform administrator for assistance." error at first login.

The skill creates `o11y_access` as a Splunk custom role with no extra
capabilities or indexes (the role itself is the gate; capabilities come
from the `o11y_*` roles assigned alongside it).

## UID Role Mapping (auto-applied at first login)

When a user signs into Splunk Observability Cloud through Unified Identity
SSO and they don't already have a Splunk Observability Cloud user, the
system auto-creates the user and maps Splunk Cloud Platform roles to
Splunk Observability Cloud roles using the fixed table below. There are
no overrides at provisioning time.

| Splunk Cloud Platform role         | Splunk Observability Cloud role |
| ---------------------------------- | ------------------------------- |
| `sc_admin`                         | `admin`                         |
| `power` AND `can_delete`           | `power`                         |
| `user`                             | `power`                         |

There is NO mapping to `usage` or `read_only`; those Splunk Observability
Cloud roles must be assigned manually after first login.

## Real Time Metrics + Related Content Capabilities

For the in-platform Real Time Metrics view and the Search & Reporting
Related Content previews to render, users need the following Splunk
capabilities:

| Capability               | Purpose                                                    |
| ------------------------ | ---------------------------------------------------------- |
| `read_o11y_content`      | Read Splunk Observability Cloud content (Real Time Metrics).|
| `write_o11y_content`     | Create / import O11y charts and service maps.              |
| `EXECUTE_SIGNAL_FLOW`    | Execute SignalFlow (Related Content troubleshooting path). |
| `READ_APM_DATA`          | Read APM data in Related Content.                          |
| `READ_BASIC_UI_ACCESS`   | Basic UI access for Related Content links.                 |
| `READ_EVENT`             | Read O11y events in Related Content.                       |

The skill assigns these capabilities to roles named in
`related_content.assign_to_roles`.

## Centralized RBAC (C-RBAC) Cutover

`acs observability enable-centralized-rbac` is the destructive cutover
that locks Splunk Observability Cloud RBAC to Splunk Cloud Platform.
After cutover:

- All UID-authenticated Splunk Observability Cloud users get their roles
  from Splunk Cloud Platform; the Splunk Observability Cloud Roles UI is
  read-only for those users.
- UID-mapped users who do not have an `o11y_*` role get the "No access"
  error and are locked out of Splunk Observability Cloud.
- Users who continue to log in to Splunk Observability Cloud locally or
  through a third-party IdP keep their existing Splunk Observability
  Cloud roles.

The skill guards this step with `--i-accept-rbac-cutover` AND a renderer
preflight that confirms every UID-mapped user already has at least one
`o11y_*` role assigned. The cutover is irreversible without Splunk
Customer Support intervention.

## Capabilities Required for the Operator

| Operation                                       | Required role / capability                                    |
| ----------------------------------------------- | ------------------------------------------------------------- |
| Create Splunk roles + assign capabilities       | `sc_admin` (Cloud) or `admin_all_objects` (Enterprise)        |
| Enable / disable token authentication           | `edit_tokens_settings` capability                             |
| Run any `acs observability` command             | `sc_admin` plus a Splunk Cloud Platform admin token (JWT)     |
| Pair via REST                                   | Splunk Cloud Platform admin JWT + Splunk Observability admin token |
| `enable-centralized-rbac`                       | Splunk Observability Cloud admin token                        |
| Configure the Discover app Configurations tabs  | `sc_admin` + Read permission on the Discover app              |
| Configure the Splunk Infrastructure Monitoring  | Splunk Cloud Platform `admin` access to the search head and IDM; SIM Add-on org token (non-admin OK if scoped to API tokens) |
| Create the Log Observer Connect role + user    | `sc_admin` (Cloud) or `admin_all_objects` (Enterprise)        |
| Configure the Workload Rule for LOC             | `sc_admin` plus the workload-management capability            |
