#!/usr/bin/env python3
"""Cross-check observed publisher accounts and explicit Stream dependencies."""

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
UA = "splunk-cisco-skills/read-only-cisco-audit"
AUTHORS = [
    "cisco",
    "nvzFlow",
    "cisco-cybervision-splunk@cisco.com",
    "Cisco Systems",
    "Cisco Systems Inc",
    "Cisco ThousandEyes Inc",
    "splunklabs",
    "svc-sfs-splunk.gen@cisco.com",
]


def fetch(url):
    with urlopen(Request(url, headers={"User-Agent": UA}), timeout=30) as response:
        body = response.read()
    name = "api_" + re.sub(r"[^A-Za-z0-9]+", "_", url).strip("_") + ".json"
    (ROOT / "raw" / name).write_bytes(body)
    return json.loads(body)


def main():
    path = ROOT / "inventory.json"
    data = json.loads(path.read_text())
    found = {str(x["id"]): x for x in data["results"]}
    candidates = {}
    logs = []
    pattern = re.compile(
        r"\b(cisco|meraki|webex|appdynamics|nexus|intersight|thousandeyes|cyber vision)\b",
        re.I,
    )
    for author in AUTHORS:
        page, count, total, offsets = 1, 0, None, []
        while total is None or count < total:
            response = fetch(
                "https://splunkbase.splunk.com/api/v2/apps/?"
                + urlencode({"author": author, "page": page})
            )
            total = response["total"]
            offset = response["offset"]
            if offset in offsets:
                raise RuntimeError(f"Repeated publisher page offset for {author}")
            offsets.append(offset)
            results = response["results"]
            count += len(results)
            for item in results:
                if pattern.search(
                    item.get("app_name", "") + " " + item.get("description", "")
                ):
                    candidates[str(item["id"])] = item
            if not results:
                break
            page += 1
        logs.append(
            {
                "filter": "author",
                "value": author,
                "total": total,
                "returned": count,
                "offsets": offsets,
            }
        )
    for aid in (1809, 5238, 5234):
        candidates[str(aid)] = fetch(
            f"https://splunkbase.splunk.com/api/v2/apps/{aid}/"
        )
    for aid, summary in candidates.items():
        if aid in found:
            continue
        url = f"https://splunkbase.splunk.com/app/{aid}/"
        with urlopen(Request(url, headers={"User-Agent": UA}), timeout=30) as response:
            html = response.read()
        match = re.search(
            rb'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S
        )
        details = json.loads(match[1])["props"]["pageProps"]["appDetails"]
        release = details.get("release") or {}
        api = (
            fetch(
                f"https://splunkbase.splunk.com/api/v1/app/{aid}/release/{release['id']}/"
            )
            if release
            else {}
        )
        normalized = {
            "id": details.get("id"),
            "title": details.get("name"),
            "name": details.get("name"),
            "display_author": details.get("displayAuthor"),
            "support": details.get("support"),
            "app_type": details.get("appType"),
            "license": details.get("license"),
            "product_types": details.get("productTypes"),
            "cloud_compatible": details.get("cloudCompatible"),
            "version_compatibility": release.get("versionCompatibility", []),
            "listing_source_sha256": hashlib.sha256(
                json.dumps(details, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "release_api": api,
            "release_default": {
                "id": release.get("id"),
                "version": release.get("name"),
                "published": release.get("publishedDatetime"),
                "filename": release.get("filename"),
                "product_types": release.get("productTypes"),
                "cloud": release.get("cloudCompatible"),
            },
            "releases_parallel": [
                {
                    "id": r.get("id"),
                    "version": r.get("name"),
                    "published": r.get("publishedDatetime"),
                }
                for r in details.get("releases", [])
            ],
        }
        (ROOT / "raw" / f"listing_{aid}.json").write_text(
            json.dumps(normalized, sort_keys=True) + "\n"
        )
        found[aid] = {
            "id": int(aid),
            "listing_url": url,
            "listing": normalized,
            "search_description": summary.get("description", "")[:180],
        }
    data["publisher_account_crosschecks"] = logs
    data["dependency_seeds"] = [1809, 5238, 5234]
    data["results"] = sorted(found.values(), key=lambda x: x["id"])
    path.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    )
    print(
        "Publisher accounts",
        len(logs),
        "candidates",
        len(found),
        "index bytes",
        path.stat().st_size,
    )


if __name__ == "__main__":
    main()
