# Splunk TA Completion Gate

Use this gate for every Splunk Technology Add-on, add-on bundle, or dashboard
companion workflow before calling setup successful.

## Data Ingest

- Install the TA or add-on on the correct tier and create the target indexes.
- Configure accounts through the add-on UI or REST handlers so secrets land in
  Splunk encrypted storage, never in rendered files or command arguments.
- Enable the data inputs, HEC tokens, file monitors, syslog receivers, DBX
  inputs, or cloud subscriptions owned by the skill or its required companion.
- Validate that events or metrics arrive in the expected index, source,
  sourcetype, host, and time window, and review `_internal` logs for add-on
  collection errors.
- Run the relevant `splunk-data-source-readiness-doctor` source pack after data
  lands when the skill has a readiness handoff.

## Pre-Built Dashboards

- Discover any package-shipped dashboards through `data/ui/views`, app metadata,
  local package evidence, or the documented dashboard companion app.
- Make dashboard apps visible in Splunk Web when the app is intended to expose
  views, and keep TA-only apps hidden only when the package intentionally ships
  no user-facing dashboards.
- Apply dashboard defaults, index macros, saved-search enablement, lookup
  building, data model acceleration, or dashboard app settings required by the
  package.
- Prove the dashboards are turned on successfully by validating that their
  searches resolve against the configured indexes and return data after ingest
  is confirmed.
- If the TA ships no pre-built dashboards, record explicit evidence and name the
  consuming app, ES/ITSI/ARI content, or readiness-doctor path that will use the
  data instead.

## Exit Criteria

A TA setup is incomplete if the package is merely installed. The completion
evidence must include enabled ingest and one of:

- dashboard app visible plus dashboard searches returning data;
- dashboard prerequisites configured and waiting only on a documented upstream
  data source with owner/date; or
- explicit package evidence that no pre-built dashboards ship with the TA.
