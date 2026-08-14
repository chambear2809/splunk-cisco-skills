# Luna Studio deployment boundary

Luna Studio is a standalone web application by default. Release and chart name:
`luna-studio`; values key: `galileo_services.luna_finetune`. The chart creates a
FastAPI backend and Next.js UI, but the customer provisions PostgreSQL, object
storage, identity/credentials, routing, and training capacity.

Mandatory out-of-band Secret contracts:

| Default Secret | Required keys |
|---|---|
| `luna-studio-jwt` | `jwt-secret-key` |
| `luna-studio-admin` | `username`, `password` |
| `luna-studio-database` | `connection-string`, `host`, `port`, `database`, `username`, `password` |
| `luna-studio-nextauth` | `secret` |

The optional `luna-studio-galileo` Secret requires `api-url` and `api-key` when
Galileo API evaluation is enabled. Provider and remote-cluster Secret contracts
are conditional and are listed in `references/training-and-storage.md`.

The database connection string uses `postgresql+asyncpg://`. The backend runs
`alembic upgrade head` on startup. The database user therefore needs permission
to create and alter tables; rollback is not assumed migration-safe.

Backend Service: `luna-studio-backend:80`, health `/health`. Browser traffic goes
to `luna-studio:80`, health `/api/health`; UI proxies backend calls internally.

Standalone preflight emits canonical
`galileo-on-prem-child-rendered-image-inventory/v1` evidence only to the new
private path supplied with `--image-evidence-file`, plus canonical host-only
`galileo-on-prem-child-rendered-endpoint-inventory/v1` evidence at
`--endpoint-evidence-file`. Air-gap preparation verifies both against the
immutable Luna child bundle, exact parent target, inputs, and Helm render.

This skill never installs, upgrades, rolls back, or uninstalls the release.
Every historical `--apply-*` mode fails before kubeconfig, bundle, or process
access. Hand `lifecycle.json` plus fresh preflight/image/endpoint evidence to a
Galileo/CSE joint-session operator.
