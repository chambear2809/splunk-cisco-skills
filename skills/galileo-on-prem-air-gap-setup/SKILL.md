---
name: galileo-on-prem-air-gap-setup
description: >-
  Build and verify a digest-bound Galileo On-Prem air-gap supply-chain bundle
  covering Helm charts, galileoctl, every ordinary/init/hook/job/test image,
  OCI archives, model bundles, architectures, private-registry mappings,
  scanning evidence, and no-egress endpoints, while surfacing explicit
  model/runtime and endpoint-rewrite evidence gates. Use when preparing,
  transferring, mirroring, upgrading, or auditing Galileo for an offline Kubernetes cluster.
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-07-02"
---

# Galileo On-Prem Air-Gap Setup

## Prerequisites

- Obtain the CSE-provided release image manifest, exact chart archives,
  `galileoctl` artifact, and any offline Wizard/Luna model bundles.
- Run the canonical Stack preflight first and retain its private, bundle-bound
  rendered-image and rendered-endpoint evidence; static archive IDs or a
  caller-authored endpoint list are not accepted as runtime proof.
- Configure that connected seed render with the final digest-pinned internal
  mirror references before the registry contains them. The air-gap assembler
  maps each rendered mirror digest back to a distinct CSE/vendor source archive;
  it never treats source and mirror names as interchangeable.
- For every optional child classified `standalone`, run its read-only preflight
  with both `--image-evidence-file` and `--endpoint-evidence-file`, and retain
  the exact immutable child bundle.
- Use a connected staging host for acquisition/scanning and an isolated transfer
  path into a registry reachable by the cluster.
- Resolve every image to an immutable OCI digest and collect every target
  architecture. Tag-only inventories are not completion evidence.
- Allocate approximately 50–60 GB or the release-specific measured total in the
  private registry and transfer area.

## Workflow Overview

```text
+-- CSE manifest --+ -> +-- Pull/scan/digest/arch --+ -> +-- Verify transfer bundle --+
                                                            -> +-- Registry handoff --+
                                                            -> +-- No-egress proof --+
```

## When to Activate

- Prepare a first Galileo install or upgrade with no cluster internet access.
- Audit private-registry completeness, architecture, digest, or scan evidence.
- Transfer Galileo charts, images, CLI, models, hooks, and test dependencies.
- Verify that rendered runtime endpoints do not require public egress.
- Diagnose `ImagePullBackOff`, missing bootstrap images, or mutable tag drift.

## Required Intake

Ask for the Galileo instance console URL and record the exact value, for example
`https://console.demo-v2.galileocloud.io/`. Pass it with
`--galileo-console-url`; this records the intended deployment without contacting
the instance.

Collect the release ID, target architectures, private registry, exact artifacts
and SHA-256 values, digest-resolved image/OCI mappings, image use classification,
scan attestations, model archives, exact Stack/child endpoint evidence, internal allowlist,
transfer medium policy, and CSE approval. Keep registry credentials outside this
skill and supply them only within the approved operator-controlled push session.

## Supply-Chain Rules

1. Require local regular current-user-owned single-link artifacts. Reject
   symlinks, hardlinks, special files, unsafe permissions, path traversal,
   duplicate archive members, PAX path overrides, oversized expansion, and
   digest drift.
2. Require every image to have a source reference, source digest, mirror
   reference, expected mirror digest, OCI archive, architectures, and one or
   more uses: `runtime`, `init`, `hook`, `job`, `test`, or `model`.
3. Reject `latest`, tag-only proof, source/mirror digest mismatch, missing target
   architectures, source/mirror role collapse (including the same registry
   authority), and any chart-discovered image absent from the CSE manifest.
   Scan attestations must be canonical duplicate-free JSON and bind the exact
   vendor source subject plus digest with a real boolean pass result.
4. Include `galileoctl`, sequencing `kubectl`, database bootstrap clients,
   migration/hook/test images, Agent Control, Luna backend/UI/training/data-gen,
   Wizard/Triton and offline models whenever enabled.
5. Classify Agent Control and Luna as `disabled`, `umbrella`, or `standalone`.
   Stack evidence owns umbrella images; every standalone child requires its own
   canonical evidence. Require exact union equality—no extras or omissions.
   Seed evidence must equal manifest `mirror` refs, while acquisition
   provenance remains in `source`; require `mirror_digest == source_digest`.
   Derive architectures only from descriptor/config platform pairs whose exact
   Linux OS, architecture, and optional variant agree through a digest-, size-,
   and media-type-closed OCI graph. Reject missing, duplicate, unknown,
   mismatched, or unreferenced OCI evidence.
6. Keep archive verification and registry push separate. `--push-registry` is a
   permanent fail-closed sentinel. Hand the exact digest inventory and CSE
   approval to an operator-controlled session that rejects tag overwrite.
7. Never auto-upload artifacts, rewrite charts, create pull Secrets, or touch
   Kubernetes. Hand the verified contract to the stack/service skills.
8. A no-egress pass requires the exact union of target/chart/input/render-bound
   Stack and standalone-child host-only endpoint evidence to be internal. The
   verifier also independently scans embedded non-secret values and chart
   templates and rejects unexplained findings. It must
   block public registries, Let’s Encrypt, SendGrid, Sentry/Logz, central feature
   flags, public model APIs, telemetry, and package repositories.
   Host-only observations do not prove endpoint rewrites. Until Stack emits
   `galileo-on-prem-stack-endpoint-rewrite-evidence/v1`, no-egress completion
   fails as `endpoint_rewrite_evidence_missing`.
9. Offline model archives remain transfer artifacts, not runtime proof. Until
   Stack emits `galileo-on-prem-stack-model-artifact-evidence/v1` binding the
   exact archive checksum to rendered mounts/config and checksum-verifier
   behavior, model completion fails as `stack_model_evidence_missing`.
10. Reject Helm `lookup`, `tpl`, root `.Files`, `.Capabilities`, `.Release`,
   random/UUID/clock, environment, DNS, crypto, and indirect root access
   recursively in the parent chart and packaged dependencies; those constructs
   make exact offline render/image/endpoint evidence impossible to prove.

Read [reference.md](reference.md), [manifest-contract.md](references/manifest-contract.md),
[registry-and-transfer.md](references/registry-and-transfer.md), and
[source-ledger.md](references/source-ledger.md) before approving a transfer.

## Commands

```bash
bash skills/galileo-on-prem-air-gap-setup/scripts/setup.sh --help
```

```bash
bash skills/galileo-on-prem-air-gap-setup/scripts/setup.sh \
  --render --spec ./air-gap.local.yaml \
  --galileo-console-url "https://console.demo-v2.galileocloud.io/" \
  --output-dir ./galileo-on-prem-rendered/air-gap
```

```bash
bash skills/galileo-on-prem-air-gap-setup/scripts/setup.sh \
  --verify --bundle ./galileo-on-prem-rendered/air-gap \
  --galileo-console-url "https://console.demo-v2.galileocloud.io/"
```

Registry push is an explicit non-mutating handoff sentinel:

```bash
bash skills/galileo-on-prem-air-gap-setup/scripts/setup.sh \
  --push-registry
```

The sentinel fails before reading a bundle, credential, approval, or result
path. The verified bundle metadata is the handoff packet for the external
Galileo/CSE operator session.

## Completion Gate

Completion requires exact hashes for every transfer artifact, safe archive
structure, all chart inventory images classified, all target architectures in
every image, passing scan attestations, verified source/mirror digest equality,
operator-supplied post-push registry inspection, and `unapproved_endpoints=[]`
plus no open evidence gates in the no-egress report. It also requires the exact Stack-plus-standalone-child image
union and the Stack seed/final equality gate. Static verification does not claim
a deployment or GPU test.

## Troubleshooting

| Symptom | Cause | Resolution |
|---|---|---|
| Image inventory mismatch | Init/hook/test/bootstrap image omitted | Regenerate inventory from the exact charts and CSE manifest |
| Architecture failure | Archive lacks a node architecture | Acquire the correct multi-arch image or constrain scheduling |
| Digest failure | Tag moved or transfer was altered | Re-pull by digest and recreate the OCI archive |
| Push blocked | Registry writes are handoff-only without an entitled live fixture | Use the exact bundle/digests in a CSE-reviewed operator session; reject tag overwrite |
| Model evidence blocked | Stack lacks rendered model mount/config/checksum-verifier proof | Keep `stack_model_evidence_missing` open until the versioned Stack evidence exists |
| Endpoint closure blocked | Host-only evidence cannot bind source-to-mirror scheme/port rewrites | Keep `endpoint_rewrite_evidence_missing` open until the versioned Stack evidence exists |
| No-egress failure | Runtime still names a public endpoint | Disable the feature or provide an approved internal endpoint |
| Unsafe archive | Traversal, links, duplicates, PAX override, or expansion limit | Reject it and obtain a clean vendor artifact |
