# Splunk Federated Search Reference

## Research Basis

This skill follows current Splunk Federated Search documentation and config
references:

- `federated.conf` defines Splunk federated provider stanzas using
  `provider://<name>`, `type = splunk`, `hostPort`, `serviceAccount`,
  `password`, and `mode = standard|transparent`.
- Standard mode providers set `appContext` and must leave
  `useFSHKnowledgeObjects = 0`. Setting `useFSHKnowledgeObjects = 1` on a
  standard provider misconfigures the provider. Transparent mode ignores
  `appContext` and always uses local search-head knowledge objects, so this
  skill renders `useFSHKnowledgeObjects = 1` for transparent providers.
- Standard mode searches require federated indexes and `federated:` search
  syntax. Transparent mode searches do not use federated indexes or
  `federated:` syntax.
- Federated indexes are represented by index definitions whose stanza name uses
  `federated:<index_name>` and whose relevant settings are
  `federated.provider` and `federated.dataset`.
- The dataset format is `<type>:<dataset_name>`, where Splunk provider dataset
  types include `index`, `metricindex`, `savedsearch`, `lastjob`, and
  `datamodel`.
- In Splunk Enterprise search head clusters, standard-mode federated index
  definitions require `conf_replication_include.indexes = true` in
  `[shclustering]` before the federated indexes are created.
- The `[general]` stanza can set `max_preview_generation_duration` and
  `max_preview_generation_inputcount` for Splunk-to-Splunk federated search
  preview generation. A value of `0` keeps the Splunk default of unlimited.

## Mode Selection

Use **standard mode** when you want explicit remote datasets represented as
local federated indexes. Search syntax references the federated index:

```spl
index=federated:remote_main
```

Use **transparent mode** when the goal is migration-style hybrid search where
users search as if remote data were local. Transparent mode has more command
restrictions and does not use federated indexes.

Do not configure multiple transparent providers or a mixed standard/transparent
set that points to the same remote deployment unless Splunk documentation for
your exact architecture says that pattern is supported.

This skill renders Splunk-to-Splunk provider assets for Splunk Enterprise
configuration files. Splunk Cloud-only Federated Search for Amazon S3 uses
`type = aws_s3` provider workflows and is intentionally documented as outside
this Enterprise file-render path.

## Service Account Handling

The remote federated provider service-account password is a secret. This skill
renders `federated.conf.template` with a placeholder and substitutes the
password only inside the generated apply script from a local-only
`--password-file`.

The service-account role on the remote deployment must have the permissions
required by the selected mode and must be able to read the remote datasets you
map through federated indexes.

## Search Head Clusters

For standard mode on Splunk Enterprise SHC:

1. Push `server.conf` with `conf_replication_include.indexes = true` through the
   deployer.
2. Then create or deploy federated index definitions.

Creating federated indexes before this replication setting exists can leave SHC
members with inconsistent federated index definitions.

## Validation

Static validation checks rendered file presence and confirms
`federated.conf.template` still contains the password placeholder. Live
validation runs the rendered `status.sh`, redacting password output.
