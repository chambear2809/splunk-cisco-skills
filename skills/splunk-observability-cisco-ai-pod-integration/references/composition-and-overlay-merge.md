# Composition + overlay merge

The AI Pod umbrella skill composes three child skills:

- `splunk-observability-cisco-nexus-integration` — Cisco network metrics
- `splunk-observability-cisco-intersight-integration` — Cisco compute metrics
- `splunk-observability-nvidia-gpu-integration` — NVIDIA GPU metrics

The umbrella invokes each child renderer as a subprocess, collects their `splunk-otel-overlay/*.yaml` outputs, deep-merges them with its own AI-Pod-specific additions, and writes a single composed `splunk-otel-overlay/values.overlay.yaml`.

## Why subprocess composition?

The umbrella could just import each child renderer as a Python module and call its functions. That would be faster but couples the umbrella tightly to each child's internal Python API. If any child renames a function, the umbrella breaks.

The subprocess approach treats each child as a standalone tool with a stable CLI contract: `setup.sh --render --output-dir <tmp>`. The contract is documented and tested per-child; changes to a child's internal Python don't affect the umbrella.

## Children's outputs and merge

Each child writes a `splunk-otel-overlay/` subdirectory containing one or more YAML overlay files:

- `nexus`: writes `splunk-otel-overlay/values.overlay.yaml` with the cisco_os receiver block.
- `intersight`: writes `splunk-otel-overlay/values.overlay.yaml` with the OTLP exporter pipeline (note: the Intersight collector itself is OUT-OF-CHART; the overlay only adds the OTLP receiver to the main agent).
- `gpu`: writes `splunk-otel-overlay/values.overlay.yaml` with the receiver_creator/dcgm-cisco block.

The umbrella's `load_child_overlay()` function:

1. Looks for `splunk-otel-overlay/` under each child's render output.
2. Loads ALL `*.yaml` files in that directory (not just `values.overlay.yaml`).
3. Deep-merges them into the running composite.

This handles children that emit multiple overlay files (e.g. a future split where Intersight separates the `pipeline` from `extraEnvs`).

## Deep merge semantics

The umbrella's `deep_merge(a, b)` function:

- For dict values: recursive merge, with `b` taking precedence for scalar leaves.
- For list values: concatenate `a + b`, then remove exact duplicates while preserving order. Lists of mappings are not smart-merged by a logical key; mappings that differ remain separate entries.
- For scalar values: `b` wins.

These are renderer-specific semantics, not a claim of exact Helm merge
equivalence. Review list-valued chart settings in the composed overlay before
the later `yq`/Helm apply handoff.

## Order of operations

1. Run each enabled child renderer sequentially in the configured child order.
2. Load each child's overlay files.
3. Deep-merge children: `composite = merge(merge(merge({}, nexus), intersight), gpu)`.
4. Render the umbrella's own additions (NIM/vLLM/Milvus/Trident/Portworx/Redfish + dual-pipeline + RBAC).
5. Deep-merge umbrella additions on top: `final = merge(composite, umbrella_additions)`.
6. Write `splunk-otel-overlay/values.overlay.yaml`.

The umbrella's additions WIN over child output for any key that exists in both. This is intentional: AI-Pod-specific configuration (e.g. dual-pipeline filtering) overrides the child's defaults.

## What if children's renders fail?

If any child returns non-zero, the umbrella aborts with the child's stderr surfaced. The composite is not written. This is intentional: a partial composite is worse than no composite (the operator might `helm upgrade` with a half-rendered overlay and lose other receivers).

## Token-scrub propagation

Each child renderer enforces its own secret-safety contract. The umbrella's
validator also scans the complete rendered output tree, including child
renders, for inline token-shaped fields before accepting the bundle.

## Re-rendering after a child changes

When you upgrade a child skill (e.g. nexus adds support for IOS-XR), re-run the umbrella's `setup.sh --render` to pick up the change. The child's rendered output is regenerated each time; there's no caching.

## Anti-patterns

- **Hand-editing `child-renders/<child>/splunk-otel-overlay/...` then re-running umbrella `--render`**: the next run overwrites your edits. Edit the umbrella's spec or the child's spec, not the rendered output.
- **Running each child's `setup.sh --apply` after the umbrella has merged them**: this double-applies the overlay. Always apply via the umbrella's composite, not per-child.
- **Inheriting `--reuse-values` without re-rendering**: if you change the umbrella's spec but `helm upgrade --reuse-values` against an old overlay, the change won't apply. Always re-render then upgrade.
