# WAF / CDN Handoff Reference

The reverse proxy is the LAST line; the WAF / CDN is the FIRST line.
Configure both. Per-platform handoff documents are rendered into
`handoff/waf-cloudflare.md`, `handoff/waf-aws.md`, and
`handoff/waf-f5-imperva.md`. This file consolidates the cross-platform
decisions.

## Required controls (any platform)

1. **Managed WAF rule sets** — OWASP Core Rule Set 4.x or vendor
   equivalent, scored above the deny threshold for high-confidence
   matches.
2. **Per-IP rate limit** on `POST /en-US/account/login` — at most 5
   requests per minute per IP. Splunk has no CAPTCHA and per-user
   lockout is rotatable.
3. **Credential stuffing list** — vendor-managed.
4. **IP reputation** — block known threat IPs.
5. **Geo fence** — operator-defined; allowlist the countries where users
   live.
6. **Bot management** — allowlist HEC user-agents (see "HEC bot allow
   list" below).
7. **Body inspection allowance for HEC** — Cloudflare default 128 KB,
   AWS WAF default 8 KB. HEC batches go up to 800 MB. Without an
   exemption on `/services/collector*` HEC traffic is silently dropped.
8. **Cookie passthrough** — `splunkweb_csrf_token_*` MUST flow through
   to the browser. Without it, Splunk Web returns "CSRF validation
   failed".
9. **Read-timeout extension** — Splunk searches stream chunked for the
   entire search duration. Default 60-100s timeouts cause 524 / 504.

## HEC bot allow list

Allow these user-agent patterns (do NOT bot-block):

- `splunk-sdk-python/*`
- `splunk-sdk-java/*`
- `splunk-sdk-csharp/*`
- `splunk-sdk-javascript/*`
- `OpenTelemetry-collector-*`
- `splunk-otel-*`
- `Splunk-UF/*`
- `Splunk-HF/*`

Add any other automation that posts to `/services/collector`.

## CSRF token allow list

Cloudflare Page Rules and AWS CloudFront cache behaviors can scrub
cookies. `splunkweb_csrf_token_<port>` and the host-keyed variant must
NOT be in any "strip cookies" rule.

## return_to query parameter

CVE-2025-20379: an attacker could craft
`?return_to=https://attacker.example.com/` to redirect the user
post-login. The reverse proxy templates already deny absolute URLs, but
many WAFs ALSO can pre-screen. A custom rule:

```
URI = "/en-US/account/login"
QUERY_STRING contains "return_to=http"
ACTION: block
```

## Header-injection rule

CVE-2025-20384: an attacker injects `\r\n` into a header that ends up
in `web_access.log`. Block:

```
ANY header value matches regex: [\r\n]
ACTION: block (400)
```

## Splunk-specific WAF gotchas

| Behavior | Vendor | Mitigation |
|---|---|---|
| Bot Fight Mode blocks Splunk SDK | Cloudflare | Allowlist SDK UAs on HEC |
| AWS WAF default 8 KB body inspect | AWS | Exempt `/services/collector*` |
| Cloudflare 100s timeout | Cloudflare Free/Pro | Use Enterprise plan |
| ALB 60s idle timeout | AWS | Raise to 600s+ |
| F5 ASM Splunk template | F5 | Use if available; otherwise OWASP Top 10 |
| Imperva default rate-limit | Imperva | Custom rule for /login |
| Page-rule cookie scrub | Cloudflare | Allowlist splunkweb_csrf_token_* |

## Choosing a CDN

| Need | Choice |
|---|---|
| Free tier acceptable | Cloudflare Free (no Enterprise features) |
| Long search timeouts | Cloudflare Enterprise |
| Native AWS integration | CloudFront + AWS WAF |
| On-prem appliance | F5 BIG-IP ASM, Imperva |
| Multi-cloud | Akamai, Fastly |

## What the CDN cannot help with

- Splunk's per-user (not per-IP) lockout.
- Splunk's lack of native CAPTCHA.
- Splunk's `enableSplunkWebClientNetloc` SSRF.
- Splunkd 8089 exposure (the CDN is HTTP-only; lock 8089 at the host
  firewall).

These all require the Splunk-side configuration that the renderer
emits.
