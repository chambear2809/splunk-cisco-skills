# ITSI 5.0.2 package access and rehearsal status

## Historical access result — 2026-10-07

Authenticated Splunkbase requests for app 1841, release 5.0.2 returned HTTP
403 through both available credential paths. The initial bounded package search
found no archive. These historical access results remain valid for those requests.

## Package access resolved — 2026-10-07

The user supplied a local Downloads archive. Its identity and complete SHA-256
were verified before staging a protected copy for the isolated rehearsal:

- Package: `splunk-it-service-intelligence_502.spl`
- Size: 577,577,273 bytes
- `SA-ITOA` version: 5.0.2; build: 117138
- SHA-256: `88cc12d00bcb114d626cc312db2eb5eb1aabcb51cfa44245e8abb6ec465b116b`

The package-access blocker is resolved. Functional qualification remains pending.
The primary still has Enterprise 10.4.3 and ITSI 5.0.1. Its tested isolated
matching-version restore, configuration/KV backups, and verified off-host cold
installation/data archive are retained.

- Impact: primary upgrade remains gated by successful ITSI update and deferred
  migration rehearsal, retained objects/data, ingestion/search and restart checks.
- Owner: validation operator.
- Next action: update ITSI in the isolated clone, validate it, set and verify
  migration deferral, then rehearse Enterprise 10.4.3 → 10.6.0.5 before repeating
  the successful sequence on the primary.

Recovery uses the tested pre-upgrade restoration. No unsupported installation
rollback is proposed. Retain recovery artifacts through final checks and the
24-hour post-upgrade observation period.


## Isolated rehearsal completed — 2026-10-07

The verified local ITSI 5.0.2 bundle was installed in the isolated 10.4.3 clone;
all six object-migration prechecks passed without skips. The clone then upgraded
to Enterprise 10.6.0.5 with explicit `postgresMigrateOnStartup=false`. KV Store
is ready with `migrationStatus=NotStarted`, and the original 106 template and
base-search records retain their identities and stable fields. Native fixture
validation, ingestion/search and a second restart passed. Entity Overview on
10.6.0.5 displays the fixture entity and dimensions.

The remaining product-access gap is **premium ITSI licensing**. Service Analyzer
reports that the deployment is IT Essentials Work and requires an ITSI license.

- Impact: premium scheduled service/KPI health cannot be qualified.
- Owner: lab owner.
- Next action: provide the path to an already-available protected ITSI license
  file, or identify an existing licensed lab/profile. Do not provide contents.

Primary rollout, fresh preflight/storage checks and final repository checks
remain pending. The primary is still Enterprise 10.4.3 / ITSI 5.0.1. Recovery
artifacts remain retained; the 24-hour post-primary-upgrade clock has not started.
