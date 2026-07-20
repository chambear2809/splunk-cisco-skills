---
name: splunk-cim-data-model
description: "Deprecated help-only compatibility alias for splunk-cim-data-model-setup. Use when an existing caller supplies the exact legacy skill name and needs an actionable canonical handoff; every operational invocation fails closed before rendering, validation, live access, or mutation."
compatibility: "Splunk Cloud Platform 10.5.2605: delegated. Compatibility is determined by the canonical replacement or selected child skill; this compatibility alias or router does not own a runtime or package."
metadata:
  splunk_cloud_10_5: "delegated"
  compatibility_verified: "2026-07-02"
  deprecated: "true"
  replaced_by: "splunk-cim-data-model-setup"
---

# Splunk CIM Data-Model Management (Deprecated Compatibility Alias)

> [!WARNING]
> `splunk-cim-data-model` is deprecated and replaced by
> [`splunk-cim-data-model-setup`](../splunk-cim-data-model-setup/SKILL.md). Use the canonical skill for all work.

## Fail-Closed Compatibility Contract

This directory preserves only exact-name discovery and an actionable handoff. No legacy
operational interface is demonstrably compatible with the canonical safety gates, so
nothing is forwarded. The setup, validation, and renderer entrypoints accept only an
exact `--help` or `-h` request. Every other invocation exits with status 2 before
rendering files, opening network connections, launching product commands, or changing
state, and names `splunk-cim-data-model-setup` as `replaced_by`.

Legacy reference and intake-template copies were removed so this alias cannot be mistaken
for an independently maintained workflow. Do not reconstruct or execute an old rendered
bundle. Read the canonical skill and collect inputs using its current contract.

## Safe Compatibility Checks

```bash
bash skills/splunk-cim-data-model/scripts/setup.sh --help
bash skills/splunk-cim-data-model/scripts/validate.sh --help
python3 skills/splunk-cim-data-model/scripts/render_assets.py --help
```

For supported behavior, begin here:

```bash
bash skills/splunk-cim-data-model-setup/scripts/setup.sh --help
bash skills/splunk-cim-data-model-setup/scripts/validate.sh --help
```

Any existing automation that supplies operational legacy flags must stop and be migrated
to the canonical interface after reviewing its apply and acceptance gates. Do not infer a
flag translation.
