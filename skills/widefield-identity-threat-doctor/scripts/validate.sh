#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIDEFIELD_SKILL_NAME="widefield-identity-threat-doctor"
WIDEFIELD_DISPLAY_NAME="WideField Identity Threat Doctor"
WIDEFIELD_KIND="doctor"
WIDEFIELD_RENDER_ROOT="widefield-identity-threat-doctor-rendered"
WIDEFIELD_DEFAULT_ACTION="validate"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/widefield_setup_helpers.sh"
widefield_main "$@"
