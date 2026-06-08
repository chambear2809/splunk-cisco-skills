---
name: splunk-syslog-web-proxy-ta-setup
description: >-
  Shared render, install, and validation workflow for Splunk Supported Add-on
  parser and web/proxy profiles: Apache, NGINX, IIS, Tomcat, HAProxy, Squid,
  Blue Coat ProxySG, Forcepoint Web Security, Check Point Log Exporter, F5
  BIG-IP, Citrix NetScaler, and Infoblox. Renders product-specific local
  file/UF, Windows UF, or SC4S/syslog transport handoffs with package-backed
  source types. Use when the user asks to onboard, configure, render, or
  validate these web, proxy, DNS/DHCP, ADC, or appliance logs in Splunk.
---

# Syslog, Web, And Proxy Supported Add-on Setup

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Shared render-first workflow for parser and web/proxy add-ons where the primary
work is transport ownership and exact package source-type stamping. Web-server
profiles default to local file/Universal Forwarder monitors, IIS defaults to a
Windows UF handoff, and network/proxy/security appliances default to SC4S or
syslog handoff.

## Workflow

```bash
bash skills/splunk-syslog-web-proxy-ta-setup/scripts/setup.sh --render \
  --products apache,nginx,iis,tomcat,haproxy,bluecoat --index web --syslog-index netproxy
```

Review `inputs.local.conf.template` for host-local file monitors and
`transport-handoff.md` for appliance/syslog profiles.

```bash
bash skills/splunk-syslog-web-proxy-ta-setup/scripts/validate.sh --index web --syslog-index netproxy
```
