# Reverse Proxy Templates Reference

The skill renders production-ready nginx and HAProxy vhosts for both
Splunk Web and HEC under `proxy/nginx/` and `proxy/haproxy/`. This
document explains the non-obvious decisions in each template so the
operator can adapt them safely.

## Why the proxy is mandatory for public exposure

Splunk Enterprise has no built-in mechanism to:

- Add HSTS / CSP / X-Content-Type-Options / Referrer-Policy /
  Permissions-Policy / Cache-Control response headers.
- Rate-limit per-IP. Splunk's `lockoutAttempts` is per-user; an attacker
  rotating usernames never trips the lockout.
- Strip CR/LF from request headers (CVE-2025-20384 log injection).
- Sanitize the `return_to` query parameter (CVE-2025-20379 open
  redirect).
- Provide CAPTCHA / bot challenge.
- Verify client TLS certificates for mTLS (HEC mTLS goes through
  `requireClientCert = true` but enforcing client-cert format and chain
  is much easier at the proxy).

A reverse proxy plus a WAF is therefore not optional.

## nginx — Splunk Web vhost

Key non-obvious settings:

- `proxy_buffering off` and `proxy_request_buffering off` — without
  these, streaming search previews and chunked HEC ACKs are delayed
  until the entire body buffers in nginx.
- `proxy_http_version 1.1` plus the `Upgrade` / `Connection` map —
  required for any future Splunk Secure Gateway / Mission Control
  WebSocket traffic. Costs nothing and future-proofs.
- `proxy_read_timeout 600s` — AWS ALB defaults to 60s and Cloudflare
  Free/Pro to 100s; long searches cause 524s without explicit raise.
- `proxy_set_header Host $host` — must NOT be `$proxy_host`. The Splunk
  CSRF cookie `splunkweb_csrf_token_<port>` is bound to the host the
  browser sees; mismatched Host produces "CSRF validation failed".
- `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for` —
  `$proxy_add_x_forwarded_for` appends, never overwrites. Combined with
  upstream stripping this prevents XFF spoofing.
- `proxy_hide_header Server` and `X-Powered-By` — strip backend version
  info.
- `if ($http_user_agent ~* "[\r\n]") { return 400; }` — CVE-2025-20384
  log injection mitigation. Same pattern can be applied to other
  forwarded headers if they appear in your audit-log searches.
- `if ($arg_return_to ~* "^https?://") { return 400; }` — CVE-2025-20379
  open redirect mitigation. Tightens to local-path-only redirects.
- `limit_req zone=splunk_login burst=10 nodelay` — Splunk has no
  CAPTCHA; this is the per-IP defense against credential stuffing.

## nginx — HEC vhost

- `client_max_body_size <hec_max_content_length>m` — matches Splunk's
  `[http_input] max_content_length` (800 MB default). Without alignment
  the proxy returns 413 before Splunk sees the request.
- `proxy_buffering off` and `proxy_request_buffering off` — keep huge
  HEC POSTs streaming to disk-less Splunk, avoid temp-file pressure.
- `proxy_pass https://splunk_hec_upstream` (TLS) — even if you trust the
  internal network, this lets HEC use Splunk's TLS termination on 8088.
- `ssl_verify_client on` (mTLS option) — for HEC mTLS, terminate at the
  proxy with `ssl_verify_depth 3` and a CA bundle that signs your client
  certificates.
- `/services/collector/health` — UNAUTHENTICATED by Splunk design. Fine
  for proxy / load-balancer health checks. Rate-limit aggressively if
  exposed publicly.

## HAProxy — Splunk Web vhost

- `option http-server-close` — NOT `option httpclose`. The latter
  forces every request to a new TCP connection and breaks HEC keepalive.
- `mode http` — HAProxy's L7 mode is required to inspect headers / URI.
- `http-request set-header X-Forwarded-Proto https` — must be set so
  Splunk's `tools.sessions.forceSecure = true` flags the cookie as
  Secure.
- `http-request deny if { req.hdrs -m reg [\r\n] }` — log injection
  mitigation.
- `http-request deny if { url_param(return_to) -m reg ^https?:// }` —
  open redirect mitigation.
- `option httpchk GET /en-US/account/login` — health check that hits
  the actual app server, not splunkd.

## HAProxy — HEC vhost

- `option http-server-close` plus `timeout client 60s / server 60s`.
- `option httpchk GET /services/collector/health` — health check against
  the unauth health endpoint.
- `server hec01 127.0.0.1:8088 check ssl verify none` — when the proxy
  trusts Splunk's TLS via the internal network, `verify none` is
  acceptable. For stricter posture, set `verify required ca-file <CA>`.

## Common pitfalls

| Pitfall | Consequence | Fix |
|---|---|---|
| `proxy_buffering on` (nginx default) | Search streams freeze | Set off |
| `option httpclose` (HAProxy) | HEC keepalive breaks | Use `http-server-close` |
| Cloudflare strips `splunkweb_csrf_token_*` | "CSRF validation failed" | Cookie allowlist rule |
| AWS WAF default 8 KB body inspect | HEC POSTs blocked | Exempt `/services/collector*` |
| AWS ALB default 60s idle timeout | Long searches → 504 | Raise to ≥ 600s |
| Cloudflare 100s Proxy Read Timeout | Long searches → 524 | Enterprise plan only |
| Strip `Host` rewrite | CSRF cookie mismatch | Pass `$host` not `$proxy_host` |
| Forward attacker-supplied XFF | Audit log spoofing | `$proxy_add_x_forwarded_for` |

## When to use nginx vs HAProxy

| Need | Choice |
|---|---|
| WebSocket plumbing for SSG / Mission Control | nginx (better `Upgrade` map) |
| L4 SNI routing | HAProxy (deeper L4 controls) |
| OpenResty / Lua scripting | nginx |
| Kubernetes ingress | nginx ingress-controller (pre-built) |
| TCP / UDP load balancing | HAProxy or nginx-stream |
| F5 BIG-IP equivalence | HAProxy (similar config style) |

Both templates produce equivalent security postures for HTTP. Pick by
operational fit.
