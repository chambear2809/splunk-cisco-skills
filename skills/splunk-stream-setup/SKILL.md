---
name: splunk-stream-setup
description: >-
  Install and configure Splunk Stream, Splunk Stream Forwarder (Splunk_TA_stream),
  and Splunk Stream Wire Data (Splunk_TA_stream_wire_data). Creates indexes,
  configures the stream forwarder (ipAddr, port, NetFlow receivers), enables
  protocol streams, and validates the deployment. Use when the user asks about
  Splunk Stream, stream forwarder, streamfwd, wire data, network capture,
  NetFlow, or packet capture setup.
---

# Splunk Stream Setup Automation

Automates installation and configuration of the **Splunk Stream** stack (v8.1.6):

| App | Package ID | Purpose |
|-----|-----------|---------|
| Splunk Stream | `splunk_app_stream` | Management UI, stream definitions, REST API |
| Splunk Add-on for Stream Forwarders | `Splunk_TA_stream` | Stream forwarder binary (`streamfwd`), captures network traffic |
| Splunk Stream Wire Data | `Splunk_TA_stream_wire_data` | CIM-compliant knowledge objects (props, transforms, eventtypes, tags) |

## Package Model

Use the original vendor archives from `splunk-ta/` as-is:

- `splunk-app-for-stream_816.tgz`
- `splunk-add-on-for-stream-forwarders_816.tgz`
- `splunk-add-on-for-stream-wire-data_816.tgz`

For Splunk Cloud, the normal workflow is hybrid:

- install `splunk_app_stream` and `Splunk_TA_stream_wire_data` on the Cloud
  side using the original archives through ACS or the approved support workflow
- install `Splunk_TA_stream` unchanged on a customer-controlled HF/UF
- apply local HF overlay files such as
  `templates/splunk-cloud-hf-netflow-any/`

Any `splunk-ta/_unpacked/` copy is review-only and not part of the normal
deployment workflow.

## Agent Behavior — Prompting

**The agent must NEVER ask for passwords or secrets in chat.**

Splunk credentials are read automatically from the project-root `credentials` file
(falls back to `~/.splunk/credentials`). If neither exists, guide the user to create it:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

The agent should still ask the user for non-secret configuration values:
- **Stream forwarder IP address** — the IP `streamfwd` listens on
- **Stream forwarder port** — default `8889`
- **Splunk Web URL** — the full URL to Splunk Web
- **SSL verification** — whether streamfwd should verify SSL certs
- **NetFlow configuration** (optional) — receiver IP, port, decoder type
- **Which protocol streams to enable**
- **Target index** for stream data

## Environment

This skill supports two different deployment patterns:

- **Splunk Enterprise**: a single-target workflow where app install, index
  creation, and `Splunk_TA_stream` configuration all happen against the same
  Splunk deployment.
- **Splunk Cloud**: a hybrid workflow where the cloud search tier hosts
  `splunk_app_stream`, while `Splunk_TA_stream` runs on forwarders or hosts
  under your control. In Cloud mode, index creation uses ACS and the combined
  `--install` / `--configure-streamfwd` path is intentionally blocked.

| Item | Value |
|------|-------|
| Search-tier API | `SPLUNK_SEARCH_API_URI` env var (legacy alias: `SPLUNK_URI`) |
| Cloud stack | `SPLUNK_CLOUD_STACK` for Cloud installs (`SPLUNK_PLATFORM` is only an override for hybrid runs) |
| TA app name | `splunk_app_stream`, `Splunk_TA_stream`, `Splunk_TA_stream_wire_data` |
| Credentials | Project-root `credentials` file (falls back to `~/.splunk/credentials`) |
| Skill scripts | `skills/splunk-stream-setup/scripts/` (relative to repo root) |

### Remote Splunk Connection

To run against a remote Splunk instance:

```bash
export SPLUNK_SEARCH_API_URI="https://splunk-host:8089"
```

## Available Packages

| File | App |
|------|-----|
| `splunk-app-for-stream_816.tgz` | splunk_app_stream |
| `splunk-add-on-for-stream-forwarders_816.tgz` | Splunk_TA_stream |
| `splunk-add-on-for-stream-wire-data_816.tgz` | Splunk_TA_stream_wire_data |

## Setup Workflow

### Step 1: Install Apps

```bash
bash skills/splunk-stream-setup/scripts/setup.sh --install
```

On Splunk Enterprise, installs any of the three apps that are not already
present. It uses the `splunk-app-install` skill's `install_app.sh` under the
hood, including the same remote-host behavior: direct REST upload first, then
SSH staging when the target cannot read the local package path directly.

On Splunk Cloud, do **not** run the combined install path against the cloud
search tier. Splunk documents Stream on Cloud as a hybrid deployment:

- `splunk_app_stream` is provisioned on the Splunk Cloud search tier with help
  from your account team / support workflow
- `Splunk_TA_stream` runs on forwarders or hosts under your control
- `Splunk_TA_stream_wire_data` should be installed according to the Stream cloud
  deployment architecture approved for your environment

### Step 2: Create Indexes

```bash
bash skills/splunk-stream-setup/scripts/setup.sh --indexes-only
```

| Index | Purpose | Max Size |
|-------|---------|----------|
| `netflow` | NetFlow/sFlow/IPFIX data | 512 GB |
| `stream` | Protocol capture data (optional, or use `main`) | 512 GB |

In Splunk Cloud, `--indexes-only` creates these indexes through ACS.

### Step 3: Configure Stream Forwarder

```bash
bash skills/splunk-stream-setup/scripts/setup.sh \
  --configure-streamfwd \
  --ip-addr "10.110.253.20" \
  --port 8889 \
  --splunk-web-url "https://10.110.253.20:8000" \
  --ssl-verify false
```

Writes `local/streamfwd.conf` and `local/inputs.conf` in the Stream TA.
For Splunk Cloud, run this step against the forwarder-side Splunk instance you
control, not the cloud search tier. Use the cloud-hosted Stream app URL on
`443` or `8443` as provided by your Splunk Cloud deployment.

Optional NetFlow receiver:

```bash
bash skills/splunk-stream-setup/scripts/setup.sh \
  --configure-streamfwd \
  --ip-addr "10.110.253.20" \
  --port 8889 \
  --splunk-web-url "https://10.110.253.20:8000" \
  --ssl-verify false \
  --netflow-ip "0.0.0.0" \
  --netflow-port 9995 \
  --netflow-decoder netflow
```

### Step 4: Enable Protocol Streams

```bash
bash skills/splunk-stream-setup/scripts/configure_streams.sh \
  --enable dns,http,tcp,udp,dhcp,netflow \
  --index main
```

The script manages stream definitions through the Stream KV Store or Stream Web
API when available. If neither endpoint is reachable, enable or disable streams
from Splunk Web instead.

Available protocols: `amqp`, `arp`, `dhcp`, `diameter`, `dns`, `ftp`, `http`,
`icmp`, `igmp`, `imap`, `ip`, `irc`, `ldap`, `mapi`, `modbus`, `mysql`,
`netflow`, `nfs`, `pop3`, `postgres`, `radius`, `rtcp`, `rtp`, `sflow`, `sip`,
`smb`, `smpp`, `smtp`, `snmp`, `tcp`, `tds`, `tns`, `udp`, `xmpp`.

Aggregated (Splunk_*) streams: `Splunk_DNSClientErrors`,
`Splunk_DNSClientQueryTypes`, `Splunk_DNSIntegrity`, `Splunk_DNSRequestResponse`,
`Splunk_DNSServerErrors`, `Splunk_DNSServerQuery`, `Splunk_DNSServerResponse`,
`Splunk_HTTPClient`, `Splunk_HTTPResponseTime`, `Splunk_HTTPStatus`,
`Splunk_HTTPURI`, `Splunk_IP`, `Splunk_MySql`, `Splunk_Postgres`,
`Splunk_SSLActivity`, `Splunk_Tcp`, `Splunk_Tds`, `Splunk_Tns`, `Splunk_Udp`.

### Step 5: Restart If Required

On Splunk Enterprise, restart Splunk after app or index changes.
On Splunk Cloud, check `acs status current-stack` and only run
`acs restart current-stack` when ACS reports `restartRequired=true`.

### Step 6: Validate

```bash
bash skills/splunk-stream-setup/scripts/validate.sh
```

Checks the cloud search tier or Enterprise target that `SPLUNK_SEARCH_API_URI`
(or legacy `SPLUNK_URI`) points to.
In Splunk Cloud, forwarder-side `Splunk_TA_stream` checks are reported as
non-fatal warnings because that component usually lives outside the cloud search
tier.

## Key Configuration Files

| File | App | Purpose |
|------|-----|---------|
| `local/streamfwd.conf` | Splunk_TA_stream | Forwarder IP, port, NetFlow receivers |
| `local/inputs.conf` | Splunk_TA_stream | Stream app location URL, forwarder ID |
| `local/indexes.conf` | splunk_app_stream | Index definitions (netflow, stream) |
| KV Store / Stream API | splunk_app_stream | Enabled/disabled stream definitions for remote-friendly automation |

## Deployment Templates

For a customer-controlled heavy forwarder sending NetFlow/IPFIX to Splunk Cloud,
use:

`skills/splunk-stream-setup/templates/splunk-cloud-hf-netflow-any/`

That template set includes:

- `Splunk_TA_stream/local/inputs.conf`
- `Splunk_TA_stream/local/streamfwd.conf`
- `system/local/outputs.conf`

The template is intentionally open to NetFlow/IPFIX from any device and is meant
to be copied onto the heavy forwarder after you replace the placeholder values.

## Sourcetypes

All stream sourcetypes follow the pattern `stream:<protocol>`:

| Sourcetype | Protocol | CIM Model |
|---|---|---|
| `stream:dns` | DNS | Network Resolution |
| `stream:http` | HTTP | Web |
| `stream:smtp` | SMTP | Email |
| `stream:tcp` | TCP | Network Traffic, Certificates/SSL |
| `stream:udp` | UDP | Network Traffic |
| `stream:dhcp` | DHCP | Network Sessions |
| `stream:mysql` | MySQL | Database |
| `stream:netflow` | NetFlow | Network Traffic |

## Known Issues

1. **Cloud deployment is hybrid**: Splunk Stream on Splunk Cloud uses a
   cloud-hosted `splunk_app_stream` plus forwarders you control. Do not treat
   it as a single-target install.
2. **Install order matters on Enterprise**: Install `splunk_app_stream` first,
   then `Splunk_TA_stream`, then `Splunk_TA_stream_wire_data`.
3. **Restart behavior differs by platform**: Enterprise restarts Splunk
   directly. Splunk Cloud uses ACS restart checks.
4. **No sudo needed**: Scripts run as the `splunk` OS user.
5. **SSL verification**: Set `sslVerifyServerCert = false` in inputs.conf for
   self-signed certs.
6. **Stream forwarder permissions**: `streamfwd` may need packet-capture
   capabilities such as `cap_net_raw` on the Splunk host. Apply those host-side
   permissions using your standard deployment process if raw capture is required.
7. **KV Store**: Stream app uses KV Store for stream definitions. Ensure KV
   Store is healthy before configuration.

