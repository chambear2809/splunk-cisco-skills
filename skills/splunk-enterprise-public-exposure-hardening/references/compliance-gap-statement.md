# Compliance Gap Statement

This skill provides hardening, NOT compliance. The operator owns
compliance attestation. The skill's role is to make compliance
achievable by removing the largest classes of gaps.

## What Splunk Cloud has, that Splunk Enterprise self-hosted does not

| Attestation | Splunk Cloud | Splunk Enterprise self-hosted |
|---|---|---|
| FedRAMP High | YES (since 2024-09-13) | NO (your org owns the boundary) |
| SOC 2 Type II | YES | NO (your org owns it) |
| ISO 27001 | YES | NO |
| PCI DSS service-provider | YES | NO (your org owns the merchant attestation) |
| HIPAA BAA | YES | NO (operator-driven) |
| HITRUST | YES | NO |
| CSA STAR | YES | NO |

Self-hosted Splunk Enterprise inherits **none** of these. The skill's
controls map to the technical requirements but the operator must close
the policy and process gaps.

## Mapping the skill's controls to common compliance frameworks

### PCI DSS 4.0

- 1.x — Network segmentation: covered by firewall snippets and
  `acceptFrom`. Operator owns the PCI segmentation boundary.
- 2.x — Default-cert refusal, `pass4SymmKey` rotation, default-password
  enforcement. Operator owns the patch cadence.
- 3.x — At-rest encryption (operator-owned via OS / cloud encryption +
  `splunk.secret`).
- 4.x — TLS 1.2+ everywhere, HSTS at proxy.
- 6.x — SVD floor enforcement; secure development is the app's
  responsibility, not Splunk's.
- 7.x — Least-privilege RBAC via `role_public_reader`.
- 8.x — IdP MFA (operator-configured at the IdP).
- 10.x — `_audit` ingest; SOC alerting handoff.
- 11.x — Validate.sh, plus operator-owned vulnerability scanning.
- 12.x — Operator-owned policy.

### HIPAA Security Rule

- §164.308 (administrative): operator-owned.
- §164.310 (physical): operator-owned (datacenter / cloud).
- §164.312 (technical):
  - (a) Access control — `role_public_reader` + IdP MFA.
  - (b) Audit controls — `_audit` + SOC handoff.
  - (c) Integrity — Splunk's data integrity (in `indexes.conf`,
    operator-driven via the index lifecycle skill).
  - (d) Authentication — SAML + IdP MFA.
  - (e) Transmission security — TLS 1.2+ everywhere.

A HIPAA Business Associate Agreement (BAA) is operator-driven; Splunk
Enterprise self-hosted does not provide one.

### SOC 2 Type II

The skill provides:

- Evidence artifacts: `metadata.json`, `validate-report.json`, the
  rendered config app.
- Technical control coverage for CC6.x (logical access),
  CC7.x (system operations).

The operator owns:

- CC1.x — control environment.
- CC2.x — communication / information.
- CC3.x — risk assessment.
- CC4.x — monitoring activities (the SOC owns this).
- CC5.x — control activities (operational policies).
- The auditor's evidence sampling.

### FedRAMP

- Splunk Cloud is FedRAMP High (since 2024-09-13).
- Splunk Enterprise self-hosted is NOT in any FedRAMP boundary.
- To run FedRAMP-bound workloads on this hardening overlay, your org
  must own the FedRAMP authorization for the host (e.g. via a
  FedRAMP-authorized cloud provider on top of which you build the
  self-hosted instance).

## CMMC / CMMC 2.0

Like FedRAMP, CMMC inherits via the host environment. The skill's
controls map to:

- AC.L2-3.1.x — access control (role_public_reader + IdP MFA).
- AT.L2-3.2.x — operator-owned training.
- AU.L2-3.3.x — `_audit` + SOC.
- CM.L2-3.4.x — change management (operator-owned).
- IA.L2-3.5.x — identification & authentication (SAML + IdP MFA).
- MA.L2-3.7.x — operator-owned maintenance.
- SC.L2-3.13.x — system & communications protection (TLS, segmentation).
- SI.L2-3.14.x — system integrity (SVD floor + `splunk.secret` rotation).

## What the skill explicitly does NOT do

- Fill out attestation paperwork.
- Provide a SOC 2 Type II audit report.
- Provide a HIPAA BAA.
- Certify FedRAMP boundaries.
- Perform vulnerability scanning of the host.
- Provide IDS / IPS at the network layer.

These are the operator's responsibility; the skill provides the
technical artifacts that compliance auditors will ask for.
