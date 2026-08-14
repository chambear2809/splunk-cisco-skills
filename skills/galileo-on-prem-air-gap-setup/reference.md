# Air-gap deployment boundary

This skill owns supply-chain evidence only. It inventories, hashes, safely
inspects, classifies, verifies, and transfers artifacts for an
already-provisioned private registry. It does not push images, install Galileo, mutate
Kubernetes, create registry credentials, create image pull Secrets, or provision
databases/storage/networking.

The verified output feeds `galileo-on-prem-stack-setup`,
`galileo-on-prem-agent-control-setup`, and
`galileo-on-prem-luna-studio-setup`. Those consumers must compare the air-gap
bundle digest and their actual chart/image inventory in the external handoff.

## Non-circular seed-to-final workflow

1. Render a read-only Stack seed with air gap disabled but the exact final chart,
   non-secret values, Secret files, target, enabled umbrella components, and
   final private-registry image references. The registry need not contain the
   images yet because this phase templates and server-dry-runs without starting
   Pods. Its rendered refs are the final internal `mirror` refs. The transfer
   manifest separately retains vendor `source` refs, and the assembler proves
   both names resolve to the same immutable digest.
2. Run Stack preflight. Its canonical image and host-only endpoint observations bind the seed bundle,
   charts, non-secret input hashes, value-free Secret contract digests, target,
   Secret-redacted render hash, and exact digest-pinned container rows.
3. Run each enabled standalone Agent Control/Luna preflight and capture its
   canonical child image and host-only endpoint evidence against the same parent target.
4. Build this air-gap bundle. It embeds and re-verifies the Stack seed bundle and
   evidence, every standalone child bundle/evidence, and their exact image and
   endpoint unions. A caller-authored runtime endpoint list is not accepted.
5. Keep completion open as `endpoint_rewrite_evidence_missing` until Stack emits
   canonical `galileo-on-prem-stack-endpoint-rewrite-evidence/v1`, binding exact
   source and internal destination schemes, host[:port], rendered consumers,
   seed/final chart/input/target/render identities, and exact final endpoint union.
6. For each model, keep `stack_model_evidence_missing` open until Stack emits
   canonical `galileo-on-prem-stack-model-artifact-evidence/v1`, binding archive
   checksum/identity to exact rendered mount, consuming config, checksum-verifier
   workload/image/command, target, and successful verification result.
7. Render the final Stack bundle with air gap enabled and this contract. Final
   Stack preflight must re-render and require exact charts, inputs, target,
   Helm-render, and Stack-image equality to `metadata.json.stack_seed` and
   `metadata.json.stack_images`. Only the Stack bundle identity may differ due
   to the embedded air-gap contract. No Kubernetes mutation precedes this gate.

Official examples use Docker save/load and mutable tags. This skill strengthens
that handoff: each image is stored as a separate OCI archive and carries an
independently resolved manifest digest plus architecture evidence. A mutable tag
may be retained for chart compatibility, but never serves as identity proof.
