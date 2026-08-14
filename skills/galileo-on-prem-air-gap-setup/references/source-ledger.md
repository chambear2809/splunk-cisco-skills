# Source ledger

Reviewed 2026-08-13:

| Claim family | Primary source |
|---|---|
| Staging host, CSE manifest, 50–60 GB images, local charts and registry overrides | <https://helm.galileo.ai/docs/deployment/airgapped-deployment/> |
| Umbrella and optional-component inventory | <https://helm.galileo.ai/docs/deployment/galileo-stack/> |
| Agent Control bootstrap/private-registry images | <https://helm.galileo.ai/docs/guides/agent-control/> |
| Luna backend/UI/training/data-gen images | <https://helm.galileo.ai/docs/guides/luna-studio/> |

Digest, archive, architecture, scanning, and no-egress checks are production
hardening layered on the vendor workflow. Exact CSE artifacts remain required.
Structural evidence never authorizes a registry write. Model runtime completion
and no-egress completion remain blocked by the versioned Stack producer
contracts named in `manifest-contract.md`; host-only or caller-authored evidence
is not a substitute.
