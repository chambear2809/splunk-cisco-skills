# Splunk Monitoring Console Reference

## Research Sources

- Splunk Monitoring Console setup overview:
  https://help.splunk.com/en/splunk-enterprise/administer/monitor/10.2/configure-the-monitoring-console/multi-instance-monitoring-console-setup-steps
- Distributed mode and automatic configuration:
  https://help.splunk.com/en/splunk-enterprise/administer/monitor/10.2/configure-the-monitoring-console/configure-the-monitoring-console-in-distributed-mode
- Standalone mode:
  https://help.splunk.com/en/data-management/monitor-and-troubleshoot/monitor-data-in-splunk-enterprise/10.2/configure-the-monitoring-console/configure-monitoring-console-in-standalone-mode
- Monitoring Console modified files:
  https://help.splunk.com/en/splunk-enterprise/administer/monitor/10.2/about-the-monitoring-console/how-the-monitoring-console-works
- Forwarder monitoring:
  https://help.splunk.com/en/splunk-enterprise/administer/monitor/10.2/configure-the-monitoring-console/configure-forwarder-monitoring-for-the-monitoring-console
- Platform alerts:
  https://help.splunk.com/en/splunk-enterprise/administer/monitor/10.2/configure-the-monitoring-console/enable-and-configure-platform-alerts
- Search peer CLI behavior:
  https://help.splunk.com/en/splunk-enterprise/administer/distributed-search/10.2/deploy-distributed-search/add-search-peers-to-the-search-head
- Distributed search groups:
  https://help.splunk.com/en/splunk-enterprise/administer/distributed-search/10.2/manage-distributed-search/create-distributed-search-groups

## Coverage

Distributed Monitoring Console setup requires:

- choosing the Monitoring Console host
- meeting prerequisites for unique `serverName` and `host` values
- forwarding internal logs and introspection logs from monitored components
- adding monitored Splunk Enterprise instances as search peers
- reviewing discovered roles and groups in Monitoring Console general setup
- optionally enabling forwarder monitoring
- optionally enabling platform alerts

Standalone setup is simpler: the instance should list search head, license
manager, and indexer roles and then apply the standalone settings in Splunk Web.

## Rendered Settings

`splunk_monitoring_console_assets.conf`:

```ini
[settings]
mc_auto_config = enabled
```

Automatic distributed mode configuration only works after search peers already
exist. A restart applies it immediately; otherwise Splunk applies it on its
normal hourly cycle.

`savedsearches.conf`:

- `DMC Forwarder - Build Asset Table` is enabled when forwarder monitoring is
  requested.
- Platform alert saved searches are enabled by name. Operators should check
  `$SPLUNK_HOME/etc/apps/splunk_monitoring_console/default/savedsearches.conf`
  on their target version for exact alert names and thresholds.

`distsearch.conf`:

- The rendered file includes a `[distributedSearch]` stanza when search peers
  are supplied.
- Optional `--search-groups` entries render `[distributedSearch:<name>]`
  stanzas with `default = true|false`. Splunk documents these groups as useful
  for Monitoring Console deployments, especially complex topologies.
- This file is rendered for review because adding peers by direct file edit
  still requires trusted key distribution to the peers.

## Peer Onboarding

The official Splunk CLI command for adding peers uses `-remotePassword`. This
skill does not generate automation that passes that value. Use Splunk Web or an
operator-controlled secure method to add peers, then run `status.sh` and the
Monitoring Console general setup page to verify roles.
