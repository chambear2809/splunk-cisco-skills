# Changelog

All notable changes should be documented here.

This project follows an `Unreleased` section first. Move entries into a dated
release section when cutting a release.

## Unreleased

- Added contributor-readiness, security, ownership, and validation guardrails.
- Added a local `splunk-cisco-skills` MCP agent server under `agent/` with
  read-only catalog/skill/template tools, dry-run planning for Cisco product
  setup, and a two-stage commit (plan + confirm) execution flow gated by
  `SPLUNK_SKILLS_MCP_ALLOW_MUTATION=1`.
- Made MCP plans single-use: a plan hash is consumed when it executes, so
  destructive commands cannot be replayed and concurrent execute calls for
  the same hash do not double-run.
- Bounded MCP subprocess stdout/stderr at 256 KiB per stream during execution
  to prevent unbounded memory growth from chatty scripts; timeouts now
  SIGTERM then SIGKILL with a short grace and report `timed_out` in the
  response.
- Tightened the MCP `read_only` heuristic: `--dry-run` and `--list-products`
  are honored only for the `cisco-product-setup` scripts that actually
  implement them; other scripts are always treated as mutating.
- Added catalog-aware allowlist for `plan_cisco_product_setup` so non-secret
  catalog fields are accepted regardless of regex shape; added a regression
  test that catches future catalog edits adding secret-shaped non-secret keys.
- Replaced `_frontmatter` ad-hoc parser with `yaml.safe_load`.
- Pinned ShellCheck CI install to a SHA-256 of the upstream archive.
- Restored stderr routing on Cisco ThousandEyes Cloud-warning lines.
- Tightened `--custom-indexes` validation in the Cisco Enterprise Networking
  setup to reject any value that is not a valid Splunk index name.
- Added `*)` fallback to the Cisco product validation phase so unknown route
  types fail loudly instead of silently succeeding.
- Promoted a single-use cleanup-trap pattern (`hbs_append_cleanup_trap`) in
  Cisco Spaces and Cisco ThousandEyes scripts so prior EXIT/INT/TERM traps
  are preserved.
