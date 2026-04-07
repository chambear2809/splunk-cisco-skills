---
name: splunk-connect-for-snmp-setup
description: >-
  Deploy and validate Splunk Connect for SNMP (SC4SNMP) for Splunk Enterprise
  or Splunk Cloud. Prepares Splunk indexes and HEC, renders Docker Compose or
  Kubernetes Helm configuration, and validates SC4SNMP polling or trap
  readiness. Use when the user asks about SC4SNMP, Splunk Connect for SNMP,
  SNMP polling, or SNMP trap ingestion through HEC.
---

# Splunk Connect for SNMP Setup

Automates the operator workflow for **Splunk Connect for SNMP** (`SC4SNMP`), an
external collector that polls SNMP devices and listens for traps before sending
events and metrics to Splunk over HEC.

## How SC4SNMP Fits This Repo

SC4SNMP is not a Splunkbase app install. The skill handles two separate areas:

1. **Splunk-side preparation**: create the default SC4SNMP indexes, verify or
   create a HEC token, and validate the Cloud vs Enterprise HEC target.
2. **Runtime deployment**: render deployment assets for customer-managed
   SC4SNMP infrastructure:
   - Docker Compose for a simple host-managed deployment
   - Kubernetes with Helm for the supported clustered deployment model

## Agent Behavior — Credentials

**The agent must NEVER ask for HEC tokens, SNMPv3 credentials, or other
secrets in chat.**

- Splunk credentials come from the project-root `credentials` file or
  `~/.splunk/credentials`.
- Use `skills/splunk-connect-for-snmp-setup/template.example` as the non-secret
  intake worksheet.
- Keep HEC tokens and SNMPv3 secrets in local-only files. For example:

```bash
printf '%s\n' '<hec_token>' > /tmp/sc4snmp_hec_token && chmod 600 /tmp/sc4snmp_hec_token
```

- For Docker Compose, keep SNMPv3 secrets in a local-only `secrets.json` file.
- For Kubernetes, prefer a token-free `values.yaml` plus a local-only
  `values.secret.yaml` and operator-managed Kubernetes secrets for SNMPv3
  credentials.
- The default render path is the gitignored repo-local directory
  `./sc4snmp-rendered/`. When a real HEC token is being rendered, the setup
  script blocks custom output directories inside the repo and asks you to use
  the default gitignored path or a directory outside the repo.

If credentials are not configured yet:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

## Environment

| Item | Value |
|------|-------|
| Search-tier API | `SPLUNK_SEARCH_API_URI` env var (legacy alias: `SPLUNK_URI`) |
| Cloud stack | `SPLUNK_CLOUD_STACK` for Splunk Cloud |
| Runtime image | `ghcr.io/splunk/splunk-connect-for-snmp/container:latest` |
| Credentials | Project-root `credentials` file (falls back to `~/.splunk/credentials`) |
| Skill scripts | `skills/splunk-connect-for-snmp-setup/scripts/` |
| Templates | `skills/splunk-connect-for-snmp-setup/templates/` |

## Setup Workflow

### Step 1: Collect Non-Secret Deployment Inputs

Copy the worksheet locally:

```bash
cp skills/splunk-connect-for-snmp-setup/template.example template.local
```

Capture items such as:

- Splunk platform: Cloud or Enterprise
- deployment model: Docker Compose or Kubernetes
- HEC URL and HEC token name
- trap listener IP, trap port, and DNS server
- poller inventory source
- scheduler profiles/groups source
- trap communities source
- optional image, replica, and secret-file paths

### Step 2: Prepare Splunk

Create the SC4SNMP indexes and verify or create a HEC token:

```bash
bash skills/splunk-connect-for-snmp-setup/scripts/setup.sh --splunk-prep
```

Useful partial runs:

```bash
bash skills/splunk-connect-for-snmp-setup/scripts/setup.sh --splunk-prep --indexes-only
```

```bash
bash skills/splunk-connect-for-snmp-setup/scripts/setup.sh --splunk-prep --hec-only
```

If you want the script to write the created token value to a local-only file
when Splunk REST returns it:

```bash
bash skills/splunk-connect-for-snmp-setup/scripts/setup.sh \
  --splunk-prep \
  --write-hec-token-file /tmp/sc4snmp_hec_token
```

### Step 3: Render Docker Compose Assets

```bash
bash skills/splunk-connect-for-snmp-setup/scripts/setup.sh \
  --render-compose \
  --output-dir ./sc4snmp-rendered \
  --hec-token-file /tmp/sc4snmp_hec_token
```

Optional custom config files:

```bash
bash skills/splunk-connect-for-snmp-setup/scripts/setup.sh \
  --render-compose \
  --output-dir ./sc4snmp-rendered \
  --hec-token-file /tmp/sc4snmp_hec_token \
  --inventory-file /path/to/inventory.csv \
  --scheduler-file /path/to/scheduler-config.yaml \
  --traps-file /path/to/traps-config.yaml
```

### Step 4: Render Kubernetes Assets

```bash
bash skills/splunk-connect-for-snmp-setup/scripts/setup.sh \
  --render-k8s \
  --output-dir ./sc4snmp-rendered \
  --namespace sc4snmp \
  --release-name sc4snmp \
  --poller-replicas 2 \
  --trap-replicas 2 \
  --hec-token-file /tmp/sc4snmp_hec_token
```

Optional trap service IP and DNS override:

```bash
bash skills/splunk-connect-for-snmp-setup/scripts/setup.sh \
  --render-k8s \
  --output-dir ./sc4snmp-rendered \
  --hec-token-file /tmp/sc4snmp_hec_token \
  --trap-listener-ip 10.10.10.50 \
  --dns-server 10.10.10.53
```

### Step 5: Optionally Apply Rendered Assets

Compose:

```bash
bash skills/splunk-connect-for-snmp-setup/scripts/setup.sh \
  --render-compose \
  --output-dir ./sc4snmp-rendered \
  --hec-token-file /tmp/sc4snmp_hec_token \
  --apply-compose
```

Helm:

```bash
bash skills/splunk-connect-for-snmp-setup/scripts/setup.sh \
  --render-k8s \
  --output-dir ./sc4snmp-rendered \
  --hec-token-file /tmp/sc4snmp_hec_token \
  --apply-k8s
```

### Step 6: Validate

```bash
bash skills/splunk-connect-for-snmp-setup/scripts/validate.sh
```

Runtime-specific checks:

```bash
bash skills/splunk-connect-for-snmp-setup/scripts/validate.sh --check-compose
```

```bash
bash skills/splunk-connect-for-snmp-setup/scripts/validate.sh --check-k8s
```

## Key Learnings / Known Issues

1. **The default indexes are split by signal type**: `em_logs` and `netops` are
   event indexes, while `em_metrics` and `netmetrics` must be metrics indexes.
2. **SC4SNMP is hybrid in Splunk Cloud**: prepare indexes and HEC in Splunk
   Cloud, but run SC4SNMP on infrastructure you control.
3. **Trap listener IP planning matters**: HA or MetalLB-style Kubernetes
   deployments need an explicit shared IP.
4. **DNS matters for HEC reachability**: the collector environment needs a DNS
   server that can resolve the Splunk HEC endpoint.
5. **SNMPv3 secrets stay local-only**: do not commit `secrets.json`,
   `values.secret.yaml`, or token files to git.
6. **Re-run apply workflows for upgrades**: compose apply now pulls images
   before `up -d`, and Kubernetes apply continues to use
   `helm upgrade --install`.

## Additional Resources

- [reference.md](reference.md) — indexes, deployment notes, and configuration
  guardrails
- [template.example](template.example) — non-secret intake worksheet
- [templates/compose/README.md](templates/compose/README.md) — compose template
  notes
- [templates/kubernetes/README.md](templates/kubernetes/README.md) — Helm
  template notes
