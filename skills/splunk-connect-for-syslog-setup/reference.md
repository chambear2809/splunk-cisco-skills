# SC4S Reference

This reference collects the SC4S defaults and operator guardrails that matter
for this repo’s setup skill.

## Default Indexes

SC4S maps vendor/product log paths to a standard set of Splunk indexes by
default. The setup script manages these event indexes automatically:

- `print`
- `osnix`
- `oswinsec`
- `oswin`
- `netipam`
- `netproxy`
- `netwaf`
- `netops`
- `netlb`
- `netids`
- `netfw`
- `netdns`
- `netdlp`
- `netauth`
- `infraops`
- `gitops`
- `fireeye`
- `epintel`
- `epav`
- `email`

Optional:

- `_metrics` as a metrics index when you want SC4S operational metrics

Important behavior from the upstream defaults:

- `lastChanceIndex = main`
- if you override indexes in SC4S, create those indexes in Splunk too
- one bad or unauthorized index can poison a whole HEC batch
- when the setup script creates `_metrics`, it now requests a metrics index
  explicitly; if `_metrics` already exists as a normal event index, setup warns
  and validation fails until it is corrected

Reference:

- [SC4S Splunk setup](https://splunk.github.io/splunk-connect-for-syslog/main/gettingstarted/getting-started-splunk-setup/)
- [SC4S reference indexes.conf](https://splunk.github.io/splunk-connect-for-syslog/main/resources/indexes.conf)

## HEC Guidance

### URL format

Host-based SC4S env files expect a base HEC URL:

```text
https://your-indexer-or-hec-lb:8088
```

The Helm chart examples typically use the collector path:

```text
https://your-indexer-or-hec-lb:8088/services/collector/event
```

The setup script normalizes whichever form you pass and renders the appropriate
host or Kubernetes value.

### Cloud vs Enterprise

- Splunk Cloud HEC usually resolves to
  `https://http-inputs-<stack>.splunkcloud.com:443`
- Splunk Enterprise HEC usually resolves to `https://<host>:8088`
- SC4S should send directly to indexer-side HEC or a load balancer in front of
  indexer HEC, not through an extra heavy-forwarder tier

### Token rules

- Do **not** enable HEC acknowledgement for the SC4S token
- Prefer leaving `Selected Indexes` blank so the token is not unintentionally
  restricted
- Make sure the token can write to every SC4S index you expect to use,
  including `_metrics` if you enable metrics

## Core Runtime Files

### Host-based deployment

Expected runtime paths:

- `/opt/sc4s/env_file`
- `/opt/sc4s/local/`
- `/opt/sc4s/local/context/`
- `/opt/sc4s/local/config/`
- `/opt/sc4s/archive/`
- `/opt/sc4s/tls/`

Required persistent volume:

- `/var/lib/syslog-ng` inside the container

Typical mounts:

- `/opt/sc4s/local:/etc/syslog-ng/conf.d/local`
- `splunk-sc4s-var:/var/lib/syslog-ng`
- `/opt/sc4s/archive:/var/lib/syslog-ng/archive`
- `/opt/sc4s/tls:/etc/syslog-ng/tls`

### Kubernetes deployment

Primary Helm values used by this skill:

- `splunk.hec_url`
- `splunk.hec_token` via a local-only secret values file
- `splunk.hec_verify_tls`
- `replicaCount`
- `sc4s.existingCert`
- `sc4s.vendor_product`
- `sc4s.context_files`
- `sc4s.config_files`

Reference:

- [SC4S Kubernetes / MicroK8s guide](https://splunk.github.io/splunk-connect-for-syslog/main/gettingstarted/k8s-microk8s/)

## Important Environment Variables

Common host env file entries:

| Variable | Typical value | Purpose |
|----------|---------------|---------|
| `SC4S_DEST_SPLUNK_HEC_DEFAULT_URL` | `https://...:8088` | Base HEC endpoint |
| `SC4S_DEST_SPLUNK_HEC_DEFAULT_TOKEN` | local-only token value | HEC authentication |
| `SC4S_DEST_SPLUNK_HEC_DEFAULT_TLS_VERIFY` | `yes` or `no` | Verify Splunk TLS |
| `SC4S_DEST_SPLUNK_HEC_DEFAULT_WORKERS` | `10` | HEC output workers |
| `SC4S_DEST_SPLUNK_HEC_DEFAULT_DISKBUFF_ENABLE` | `yes` | Enable disk buffering |
| `SC4S_DEST_SPLUNK_HEC_DEFAULT_DISKBUFF_RELIABLE` | `no` | Prefer normal buffering |
| `SC4S_DEST_SPLUNK_HEC_DEFAULT_DISKBUFF_DISKBUFSIZE` | `53687091200` | 50 GB per worker default |
| `SC4S_ARCHIVE_GLOBAL` | `yes` | Enable global archive |
| `SC4S_GLOBAL_ARCHIVE_MODE` | `compliance` or `diode` | Archive layout |
| `SC4S_SOURCE_TLS_ENABLE` | `yes` | Enable inbound TLS |
| `SC4S_LISTEN_DEFAULT_TLS_PORT` | `6514` | Default TLS listener |

Upstream reference:

- [SC4S configuration variables](https://splunk.github.io/splunk-connect-for-syslog/main/configuration/)

## Dedicated Vendor Ports

The skill supports repeatable `--vendor-port` flags in the format:

```text
--vendor-port vendor_product:protocol:port
```

Examples:

```text
--vendor-port checkpoint:tcp:9000
--vendor-port checkpoint:udp:9000
--vendor-port cisco_asa:tcp:5514
```

Host rendering converts these to env vars such as:

```text
SC4S_LISTEN_CHECKPOINT_TCP_PORT=9000
SC4S_LISTEN_CISCO_ASA_TCP_PORT=5514
```

Kubernetes rendering converts them to `sc4s.vendor_product` blocks:

```yaml
sc4s:
  vendor_product:
    - name: checkpoint
      ports:
        tcp: [9000]
        udp: [9000]
```

Guardrails:

- dedicated listener ports must be unique
- avoid using the default ports as dedicated vendor ports
- the current host renderer only supports `tcp`, `udp`, and `tls`

## Context And Config Files

The setup script accepts repeatable file flags:

```text
--context-file splunk_metadata.csv=/path/to/splunk_metadata.csv
--config-file app-workaround-cisco_asa.conf=/path/to/app-workaround-cisco_asa.conf
```

Behavior:

- host rendering copies them into `local/context/` and `local/config/`
- Kubernetes rendering embeds them under `sc4s.context_files` and
  `sc4s.config_files`

Use cases:

- `splunk_metadata.csv` for index/sourcetype overrides
- `host.csv` for IP-to-host mappings
- `compliance_meta_by_source.*` for compliance-based overrides
- custom `.conf` snippets for parser/filter workarounds

## Rendered Assets

### Host output

The host renderer creates a local working set similar to:

```text
<output-dir>/host/
├── README.md
├── env_file
├── docker-compose.yml or sc4s.service
├── compose-up.sh          # compose mode
├── compose-down.sh        # compose mode
├── systemd-install.sh     # systemd mode
├── local/
│   ├── config/
│   └── context/
├── archive/
└── tls/
```

For compose mode, that rendered `host/` directory is the deployment root:

- `docker-compose.yml` reads `./env_file`
- bind mounts use `./local`, `./archive`, and `./tls`
- `--apply-host` installs or upgrades the stack directly from that rendered directory
- `compose-up.sh` pulls images before running `compose up -d`
- `systemd-install.sh` syncs rendered files into `SC4S_ROOT` without deleting
  unrelated files, then reloads and restarts the `sc4s` service
- the default repo-local render path is `./sc4s-rendered/`, which is gitignored
  for local-only use

### Kubernetes output

The Kubernetes renderer creates:

```text
<output-dir>/k8s/
├── README.md
├── namespace.yaml
├── values.yaml
├── values.secret.yaml     # local-only, optional
└── helm-install.sh
```

`values.secret.yaml` is written only when a HEC token file is supplied.
When a real token is being rendered, the setup script refuses custom output
directories inside the repo and requires the default gitignored path or a
directory outside the repo.

## Validation Checks

`scripts/validate.sh` checks:

- Splunk credential/authentication health
- default SC4S indexes
- HEC token existence
- HEC ACK status when token details are visible
- SC4S startup events in Splunk (`sourcetype=sc4s:events`)
- optional host container status and logs
- optional Helm release and pod readiness

## Troubleshooting Commands

### Splunk-side checks

Search:

```text
index=* sourcetype=sc4s:events "starting up"
```

### Host container checks

```bash
docker logs SC4S
```

```bash
podman logs SC4S
```

For systemd:

```bash
journalctl -b -u sc4s
```

### Kubernetes checks

```bash
helm status sc4s -n sc4s
```

```bash
kubectl get pods -n sc4s
```

## Operational Warnings

1. SC4S disk buffers can become very large during Splunk outages.
2. SC4S does not prune archive files automatically.
3. Non-root Podman cannot bind the standard syslog ports `514` and `601`.
4. `SC4S_DEBUG_CONTAINER=yes` should be used with direct container runs, not
   under systemd.
5. Kernel UDP receive buffer settings should align with the SC4S defaults
   (`17039360`) to avoid packet-loss warnings.
6. A disabled HEC token is treated as a setup error condition; the setup flow
   now attempts to enable it and fails clearly if that cannot be done.
