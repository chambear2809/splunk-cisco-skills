# Scenarios Gallery

Six worked end-to-end examples for the Splunk Platform <-> Splunk
Observability Cloud integration. Each shows the exact `setup.sh`
invocations and the prerequisites they assume.

## 1. Cloud Quickstart (Greenfield)

A fresh Splunk Cloud Platform stack pairing with one Splunk Observability
Cloud org. Unified Identity, the Splunk Infrastructure Monitoring Add-on,
the Discover Splunk Observability Cloud app, and Related Content previews
in one shot.

```bash
bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh \
  --quickstart \
  --realm us0 \
  --admin-token-file /tmp/splunk_o11y_admin_token \
  --org-token-file /tmp/splunk_o11y_org_token
```

Expected behavior:

- The skill renders the full plan tree, applies it (idempotent), then
  validates.
- `enable-centralized-rbac` is NOT run in quickstart mode (operator must
  opt in separately with `--apply rbac --i-accept-rbac-cutover`).
- The Discover app's "Make Default" step is rendered as a deeplink because
  there's only one O11y org (no default to set).

## 2. Multi-Org Cloud

Three Splunk Observability Cloud orgs paired to one Splunk Cloud Platform
stack. The first org becomes the default through the Discover app UI
(no public API for Make Default).

```bash
# Spec includes pairing.multi_org with three entries:
#   - us0  (label: production, make_default: true)
#   - us1  (label: staging)
#   - eu0  (label: emea)

bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh \
  --apply pairing,centralized_rbac \
  --i-accept-rbac-cutover \
  --spec my-multi-org.yaml \
  --admin-token-file /tmp/splunk_o11y_admin_token

# Then the operator follows the rendered Make Default deeplink.
bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh \
  --make-default-deeplink \
  --realm us0
```

## 3. Cloud Service Account Only (no UID)

A Splunk Cloud Platform stack that wants Splunk Observability Cloud
Related Content + the SIM Add-on streaming, but where Unified Identity is
out of scope (e.g., the org keeps a third-party IdP for O11y).

```yaml
# spec.yaml
target: cloud
realm: us0
splunk_cloud_stack: example-stack
pairing:
  mode: service_account
centralized_rbac:
  enable_capabilities: false
  enable_centralized_rbac: false
related_content:
  enable: true
sim_addon:
  install: true
```

```bash
bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh \
  --apply \
  --spec spec.yaml \
  --token-file /tmp/splunk_o11y_token \
  --org-token-file /tmp/splunk_o11y_org_token
```

UID-related sections are marked `not_applicable` in the coverage report.
The Discover app's Access tokens tab gets the `--token-file` value; the
Configurations tabs are still configured by sc_admin.

## 4. Migrate Service Account -> Unified Identity

An existing customer that has been on Service Account pairing wants to
move to Unified Identity. The skill detects the existing SA connection,
renders a numbered migration plan, and produces deeplinks for the SA
removal step (Discover app Configurations UI; no public API for connection
delete).

```bash
# Discover existing state.
bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh \
  --discover \
  --realm us0 \
  --token-file /tmp/splunk_o11y_token

# Diagnose what's missing for UID.
bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh \
  --doctor \
  --realm us0 \
  --admin-token-file /tmp/splunk_o11y_admin_token

# Apply the UID pairing while leaving the SA connection in place.
bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh \
  --apply pairing,centralized_rbac.capabilities,related_content,discover_app \
  --spec migration.yaml \
  --admin-token-file /tmp/splunk_o11y_admin_token

# Operator follows the rendered deeplink to remove the old SA connection
# from Discover app > Configurations.
```

After the operator confirms UID is healthy, optionally run the destructive
RBAC cutover:

```bash
bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh \
  --apply rbac \
  --i-accept-rbac-cutover \
  --spec migration.yaml \
  --admin-token-file /tmp/splunk_o11y_admin_token
```

## 5. Splunk Enterprise (no UID)

Splunk Enterprise customer with Splunk Observability Cloud. UID is
`not_applicable` (Enterprise + UID combination is not supported); the
skill configures Service Account pairing, Related Content, the SIM Add-on,
and the SE-flavor Log Observer Connect TLS-cert path.

```bash
bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh \
  --quickstart-enterprise \
  --realm us0 \
  --token-file /tmp/splunk_o11y_token \
  --org-token-file /tmp/splunk_o11y_org_token \
  --service-account-password-file /tmp/loc_svc_account_password
```

The rendered `06-log-observer-connect.md` includes the TLS-cert extraction
helper that captures the first cert in the search head's TLS chain and
writes a paste-ready PEM under `<rendered>/06-log-observer-connect/leaf-cert.pem`.

## 6. Inherit Existing Integration

A new operator inherits a Splunk Cloud Platform stack that already has
a Splunk Observability Cloud integration. They run discover, then doctor,
then targeted apply to converge the live state with the team's spec.

```bash
# Snapshot live state.
bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh \
  --discover \
  --realm us0 \
  --admin-token-file /tmp/splunk_o11y_admin_token

# Diagnose drift.
bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh \
  --doctor \
  --realm us0 \
  --admin-token-file /tmp/splunk_o11y_admin_token

# Review doctor-report.md and run the recommended fix commands one by one.
# For example, after the doctor identifies a missing o11y_access role:
bash skills/splunk-observability-cloud-integration-setup/scripts/setup.sh \
  --apply centralized_rbac \
  --spec inherited.yaml
```

The `--discover` mode is read-only and writes `current-state.json` so
operators have a baseline before any changes. The `--doctor` mode writes
`doctor-report.md` with a numbered, prioritized fix list — every entry
includes the exact `setup.sh` command that resolves it.
