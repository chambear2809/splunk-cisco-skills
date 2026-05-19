---
name: splunk-cloud-acs-allowlist-setup
description: >-
  Compatibility alias for the older Splunk Cloud ACS IP allowlist workflow.
  Use splunk-cloud-acs-admin-setup for new ACS work, including allowlists,
  indexes, HEC tokens, users, roles, capabilities, app permissions, private
  connectivity, outbound ports, DDSS self-storage, limits, maintenance windows,
  and restarts. Use when an existing handoff or slash command still references
  splunk-cloud-acs-allowlist-setup.
---

# Splunk Cloud ACS Allowlist Setup

This skill remains as a compatibility path for existing allowlist-only handoffs.
New work should use
[`splunk-cloud-acs-admin-setup`](../splunk-cloud-acs-admin-setup/SKILL.md),
which preserves the allowlist safety model and adds broader ACS administration.

The scripts in this directory still render and apply the original allowlist
workflow for all seven ACS allowlist features (`acs`, `search-api`, `hec`,
`s2s`, `search-ui`, `idm-api`, `idm-ui`) with IPv4 and IPv6 coverage.
