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

All scripts operate entirely via the Splunk REST API and can run from any host with
network access to the Splunk management port (8089). No local Splunk installation is
required.

| Item | Value |
|------|-------|
| Management API | `SPLUNK_URI` env var (default: `https://localhost:8089`) |
| TA app name | `splunk_app_stream`, `Splunk_TA_stream`, `Splunk_TA_stream_wire_data` |
| Credentials | Project-root `credentials` file (falls back to `~/.splunk/credentials`) |
| Skill scripts | `skills/splunk-stream-setup/scripts/` (relative to repo root) |

### Remote Splunk Connection

To run against a remote Splunk instance:

```bash
export SPLUNK_URI="https://splunk-host:8089"
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

Installs any of the three apps that are not already present. Uses the
`splunk-app-install` skill's `install_app.sh` under the hood or installs
directly via the REST API.

### Step 2: Create Indexes

```bash
bash skills/splunk-stream-setup/scripts/setup.sh --indexes-only
```

| Index | Purpose | Max Size |
|-------|---------|----------|
| `netflow` | NetFlow/sFlow/IPFIX data | 512 GB |
| `stream` | Protocol capture data (optional, or use `main`) | 512 GB |

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

### Step 5: Restart Splunk

New indexes require a restart to activate. Restart via the Splunk UI, CLI on the
server, or REST API.

### Step 6: Validate

```bash
bash skills/splunk-stream-setup/scripts/validate.sh
```

Checks: all three apps installed, indexes exist, streamfwd configuration,
enabled streams, and data flow.

## Key Configuration Files

| File | App | Purpose |
|------|-----|---------|
| `local/streamfwd.conf` | Splunk_TA_stream | Forwarder IP, port, NetFlow receivers |
| `local/inputs.conf` | Splunk_TA_stream | Stream app location URL, forwarder ID |
| `local/indexes.conf` | splunk_app_stream | Index definitions (netflow, stream) |
| `local/streams/<name>` | splunk_app_stream | Enabled/disabled stream definitions |

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

1. **Install order matters**: Install `splunk_app_stream` first, then
   `Splunk_TA_stream`, then `Splunk_TA_stream_wire_data`.
2. **Splunk restart required**: After index creation and app installation.
3. **No sudo needed**: Scripts run as the `splunk` OS user.
4. **SSL verification**: Set `sslVerifyServerCert = false` in inputs.conf for
   self-signed certs.
5. **Stream forwarder permissions**: `streamfwd` may need `cap_net_raw`
   capability for raw packet capture. Run `set_permissions.sh` if needed.
6. **KV Store**: Stream app uses KV Store for stream definitions. Ensure KV
   Store is healthy before configuration.

