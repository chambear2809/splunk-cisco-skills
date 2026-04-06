# SC4SNMP Reference

This reference collects the SC4SNMP defaults and operator guardrails that matter
for this repo's automation.

## Default Splunk Indexes

Create these indexes before sending production data:

- `em_logs` as an event index for SC4SNMP connector logs
- `em_metrics` as a metrics index for SC4SNMP connector metrics
- `netops` as an event index for polled or trap event data
- `netmetrics` as a metrics index for metric polling data

If you override the destination indexes in runtime configuration, create those
indexes in Splunk too.

## HEC Notes

- SC4SNMP sends to the standard Splunk HEC event collector endpoint.
- For Splunk Cloud, the normal target is `https://http-inputs-<stack>.splunkcloud.com:443`.
- For Splunk Enterprise, the normal target is `https://<host>:8088`.
- Keep HEC tokens in local-only files. Do not commit them to git.

## Runtime Notes

- SC4SNMP is an external collector. Do not attempt to install it on a Splunk
  Cloud search tier.
- Docker Compose is useful for small or lab deployments.
- Kubernetes is the normal clustered deployment model and supports explicit trap
  service IP management.
- The collector environment must be able to resolve the HEC hostname.

## Configuration Files

Docker Compose mode centers on:

- `.env`
- `inventory.csv`
- `scheduler-config.yaml`
- `traps-config.yaml`
- `secrets/secrets.json` for SNMPv3 credentials

Kubernetes mode centers on:

- `values.yaml`
- `values.secret.yaml`
- inventory and scheduler content embedded in the values file
- operator-managed Kubernetes secrets for SNMPv3 usernames where needed

## Validation Targets

This repo's validation focuses on:

- the four default indexes existing with the correct data types
- the named HEC token existing and being enabled
- SC4SNMP data or logs appearing in Splunk
- optional compose runtime or Helm pod readiness checks

## Official References

- [SC4SNMP architecture](https://splunk.github.io/splunk-connect-for-snmp/main/architecture/design/)
- [Splunk requirements](https://splunk.github.io/splunk-connect-for-snmp/main/gettingstarted/splunk-requirements/)
- [SC4SNMP installation](https://splunk.github.io/splunk-connect-for-snmp/main/gettingstarted/sc4snmp-installation/)
- [Docker Compose env file configuration](https://splunk.github.io/splunk-connect-for-snmp/main/dockercompose/6-env-file-configuration/)
