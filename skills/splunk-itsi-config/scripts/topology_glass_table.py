#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lib.common import SkillError, load_json, write_json, write_yaml


def _node_service_title(node: dict[str, Any], refs: dict[str, str]) -> str:
    if node.get("ref"):
        ref = str(node["ref"])
        if ref not in refs:
            raise SkillError(f"Topology glass table node references unknown ref '{ref}'.")
        return refs[ref]
    if "service_ref" in node:
        service_ref = node["service_ref"]
        if isinstance(service_ref, str):
            return service_ref
        if isinstance(service_ref, dict) and service_ref.get("title"):
            return str(service_ref["title"])
    service = node.get("service")
    if isinstance(service, dict) and service.get("title"):
        return str(service["title"])
    raise SkillError(f"Topology node must define service_ref, service.title, or ref: {node}")


def _collect_topology_nodes(spec: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    roots = spec.get("topology", {}).get("roots", [])
    if not isinstance(roots, list):
        raise SkillError("topology.roots must be a list.")
    refs: dict[str, str] = {}
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    depth_counts: dict[int, int] = {}

    def collect_refs(node: dict[str, Any]) -> None:
        if not isinstance(node, dict):
            raise SkillError("topology nodes must be mappings.")
        if node.get("id") and not node.get("ref"):
            refs[str(node["id"])] = _node_service_title(node, refs)
        for child in node.get("children", []) or []:
            collect_refs(child)

    def visit(node: dict[str, Any], parent_id: str | None, depth: int) -> None:
        if not isinstance(node, dict):
            raise SkillError("topology nodes must be mappings.")
        node_id = str(node.get("id") or node.get("ref") or f"node_{len(nodes) + 1}")
        title = _node_service_title(node, refs)
        order = depth_counts.get(depth, 0)
        depth_counts[depth] = order + 1
        nodes.append(
            {
                "id": node_id,
                "service_title": title,
                "x": 80 + depth * 320,
                "y": 80 + order * 150,
                "width": 220,
                "height": 72,
            }
        )
        if parent_id:
            edges.append({"source": parent_id, "target": node_id, "kpis": node.get("kpis", [])})
        for child in node.get("children", []) or []:
            visit(child, node_id, depth + 1)

    for root in roots:
        collect_refs(root)
    for root in roots:
        visit(root, None, 0)
    return nodes, edges


def build_glass_table_spec(spec: dict[str, Any], title: str) -> dict[str, Any]:
    nodes, edges = _collect_topology_nodes(spec)
    return {
        "glass_tables": [
            {
                "title": title,
                "description": "Starter glass table generated from the topology tree. Review layout and visual tokens before applying.",
                "payload": {
                    "generated_by": "splunk-itsi-config topology_glass_table.py",
                    "layout": {"type": "absolute", "width": 1200, "height": max(600, 180 + len(nodes) * 120)},
                    "nodes": nodes,
                    "edges": edges,
                },
            }
        ]
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a starter native glass-table spec from a topology JSON spec.")
    parser.add_argument("--spec-json", required=True, help="Path to a JSON topology spec.")
    parser.add_argument("--title", default="Generated Topology Glass Table")
    parser.add_argument("--output", required=True, help="Output path.")
    parser.add_argument("--output-format", choices=["json", "yaml"], default="yaml")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        payload = build_glass_table_spec(load_json(args.spec_json), args.title)
        if args.output_format == "json":
            write_json(args.output, payload)
        else:
            write_yaml(args.output, payload)
        print(json.dumps({"output": args.output, "glass_tables": [item["title"] for item in payload["glass_tables"]]}, indent=2))
        return 0
    except SkillError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
