#!/usr/bin/env python3
"""Splunk platform sizing engine.

Pure-stdlib calculator that turns a use case (daily ingest, retention, search
load, premium apps, HA) into a sizing recommendation across All-In-One
standalone, distributed Splunk Validated Architectures, Splunk on Kubernetes
(SOK + Splunk POD), and Splunk Cloud.

Outputs a human-readable Markdown report plus a machine-readable sizing.json.
All numbers are planning estimates; see reference.md for the model and its
limits. This is not a substitute for a Splunk Professional Services sizing.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"

# --- Sizing model constants (documented in reference.md) ----------------------

# Per-indexer searchable ingest ceiling (GB/day) on Splunk reference hardware,
# before the search-density multiplier is applied.
PROFILE_CEILING_GB = {
    "core": 250,
    "es": 100,
    "itsi": 150,
    "es_itsi": 80,
}

# Search-density multiplier applied to the per-indexer ceiling. Denser search
# concurrency lowers the volume a single indexer can serve.
DENSITY_MULTIPLIER = {
    "light": 1.2,
    "medium": 1.0,
    "dense": 0.7,
}

# Fraction of ingested volume retained on disk after Splunk compression
# (rawdata journal + tsidx). Rule of thumb ~50% of the original.
COMPRESSION_RATIO = 0.5

# Concurrent historical searches a reference search head sustains.
SEARCHES_PER_SH = 24

# Standalone All-In-One eligibility ceiling (effective GB/day).
AIO_MAX_INGEST_GB = 300

# Reference hardware per role. vCPU / RAM(GB) / data-disk IOPS guidance.
REFERENCE_HARDWARE = {
    "indexer_core": {"vcpu": 16, "ram_gb": 32, "iops": 800},
    "indexer_premium": {"vcpu": 32, "ram_gb": 64, "iops": 1200},
    "search_head_core": {"vcpu": 16, "ram_gb": 32, "iops": 200},
    "search_head_premium": {"vcpu": 16, "ram_gb": 64, "iops": 200},
    "cluster_manager": {"vcpu": 16, "ram_gb": 32, "iops": 200},
    "deployer": {"vcpu": 8, "ram_gb": 16, "iops": 200},
    "support": {"vcpu": 8, "ram_gb": 16, "iops": 200},
    "standalone_core": {"vcpu": 16, "ram_gb": 32, "iops": 800},
    "standalone_premium": {"vcpu": 32, "ram_gb": 64, "iops": 1200},
}

WORKLOAD_CHOICES = ("core", "es", "itsi", "es_itsi")
DENSITY_CHOICES = ("light", "medium", "dense")
TARGET_CHOICES = ("auto", "standalone", "distributed", "sok", "pod", "cloud")


def ceil_div(numerator: float, denominator: float) -> int:
    return int(math.ceil(numerator / denominator)) if denominator else 0


def is_premium(profile: str) -> bool:
    return profile in ("es", "itsi", "es_itsi")


def premium_apps(profile: str) -> list[str]:
    apps = []
    if profile in ("es", "es_itsi"):
        apps.append("Enterprise Security")
    if profile in ("itsi", "es_itsi"):
        apps.append("ITSI")
    return apps


# --- Core computation ---------------------------------------------------------


def compute(inputs: dict[str, Any]) -> dict[str, Any]:
    profile = inputs["workload_profile"]
    density = inputs["search_density"]
    daily = inputs["daily_ingest_gb"]
    growth_pct = inputs["growth_pct"]
    retention = inputs["retention_days"]
    smartstore = inputs["smartstore"]
    multisite = inputs["multisite"]
    sites = inputs["sites"]

    effective_daily = round(daily * (1 + growth_pct / 100.0), 2)

    base_ceiling = PROFILE_CEILING_GB[profile]
    per_indexer_ceiling = round(base_ceiling * DENSITY_MULTIPLIER[density], 1)

    ha = inputs["ha"]
    # Replication/search factor: explicit, else defaults for clustered vs not.
    if ha:
        rf = inputs["replication_factor"] or 3
        sf = inputs["search_factor"] or 2
    else:
        rf = inputs["replication_factor"] or 1
        sf = inputs["search_factor"] or 1
    if sf > rf:
        raise ValueError(
            f"search factor ({sf}) cannot exceed replication factor ({rf})"
        )

    indexer_for_ingest = max(1, ceil_div(effective_daily, per_indexer_ceiling))
    if ha:
        cluster_min = max(rf, 3, sites if multisite else 1)
        indexer_count = max(indexer_for_ingest, cluster_min)
    else:
        indexer_count = indexer_for_ingest

    # Search head sizing.
    if inputs["concurrent_searches"] is not None:
        concurrent_searches = inputs["concurrent_searches"]
    elif inputs["concurrent_users"] is not None:
        concurrent_searches = max(1, round(inputs["concurrent_users"] * 0.5))
    else:
        concurrent_searches = 12

    core_sh = max(1, ceil_div(concurrent_searches, SEARCHES_PER_SH))
    shc = core_sh > 1 or ha
    if shc and core_sh < 3:
        core_sh = 3

    dedicated_premium_sh = premium_apps(profile)

    # Storage.
    indexed_per_day = round(effective_daily * COMPRESSION_RATIO, 2)
    cluster_storage = round(indexed_per_day * retention * rf, 2)
    per_indexer_storage = round(cluster_storage / indexer_count, 2)
    smartstore_local_cache = (
        round(per_indexer_storage * 0.3, 2) if smartstore else None
    )

    # All-In-One eligibility.
    aio_reasons: list[str] = []
    if effective_daily > AIO_MAX_INGEST_GB:
        aio_reasons.append(
            f"effective ingest {effective_daily} GB/day exceeds the "
            f"All-In-One ceiling of {AIO_MAX_INGEST_GB} GB/day"
        )
    if ha:
        aio_reasons.append("high availability requires multiple indexers (cluster)")
    if indexer_for_ingest > 1:
        aio_reasons.append(
            f"ingest needs {indexer_for_ingest} indexers at "
            f"{per_indexer_ceiling} GB/day each"
        )
    if concurrent_searches > SEARCHES_PER_SH:
        aio_reasons.append(
            f"{concurrent_searches} concurrent searches exceed a single "
            f"instance capacity (~{SEARCHES_PER_SH})"
        )
    aio_eligible = not aio_reasons

    return {
        "effective_daily_ingest_gb": effective_daily,
        "per_indexer_ceiling_gb": per_indexer_ceiling,
        "indexer_for_ingest": indexer_for_ingest,
        "indexer_count": indexer_count,
        "replication_factor": rf,
        "search_factor": sf,
        "concurrent_searches": concurrent_searches,
        "search_head_count": core_sh,
        "search_head_cluster": shc,
        "dedicated_premium_search_heads": dedicated_premium_sh,
        "indexed_per_day_gb": indexed_per_day,
        "cluster_storage_gb": cluster_storage,
        "per_indexer_storage_gb": per_indexer_storage,
        "smartstore": smartstore,
        "smartstore_local_cache_gb": smartstore_local_cache,
        "multisite": multisite,
        "sites": sites,
        "aio_eligible": aio_eligible,
        "aio_reasons": aio_reasons,
        "premium": is_premium(profile),
    }


# --- Recommendation + per-target mapping --------------------------------------


def sva_category(computed: dict[str, Any]) -> str:
    if computed["multisite"]:
        return "M-series (multisite indexer + search head cluster)"
    if computed["search_head_cluster"]:
        return "C3 (single-site, search head cluster + indexer cluster)"
    return "C1 (single-site, single search head + indexer cluster)"


def sok_architecture(computed: dict[str, Any], aio_target: bool) -> str:
    if aio_target:
        return "s1"
    if computed["multisite"]:
        return "m4"
    return "c3"


def pod_profile(computed: dict[str, Any]) -> str:
    idx = computed["indexer_count"]
    if idx <= 3:
        return "pod-small"
    if idx <= 6:
        return "pod-medium"
    return "pod-large"


def indexer_hw_key(computed: dict[str, Any]) -> str:
    return "indexer_premium" if computed["premium"] else "indexer_core"


def search_head_hw_key(computed: dict[str, Any]) -> str:
    return "search_head_premium" if computed["premium"] else "search_head_core"


def build_topology(computed: dict[str, Any]) -> dict[str, Any]:
    idx_hw = REFERENCE_HARDWARE[indexer_hw_key(computed)]
    sh_hw = REFERENCE_HARDWARE[search_head_hw_key(computed)]
    roles: list[dict[str, Any]] = [
        {
            "role": "indexer",
            "count": computed["indexer_count"],
            "hardware": idx_hw,
            "data_disk_gb_each": computed["per_indexer_storage_gb"],
        },
        {
            "role": "search_head",
            "count": computed["search_head_count"],
            "hardware": sh_hw,
            "clustered": computed["search_head_cluster"],
        },
        {
            "role": "cluster_manager",
            "count": 1,
            "hardware": REFERENCE_HARDWARE["cluster_manager"],
        },
    ]
    if computed["search_head_cluster"]:
        roles.append(
            {
                "role": "deployer",
                "count": 1,
                "hardware": REFERENCE_HARDWARE["deployer"],
            }
        )
    for app in computed["dedicated_premium_search_heads"]:
        roles.append(
            {
                "role": f"dedicated_search_head_{app.lower().replace(' ', '_')}",
                "count": 3 if computed["search_head_cluster"] else 1,
                "hardware": sh_hw,
                "note": f"Dedicated {app} search head(s)",
            }
        )
    roles.append(
        {
            "role": "support_nodes",
            "count": 1,
            "hardware": REFERENCE_HARDWARE["support"],
            "note": "License manager / Monitoring Console / deployment server "
            "(can be co-located at small scale).",
        }
    )
    return {"roles": roles}


def recommend(computed: dict[str, Any], requested_target: str) -> dict[str, Any]:
    if requested_target == "auto":
        resolved = "standalone" if computed["aio_eligible"] else "distributed"
    else:
        resolved = requested_target

    aio_target = resolved == "standalone" or (
        resolved in ("sok",) and computed["aio_eligible"] and not computed["multisite"]
    )

    rec: dict[str, Any] = {
        "requested_target": requested_target,
        "resolved_target": resolved,
    }

    if resolved == "standalone":
        rec["sva_category"] = "S1 (single-server / All-In-One)"
        hw_key = "standalone_premium" if computed["premium"] else "standalone_core"
        rec["topology"] = {
            "roles": [
                {
                    "role": "all_in_one",
                    "count": 1,
                    "hardware": REFERENCE_HARDWARE[hw_key],
                    "data_disk_gb": computed["cluster_storage_gb"],
                }
            ]
        }
    elif resolved in ("distributed", "pod"):
        rec["sva_category"] = sva_category(computed)
        rec["topology"] = build_topology(computed)
        if resolved == "pod":
            rec["pod_profile"] = pod_profile(computed)
    elif resolved == "sok":
        arch = sok_architecture(computed, aio_target)
        rec["sva_category"] = sva_category(computed) if arch != "s1" else "S1 (standalone)"
        rec["sok_architecture"] = arch
        rec["topology"] = (
            {"roles": [{"role": "standalone", "count": 1}]}
            if arch == "s1"
            else build_topology(computed)
        )
    elif resolved == "cloud":
        rec["sva_category"] = "Splunk Cloud Platform (Splunk-managed)"
        rec["note"] = (
            "Splunk Cloud is sized by ingest volume and workload (SVC) tier; "
            "indexer/search-head counts are managed by Splunk. The indexer and "
            "search-head estimates below are for capacity reference only."
        )
        rec["topology"] = build_topology(computed)

    return rec


def build_targets(computed: dict[str, Any]) -> dict[str, Any]:
    aio_target = computed["aio_eligible"] and not computed["multisite"]
    return {
        "standalone": {
            "eligible": computed["aio_eligible"],
            "reasons_against": computed["aio_reasons"],
            "sva_category": "S1 (single-server / All-In-One)",
        },
        "distributed": {
            "sva_category": sva_category(computed),
            "indexers": computed["indexer_count"],
            "search_heads": computed["search_head_count"],
            "search_head_cluster": computed["search_head_cluster"],
        },
        "sok": {
            "architecture": sok_architecture(computed, aio_target),
            "indexer_replicas": (
                1
                if (sok_architecture(computed, aio_target) == "s1")
                else (
                    ceil_div(computed["indexer_count"], max(1, computed["sites"]))
                    if computed["multisite"]
                    else computed["indexer_count"]
                )
            ),
            "search_head_replicas": (
                1
                if sok_architecture(computed, aio_target) == "s1"
                else max(3, computed["search_head_count"])
            ),
            "site_count": computed["sites"] if computed["multisite"] else 1,
            "var_storage_gb_each": computed["per_indexer_storage_gb"],
        },
        "pod": {
            "profile": pod_profile(computed),
            "indexers": computed["indexer_count"],
        },
        "cloud": {
            "ingest_gb_day": computed["effective_daily_ingest_gb"],
            "workload": "premium (ES/ITSI)" if computed["premium"] else "core",
            "note": "Splunk-managed; size by ingest volume + SVC workload tier.",
        },
    }


def build_handoffs(resolved: str, computed: dict[str, Any]) -> list[dict[str, str]]:
    handoffs: list[dict[str, str]] = []
    if resolved == "standalone":
        handoffs.append(
            {
                "skill": "splunk-enterprise-host-setup",
                "why": "Install the single All-In-One Splunk Enterprise host.",
            }
        )
    elif resolved == "distributed":
        handoffs.append(
            {
                "skill": "splunk-enterprise-host-setup",
                "why": "Install Splunk Enterprise on each indexer/search-head host.",
            }
        )
        handoffs.append(
            {
                "skill": "splunk-indexer-cluster-setup",
                "why": "Bootstrap the indexer cluster with the chosen RF/SF.",
            }
        )
        if computed["search_head_cluster"]:
            handoffs.append(
                {
                    "skill": "splunk-search-head-cluster-setup",
                    "why": "Bootstrap the search head cluster (deployer + members).",
                }
            )
    elif resolved in ("sok", "pod"):
        handoffs.append(
            {
                "skill": "splunk-enterprise-kubernetes-setup",
                "why": "Render and apply the SOK CR or Splunk POD cluster config.",
            }
        )
    elif resolved == "cloud":
        handoffs.append(
            {
                "skill": "splunk-cloud-acs-admin-setup",
                "why": "Create indexes and manage the Splunk Cloud stack via ACS.",
            }
        )
    handoffs.append(
        {
            "skill": "splunk-index-lifecycle-smartstore-setup",
            "why": "Render indexes.conf retention"
            + (" and SmartStore volumes." if computed["smartstore"] else "."),
        }
    )
    return handoffs


def assemble(inputs: dict[str, Any]) -> dict[str, Any]:
    computed = compute(inputs)
    rec = recommend(computed, inputs["deployment_target"])
    return {
        "schema_version": SCHEMA_VERSION,
        "disclaimer": "Planning estimate only; not a substitute for a Splunk "
        "Professional Services sizing.",
        "inputs": inputs,
        "computed": computed,
        "recommendation": rec,
        "targets": build_targets(computed),
        "handoffs": build_handoffs(rec["resolved_target"], computed),
    }


# --- Markdown report ----------------------------------------------------------


def hw_str(hw: dict[str, Any]) -> str:
    return f"{hw['vcpu']} vCPU / {hw['ram_gb']} GB RAM / ~{hw['iops']} IOPS"


def render_report(result: dict[str, Any]) -> str:
    c = result["computed"]
    rec = result["recommendation"]
    inp = result["inputs"]
    lines: list[str] = []
    lines.append("# Splunk Platform Sizing Recommendation")
    lines.append("")
    lines.append(f"> {result['disclaimer']}")
    lines.append("")
    lines.append("## Use case")
    lines.append("")
    lines.append(f"- Daily ingest: {inp['daily_ingest_gb']} GB/day")
    lines.append(f"- Growth headroom: {inp['growth_pct']}%")
    lines.append(f"- Effective ingest: {c['effective_daily_ingest_gb']} GB/day")
    lines.append(f"- Searchable retention: {inp['retention_days']} days")
    lines.append(f"- Workload profile: {inp['workload_profile']}")
    lines.append(f"- Search density: {inp['search_density']}")
    lines.append(f"- Concurrent searches: {c['concurrent_searches']}")
    lines.append(f"- High availability: {'yes' if inp['ha'] else 'no'}")
    lines.append(f"- SmartStore: {'yes' if inp['smartstore'] else 'no'}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append("")
    lines.append(f"- Requested target: `{rec['requested_target']}`")
    lines.append(f"- Resolved target: `{rec['resolved_target']}`")
    lines.append(f"- SVA category: {rec['sva_category']}")
    if "sok_architecture" in rec:
        lines.append(f"- SOK architecture: `{rec['sok_architecture']}`")
    if "pod_profile" in rec:
        lines.append(f"- Splunk POD profile: `{rec['pod_profile']}`")
    if "note" in rec:
        lines.append(f"- Note: {rec['note']}")
    lines.append("")
    lines.append("## Capacity math")
    lines.append("")
    lines.append(
        f"- Per-indexer ingest ceiling: {c['per_indexer_ceiling_gb']} GB/day "
        f"({inp['workload_profile']} profile, {inp['search_density']} density)"
    )
    lines.append(f"- Indexers (ingest-driven): {c['indexer_for_ingest']}")
    lines.append(f"- Indexers (recommended): {c['indexer_count']}")
    lines.append(
        f"- Replication factor / search factor: {c['replication_factor']} / "
        f"{c['search_factor']}"
    )
    lines.append(f"- Search heads: {c['search_head_count']}"
                 f" ({'SHC' if c['search_head_cluster'] else 'single'})")
    if c["dedicated_premium_search_heads"]:
        lines.append(
            "- Dedicated premium search heads: "
            + ", ".join(c["dedicated_premium_search_heads"])
        )
    lines.append(
        f"- Indexed/day after compression: {c['indexed_per_day_gb']} GB "
        f"(~{int(COMPRESSION_RATIO * 100)}% of ingest)"
    )
    lines.append(f"- Total cluster storage: {c['cluster_storage_gb']} GB")
    lines.append(f"- Storage per indexer: {c['per_indexer_storage_gb']} GB")
    if c["smartstore"]:
        lines.append(
            f"- SmartStore local cache per indexer (~30% guidance): "
            f"{c['smartstore_local_cache_gb']} GB (remote holds full retention)"
        )
    lines.append("")
    if not c["aio_eligible"]:
        lines.append("## All-In-One eligibility")
        lines.append("")
        lines.append("All-In-One (single instance) is **not** recommended:")
        for reason in c["aio_reasons"]:
            lines.append(f"- {reason}")
        lines.append("")
    lines.append("## Topology")
    lines.append("")
    lines.append("| Role | Count | Reference hardware |")
    lines.append("| --- | --- | --- |")
    for role in rec["topology"]["roles"]:
        hw = role.get("hardware")
        hw_text = hw_str(hw) if hw else "(managed)"
        lines.append(f"| {role['role']} | {role['count']} | {hw_text} |")
    lines.append("")
    lines.append("## Hand-offs")
    lines.append("")
    for handoff in result["handoffs"]:
        lines.append(f"- `{handoff['skill']}` - {handoff['why']}")
    lines.append("")
    return "\n".join(lines)


# --- CLI ----------------------------------------------------------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Splunk platform sizing engine (planning estimate)."
    )
    parser.add_argument("--daily-ingest-gb", type=float, required=True,
                        help="Daily ingest volume in GB/day.")
    parser.add_argument("--retention-days", type=int, default=90,
                        help="Searchable retention in days (default: 90).")
    parser.add_argument("--workload-profile", choices=WORKLOAD_CHOICES,
                        default="core",
                        help="core | es | itsi | es_itsi (default: core).")
    parser.add_argument("--search-density", choices=DENSITY_CHOICES,
                        default="medium",
                        help="light | medium | dense (default: medium).")
    parser.add_argument("--concurrent-searches", type=int, default=None,
                        help="Peak concurrent searches (overrides users).")
    parser.add_argument("--concurrent-users", type=int, default=None,
                        help="Concurrent users (estimates searches if set).")
    parser.add_argument("--ha", action="store_true",
                        help="Require high availability (clustering).")
    parser.add_argument("--replication-factor", type=int, default=None,
                        help="Indexer replication factor (clustered).")
    parser.add_argument("--search-factor", type=int, default=None,
                        help="Indexer search factor (clustered).")
    parser.add_argument("--multisite", action="store_true",
                        help="Multisite (geo-distributed) indexer cluster.")
    parser.add_argument("--sites", type=int, default=2,
                        help="Number of sites when --multisite (default: 2).")
    parser.add_argument("--smartstore", action="store_true",
                        help="Use SmartStore (remote object storage).")
    parser.add_argument("--growth-pct", type=float, default=15.0,
                        help="Growth headroom percent (default: 15).")
    parser.add_argument("--deployment-target", choices=TARGET_CHOICES,
                        default="auto",
                        help="auto|standalone|distributed|sok|pod|cloud.")
    parser.add_argument("--output-dir", default=None,
                        help="Directory for sizing-report.md and sizing.json.")
    parser.add_argument("--json", action="store_true",
                        help="Print the sizing JSON to stdout.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute and print, but write no files.")
    return parser.parse_args(argv)


def validate(args: argparse.Namespace) -> None:
    if not math.isfinite(args.daily_ingest_gb) or args.daily_ingest_gb <= 0:
        raise SystemExit("ERROR: --daily-ingest-gb must be greater than 0.")
    if args.retention_days < 1:
        raise SystemExit("ERROR: --retention-days must be at least 1.")
    if not math.isfinite(args.growth_pct) or args.growth_pct < 0:
        raise SystemExit("ERROR: --growth-pct must be a finite nonnegative number.")
    projected_daily = args.daily_ingest_gb * (1 + args.growth_pct / 100.0)
    if not math.isfinite(projected_daily):
        raise SystemExit("ERROR: daily ingest plus growth headroom exceeds the supported numeric range.")
    if args.sites < 1:
        raise SystemExit("ERROR: --sites must be at least 1.")
    if args.multisite and args.sites < 2:
        raise SystemExit("ERROR: --sites must be at least 2 with --multisite.")
    for name, value in (
        ("--replication-factor", args.replication_factor),
        ("--search-factor", args.search_factor),
        ("--concurrent-searches", args.concurrent_searches),
        ("--concurrent-users", args.concurrent_users),
    ):
        if value is not None and value < 1:
            raise SystemExit(f"ERROR: {name} must be at least 1.")
    factor_implies_ha = (args.replication_factor or 1) > 1 or (args.search_factor or 1) > 1
    effective_ha = args.ha or args.multisite or factor_implies_ha
    effective_rf = args.replication_factor or (3 if effective_ha else 1)
    effective_sf = args.search_factor or (2 if effective_ha else 1)
    if effective_sf > effective_rf:
        raise SystemExit(
            "ERROR: --search-factor cannot exceed --replication-factor "
            f"(effective values: SF={effective_sf}, RF={effective_rf})."
        )


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    validate(args)

    inputs = {
        "daily_ingest_gb": args.daily_ingest_gb,
        "retention_days": args.retention_days,
        "workload_profile": args.workload_profile,
        "search_density": args.search_density,
        "concurrent_searches": args.concurrent_searches,
        "concurrent_users": args.concurrent_users,
        "ha": (
            args.ha
            or args.multisite
            or (args.replication_factor or 1) > 1
            or (args.search_factor or 1) > 1
        ),
        "replication_factor": args.replication_factor,
        "search_factor": args.search_factor,
        "multisite": args.multisite,
        "sites": args.sites,
        "smartstore": args.smartstore,
        "growth_pct": args.growth_pct,
        "deployment_target": args.deployment_target,
    }

    result = assemble(inputs)

    # Hard gate: explicit standalone request that is not AIO-eligible.
    if (
        args.deployment_target == "standalone"
        and not result["computed"]["aio_eligible"]
    ):
        sys.stderr.write(
            "ERROR: All-In-One (standalone) is not viable for this use case:\n"
        )
        for reason in result["computed"]["aio_reasons"]:
            sys.stderr.write(f"  - {reason}\n")
        sys.stderr.write(
            "Use --deployment-target distributed (or sok/pod) instead.\n"
        )
        return 2

    report = render_report(result)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(report)

    if not args.dry_run:
        if not args.output_dir:
            raise SystemExit("ERROR: --output-dir is required unless --dry-run.")
        out = Path(args.output_dir).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        (out / "sizing.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
        (out / "sizing-report.md").write_text(report + "\n", encoding="utf-8")
        sys.stderr.write(f"Wrote {out / 'sizing-report.md'}\n")
        sys.stderr.write(f"Wrote {out / 'sizing.json'}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
