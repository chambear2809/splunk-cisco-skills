#!/usr/bin/env bash
# Convenience wrapper around setup.sh --phase validate.
#
# Re-renders the assets so the live validation probes match the operator's
# current intent (--target / --cm-fqdn / --enable-mtls / etc.) and then
# runs the rendered validate.sh against the local Splunk host.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${SCRIPT_DIR}/setup.sh" --phase validate "$@"
