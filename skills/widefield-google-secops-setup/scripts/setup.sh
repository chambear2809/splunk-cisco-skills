#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIDEFIELD_SKILL_NAME="widefield-google-secops-setup"
WIDEFIELD_DISPLAY_NAME="WideField Google SecOps Setup"
WIDEFIELD_KIND="google"
WIDEFIELD_RENDER_ROOT="widefield-google-secops-rendered"
WIDEFIELD_DEFAULT_ACTION="render"

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/widefield_setup_helpers.sh"
widefield_main "$@"
