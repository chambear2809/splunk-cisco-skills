# Lookup File Editing Reference

Primary app: Splunk App for Lookup File Editing (Splunkbase `1724`, app
directory commonly `lookup_editor`).

## Readiness Scope

- Install the app on the search tier.
- Inventory CSV lookup files, lookup definitions, automatic lookups, and KV
  Store-backed lookups before enabling broad editor access.
- For search head clusters, review backup replication and `allowRestReplay`
  requirements in the app's local configuration.
- Delegate lookup ownership, ACL, and automatic lookup governance to
  `splunk-knowledge-objects-setup`; delegate KV Store health to
  `splunk-kvstore-admin-setup`.

## Guardrails

- Do not pass lookup contents or secrets on argv.
- Treat app install separately from lookup ACL and content governance.
- Validate SHC replication behavior in a non-production app context before
  using Lookup Editor as an operational process.
