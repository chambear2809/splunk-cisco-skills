# WideField Saviynt Integration Reference

## Public Sources

- Saviynt exchange listing: https://exchange.saviynt.com/products/widefield-security
- WideField platform page: https://www.widefield.ai/

The Saviynt listing identifies WideField Security as an API integration and
describes remediation actions including access revocation, password reset, and
micro-certification.

## Mutation Boundary

This repository does not include official Saviynt write API documentation for
creating or modifying the WideField integration. `--apply` therefore fails
closed. Add official Saviynt documentation or customer-provided API reference
here before enabling live mutation.

## Validation Evidence

Evidence should include:

- WideField finding ID or case ID.
- Saviynt remediation action.
- Timestamp, actor, and target identity.
- Outcome and rollback/exception notes.
- Capability area from `capability-coverage.md`, especially non-human identity
  ownership, human identity posture, connected application risk, AI identity
  access, or authentication/session analysis.

`validate.sh` and `setup.sh --validate` require `--evidence-file`. The file
must be valid JSON and contain at least one remediation outcome marker matching
revoke, password reset, micro-certification, or remediation; missing evidence
or a marker mismatch exits nonzero. Use `--dry-run` to inspect validation
without supplying evidence.

## Remediation Coverage

Rendered policy maps cover:

- Access revocation for compromised identities, over-privileged application
  grants, and orphaned non-human identities.
- Password reset for weak, stale, or exposed credentials.
- Micro-certification for anomalous entitlement, session, and ownership
  findings.
