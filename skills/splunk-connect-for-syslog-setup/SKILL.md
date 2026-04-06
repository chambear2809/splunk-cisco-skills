---
name: splunk-connect-for-syslog-setup
description: >-
  Deploy and validate Splunk Connect for Syslog (SC4S) for Splunk Enterprise or
  Splunk Cloud. Prepares Splunk indexes and HEC, renders Docker/Podman/systemd
  or Kubernetes Helm configuration, and validates SC4S startup. Use when the
  user asks about SC4S, Splunk Connect for Syslog, syslog-ng collector setup, or
  syslog ingestion through HEC.
---

# Splunk Connect for Syslog Setup

Automates the operator workflow for **Splunk Connect for Syslog** (`SC4S`), an
external syslog-ng based collector that forwards events to Splunk over HEC.

## How SC4S Fits This Repo

SC4S is not a normal Splunkbase TA install. The skill handles two separate
areas:

1. **Splunk-side preparation**: create the default SC4S indexes, verify or
   create a HEC token, and validate the Cloud vs Enterprise HEC target.
2. **Runtime deployment**: render deployment assets for customer-managed SC4S
   infrastructure:
   - host-based Linux with Docker/Podman plus compose or systemd
   - Kubernetes with Helm

## Agent Behavior

**The agent must NEVER ask for HEC tokens or other secrets in chat.**

- Splunk credentials come from the project-root `credentials` file or
  `~/.splunk/credentials`.
- Use `skills/splunk-connect-for-syslog-setup/template.example` as the
  non-secret intake worksheet.
- Keep HEC tokens in temporary or local-only files, for example:

```bash
printf '%s\n' '<hec_token>' > /tmp/sc4s_hec_token && chmod 600 /tmp/sc4s_hec_token
```

- For Kubernetes, prefer a token-free `values.yaml` plus a local-only
  `values.secret.yaml` or an operator-managed install command. Do not commit HEC
  tokens to git.
- The default render path is the gitignored repo-local directory
  `./sc4s-rendered/`. When a real HEC token is being rendered, the setup script
  blocks custom output directories inside the repo and asks you to use the
  default gitignored path or a directory outside the repo.

If credentials are not configured yet:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

## Environment

| Item | Value |
|------|-------|
| Search-tier API | `SPLUNK_SEARCH_API_URI` env var (legacy alias: `SPLUNK_URI`) |
| Cloud stack | `SPLUNK_CLOUD_STACK` for Splunk Cloud |
| Runtime image | `ghcr.io/splunk/splunk-connect-for-syslog/container3:latest` |
| Credentials | Project-root `credentials` file (falls back to `~/.splunk/credentials`) |
| Skill scripts | `skills/splunk-connect-for-syslog-setup/scripts/` |
| Templates | `skills/splunk-connect-for-syslog-setup/templates/` |

## Setup Workflow

### Step 1: Collect Non-Secret Deployment Inputs

Copy the worksheet locally:

```bash
cp skills/splunk-connect-for-syslog-setup/template.example template.local
```

Capture items such as:

- Splunk platform: Cloud or Enterprise
- deployment model: host or Kubernetes
- SC4S runtime root path
- HEC URL and HEC token name
- archive/TLS choices
- vendor/product dedicated listener ports
- optional context/config override files

### Step 2: Prepare Splunk

Create the SC4S indexes and verify or create a HEC token:

```bash
bash skills/splunk-connect-for-syslog-setup/scripts/setup.sh --splunk-prep
```

Useful partial runs:

```bash
bash skills/splunk-connect-for-syslog-setup/scripts/setup.sh --splunk-prep --indexes-only
```

```bash
bash skills/splunk-connect-for-syslog-setup/scripts/setup.sh --splunk-prep --hec-only
```

If you want the script to write the created token value to a local-only file
when Splunk REST returns it:

```bash
bash skills/splunk-connect-for-syslog-setup/scripts/setup.sh \
  --splunk-prep \
  --write-hec-token-file /tmp/sc4s_hec_token
```

### Step 3: Render Host Deployment Assets

Compose example:

```bash
bash skills/splunk-connect-for-syslog-setup/scripts/setup.sh \
  --render-host \
  --host-mode compose \
  --output-dir ./sc4s-rendered \
  --hec-token-file /tmp/sc4s_hec_token
```

The rendered compose directory is self-contained, so `--apply-host` can install
or upgrade it directly from `./sc4s-rendered/host/` without copying files into
`/opt/sc4s` first.

Systemd example:

```bash
bash skills/splunk-connect-for-syslog-setup/scripts/setup.sh \
  --render-host \
  --host-mode systemd \
  --runtime podman \
  --output-dir ./sc4s-rendered \
  --sc4s-root /opt/sc4s \
  --hec-token-file /tmp/sc4s_hec_token
```

Systemd apply example:

```bash
bash skills/splunk-connect-for-syslog-setup/scripts/setup.sh \
  --render-host \
  --host-mode systemd \
  --runtime podman \
  --output-dir ./sc4s-rendered \
  --sc4s-root /opt/sc4s \
  --hec-token-file /tmp/sc4s_hec_token \
  --apply-host
```

Optional dedicated vendor port:

```bash
bash skills/splunk-connect-for-syslog-setup/scripts/setup.sh \
  --render-host \
  --output-dir ./sc4s-rendered \
  --hec-token-file /tmp/sc4s_hec_token \
  --vendor-port checkpoint:tcp:9000
```

### Step 4: Render Kubernetes Assets

```bash
bash skills/splunk-connect-for-syslog-setup/scripts/setup.sh \
  --render-k8s \
  --output-dir ./sc4s-rendered \
  --namespace sc4s \
  --release-name sc4s \
  --replica-count 2 \
  --hec-token-file /tmp/sc4s_hec_token
```

Optional context/config overrides:

```bash
bash skills/splunk-connect-for-syslog-setup/scripts/setup.sh \
  --render-k8s \
  --output-dir ./sc4s-rendered \
  --hec-token-file /tmp/sc4s_hec_token \
  --context-file splunk_metadata.csv=/path/to/splunk_metadata.csv \
  --config-file app-workaround-cisco_asa.conf=/path/to/app-workaround-cisco_asa.conf
```

### Step 5: Optionally Apply Rendered Assets

Compose:

```bash
bash skills/splunk-connect-for-syslog-setup/scripts/setup.sh \
  --render-host \
  --host-mode compose \
  --output-dir ./sc4s-rendered \
  --hec-token-file /tmp/sc4s_hec_token \
  --apply-host
```

Systemd:

```bash
bash skills/splunk-connect-for-syslog-setup/scripts/setup.sh \
  --render-host \
  --host-mode systemd \
  --runtime podman \
  --output-dir ./sc4s-rendered \
  --sc4s-root /opt/sc4s \
  --hec-token-file /tmp/sc4s_hec_token \
  --apply-host
```

Helm:

```bash
bash skills/splunk-connect-for-syslog-setup/scripts/setup.sh \
  --render-k8s \
  --output-dir ./sc4s-rendered \
  --hec-token-file /tmp/sc4s_hec_token \
  --apply-k8s
```

### Step 6: Validate

```bash
bash skills/splunk-connect-for-syslog-setup/scripts/validate.sh
```

Runtime-specific checks:

```bash
bash skills/splunk-connect-for-syslog-setup/scripts/validate.sh --check-host
```

```bash
bash skills/splunk-connect-for-syslog-setup/scripts/validate.sh --check-k8s
```

## Key Learnings / Known Issues

1. **HEC ACK must stay off**: SC4S does not support HEC acknowledgement.
2. **Avoid index restrictions on the HEC token**: a restricted token can block
   batches when SC4S sends to an index not on the allow-list.
3. **Disabled HEC tokens are not treated as success**: the setup flow now
   enables an existing disabled token or fails clearly if it cannot.
4. **Disk buffer sizing matters**: the persistent volume can grow significantly
   during Splunk outages.
5. **Host networking differs by runtime**: compose typically publishes ports,
   while systemd examples often use host networking.
6. **Non-root Podman cannot bind 514/601**: if you need non-root operation, use
   alternate listener ports and update the sending devices accordingly.
7. **Kubernetes values differ from env_file settings**: use `values.yaml`,
   `context_files`, and `config_files` instead of copying host env_file layouts.
8. **`_metrics` must be a metrics index**: the setup flow now creates it as a
   metrics index and validation reports when an existing `_metrics` index was
   created with the wrong type.
9. **Re-run apply workflows for upgrades**: compose apply now pulls images
   before `up -d`, systemd apply syncs the rendered working set into
   `SC4S_ROOT`, and Kubernetes apply continues to use `helm upgrade --install`.

## Additional Resources

- [reference.md](reference.md) — index defaults, HEC behavior, deployment notes,
  and troubleshooting guidance
- [template.example](template.example) — non-secret intake worksheet
- [templates/host/README.md](templates/host/README.md) — host template notes
- [templates/kubernetes/README.md](templates/kubernetes/README.md) — Helm
  template notes
