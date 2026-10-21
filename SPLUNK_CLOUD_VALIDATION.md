# Splunk Cloud Platform Validation

Validation date: `2026-10-21`

## Scope and evidence boundary

This record covers an unnamed existing Splunk Cloud tenant. The tenant assessment
was read-only; no ACS, REST, source-system, lifecycle, or companion-runtime
mutation was performed. The live observations are a dated snapshot, and the
local correction checks are offline repository evidence. They do not constitute
post-rebase recertification of the live tenant.

The catalog scope accounted for 169 entries: 78 applicable, 40 conditional, 50
not applicable, and one compatibility alias. The recorded Cloud runtime was
Splunk `10.6.0.5`, build `86587d4e3b27`.

## Cloud findings and limits

- No source inputs were available. End-to-end ingestion, source-aligned searches,
  and populated-dashboard checks therefore remain blocked. Installed views or
  packages are not evidence of populated data.
- ACS reported that a restart was required; no restart was performed, so no
  post-restart health claim is made.
- License entitlement is unassessed. Static ACS command terms or help do not
  establish tenant entitlement evidence; a support handoff is required.
- Lifecycle plans were prepared but remain unapplied pending approval.

## Local corrections and verification

The retained correction pass addressed Cloud-version parsing, render-only
dashboard behavior, ACS observations, license evidence, MCP dependency hints,
Cloud index metadata, and SC4X context/HEC snapshot reuse. It added a focused
HEC snapshot regression. ACS checks cover IPv4/IPv6 describe binding and
fail-closed malformed observations without mutation.

The pre-correction baseline was 4,841 pytest nodes: 4,805 passed, 10 failed,
and 26 skipped. That complete baseline was not rerun after correction. Recorded
post-correction groups were:

| Group | Result |
| --- | ---: |
| SC4X regression methods | 32 passed |
| HEC snapshot regression | 1 passed |
| Doctor/platform-version contract | 46 passed |
| MCP core | 109 passed |
| Metadata/catalog/docs | 90 passed |
| ACS/review/transport/docs | 27 passed |
| Selected shell regressions | 161 passed |

These groups overlap and their counts must not be summed. All checks were local
or offline and made no live Cloud changes. Original SC4X assertions and native
subprocess timeouts were retained. Three completed SC4X passes have status from
the final verbose evidence but no duration because the runner was interrupted
after completion; the final statuses are recorded in the correction ledger.

## Integration and future Cloud validation

The changes were integrated with repository base `7291139`. A targeted run of
Doctor, MCP core, ACS, Dashboard Studio, review-finding, and registry regressions
passed 224 tests and 1,487 subtests against the combined working tree. The
historical group counts above describe the retained correction snapshot and
must not be added to this result. Required pull-request
checks in [repository CI](https://github.com/chambear2809/splunk-cisco-skills/actions/workflows/ci.yml)
record validation of the integrated revision separately. They do not recertify
the live Cloud tenant. A future Cloud run requires source inputs before
ingestion and populated-dashboard gates can be evaluated.

## Retained evidence

The [sanitized run summary](skills/shared/references/splunk_cloud_validation_evidence.json)
is checked in. Detailed local reports are retained outside version control:

- Prior assessment: `splunk-live-validation-runs/cloud-assessment-20261021T165916Z-0d8f25bf/REPORT.md`
- Correction report: `splunk-live-validation-runs/cloud-fixes-20261021T183248Z/REPORT.md`
- Correction ledger: `splunk-live-validation-runs/cloud-fixes-20261021T183248Z/fixes.json`
