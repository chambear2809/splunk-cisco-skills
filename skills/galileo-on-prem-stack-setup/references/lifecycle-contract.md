# Lifecycle Contract

## Invariants

1. Inspect and render are offline and non-mutating.
2. A bundle is content-addressed, private, regular-file-only, and immutable.
3. Connected preflight and status are read-only. Server-side dry-run admission
   requests must never persist resources.
4. Every `--apply-*` entry point rejects before file I/O, state writes,
   executable resolution, or subprocess execution.
5. Installation, upgrade, rollback, uninstall, CRD ownership changes,
   galileoctl, air-gap, GPU/local inference, and lab bootstrap are Galileo/CSE
   joint-session handoffs.
6. One official installation method owns a release. Never switch methods or
   conflate evidence from separate Helm releases.
7. Failure evidence is preserved; this skill never performs cleanup,
   auto-rollback, adoption, or destructive recovery.
8. `production_ready` is always false. Preflight returns
   `preflight-incomplete` while any gate remains, or
   `evidence-complete-handoff-required`; neither state authorizes mutation.
9. Evidence generations are immutable and content-addressed for local
   tamper detection. They are not signed authorization; external Galileo/CSE
   authentication remains a separate prerequisite.

## Bundle Integrity

The versioned manifest records relative path, SHA-256, and mode for every file
except itself. Verification reruns the closed spec validator and recomputes
chart inventory, runtime inventory, coverage, and handoff-plan content from the
exact bundled archive and non-secret values. It rejects forged derived data,
missing or extra files, links, special files, wrong ownership/modes, unsafe
paths, and a directory name that differs from the content digest.

Archive inspection rejects absolute paths, traversal, links, devices, FIFOs,
duplicate paths, multiple chart roots, unsafe expansion, ambiguous YAML, and
unreviewed runtime items. The immutable bundle is authoritative for its own
embedded reviewed contracts; a later skill update must not silently rewrite an
old bundle's meaning.

## Secret Inputs

Runtime secret files must be current-user-owned, mode `0600` or stricter,
regular, non-symlink, and one-link files. YAML duplicate keys, aliases, merge
keys, lists, unknown leaf paths, empty values, and common defaults are rejected.
Each reviewed leaf is independently perturbed in memory and must affect only a
classified rendered Secret payload path. Raw and perturbed values are never
persisted.

The handoff candidate may contain a canonical manifest with only Secret payload
values replaced by stable path markers. It must never contain raw Secret data,
Helm NOTES, or subprocess stderr that could echo values.

## Target and Tool Binding

Bind the named context, canonical HTTPS API server, decoded CA bytes hash,
`kube-system` UID, namespace UID, exact Helm release inventory, Kubernetes
version/API discovery, and tool identity before connected conclusions. Reject
insecure kubeconfig TLS settings and unreviewed proxy/auth-helper behavior.

Observer capability, non-persisting admission-dry-run capability, and proposed
installer RBAC are separate evidence classes. Read-only preflight must not call
installer privileges proof an authorization approval.

## Handoff and Approval

Local YAML approval/attestation files are operator statements; they are not
authenticated Galileo/CSE authorization. `handoff-candidate.json` is explicitly
pre-approval and `authorized:false`. The external Galileo/CSE workflow must
bind its digest plus the canonical preflight digest, bundle, target, action,
runtime-input path/influence contracts, rendered-resource/image/endpoint
inventories, release state, backups, and explicit unresolved gates. This skill does not emit a final
authenticated attestation in this release.

The Galileo/CSE operator owns the actual vendor command, timing, staged
validation, recovery, and rollback decision. Re-run read-only status afterward;
without independently verified live provenance, report `unverified-observed`
or degraded—not installed, healthy, or production-ready.
