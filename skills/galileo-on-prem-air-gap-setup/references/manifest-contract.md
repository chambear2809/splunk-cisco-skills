# Artifact manifest contract

`image-manifest.json` uses schema `galileo-air-gap-image-manifest/v1`:

- `release`: exact Galileo release identifier.
- `images[]`: unique `source`, `source_digest`, `mirror`, `mirror_digest`, local
  OCI `archive`, `archive_sha256`, `architectures`, `uses`, and scan attestation.
- Digests use `sha256:<64 lowercase hex>`. `source_digest` and `mirror_digest`
  must match before push; the destination is re-inspected after push.
- `source` and `mirror` are different roles and different registry authorities:
  the source is the CSE/vendor acquisition reference and the mirror is beneath
  the approved internal destination prefix. Equal names, same-registry role
  collapse, and destination-local sources fail even when their digests match.
- Each scan file is canonical, duplicate-free JSON with the closed schema
  `galileo-image-scan-attestation/v1`: exact source `subject`, `image_digest`,
  boolean `passed: true`, scanner, scanner version, timestamp, and policy. An
  extra/missing field, wrong subject/digest, integer-as-boolean, or noncanonical
  representation is rejected. The bundle rewrites only that normalized
  canonical object and requires both the acquisition-attestation digest and
  bundled-attestation digest to equal its exact bytes; it does not reinterpret
  YAML or accept a semantic-but-byte-different attestation.
- `uses` is a non-empty subset of `runtime`, `init`, `hook`, `job`, `test`, and
  `model`. Canonical Stack plus every enabled standalone-child render evidence
  must exactly equal manifest `mirror` refs. Vendor/CSE `source` refs remain
  distinct acquisition provenance; each mirror is mapped back by the equal
  immutable source/mirror digest.
- `chart-image-inventory.json` binds the exact chart name/version/SHA-256 set and
  the exact Stack render bundle under `generated_by`. Its six use categories
  carry counts; a zero count requires a non-empty reviewed reason. Literal image
  references derived from supplied chart templates may not be omitted.
- The air-gap spec supplies that immutable Stack bundle/digest and the private
  canonical Stack preflight artifact
  `.state/<bundle_sha256>/rendered-image-inventory-evidence.json` plus SHA-256.
  The evidence schema is
  `galileo-on-prem-stack-rendered-image-inventory/v1`; it binds the exact Stack
  and optional galileoctl charts, non-secret value hashes, value-free Secret
  contract digests, target, Secret-redacted render digest, timestamp, and every
  workload/init/hook/test container image.
  Offline verification requires a non-empty digest-pinned set and compares it
  exactly to the transfer inventory. A caller-authored `generated_by` hash or
  sanitized archive/runtime ID is never proof alone.
- The same preflight supplies
  `.state/<bundle_sha256>/rendered-endpoint-inventory-evidence.json`, schema
  `galileo-on-prem-stack-rendered-endpoint-inventory/v1`. It carries the same
  chart/input/render/target/timestamp binding as image evidence and only exact
  lowercase host[:port] plus sanitized purpose/source identifiers. Private
  Secret URLs are decoded only in memory.
- Host-only endpoint observation is not endpoint-rewrite proof. The currently
  required producer contract is
  `galileo-on-prem-stack-endpoint-rewrite-evidence/v1`: a closed, canonical
  Stack artifact binding exact seed and final chart/input/target/render
  identities, every source and internal mirror scheme plus host[:port], the
  rendered consuming object/field, and the exact final endpoint union. Stack
  does not yet emit it, so completion records
  `endpoint_rewrite_evidence_missing`; no caller-authored fallback is accepted.
- `release.optional_components` explicitly classifies Agent Control and Luna as
  `disabled`, `umbrella`, or `standalone`. Umbrella images must already appear
  in Stack evidence. Each standalone child supplies its exact immutable bundle
  plus canonical image and endpoint preflight evidence. Endpoint schema is
  `galileo-on-prem-child-rendered-endpoint-inventory/v1`. Missing, extra, stale,
  wrong-chart, wrong-input, wrong-render, or wrong-target evidence fails closed.
  Child inputs contain only public base/overlay hashes plus the closed
  `galileo-on-prem-redacted-secret-input-contract/v1` path/type/influence
  contract; raw Secret values and unsalted Secret hashes are forbidden. Child
  render evidence binds a structural inventory and an all-scalar-redacted
  render hash.
- Output metadata includes the closed `stack_seed` equivalence contract and a
  `stack_images` subset. The final Stack preflight compares its re-rendered
  charts, non-secret value digests, value-free Secret contract digests, target,
  Secret-redacted render digest, and image set before any mutation. Aggregate
  `images` remains the Stack-plus-children union.
- Architectures use OCI names such as `amd64` and `arm64`. Each canonical
  rendered image row carries `eligible_architectures`, derived from the exact
  live node inventory plus nodeName, nodeSelector, required node affinity, and
  hard taints/tolerations. Its OCI archive must cover that exact eligible set;
  an amd64-only image is valid only when every consuming workload excludes
  arm64 nodes. The row set and mirror set must be exactly equal.
- OCI architecture proof is cross-layer, not a union of untrusted labels. Every
  manifest descriptor inside an image index must carry an exact closed
  `os`/`architecture`/optional-`variant` platform and it must equal the
  referenced config object's platform. A direct single-manifest root may omit
  the redundant descriptor platform; the verifier derives it only from the
  config. Missing, conflicting, duplicate, non-Linux, or unknown platforms are
  rejected. Descriptor digest, byte size, and media type are verified through
  index, manifest, config, and layer edges, and unreferenced blobs or archive
  extras fail closed.
- A model archive checksum and safe archive inspection are transfer evidence,
  not runtime evidence. The required producer contract is
  `galileo-on-prem-stack-model-artifact-evidence/v1`: closed canonical evidence
  binding the exact Stack bundle/chart/input/render/target, model archive name,
  digest and architectures, rendered mount and consumer configuration, and an
  exact checksum-verifier workload/image/command plus successful result. Stack
  does not yet emit it, so any model keeps
  `stack_model_evidence_missing` open; no self-authored checksum attestation is
  accepted.

Chart, CLI, model, image-inventory, derived endpoint-union, and scan evidence files
are independently hashed. Never place registry credentials, image pull Secret
data, vendor repository tokens, database passwords, or model API keys in a
manifest or bundle.

Chart inspection recursively covers packaged dependencies to four levels for
literal images and endpoint literals. Helm `lookup`, `tpl`, and `.Files`
`Get`/`GetBytes`/`Glob`/`Lines`/`AsConfig`/`AsSecrets` dynamic access all fail
closed because client/offline evidence cannot prove their exact result. It also
rejects random/UUID/clock/environment/DNS/crypto helpers and every
`.Capabilities` or `.Release` access, including root-alias and `index`/`get`
bypasses.
