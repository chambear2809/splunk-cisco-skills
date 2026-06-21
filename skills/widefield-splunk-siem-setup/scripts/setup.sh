#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIDEFIELD_SKILL_NAME="widefield-splunk-siem-setup"
WIDEFIELD_DISPLAY_NAME="WideField Splunk SIEM Setup"
WIDEFIELD_KIND="splunk"
WIDEFIELD_RENDER_ROOT="widefield-splunk-siem-rendered"
WIDEFIELD_DEFAULT_ACTION="render"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/widefield_setup_helpers.sh"
widefield_main "$@"
