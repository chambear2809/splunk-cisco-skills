#!/usr/bin/env python3
"""Refresh AI Agent Monitoring package metadata from PyPI into rendered output."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PACKAGES = [
    "splunk-opentelemetry",
    "splunk-otel-util-genai",
    "splunk-otel-genai-emitters-splunk",
    "splunk-otel-genai-evals-deepeval",
    "splunk-otel-instrumentation-crewai",
    "splunk-otel-instrumentation-langchain",
    "splunk-otel-instrumentation-llamaindex",
    "splunk-otel-instrumentation-openai",
    "splunk-otel-instrumentation-openai-agents",
    "splunk-otel-instrumentation-fastmcp",
    "splunk-otel-instrumentation-weaviate",
    "splunk-otel-instrumentation-aidefense",
    "opentelemetry-instrumentation-openai-v2",
    "opentelemetry-instrumentation-anthropic",
    "opentelemetry-instrumentation-vertexai",
    "opentelemetry-instrumentation-bedrock",
    "opentelemetry-instrumentation-cohere",
    "opentelemetry-instrumentation-mistralai",
    "opentelemetry-instrumentation-google-genai",
    "splunk-otel-util-genai-translator-langsmith",
    "splunk-otel-util-genai-translator-openlit",
    "splunk-otel-util-genai-translator-traceloop",
    "splunk-otel-instrumentation-openai-v2",
    "splunk-otel-instrumentation-vertexai",
    "opentelemetry-instrumentation-litellm",
]


def fetch_package(name: str) -> dict[str, str]:
    url = f"https://pypi.org/pypi/{name}/json"
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            data = json.load(response)
        info = data.get("info", {})
        return {
            "name": name,
            "status": "found",
            "version": str(info.get("version") or ""),
            "requires_python": str(info.get("requires_python") or ""),
            "url": url,
        }
    except urllib.error.HTTPError as exc:
        return {"name": name, "status": "not_found", "error": f"HTTP {exc.code}", "url": url}
    except Exception as exc:  # pragma: no cover - network failures vary
        return {"name": name, "status": "error", "error": type(exc).__name__, "url": url}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("splunk-observability-ai-agent-monitoring-rendered"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "packages": [fetch_package(name) for name in PACKAGES],
    }
    out = args.output_dir / "package-catalog-refreshed.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        found = sum(1 for item in payload["packages"] if item["status"] == "found")
        print(f"refresh-package-catalog: wrote {out} ({found}/{len(PACKAGES)} found)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
