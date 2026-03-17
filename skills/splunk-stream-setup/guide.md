# Splunk Stream Setup — Usage Guide

## Quick Start

Ask the agent:

> "Set up Splunk Stream for network traffic capture"

The agent will prompt you for:
1. Splunk admin username and password
2. The IP address of this machine (for `streamfwd` to bind to)
3. The Splunk Web URL (e.g., `https://10.110.253.20:8000`)
4. Whether to configure NetFlow collection
5. Which protocol streams to enable

## Example Prompts

### Full Setup (all three apps + configuration)

> "Install and configure all Splunk Stream components"

This runs the full workflow: installs any missing apps (`splunk_app_stream`,
`Splunk_TA_stream`, `Splunk_TA_stream_wire_data`), creates indexes, configures
the stream forwarder, and prompts for stream enablement.

### Install Only

> "Install the Splunk Stream apps"

Installs the three packages from the project-root `splunk-ta/` directory without
configuring streams.

### Configure Stream Forwarder

> "Configure the stream forwarder to listen on 10.110.253.20 port 8889
> with NetFlow on port 9995"

The agent runs `setup.sh --configure-streamfwd` with the provided values.

### Enable Streams

> "Enable DNS, HTTP, and TCP streams"

> "Enable netflow stream and send to the netflow index"

The agent runs `configure_streams.sh --enable dns,http,tcp` or similar.

### List Available Streams

> "Show me all available stream protocols"

Runs `configure_streams.sh --list` to display all protocols and their status.

### Validate Setup

> "Validate the Splunk Stream deployment"

Runs `validate.sh` to check all components, configs, and data flow.

## What the Agent Asks

The agent will ask you for these values (never assumes):

| Value | Why | Example |
|-------|-----|---------|
| Splunk username | REST API authentication | `admin` |
| Splunk password | REST API authentication | (your password) |
| Machine IP | `streamfwd` bind address | `10.110.253.20` |
| Splunk Web URL | `streamfwd` → Stream app communication | `https://10.110.253.20:8000` |
| Stream forwarder port | Port for forwarder traffic | `8889` (default) |
| SSL verify | Cert verification for self-signed certs | `false` |
| NetFlow IP/port | Optional flow collection | `0.0.0.0:9995` |
| Protocols to enable | Which traffic to capture | `dns,http,tcp,udp` |
| Target index | Where stream data lands | `main` or `netflow` |

## Post-Setup Checklist

After the agent completes setup:

1. Restart Splunk: `/opt/splunk/bin/splunk restart`
2. Open Splunk Web and navigate to **Splunk Stream** app
3. Verify stream forwarder is connected (Stream > Configuration > Distributed Forwarder Management)
4. Check for data: `source=stream` or `index=netflow`
5. If packet capture needed, run `set_permissions.sh` in the Stream TA for `cap_net_raw`
