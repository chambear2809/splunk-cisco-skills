# Galileo On-Prem deployment source ledger

Verified 2026-08-13. Only current official Galileo deployment documentation is
used for product and support claims. Exact entitled chart archives, their
schemas/templates/locks, questionnaire output, release notes, and written CSE
decisions supersede generic examples for a specific deployment.

| Source | Coverage used by this skill | Review boundary |
| --- | --- | --- |
| [Helm charts overview](https://helm.galileo.ai/docs/getting-started/overview/) | Chart groups, prerequisites, umbrella relationship, quick-start alternatives | Descriptive chart lists never replace exact archive inventory |
| [Installation](https://helm.galileo.ai/docs/getting-started/installation/) | Four platform installation methods: recommended galileoctl UI/CLI over the umbrella chart, direct umbrella Helm, deployment script, and ordered charts | Treat both galileoctl interfaces as Method A, use the currently required UI for first install, pin chart/CLI versions, and never mix lifecycle ownership across methods |
| [Deployment readiness](https://helm.galileo.ai/docs/getting-started/deployment-readiness/) | People, access, security, network, storage, data-service and optional GPU readiness | The skill may validate evidence but cannot self-attest ownership, access or customer readiness |
| [Architecture overview](https://helm.galileo.ai/docs/architecture/overview/) | Components, dependencies, data flows, persistence and trust boundaries | Exact chart resources and customer network/data-flow decisions win over descriptive diagrams |
| [Deployment guide](https://helm.galileo.ai/docs/deployment/deployment-guide/) | Joint deployment, infrastructure, nodes, persistence, services, production completion | Public sizing and Kubernetes floors conflict with other pages; questionnaire/CSE decision wins |
| [Galileo Stack](https://helm.galileo.ai/docs/deployment/galileo-stack/) | Umbrella dependencies, component groups, approximate aggregate resources | The advertised 31-chart list omits components named elsewhere; exact Chart.yaml/lock/templates win |
| [AWS deployment](https://helm.galileo.ai/docs/deployment/aws-deployment/) | EKS, RDS, ElastiCache, S3, IRSA, registry, networking, DNS, TLS and sizing | Provider provisioning is an owned handoff; never run example cloud/database commands or accept literal credentials |
| [GCP deployment](https://helm.galileo.ai/docs/deployment/gcp-deployment/) | GKE, Cloud SQL, Memorystore, GCS, Workload Identity, registry, networking, DNS, TLS and sizing | Provider provisioning is an owned handoff; exact GCS metadata permissions and identities require validation |
| [Azure deployment](https://helm.galileo.ai/docs/deployment/azure-deployment/) | AKS, managed/in-cluster data options, MinIO, identity, registry, networking, DNS, TLS and sizing | Core object-storage guidance differs elsewhere; bind the exact package and written Galileo decision |
| [Configuration](https://helm.galileo.ai/docs/guides/configuration/) | Values layout, services, routing, identity, email, flags, Wizard and storage | Never infer undocumented keys; Azure core storage and embedded Redis claims require exact-package review |
| [Migrating to YAML anchors](https://helm.galileo.ai/docs/guides/values-anchors/) | Values deduplication and anchor migration | Require parsed-value and exact-render equivalence; never mechanically rewrite secret files |
| [AWS Secrets Manager](https://helm.galileo.ai/docs/guides/aws-secrets-manager/) | Current provider integration behavior and limits | Provider configuration is not proof that every application receives its native Secret; external synchronization remains customer-owned |
| [galileoctl](https://helm.galileo.ai/docs/guides/galileoctl/) | Platform install/upgrade, validation, smoke tests, support bundles, audit and privileged operations | Treat its in-cluster console as a separate privileged release; default to authenticated port-forward, require a reviewed dry run, and grant temporary management access only for the UI installer |
| [Agent Control](https://helm.galileo.ai/docs/guides/agent-control/) | Packaged service, database/migrations, resilience, UI and routing | Standalone and umbrella documentation conflict; exact package selects one owner |
| [Luna Studio](https://helm.galileo.ai/docs/guides/luna-studio/) | Dedicated release, Secrets, storage, training modes, GPU and routing | Standalone is default; umbrella ownership needs package evidence and CSE approval |
| [Air-gapped deployment](https://helm.galileo.ai/docs/deployment/airgapped-deployment/) | Image/chart/model manifest, mirroring and offline requirements | CSE manifest plus exact chart inspection must include init/hook/test/job images and pinned kubectl |
| [Post-deployment overview](https://helm.galileo.ai/docs/post-deployment/overview/) | Monitoring, alerts, validation, diagnostics and operations | VictoriaLogs is named but absent from chart inventories; classify dynamically |
| [CI/CD setup and first deploy](https://helm.galileo.ai/docs/post-deployment/cicd-setup-first-deploy/) | Source control, secret delivery, first deployment and promotion | Pipelines must invoke immutable child phases and retain approval/target gates; never commit secret-values |
| [Monitoring](https://helm.galileo.ai/docs/guides/monitoring/) | Dashboard, alert, metric, logging and infrastructure-monitoring inventory | Validate only the components enabled and present in the pinned package |
| [SSO integration](https://helm.galileo.ai/docs/guides/sso-integration/) | OIDC/SAML, claims, JIT roles and access-token behavior | Deployment owns prerequisites; the running-platform workflow owns identity validation and offboarding |
| [User onboarding](https://helm.galileo.ai/docs/guides/user-onboarding/) | First administrator, invitation, direct-link and signup paths | Require a named bootstrap owner and preserve offboarding/break-glass gaps |
| [Email configuration](https://helm.galileo.ai/docs/guides/email-configuration/) | SMTP/STARTTLS and SendGrid behavior and precedence | Never place credentials in the parent spec; real delivery tests need explicit approval |
| [Upgrades and ongoing operations](https://helm.galileo.ai/docs/post-deployment/upgrades-ongoing-operations/) | Upgrades, rollback constraints, backups, uninstall and troubleshooting | Every mutation belongs to a child immutable bundle and preserves failed state for diagnosis |
| [AWS disaster recovery](https://helm.galileo.ai/docs/post-deployment/aws-disaster-recovery/) | S3/RDS/ElastiCache/ClickHouse recovery, same-region restore and cross-region failover | Provider-specific, destructive recovery stays a rehearsed customer/Galileo handoff; never transpose it to generic on-prem automation |
| [GCP disaster recovery](https://helm.galileo.ai/docs/post-deployment/gcp-disaster-recovery/) | GCS/Cloud SQL/Memorystore/ClickHouse recovery, same-region restore and cross-region failover | Provider-specific, destructive recovery stays a rehearsed customer/Galileo handoff; never transpose it to generic on-prem automation |
| [Troubleshooting overview](https://helm.galileo.ai/docs/troubleshooting/overview/) | Diagnostic routing and evidence collection | Bounded, redacted, release-owned observations only |
| [Deployment troubleshooting](https://helm.galileo.ai/docs/troubleshooting/deployment/) | Helm, image pull, timeout, CRD, hook, routing and rollout failures | No raw Helm release content, Secret dumps or unsafe recovery flags |
| [Infrastructure troubleshooting](https://helm.galileo.ai/docs/troubleshooting/infra/) | Kubernetes, network, storage, queue, cache and database infrastructure | Diagnose without unrelated namespace collection or destructive repair |
| [API troubleshooting](https://helm.galileo.ai/docs/troubleshooting/api/) | API initialization, schema, connectivity, triggers and ingress | Collect bounded state/logs; changes need a separately reviewed lifecycle bundle |
| [Jobs troubleshooting](https://helm.galileo.ai/docs/troubleshooting/jobs/) | Runner, queue, backlog and execution failures | Never purge queues or retry mutations implicitly |
| [Wizard troubleshooting](https://helm.galileo.ai/docs/troubleshooting/wizard/) | Model serving, Triton, GPU, images, storage and startup | CPU fixtures do not substitute for live GPU/model evidence |
| [Database troubleshooting](https://helm.galileo.ai/docs/troubleshooting/database/) | PostgreSQL, ClickHouse, Redis, connectivity, backup and restore | Never infer migration reversibility or run restore/destructive commands from diagnostics |

## Conflicts that must remain visible

- Kubernetes minimums appear as 1.24, 1.25, and 1.27. Default to
  `max(1.27, Chart.yaml kubeVersion)` unless Galileo approves a version-specific
  exception.
- Examples use both `galileo` and `galileo-stack` release names. Require an
  explicit name and reuse existing identity.
- The installation guide has four platform methods. Method A is the recommended
  galileoctl UI or CLI workflow; both interfaces apply the umbrella chart.
  Installing the separate galileoctl console release is a prerequisite for the
  UI path and is distinct from the platform installation it subsequently drives.
  The current guide marks the UI path as required for the first install; treat
  CLI use as the documented workstation/CI path, not an unreviewed substitute.
- This repository directly automates a pinned local umbrella chart for the
  deterministic headless path. The galileoctl UI/CLI, vendor script, and ordered
  chart methods remain fully covered, source-backed operator handoffs unless an
  exact child lifecycle adds equivalent immutable and action-specific gates.
- Installation timeout examples range from 15 to 120 minutes. Keep the value
  explicit; suggest 120 minutes for the first install.
- The Stack page lists 31 subcharts while other guides name Alertmanager and a
  messaging-topology operator. Inventory the pinned archive.
- Agent Control and Luna Studio appear both as umbrella options and separate
  releases. Select exactly one mutation owner for each.
- Wizard enablement is represented at more than one values surface. Validate
  the exact schema and rendered resources.
- Redis support/topology and core Azure Blob support are not consistent across
  pages. Fail closed without exact-package and written support evidence.
- VictoriaLogs is described operationally but is not present in published
  chart group lists. Do not claim it is installed without runtime inventory.
- Secret-manager configuration does not by itself prove application mounts.
  Require an external sync design that creates exact native Secrets.
- Public resource totals and topology tables differ. Bind production sizing to
  the customer questionnaire and CSE approval. The current on-prem table calls
  for 4–10 core and 1–5 runner nodes and labels the pools `galileo-core`,
  `galileo-runner`, and `galileo-ml`; version-specific chart/CSE evidence must
  approve any different label or count.
- Public DR material does not define a generic on-premises workflow. Preserve
  an unsupported automation boundary and require a customer/Galileo runbook.
