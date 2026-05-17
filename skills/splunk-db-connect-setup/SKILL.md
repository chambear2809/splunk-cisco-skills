---
name: splunk-db-connect-setup
description: >-
  Render, preflight, validate, and hand off production-safe Splunk DB Connect
  JDBC ingestion, lookup, enrichment, and export assets for Splunk Platform. Use
  when the user asks to install or plan DB Connect, configure DBX Java and JDBC
  drivers, prepare identities, connections, inputs, outputs, lookups, SQL
  Explorer, dbxquery, dbxoutput, dbxlookup, DB Connect over Federated Search,
  or validate DB Connect topology.
---

# Splunk DB Connect Setup

Use this skill for Splunk DB Connect (`splunk_app_db_connect`, Splunkbase app
`2686`) and the supported Splunk-published JDBC driver add-ons. The default
path is render, preflight, and validate only. Installing packages is explicit
and delegated to `splunk-app-install`; live DB Connect object mutation is out of
scope for v1.

## Safety Rules

- Never ask for database passwords, tokens, wallet passphrases, private keys, or
  CyberArk/Vault secrets in chat.
- Never put secrets in argv, specs, environment-variable prefixes, rendered
  files, or JDBC URLs.
- Use local chmod-600 secret files or external secret references only.
- Treat DBX encrypted values such as `$7$...` as non-portable local artifacts;
  do not paste or render them as identity values.
- Do not deploy DB Connect through Deployment Server.
- Do not install DB Connect on universal forwarders or indexers.
- Do not self-service DB Connect installation on Splunk Cloud Classic; use IDM,
  a customer-managed heavy forwarder, or a Splunk Cloud support workflow.
- Treat Splunk Cloud Victoria as a Cloud search-head DB Connect target. Model
  customer-managed heavy forwarders as Enterprise runtime hosts paired to Cloud.
- Do not install archived JDBC add-ons unless the spec explicitly opts into
  archived driver handling.
- Do not use the automated install handoff for FIPS DB Connect. FIPS requires a
  fresh manual installation plan and PKCS12 keystore/truststore handling.

## Primary Workflow

1. Copy `template.example` to a local working spec and fill in only non-secret
   values.
2. Run a read-only preflight:

```bash
bash skills/splunk-db-connect-setup/scripts/setup.sh \
  --preflight \
  --spec my-db-connect.yaml
```

3. Render and validate the handoff packet:

```bash
bash skills/splunk-db-connect-setup/scripts/setup.sh \
  --render \
  --validate \
  --spec my-db-connect.yaml \
  --output-dir splunk-db-connect-rendered
```

4. If app installation is required, use the explicit install path:

```bash
bash skills/splunk-db-connect-setup/scripts/setup.sh \
  --install-apps \
  --accept-install \
  --spec my-db-connect.yaml \
  --output-dir splunk-db-connect-rendered
```

5. Apply DBX objects manually or through a future version after reviewing the
   rendered `dbx/*.preview` files. This v1 skill does not mutate DB Connect
   identities, connections, inputs, outputs, or lookups.

## Supported Topologies

- Single search head
- Distributed search with a dedicated DBX search head or heavy forwarder
- Search head cluster through the deployer
- Heavy forwarder
- Heavy forwarder HA with etcd planning
- Splunk Cloud Victoria with outbound allowlist planning
- Splunk Cloud Classic through IDM, a customer-managed heavy forwarder, or a
  support-managed install path

## Required Runtime Checks

Rendered assets include checks for:

- DB Connect app and JDBC add-on installation
- Java `17` or `21` on Enterprise/customer-managed runtimes; Splunk-managed
  JRE validation for Splunk Cloud Victoria search heads
- working KV Store
- DBX file permissions
- JDBC driver placement on every DBX instance
- SHC deployer bundle workflow when search head clusters are involved
- Cloud Victoria outbound database connectivity allowlists
- Splunk Cloud custom JDBC driver app skeletons under `lib/dbxdrivers`
- index and optional HEC readiness
- REST, btool, SQL Explorer, `dbxquery`, `dbxoutput`, and `dbxlookup` validation
- DB Connect over Federated Search saved-search handoffs

Read `reference.md` for driver catalog details, topology notes, Cloud behavior,
security controls, migration notes, and troubleshooting.
