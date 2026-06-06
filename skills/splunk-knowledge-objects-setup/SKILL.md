---
name: splunk-knowledge-objects-setup
description: >-
  Render, validate, and apply governance for Splunk knowledge objects: saved
  searches and alerts, search macros, CSV and KV Store lookups (with automatic
  lookup binding), eventtypes, tags, and field knowledge, plus sharing and
  ownership (ACL) governance across user, app, and global scopes. Use when the
  user asks to create or govern saved searches, scheduled searches, alerts,
  macros, lookups, eventtypes, tags, or to set knowledge-object permissions,
  ownership, or app sharing. Not for Enterprise Security detections, which live
  in splunk-enterprise-security-config.
---

# Splunk Knowledge Objects Setup

This skill renders and applies common Splunk knowledge objects and their
permissions. It is render-first so you can review the exact conf stanzas and
ACL plan before writing them live.

## Agent Behavior

Never ask for the Splunk admin password; apply reads the project `credentials`
file via the shared helper. Setting `sharing=global` is broad and refuses to
apply without `--accept-global-sharing`.

## Quick Start

Render a search macro:

```bash
bash skills/splunk-knowledge-objects-setup/scripts/setup.sh --object-kind macro --name net_idx --definition 'index IN ("a","b")'
```

Apply a scheduled saved search live:

```bash
bash skills/splunk-knowledge-objects-setup/scripts/setup.sh --phase apply \
  --object-kind savedsearch --name "Daily Count" --app-name search \
  --search 'index=main | stats count' --is-scheduled true --cron-schedule '0 6 * * *'
```

Apply a KV Store lookup definition shared at app scope:

```bash
bash skills/splunk-knowledge-objects-setup/scripts/setup.sh --phase apply \
  --object-kind lookup --name asset_lookup --lookup-type kvstore --collection asset_inventory \
  --fields-list "_key,ip,risk" --sharing app --owner nobody --read-roles "*"
```

## What It Renders

- `savedsearches.conf`, `macros.conf`, `transforms.conf`, `props.conf`,
  `eventtypes.conf`, `tags.conf` (whichever the object kind needs)
- `lookup-stub.csv` for CSV lookups
- `acl-plan.json` describing sharing/ownership applied to the object `/acl`

## Apply And ACL

Apply writes the object via the REST `configs/conf-*` endpoints (SHC
deployer-bundle aware) and then sets sharing/ownership on the object's `/acl`
endpoint. CSV lookup content is placed in the app `lookups/` directory or
uploaded via the lookup editor; the definition is written via REST.
