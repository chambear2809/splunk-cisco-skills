#!/usr/bin/env bash
# Convenience wrapper around setup.sh --phase validate.
#
# Use this when you only want to run the live validation probes against an
# already-deployed search head. It re-renders the assets so the probes
# match the current intent expressed by the operator's --public-fqdn /
# --proxy-cidr / etc. arguments.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${SCRIPT_DIR}/setup.sh" --phase validate "$@"
