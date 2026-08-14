# Source ledger

Reviewed 2026-08-13:

| Claim family | Primary source |
|---|---|
| Component, database, route, UI and feature-flag lifecycle | <https://helm.galileo.ai/docs/guides/agent-control/> |
| Umbrella component ownership and configuration blocks | <https://helm.galileo.ai/docs/deployment/galileo-stack/> |
| Values/questionnaire authority | <https://helm.galileo.ai/docs/guides/configuration/> |
| Production approval and completion gates | <https://helm.galileo.ai/docs/deployment/deployment-guide/> |

The pinned chart archive and its schema/templates override examples in these
pages. Any chart-discovered field, image, hook, migration, CRD, PVC, route, RBAC
object, or workload absent from the reviewed inventory is an unresolved coverage
gap and must block mutation.
Execution remains an external Galileo/CSE handoff even after the gap closes.
