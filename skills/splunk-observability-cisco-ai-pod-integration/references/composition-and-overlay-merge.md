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
- For list values: concatenate `a + b`. (Caveat: lists of dicts are NOT smart-merged by key; if the same exporter appears in both `a` and `b`, you'll see duplicate entries. The umbrella avoids this by using disjoint receiver/processor/pipeline names per child.)
- For scalar values: `b` wins.

This matches Helm's `deepCopy + merge` semantics, so the resulting overlay can be passed directly to `helm upgrade --reuse-values` without surprises.

## Order of operations

1. Run each child renderer (in parallel where possible).
2. Load each child's overlay files.
3. Deep-merge children: `composite = merge(merge(merge({}, nexus), intersight), gpu)`.
4. Render the umbrella's own additions (NIM/vLLM/Milvus/Trident/Portworx/Redfish + dual-pipeline + RBAC).
5. Deep-merge umbrella additions on top: `final = merge(composite, umbrella_additions)`.
6. Write `splunk-otel-overlay/values.overlay.yaml`.

The umbrella's additions WIN over child output for any key that exists in both. This is intentional: AI-Pod-specific configuration (e.g. dual-pipeline filtering) overrides the child's defaults.

## What if children's renders fail?

If any child returns non-zero, the umbrella aborts with the child's stderr surfaced. The composite is not written. This is intentional: a partial composite is worse than no composite (the operator might `helm upgrade` with a half-rendered overlay and lose other receivers).

## Token-scrub propagation

Each child's renderer enforces its own token-scrub (no secrets in the rendered overlay). The umbrella does NOT re-scrub child output; instead it relies on each child's contract. When you write `tests/test_splunk_observability_cisco_ai_pod_integration.py`, you assert no secret-shaped strings appear in the composite, which catches any child that breaks its contract.

## Re-rendering after a child changes

When you upgrade a child skill (e.g. nexus adds support for IOS-XR), re-run the umbrella's `setup.sh --render` to pick up the change. The child's rendered output is regenerated each time; there's no caching.

## Testing

The umbrella's `tests/test_splunk_observability_cisco_ai_pod_integration.py` includes:

- `test_composition_invokes_all_three_children`: confirms subprocess invocation.
- `test_composed_overlay_contains_all_child_blocks`: asserts cisco_os, OTLP, dcgm-cisco all appear in the final overlay.
- `test_composed_overlay_is_valid_yaml`: asserts the merge produces parseable YAML.
- `test_intersight_pipeline_merged`: regression for the bug where Intersight's overlay was silently dropped.

## Anti-patterns

- **Hand-editing `child-renders/<child>/splunk-otel-overlay/...` then re-running umbrella `--render`**: the next run overwrites your edits. Edit the umbrella's spec or the child's spec, not the rendered output.
- **Running each child's `setup.sh --apply` after the umbrella has merged them**: this double-applies the overlay. Always apply via the umbrella's composite, not per-child.
- **Inheriting `--reuse-values` without re-rendering**: if you change the umbrella's spec but `helm upgrade --reuse-values` against an old overlay, the change won't apply. Always re-render then upgrade.
