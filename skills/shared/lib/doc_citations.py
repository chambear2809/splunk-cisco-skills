#!/usr/bin/env python3
"""Validate that a reference document still cites the sources its claims need.

Why this is not a slug allow-list
---------------------------------
The obvious way to test "does ``authoritative-sources.md`` still cite the KV
Store certificate page" is to assert that some vendor URL slug appears in the
file. That is what this repository did, in two places, and it broke twice in a
single review session: Splunk is mid-migration from ``docs.splunk.com`` to
``help.splunk.com``, and the same page moved from ``CustomCertsKVstore`` to
``preparing-custom-certificates-for-use-with-kv-store``. Nothing was wrong with
the document either time. The test was re-encoding a string the vendor owns and
we do not, so a vendor-side rename presented as a local test failure.

Deleting the assertions would trade that fragility for blindness, because the
slug check is also what catches a citation pointing at the wrong page. So the
check is split into the part we own and the part the vendor owns:

* **Link title** -- authored here, stable across vendor migrations, and the
  thing that actually identifies *which claim* is being supported. Matching on
  the title means a migration is a one-line URL edit in the markdown, with no
  test change at all.
* **URL topic token** -- a normalised fragment of the vendor's slug that
  survives renaming, checked only to confirm the URL is plausibly the page the
  title promises. Normalisation strips case and separators, so
  ``CustomCertsKVstore`` and ``preparing-custom-certificates-for-use-with-kv-store``
  both contain ``kvstore``. Vendors keep the topic noun in the slug for search
  reasons even when they restructure everything around it, which is what makes
  this durable rather than merely looser.
* **Host allow-list** -- catches a citation repointed at a blog or an
  unrelated domain, which neither of the above would notice.

The residual gap is a vendor page that keeps its topic noun while materially
changing what it says. No string check can catch that; the ``Last reviewed``
date and a human re-read are the control for it, and liveness belongs to the
scheduled repository-wide documentation citation audit rather than to a unit
test.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Markdown inline links: [title](url). Titles here never contain nested
# brackets, so the simple negated class is sufficient and avoids a catastrophic
# backtracking pattern on long reference files.
_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def normalize(value: str) -> str:
    """Case- and separator-insensitive form used for all comparisons.

    Collapsing ``-``, ``_``, spaces, and punctuation is the whole trick: it is
    what lets one token match a slug both before and after the vendor switches
    between CamelCase and kebab-case.
    """

    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def extract_links(markdown: str) -> list[tuple[str, str]]:
    """Return every ``(title, url)`` inline markdown link, in document order."""

    return [(title.strip(), url.strip()) for title, url in _LINK_RE.findall(markdown)]


def check_citations(
    markdown: str, manifest: dict[str, Any], *, label: str = "document"
) -> list[str]:
    """Return human-readable violations; empty means the contract is satisfied."""

    violations: list[str] = []
    required = manifest.get("required_citations")
    if not isinstance(required, list) or not required:
        return [f"{label}: manifest declares no required_citations"]

    allowed_hosts = {
        str(h).lower() for h in manifest.get("allowed_hosts", []) if str(h).strip()
    }
    links = extract_links(markdown)
    if not links:
        return [f"{label}: no markdown links found"]

    seen_ids: set[str] = set()
    for entry in required:
        if not isinstance(entry, dict):
            violations.append(f"{label}: required_citations entry must be an object")
            continue

        cid = str(entry.get("id") or "").strip()
        if not cid:
            violations.append(f"{label}: required_citations entry is missing an id")
            continue
        if cid in seen_ids:
            violations.append(f"{label}: duplicate citation id {cid!r}")
            continue
        seen_ids.add(cid)

        title_contains = str(entry.get("title_contains") or "").strip()
        if not title_contains:
            violations.append(f"{cid}: manifest entry is missing title_contains")
            continue

        needle = normalize(title_contains)
        matches = [(t, u) for t, u in links if needle in normalize(t)]

        if not matches:
            violations.append(
                f"{cid}: no link titled like {title_contains!r} in {label}. "
                "The claim this supports lost its citation, or the link title "
                "was reworded -- update title_contains in the manifest if the "
                "rewording was intentional."
            )
            continue
        if len(matches) > 1:
            # Ambiguity means the contract is no longer pinning one page, so a
            # later edit could silently satisfy it with the wrong citation.
            titles = ", ".join(repr(t) for t, _ in matches)
            violations.append(
                f"{cid}: title_contains {title_contains!r} matches "
                f"{len(matches)} links ({titles}); make it more specific"
            )
            continue

        title, url = matches[0]
        host = (urlparse(url).hostname or "").lower()
        if allowed_hosts and host not in allowed_hosts:
            violations.append(
                f"{cid}: {title!r} cites host {host!r}, which is not in the "
                f"allowed vendor host list ({', '.join(sorted(allowed_hosts))})"
            )

        tokens = [str(t) for t in entry.get("url_topic_tokens", []) if str(t).strip()]
        if tokens:
            normalized_url = normalize(url)
            if not any(normalize(tok) in normalized_url for tok in tokens):
                violations.append(
                    f"{cid}: {title!r} points at {url} , which contains none of "
                    f"the expected topic tokens {tokens}. Either the citation "
                    "now points at the wrong page, or the vendor renamed the "
                    "page beyond recognition -- confirm the page still says "
                    "what the claim assumes, then update url_topic_tokens."
                )

    return violations


def load_and_check(markdown_path: Path, manifest_path: Path) -> list[str]:
    """Validate ``markdown_path`` against the contract in ``manifest_path``."""

    if not markdown_path.is_file():
        return [f"missing reference document: {markdown_path}"]
    if not manifest_path.is_file():
        return [f"missing citation manifest: {manifest_path}"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{manifest_path.name}: invalid JSON ({exc})"]
    return check_citations(
        markdown_path.read_text(encoding="utf-8"), manifest, label=markdown_path.name
    )


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            "usage: doc_citations.py <reference.md> <required-citations.json>",
            file=sys.stderr,
        )
        return 2
    violations = load_and_check(Path(argv[1]), Path(argv[2]))
    for violation in violations:
        print(f"ERROR: {violation}", file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
