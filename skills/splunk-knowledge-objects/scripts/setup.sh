#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/deprecated_skill_alias.sh"

deprecated_skill_alias_main "splunk-knowledge-objects" "splunk-knowledge-objects-setup" "setup.sh" "$@"
