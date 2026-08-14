# Source ledger

Reviewed 2026-08-13:

| Claim family | Primary source |
|---|---|
| Secrets, database, providers, training, routes and validation | <https://helm.galileo.ai/docs/guides/luna-studio/> |
| Optional umbrella component inventory | <https://helm.galileo.ai/docs/deployment/galileo-stack/> |
| CSE values/questionnaire authority | <https://helm.galileo.ai/docs/guides/configuration/> |
| Air-gap artifacts and private registry | <https://helm.galileo.ai/docs/deployment/airgapped-deployment/> |

The exact pinned chart schema/templates remain authoritative. Any new image,
hook, migration, Secret, PVC, route, RBAC object, workload, API kind, or value
flag is an unresolved coverage gap until classified.
Execution remains an external Galileo/CSE handoff even after every gap closes.
