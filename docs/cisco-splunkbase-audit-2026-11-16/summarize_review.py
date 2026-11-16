#!/usr/bin/env python3
"""Build a compact package/skill coverage projection from retained live sources."""

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]


def read(path):
    return json.loads(path.read_text())


def cell(value):
    return (
        str(value if value is not None else "unavailable")
        .replace("|", "/")
        .replace("\n", " ")
    )


def main():
    discovery = read(ROOT / "inventory.json")
    registry = {
        str(a.get("splunkbase_id")): a
        for a in read(REPO / "skills/shared/app_registry.json")["apps"]
    }
    routes = {
        p["id"]: p
        for p in read(REPO / "skills/cisco-product-setup/catalog.json")["products"]
    }
    packages = read(REPO / "docs/cisco-package-evidence-2026-11-16.json")["packages"]
    unrelated = {
        "5357": "uberAgent ESA is not Cisco ESA",
        "6590": "uberAgent ESA companion is not Cisco ESA",
        "6808": "ESET endpoint security is not Cisco Secure Endpoint",
    }
    use_cases = {
        "1711": (
            "cisco-meraki-ta-setup",
            "Meraki telemetry is covered; the legacy presence-specific collector requires independent API and privacy qualification.",
        ),
        "5116": (
            "cisco-secure-email-web-gateway-setup",
            "ESA transport/parsing is covered; MIME decoding/search commands remain a distinct unowned extension.",
        ),
        "5543": (
            "cisco-security-cloud-setup",
            "Firepower/FTD API, eStreamer and syslog use cases exist; this CCX package is not an approved replacement.",
        ),
        "5743": (
            "cisco-product-setup",
            "The product router covers multiple Cisco families; this separate suite has no reviewed multi-package deployment or dashboard contract.",
        ),
        "5746": (
            "cisco-appdynamics-setup",
            "Controller/Analytics collection overlaps; JDS input and index contracts require separate review.",
        ),
        "6398": (
            "cisco-security-cloud-setup",
            "Secure Network Analytics collection exists; this separate visualization app needs sourcetype/macro and licensing qualification.",
        ),
        "6460": (
            "cisco-catalyst-ta-setup",
            "ISE API/syslog use cases are covered through another package; CCX parser and input equivalence is unverified.",
        ),
        "6481": (
            "cisco-security-cloud-setup",
            "Secure Endpoint API collection exists; this CCX package is not configured by that workflow.",
        ),
        "6544": (
            "cisco-security-cloud-setup",
            "Duo collection exists; this CCX connector and its support/licensing remain separate.",
        ),
        "7548": (
            "cisco-catalyst-ta-setup",
            "ISE telemetry collection exists; outbound MAC-blocking response is a distinct unowned mutation workflow.",
        ),
        "7581": (
            "splunk-itsi-config",
            "Catalyst telemetry and ITSI service/KPI modeling exist; Atlas content-pack import and model mapping need separate qualification.",
        ),
        "8358": (
            "cisco-webex-setup",
            "Webex event collection exists; sending alert-action messages is a distinct unowned outbound integration.",
        ),
        "8429": (
            "cisco-webex-setup",
            "Webex collection exists; this Sideview app is a separate entitlement/dependency contract, not automatically selected.",
        ),
        "10065": (
            "cisco-webex-setup",
            "Webex collection exists; this Sideview add-on is a separate entitlement/dependency contract, not automatically selected.",
        ),
        "8702": (
            "cisco-meraki-ta-setup",
            "Meraki collection and CIM readiness exist; this CIM overlay needs field/tag/model and parser-overlap review.",
        ),
        "9257": (
            "splunk-app-install",
            "Generic package handoff only. Secure Networking Essentials has no first-class ingest, dependency, dashboard or migration workflow here; its exact package remains uninspected.",
        ),
        "10081": (
            "cisco-security-cloud-setup",
            "FMC/eStreamer collection exists; the separately published receiver/parser is not automatically substituted.",
        ),
        "10276": (
            "cisco-security-cloud-setup",
            "Secure Endpoint events overlap; this package's audit-log coverage and credentials need independent qualification.",
        ),
        "10286": (
            "cisco-asa-ta-setup",
            "ASA/FTD syslog parsing exists, with a separate Security Cloud route; do not co-enable overlapping field-extraction packages without precedence review.",
        ),
        "10306": (
            "cisco-security-cloud-setup",
            "FMC/FTD API and syslog paths are adjacent; this exact FMC audit/syslog parsing contract is not configured by the existing workflow.",
        ),
    }
    relations = {}
    companions = {
        "7538": [
            ("7539", "visualization companion"),
            ("6872", "optional NetFlow mapping companion"),
        ],
        "7539": [
            ("7538", "required collection/normalization companion"),
            ("6872", "optional NetFlow mapping companion"),
        ],
        "6872": [
            ("7538", "shared product guide and collection health"),
            ("7539", "optional visualization consumer"),
        ],
        "7569": [("5558", "visualization/settings companion")],
        "5558": [("7569", "event collection companion")],
        "8365": [("4992", "visualization companion")],
        "4992": [("8365", "customer-managed collection companion; Enterprise-only")],
        "4221": [("2992", "CESA visualization companion")],
        "2992": [("4221", "CESA parser and external nvzFlow collector bundle")],
        "5748": [("5747", "Cyber Vision visualization companion")],
        "5747": [
            ("5748", "Cyber Vision collection companion; platform range stops at 10.4")
        ],
    }
    for aid, pairs in companions.items():
        relations[aid] = [
            {
                "product": f"Splunkbase {target}",
                "related_splunkbase_id": target,
                "relationship": kind,
                "use_case_skill": registry.get(aid, {}).get("skill"),
                "source": "dated package review; not an inferred install_requires dependency",
            }
            for target, kind in pairs
        ]
    for aid in ("1809", "5238", "5234"):
        relations[aid] = [
            {
                "product": "Cisco NetFlow/IPFIX receiver path",
                "relationship": "optional Stream collection dependency",
                "use_case_skill": "splunk-stream-setup",
            }
        ]
    for product in read(REPO / "skills/cisco-product-setup/scan_products.fixture.json")[
        "products"
    ]:
        for key in (
            "addon_uid",
            "app_viz_uid",
            "app_viz_2_uid",
            "legacy_uids",
            "community_uids",
            "soar_connector_uids",
            "alert_action_uids",
        ):
            for aid in re.findall(r"\d+", str(product.get(key, ""))):
                relation = {
                    "product": product.get("display_name"),
                    "relationship": key,
                    "use_case_skill": routes.get(product.get("id"), {}).get(
                        "primary_skill"
                    ),
                }
                if relation not in relations.setdefault(aid, []):
                    relations[aid].append(relation)
    words = re.compile(
        r"\b(cisco|meraki|webex|appdynamics|intersight|nexus|aci|apic|ucs|thousandeyes|secure access|spaces|cyber vision|endpoint security|catalyst|asa|ise|esa|wsa|stealthwatch)\b",
        re.I,
    )
    result = []
    for item in discovery["results"]:
        aid = str(item["id"])
        if aid in unrelated:
            continue
        d = item["listing"]
        title = d.get("title") or d.get("name") or "unavailable"
        reg = registry.get(aid)
        if not (
            words.search(title + " " + item.get("search_description", ""))
            or aid in relations
            or reg
            and str(reg.get("skill", "")).startswith("cisco-")
        ):
            continue
        default = d.get("release_default") or {}
        api_file = (
            ROOT
            / "raw"
            / f"api_https_splunkbase_splunk_com_api_v1_app_{aid}_release_{default.get('id')}.json"
        )
        api = read(api_file) if api_file.exists() else {}
        listing_versions = [
            v.get("versionString") for v in d.get("version_compatibility", [])
        ]
        comparison = (
            "matched"
            if (
                api
                and str(api.get("app")) == aid
                and api.get("name") == default.get("version")
                and str(api.get("published_datetime") or "")[:10]
                == str(default.get("published") or "")[:10]
                and api.get("product_versions") == listing_versions
            )
            else "unavailable or inconsistent; do not approve from metadata"
        )
        versions = api.get("product_versions") or [
            v.get("versionString") for v in d.get("version_compatibility", [])
        ]
        newer = [
            {k: p.get(k) for k in ("version", "published")}
            for p in d.get("releases_parallel", [])
            if str(p.get("published") or "") > str(default.get("published") or "")
        ]
        inspected = [p for p in packages if p["splunkbase_id"] == aid]
        if reg:
            disposition = "Exact registry workflow. Complete ingest/dashboard gates; retain documented holds when selected pin differs from default."
        elif aid in relations:
            disposition = "Existing product use-case route; exact package unapproved. Review collector/parser overlap, placement, license, and dashboards before selecting this alternative."
        else:
            disposition = "Distinct package workflow gap: inspect package/collector, placement, license, ingest and dashboard contract before automation."
        if aid in {"669", "4434", "4640", "8413", "8592", "8593"}:
            disposition = "Sideview third-party package: cisco-collaboration-setup offers evidence-only selection; exact version, tier, license and receiver gates apply."
        if aid in {"4221", "2992"}:
            disposition = "Cisco-authored CESA, not_supported. Endpoint license/SEULA and external nvzFlow collector qualification required; Security Cloud NVM overlap does not establish equivalence."
        if aid in {"5748", "5747"}:
            disposition = "Cisco-authored Cyber Vision, developer support. Separate add-on/app pair; add-on compatibility stops at 10.4. Existing Catalyst flow has a different package contract."
        if aid == "1915":
            disposition = "Splunk-developed ISE parser; existing Catalyst ISE API/parser route is a different package. Separate parser/transport, CIM and migration qualification needed."
        if aid in use_cases:
            owner, boundary = use_cases[aid]
            disposition = f"Use-case scope: {owner}. {boundary} Exact package is unapproved; no automated install/configuration is claimed."
        result.append(
            dict(
                splunkbase_id=aid,
                listing_url=item["listing_url"],
                title=title,
                publisher=(d.get("display_author") or {}).get("name"),
                support=d.get("support"),
                package_type=d.get("app_type"),
                license=d.get("license"),
                listing_default_version=default.get("version"),
                listing_default_date=default.get("published"),
                release_api_url=f"https://splunkbase.splunk.com/api/v1/app/{aid}/release/{default.get('id')}/"
                if default.get("id")
                else None,
                release_api_crosscheck=comparison,
                enterprise_advertised="enterprise"
                in (default.get("product_types") or d.get("product_types") or []),
                cloud_advertised=api.get(
                    "cloud_compatible", default.get("cloud", d.get("cloud_compatible"))
                ),
                platform_versions=versions,
                newer_parallel_releases=newer,
                registry_entry={
                    k: reg[k]
                    for k in (
                        "skill",
                        "app_name",
                        "splunkbase_id",
                        "latest_verified_version",
                        "relationship",
                        "install_requires",
                    )
                    if k in reg
                }
                if reg
                else None,
                relationships=relations.get(aid, []),
                inspected_packages=[
                    {
                        k: p[k]
                        for k in (
                            "package_version",
                            "binary_sha256",
                            "evidence_reports",
                        )
                    }
                    for p in inspected
                ],
                disposition=disposition,
            )
        )
    payload = {
        "date": "2026-11-16",
        "candidate_count": len(discovery["results"]),
        "covered_count": len(result),
        "coverage_rule": "Whole product words, catalog package relationships, or exact Cisco skill registry entries; source metadata alone does not establish publisher ownership or package approval.",
        "packages": result,
        "explicit_product_collisions": unrelated,
    }
    (ROOT / "coverage.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    )
    lines = [
        "# Package and workflow coverage — 2026-11-16",
        "",
        "See [method and limits](README.md), [implementation decisions](../cisco-splunkbase-audit-results-2026-11-16.md), [complete structured inventory](coverage.json), and [binary evidence](../cisco-package-evidence-2026-11-16.json).",
        "",
        f"{len(result)} package/relationship rows from {len(discovery['results'])} discovered candidates. Exact release API identity, dates, compatibility and support remain separate from static package review. All fields, licenses, companion/dependency relationships, source URLs and newer parallel releases are retained in coverage.json.",
        "",
        "| ID / listing | Publisher; support; type | Default / date; newer parallel | Enterprise / Cloud; versions | Registry skill / selected; inspected | Relationship and disposition |",
        "|---|---|---|---|---|---|",
    ]
    for p in result:
        reg = p["registry_entry"] or {}
        relation = "; ".join(
            sorted(
                {
                    str(r["product"]) + " (" + r["relationship"] + ")"
                    for r in p["relationships"]
                }
            )
        )
        values = [
            f"[{p['splunkbase_id']} — {cell(p['title'])}]({p['listing_url']})",
            f"{p['publisher']}; {p['support']}; {p['package_type']}",
            f"{p['listing_default_version']} / {str(p['listing_default_date'] or '')[:10]}; newer: {','.join(str(x['version']) for x in p['newer_parallel_releases']) or 'none'}",
            f"Enterprise={p['enterprise_advertised']}; Cloud={p['cloud_advertised']}; {','.join(p['platform_versions'])}",
            f"{reg.get('skill', 'no exact registry entry')} / {reg.get('latest_verified_version', 'none')}; inspected: {','.join(x['package_version'] for x in p['inspected_packages']) or 'unreviewed'}",
            relation + "; " + p["disposition"],
        ]
        lines.append("| " + " | ".join(cell(x) for x in values) + " |")
    (ROOT / "coverage.md").write_text("\n".join(lines) + "\n")
    print(
        "Coverage rows",
        len(result),
        "bytes",
        (ROOT / "coverage.json").stat().st_size,
        "release identity checks",
        sum(p["release_api_crosscheck"] == "matched" for p in result),
    )


if __name__ == "__main__":
    main()
