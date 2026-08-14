# Registry, transfer, and no-egress gates

Use digest-preserving OCI tools such as `skopeo copy --all` only in the external
operator handoff. Keep staging pull credentials and destination push credentials
in separate mode-0600 auth files. This skill's `--push-registry` mode always
fails before reading either the bundle or credentials. The operator must inspect
the destination first, reject tag overwrite, copy the exact OCI digest set, and
re-inspect every mirror digest.

The destination registry hostname must be covered by `exact_internal_hosts` or
an exact label-boundary match under `internal_dns_suffixes`. A private IP is not
implicitly approved; list it in `exact_internal_hosts`. Vendor `source` and
private `mirror` references must use different registry authorities.

Transfer media should be encrypted, inventoried, malware-scanned, and subject to
customer chain-of-custody controls. Verify all hashes again after crossing the
air gap and before the external registry handoff.

No-egress inventory must include every hostname or IP used for image pulls,
object storage, PostgreSQL, Redis, email, identity, feature flags, telemetry,
license/support services, model APIs, Vertex AI, certificate issuance, and
external webhooks. Strict air-gap mode permits only exact internal endpoints
listed in the spec. DNS resolution alone does not prove reachability or trust.
Host-only evidence remains insufficient for source-to-mirror endpoint rewrites;
retain `endpoint_rewrite_evidence_missing` until the versioned Stack contract in
`reference.md` is emitted and verified.
