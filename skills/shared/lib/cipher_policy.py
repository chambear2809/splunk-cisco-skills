#!/usr/bin/env python3
"""Structured OpenSSL cipher-suite classification and policy enforcement.

Why this is structured parsing rather than substring matching
-------------------------------------------------------------
``algorithm-policy.json`` previously expressed its cipher guardrails as a
``forbidden_cipher_substrings`` list containing ``"CBC"``, ``"SHA1"``, and (in
the STIG preset) ``"SHA256"``. Every one of those three entries is wrong,
because OpenSSL cipher names do not spell out the properties they describe:

* CBC suites carry no ``CBC`` token. ``ECDHE-RSA-AES256-SHA384`` is CBC mode
  (``openssl ciphers -v`` reports ``Enc=AES(256)``), so a ``"CBC"`` substring
  never matches and the rule silently passes everything.
* SHA-1 suites are named ``-SHA``, never ``-SHA1``. ``ECDHE-RSA-AES128-SHA``
  is HMAC-SHA-1, so a ``"SHA1"`` substring never matches either.
* ``"SHA256"`` matches ``ECDHE-ECDSA-AES128-GCM-SHA256`` and
  ``TLS_AES_128_GCM_SHA256``, where the trailing hash is the PRF/KDF hash of
  an AEAD suite rather than an HMAC. The STIG preset therefore forbade its own
  rendered output.

Two of the rules could never fire and the third fired on the wrong thing. That
is not a matching bug that a more careful substring fixes; the property being
tested (block cipher mode, MAC algorithm) is simply not present in the name as
a literal. So the suite is decomposed into tokens and classified, and policies
are expressed against the classification. A future preset edit states intent
("no CBC") instead of restating a naming coincidence, which is what made the
original list quietly wrong.

Token comparison is exact, never substring. That is deliberate: substring
comparison is how ``SHA256`` matched ``SHA384``-era AEAD names in the first
place, and how ``DES`` would match a hypothetical future ``3DES``-like token
that is actually fine.
"""

from __future__ import annotations

from typing import Any, Iterable

# Presence of any of these tokens makes the suite AEAD. POLY1305 covers the
# CHACHA20-POLY1305 pairing, whose AEAD-ness lives in the second token.
_AEAD_TOKENS = frozenset({"GCM", "CCM", "CCM8", "POLY1305"})

# Trailing hash tokens. For an AEAD suite this is the PRF hash; for a non-AEAD
# suite it is the HMAC algorithm. Conflating the two is the original defect.
_HASH_TOKENS = frozenset({"SHA", "SHA256", "SHA384", "SHA512", "MD5"})

# OpenSSL spells SHA-1 as a bare "SHA".
_SHA1_TOKEN = "SHA"

_CIPHER_FIELDS = (
    "cipher_suite",
    "tls13_cipher_suite",
    "ldap_tls_cipher_suite",
)
_CIPHER_POLICY_BOOLEAN_FIELDS = (
    "require_aead",
    "forbid_cbc_mode",
    "forbid_sha1_mac",
)
_CIPHER_POLICY_REQUIRED_FIELDS = frozenset(
    (*_CIPHER_POLICY_BOOLEAN_FIELDS, "forbidden_tokens")
)


def split_cipher_list(value: str) -> list[str]:
    """Split a colon- or comma-delimited OpenSSL cipher list."""

    parts: list[str] = []
    for chunk in str(value or "").replace(",", ":").split(":"):
        name = chunk.strip()
        if name:
            parts.append(name)
    return parts


def parse_cipher_suite(name: str) -> dict[str, Any]:
    """Decompose one OpenSSL cipher-suite name into classified components."""

    raw = str(name or "").strip()
    if not raw:
        raise ValueError("empty cipher suite name")

    if raw.upper().startswith("TLS_"):
        # TLS 1.3 names are underscore-delimited and are AEAD by construction;
        # the ciphersuite registry defines no CBC or standalone-HMAC option.
        tokens = [tok for tok in raw.split("_")[1:] if tok]
        family = "tls1.3"
    else:
        tokens = [tok for tok in raw.split("-") if tok]
        family = "tls1.2"

    upper = [tok.upper() for tok in tokens]
    token_set = frozenset(upper)
    aead = bool(_AEAD_TOKENS & token_set) or family == "tls1.3"

    trailing = upper[-1] if upper and upper[-1] in _HASH_TOKENS else None
    prf = trailing if aead else None
    mac = None
    if not aead and trailing:
        mac = "SHA1" if trailing == _SHA1_TOKEN else trailing

    if "RC4" in token_set:
        mode = "stream"
    elif "NULL" in token_set:
        mode = "null"
    elif aead:
        mode = "aead"
    else:
        # Every non-AEAD, non-stream suite Splunk can negotiate is CBC.
        mode = "cbc"

    return {
        "name": raw,
        "family": family,
        "tokens": token_set,
        "aead": aead,
        "mode": mode,
        "mac": mac,
        "prf": prf,
    }


def check_cipher_list(
    cipher_list: str, cipher_policy: dict[str, Any] | None, *, label: str = "cipher_suite"
) -> list[str]:
    """Return a list of human-readable violations; empty means compliant."""

    if not cipher_policy:
        return []

    forbidden_tokens = {
        str(tok).upper() for tok in cipher_policy.get("forbidden_tokens", [])
    }
    require_aead = bool(cipher_policy.get("require_aead"))
    forbid_cbc = bool(cipher_policy.get("forbid_cbc_mode"))
    forbid_sha1 = bool(cipher_policy.get("forbid_sha1_mac"))

    violations: list[str] = []
    suites = split_cipher_list(cipher_list)
    if not suites:
        return [f"{label}: empty cipher list"]

    for name in suites:
        try:
            info = parse_cipher_suite(name)
        except ValueError as exc:
            violations.append(f"{label}: {exc}")
            continue

        hit = sorted(forbidden_tokens & info["tokens"])
        if hit:
            violations.append(
                f"{label}: {name} uses forbidden primitive(s) {', '.join(hit)}"
            )
        if require_aead and not info["aead"]:
            violations.append(
                f"{label}: {name} is not an AEAD suite "
                f"(mode={info['mode']}); this policy requires AEAD"
            )
        if forbid_cbc and info["mode"] == "cbc":
            violations.append(
                f"{label}: {name} is CBC mode; this policy forbids CBC. "
                "Note the name does not contain 'CBC' -- it is inferred from "
                "the absence of an AEAD token."
            )
        if forbid_sha1 and info["mac"] == "SHA1":
            violations.append(
                f"{label}: {name} uses HMAC-SHA-1 (spelled '-SHA'); "
                "this policy forbids SHA-1 MACs"
            )
    return violations


def check_signature_algorithms(
    allowed: Iterable[str] | None,
    forbidden: Iterable[str] | None,
    *,
    label: str = "allowed_signature_algorithms",
) -> list[str]:
    """Reject a preset whose allow-list overlaps its own forbid-list."""

    allow = {str(item).upper() for item in (allowed or [])}
    forbid = {str(item).upper() for item in (forbidden or [])}
    overlap = sorted(allow & forbid)
    if overlap:
        return [
            f"{label}: {', '.join(overlap)} appears in both the allowed and "
            "forbidden signature algorithm lists"
        ]
    return []


def check_cipher_policy_schema(
    cipher_policy: Any, *, label: str = "cipher_policy"
) -> list[str]:
    """Validate the fail-closed schema for one preset's cipher guardrails.

    Policy values come from operator-supplied JSON as well as the bundled
    document.  Truthiness coercion is unsafe here: an absent/empty block used to
    disable every cipher check, while a string such as ``"false"`` enabled a
    boolean rule.  Require the complete small schema so every relaxation is
    explicit and reviewable.
    """

    if not isinstance(cipher_policy, dict) or not cipher_policy:
        return [f"{label}: must be a non-empty object"]

    violations: list[str] = []
    missing = sorted(_CIPHER_POLICY_REQUIRED_FIELDS - cipher_policy.keys())
    if missing:
        violations.append(
            f"{label}: missing required field(s) {', '.join(missing)}"
        )

    for field in _CIPHER_POLICY_BOOLEAN_FIELDS:
        if field in cipher_policy and not isinstance(cipher_policy[field], bool):
            violations.append(f"{label}.{field}: must be a boolean")

    if "forbidden_tokens" in cipher_policy:
        tokens = cipher_policy["forbidden_tokens"]
        if not isinstance(tokens, list):
            violations.append(f"{label}.forbidden_tokens: must be an array")
        elif any(not isinstance(token, str) or not token.strip() for token in tokens):
            violations.append(
                f"{label}.forbidden_tokens: entries must be non-empty strings"
            )
    return violations


def check_preset(name: str, preset: dict[str, Any]) -> list[str]:
    """Validate one preset against its own declared guardrails.

    A preset that rejects its own rendered output is the failure mode this
    exists to prevent, so every cipher-bearing field is checked, not just the
    primary ``cipher_suite``.
    """

    violations: list[str] = []
    cipher_fields = [field for field in _CIPHER_FIELDS if preset.get(field)]
    policy = preset.get("cipher_policy")
    if cipher_fields:
        policy_violations = check_cipher_policy_schema(
            policy, label=f"{name}.cipher_policy"
        )
        violations.extend(policy_violations)
    else:
        policy_violations = []

    # Never pass a malformed policy into the rule evaluator.  Besides avoiding
    # an AttributeError traceback for a non-object value, this ensures schema
    # failure cannot be mistaken for successful cipher validation.
    for field in cipher_fields:
        value = preset.get(field)
        if not policy_violations:
            violations.extend(
                check_cipher_list(value, policy, label=f"{name}.{field}")
            )
    violations.extend(
        check_signature_algorithms(
            preset.get("allowed_signature_algorithms"),
            preset.get("forbidden_signature_algorithms"),
            label=f"{name}.allowed_signature_algorithms",
        )
    )
    return violations


def check_policy_document(policy: dict[str, Any]) -> list[str]:
    """Validate every preset in an algorithm-policy document."""

    violations: list[str] = []
    presets = policy.get("presets") or {}
    if not isinstance(presets, dict) or not presets:
        return ["algorithm policy contains no presets"]
    for name, preset in presets.items():
        if not isinstance(preset, dict):
            violations.append(f"{name}: preset must be an object")
            continue
        violations.extend(check_preset(str(name), preset))
    return violations
