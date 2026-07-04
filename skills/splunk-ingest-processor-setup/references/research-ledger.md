# Ingest Processor Research Ledger

- 2026-05-17: Ingest Processor is a Splunk-hosted service for Splunk Cloud
  Platform Victoria Experience. Provisioning and some first-time setup remain
  support/UI workflows.
- 2026-05-17: Current docs make SPL2 pipelines central to Ingest Processor and
  define runtime profile `ingestProcessor`.
- 2026-05-17: Recent release notes add custom pipeline templates, Automated
  Field Extraction, stats, XML conversion, decrypt, OCSF, index partitioning,
  and PCRE2 migration surfaces.
- 2026-05-17: Destinations are paired Splunk Cloud indexes, Observability
  Cloud, metrics indexes, and Amazon S3. Splunk Enterprise destination routing
  is Edge Processor territory.
- 2026-05-17: Queueing and delivery caveats require explicit operator review,
  especially for branch/route fan-out and blocked destinations.
- 2026-06-17: Cisco Data Fabric/Cisco Live 2026 messaging adds AI-powered data
  management and auto-schematization language around onboarding and pipeline
  management. This skill treats those as UI handoffs and still refuses private
  Data Management CRUD.
- 2026-07-03: Splunk's March 11, 2026 AI-powered Data Management announcement
  labels Automated Field Extraction as Controlled Availability and Guided
  Onboarding with Auto-Schematization as Alpha. The latter can recommend CIM
  mappings and candidate TA or SPL2 outputs, but no stable public API or
  Ingest Processor release-note entry was found. Both remain entitlement-
  checked, human-reviewed UI handoffs; the renderer does not enroll tenants,
  invoke either AI workflow, generate or install TAs, or apply suggestions.
  Although the announcement says three capabilities, it publicly names only
  these two; the skill does not invent a third capability.
