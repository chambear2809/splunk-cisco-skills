# Lifecycle contract

Required order: healthy core API/PostgreSQL/routing, out-of-band Secrets,
standalone Luna release or parent overlay, DNS/TLS, health/login, storage test,
then training validation.

The parent stack release contract and every local artifact are SHA-256 bound.
Preflight records the explicit kube context, API endpoint/CA, cluster UID,
namespace UID, release identity, Secret keys, a value-free secret path/type
influence contract, and expiry. Raw Secret values and their unsalted hashes are
never persisted; a process-local keyed HMAC protects only the private snapshot
copy, while the render hash replaces every scalar with a fixed type marker. The
skill never executes a mutation; the exact evidence is a Galileo/CSE
joint-session handoff.

The immutable `lifecycle.json` names the blocked apply modes and exact evidence
packet. Historical `--apply-*` CLI modes fail before kubeconfig, bundle, Helm,
kubectl, or state access. Evidence JSON is duplicate-free, closed-schema, and
canonical; parent and child live release objects are recomputed during
preflight rather than trusted from a file.

The external operator handoff must use complete values, `--reset-values` for
upgrades, `--wait --wait-for-jobs`, and an explicit timeout. Do not use automatic rollback,
`upgrade --install`, reused values, forced replacement, ownership takeover,
disabled validation, insecure TLS, or disabled hooks.

Rollback uses a prior immutable bundle only when a database backup, release
notes, and explicit migration compatibility are approved. Automated uninstall
always fails closed because Helm, CR, finalizer, and chart-specific deletion
effects cannot be proven safe generically. The manual handoff must preserve the
Luna database, bucket/container, Secrets, PVCs, PVs, and namespace.

Every non-uninstall preflight writes canonical
`galileo-on-prem-child-rendered-image-inventory/v1` evidence to a new private
operator-selected path. Backend, UI, training, data-generation, init, hook, Job,
and test containers must be `@sha256:` pinned. The external operator must
re-render and require the same redacted render and image inventory evidence
before mutation.
The inventory and structural render digest are derived from the API server's
strict server-dry-run response, so Kubernetes defaulting and dry-run-capable
admission mutations are included rather than trusting Helm's client output.
It also requires canonical
`galileo-on-prem-child-rendered-endpoint-inventory/v1` evidence at a new private
`--endpoint-evidence-file`. Private Secret values and decoded rendered Secret
data are inspected only in memory; evidence persists only host[:port] and safe
source/purpose identifiers. The external operator must re-derive it before Helm.

Parent and packaged dependency templates are recursively inspected through four
nested chart archives. Helm `lookup`, `tpl`, any root `.Files`, `.Capabilities`,
or `.Release` access, and random/UUID/clock, environment, DNS, crypto, or
indirect root-access helpers fail
closed for the handoff: client-side evidence cannot prove their install/upgrade
payload. Hooks and persistence/finalizer risks in dependencies
are included in review. Render validation requires exactly one reviewed
Ingress rule host and TLS host/Secret binding, or exactly one HTTPRoute
hostname. Wildcards, suffix substitutions, extra hosts, hostless default
backends, and host-override annotations fail closed.
