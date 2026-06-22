#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIDEFIELD_SKILL_NAME="widefield-okta-integration-setup"
WIDEFIELD_DISPLAY_NAME="WideField Okta Integration Setup"
WIDEFIELD_KIND="okta"
WIDEFIELD_RENDER_ROOT="widefield-okta-integration-rendered"
WIDEFIELD_DEFAULT_ACTION="render"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/widefield_setup_helpers.sh"
widefield_main "$@"
