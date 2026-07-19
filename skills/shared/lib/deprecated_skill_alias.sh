#!/usr/bin/env bash
# Shared fail-closed entrypoint for deprecated skill aliases.

deprecated_skill_alias_main() {
    local legacy_skill="$1"
    local canonical_skill="$2"
    local entrypoint="$3"
    shift 3

    if [[ "$#" -eq 1 && ( "$1" == "--help" || "$1" == "-h" ) ]]; then
        cat <<EOF
DEPRECATED: ${legacy_skill} is replaced_by ${canonical_skill}.

This compatibility entrypoint is help-only. It never renders assets, validates
live state, or performs apply, restore, enable, register, reassign, or other
operational phases.

Canonical handoff:
  bash skills/${canonical_skill}/scripts/${entrypoint} --help
EOF
        return 0
    fi

    printf '%s\n' \
        "ERROR: deprecated skill '${legacy_skill}' is replaced_by '${canonical_skill}'; legacy ${entrypoint} is help-only and refuses all operational arguments." \
        "HANDOFF: bash skills/${canonical_skill}/scripts/${entrypoint} --help" >&2
    return 2
}
