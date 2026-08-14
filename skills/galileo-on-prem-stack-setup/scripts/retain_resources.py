#!/usr/bin/env python3
"""Helm post-renderer that makes chart-owned persistent claims retention-safe."""

from __future__ import annotations

import sys

import yaml


KEEP = "helm.sh/resource-policy"


class StrictSafeLoader(yaml.SafeLoader):
    """Reject ambiguous duplicate, alias, and merge-key YAML."""

    def compose_node(self, parent: object, index: object) -> object:
        if self.check_event(yaml.AliasEvent):
            raise yaml.constructor.ConstructorError(None, None, "YAML aliases are not allowed", self.peek_event().start_mark)
        return super().compose_node(parent, index)

    def construct_mapping(self, node: object, deep: bool = False) -> dict:
        if not isinstance(node, yaml.MappingNode):
            raise yaml.constructor.ConstructorError(None, None, "expected a mapping", node.start_mark)
        result = {}
        for key_node, value_node in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise yaml.constructor.ConstructorError(None, None, "YAML merge keys are not allowed", key_node.start_mark)
            key = self.construct_object(key_node, deep=deep)
            if key in result:
                raise yaml.constructor.ConstructorError(None, None, f"duplicate YAML key: {key!r}", key_node.start_mark)
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def annotations(metadata: dict) -> dict:
    value = metadata.setdefault("annotations", {})
    if not isinstance(value, dict):
        raise ValueError("resource metadata.annotations must be a mapping")
    value[KEEP] = "keep"
    return value


def retain(document: object) -> object:
    if not isinstance(document, dict):
        return document
    if document.get("kind") == "PersistentVolumeClaim":
        metadata = document.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("PVC metadata must be a mapping")
        annotations(metadata)
    if document.get("kind") == "StatefulSet":
        spec = document.setdefault("spec", {})
        if not isinstance(spec, dict):
            raise ValueError("StatefulSet spec must be a mapping")
        policy = spec.setdefault("persistentVolumeClaimRetentionPolicy", {})
        if not isinstance(policy, dict):
            raise ValueError("StatefulSet PVC retention policy must be a mapping")
        policy.update({"whenDeleted": "Retain", "whenScaled": "Retain"})
        claims = spec.get("volumeClaimTemplates", [])
        if not isinstance(claims, list):
            raise ValueError("StatefulSet volumeClaimTemplates must be a list")
        for claim in claims:
            if not isinstance(claim, dict):
                raise ValueError("StatefulSet volumeClaimTemplate must be a mapping")
            metadata = claim.setdefault("metadata", {})
            if not isinstance(metadata, dict):
                raise ValueError("StatefulSet volumeClaimTemplate metadata must be a mapping")
            annotations(metadata)
    return document


def main() -> int:
    try:
        documents = [retain(document) for document in yaml.load_all(sys.stdin.buffer, Loader=StrictSafeLoader)]
        yaml.safe_dump_all(documents, sys.stdout, sort_keys=True, explicit_start=True)
    except (ValueError, yaml.YAMLError) as exc:
        print(f"retention post-render failed: {type(exc).__name__}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
