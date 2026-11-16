#!/usr/bin/env python3
"""Read-only Splunkbase Cisco discovery (listing API + rendered metadata)."""

import json
import re
import time
import hashlib
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).parent
RAW = ROOT / "raw"
RAW.mkdir(parents=True, exist_ok=True)
UA = "Mozilla/5.0 (Splunk Cisco Skills audit; read-only)"
REGISTRY = {
    str(x.get("splunkbase_id")): x
    for x in json.loads(Path("skills/shared/app_registry.json").read_text()).get(
        "apps", []
    )
}


def get_json(url):
    p = RAW / ("api_" + re.sub(r"[^A-Za-z0-9]+", "_", url).strip("_") + ".json")
    if p.exists():
        return json.loads(p.read_text())
    with urlopen(Request(url, headers={"User-Agent": UA}), timeout=30) as r:
        data = r.read()
    parsed = json.loads(data)
    if (
        isinstance(parsed, dict)
        and "authorization" in str(parsed.get("troubleshooting", "")).lower()
    ):
        parsed["troubleshooting"] = (
            "[Vendor curl authorization examples omitted; consult the live listing.]"
        )
        parsed["_retention"] = {
            "source_url": url,
            "source_payload_sha256": hashlib.sha256(data).hexdigest(),
            "omitted_fields": ["troubleshooting"],
            "reason": "Retain metadata without credential-shaped vendor examples.",
        }
        data = (json.dumps(parsed, sort_keys=True) + "\n").encode()
    p.write_bytes(data)
    return parsed


def get_release(app_id, release_id):
    if not release_id:
        return None
    return get_json(
        f"https://splunkbase.splunk.com/api/v1/app/{app_id}/release/{release_id}/"
    )


def get_html(app_id):
    p = RAW / f"listing_{app_id}.json"
    u = f"https://splunkbase.splunk.com/app/{app_id}/"
    with urlopen(Request(u, headers={"User-Agent": UA}), timeout=30) as r:
        b = r.read()
    s = b.decode("utf-8", "replace")
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', s
    )
    d = json.loads(m.group(1))["props"]["pageProps"]["appDetails"] if m else {}
    # Keep only structured listing facts; raw HTML is deliberately not retained.
    p.write_text(json.dumps(d, sort_keys=True))
    return d


terms = [
    "cisco",
    "nexus",
    "aci",
    "apic",
    "ucs",
    "intersight",
    "webex",
    "appdynamics",
    "cyber vision",
    "endpoint security",
    "secure access",
    "meraki",
    "spaces",
    "thousandeyes",
    "catalyst",
    "asa",
    "ise",
    "esa",
    "wsa",
]
found = {}
search_log = []
for term in terms:
    first = get_json(
        "https://splunkbase.splunk.com/api/v2/apps/?"
        + urlencode({"query": term, "page": 1})
    )
    pages = max(
        1,
        (first.get("total", 0) + first.get("limit", 20) - 1) // first.get("limit", 20),
    )
    offsets = []
    for page in range(1, pages + 1):
        d = (
            first
            if page == 1
            else get_json(
                "https://splunkbase.splunk.com/api/v2/apps/?"
                + urlencode({"query": term, "page": page})
            )
        )
        offsets.append(d.get("offset"))
        for x in d.get("results", []):
            found[str(x["id"])] = x
        if not d.get("results"):
            break
    time.sleep(0.05)
    search_log.append(
        {
            "filter": "query",
            "value": term,
            "total": first.get("total"),
            "limit": first.get("limit"),
            "pages": pages,
            "offsets": offsets,
        }
    )
# Cisco publisher filter is a separate, explicit coverage input.
for page in range(1, 10):
    d = get_json(
        "https://splunkbase.splunk.com/api/v2/apps/?"
        + urlencode({"author": "cisco", "page": page})
    )
    for x in d.get("results", []):
        found[str(x["id"])] = x
    if len(found) >= d.get("total", 0) and page * d.get("limit", 20) >= d.get(
        "total", 0
    ):
        break
    if not d.get("results"):
        break
    search_log.append(
        {
            "filter": "author",
            "value": "cisco",
            "page": page,
            "offset": d.get("offset"),
            "total": d.get("total"),
            "returned": len(d.get("results", [])),
        }
    )
# Seed IDs explicitly named by the repository/user so keyword ranking cannot hide them.
for aid in [
    1620,
    1747,
    1761,
    2731,
    2992,
    4221,
    4992,
    5558,
    5580,
    5747,
    5748,
    6460,
    6872,
    7404,
    7538,
    7539,
    7569,
    7719,
    7777,
    7828,
    8358,
    8365,
    8413,
    8485,
]:
    u = f"https://splunkbase.splunk.com/api/v2/apps/{aid}/"
    try:
        d = get_json(u)
        found[str(aid)] = d
    except Exception:
        pass

out = []
for aid, summary in sorted(found.items(), key=lambda kv: int(kv[0])):
    detail = get_html(aid)

    def rel(r):
        if not r:
            return None
        man = r.get("manifest") or {}
        info = man.get("info") or {}
        ident = info.get("id") or {}
        return {
            "id": r.get("id"),
            "version": r.get("name") or ident.get("version"),
            "release_date": info.get("releaseDate"),
            "published": r.get("publishedDatetime"),
            "download": r.get("path"),
            "sha256_listing": r.get("sha256"),
            "md5": r.get("md5"),
            "cloud": r.get("cloudCompatible"),
            "product_types": r.get("productTypes"),
            "platform_requirements": man.get("platformRequirements"),
            "dependencies": man.get("dependencies"),
            "content": r.get("content"),
            "filename": r.get("filename"),
        }

    default = rel(detail.get("release"))
    release_api = get_release(aid, default.get("id") if default else None)
    api_compact = (
        {
            k: release_api.get(k)
            for k in (
                "id",
                "app",
                "name",
                "published_time",
                "release_date",
                "cloud_compatible",
                "product_types",
                "spl_compatibility",
            )
        }
        if release_api
        else None
    )
    parallel = [rel(r) for r in detail.get("releases", [])]
    parallel_summary = [
        {
            k: r.get(k)
            for k in (
                "id",
                "version",
                "release_date",
                "published",
                "cloud",
                "product_types",
                "download",
            )
        }
        for r in parallel
    ]
    compact = {
        "id": detail.get("id"),
        "title": detail.get("title"),
        "name": detail.get("name"),
        "display_author": detail.get("displayAuthor"),
        "show_as_built_by": detail.get("showAsBuiltBy"),
        "support": detail.get("support"),
        "is_splunk_built": detail.get("isSplunkBuilt"),
        "app_type": detail.get("appType"),
        "product_types": detail.get("productTypes"),
        "product_compatibility": detail.get("productCompatibility"),
        "cloud_compatible": detail.get("cloudCompatible"),
        "license": detail.get("license"),
        "license_ack_required": detail.get("licenseAgreementReadRequired"),
        "published": detail.get("publishedDatetime"),
        "updated": detail.get("updatedTime"),
        "repo_name": detail.get("repoName"),
        "repo_url": detail.get("repoUrl"),
        "release_default": default,
        "release_api": api_compact,
        "version_compatibility": (detail.get("release") or {}).get(
            "versionCompatibility", []
        ),
        "releases_parallel": parallel_summary,
        "listing_source_sha256": hashlib.sha256(
            json.dumps(detail, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    # Replace the cached listing payload with the compact review record.
    (RAW / f"listing_{aid}.json").write_text(json.dumps(compact, sort_keys=True))
    rr = REGISTRY.get(str(aid))
    registry = {
        k: rr.get(k)
        for k in (
            "skill",
            "latest_verified_version",
            "latest_release_version",
            "compatibility_status",
            "relationships",
        )
        if rr and rr.get(k) is not None
    }
    out.append(
        {
            "id": int(aid),
            "listing_url": f"https://splunkbase.splunk.com/app/{aid}/",
            "api_url": f"https://splunkbase.splunk.com/api/v2/apps/?id={aid}",
            "search_description": (summary.get("description") or "")[:180],
            "registry": registry,
            "listing": compact,
        }
    )
    time.sleep(0.03)
(ROOT / "inventory.json").write_text(
    json.dumps(
        {
            "generated_utc": "2026-11-16",
            "terms": terms,
            "publisher_filter": "author=cisco",
            "search_log": search_log,
            "publisher_variations": [
                "cisco",
                "Cisco Systems",
                "Cisco Systems Inc",
                "Cisco ThousandEyes Inc",
                "Splunk Works",
            ],
            "results": out,
        },
        indent=2,
        sort_keys=True,
    )
    + "\n"
)
print(f"found {len(out)} unique listings")
