#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<EOF
Write Secret File

Usage: $(basename "$0") [OPTIONS] PATH

Options:
  --prompt TEXT   Prompt label to show while reading the secret
  --editor        Open PATH in \$VISUAL or \$EDITOR instead of reading one secret line
  --force         Overwrite PATH if it already exists
  --help          Show this help

Reads a secret interactively without echoing it, asks for confirmation, and
writes PATH with mode 600. This avoids putting secrets in shell history or
process arguments.
EOF
}

PROMPT="Secret"
FORCE=false
EDITOR_MODE=false
OUTPUT_PATH=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prompt)
            if [[ $# -lt 2 ]]; then
                echo "ERROR: --prompt requires a value." >&2
                exit 1
            fi
            PROMPT="$2"
            shift 2
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --editor)
            EDITOR_MODE=true
            shift
            ;;
        --help)
            usage
            exit 0
            ;;
        -*)
            echo "ERROR: Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
        *)
            if [[ -n "${OUTPUT_PATH}" ]]; then
                echo "ERROR: Only one output path is supported." >&2
                exit 1
            fi
            OUTPUT_PATH="$1"
            shift
            ;;
    esac
done

if [[ -z "${OUTPUT_PATH}" ]]; then
    usage >&2
    exit 1
fi

parent_dir="$(dirname "${OUTPUT_PATH}")"
if [[ ! -d "${parent_dir}" ]]; then
    echo "ERROR: Parent directory does not exist: ${parent_dir}" >&2
    exit 1
fi

if [[ -e "${OUTPUT_PATH}" && "${FORCE}" != "true" ]]; then
    echo "ERROR: Refusing to overwrite existing file: ${OUTPUT_PATH}" >&2
    echo "Use --force if you intentionally want to replace it." >&2
    exit 1
fi

if [[ "${EDITOR_MODE}" == "true" ]]; then
    umask 077
    install -m 600 /dev/null "${OUTPUT_PATH}"
    chmod 600 "${OUTPUT_PATH}"
    editor_cmd="${VISUAL:-${EDITOR:-vi}}"
    # shellcheck disable=SC2206  # honor common EDITOR values such as "code -w"
    editor_args=(${editor_cmd})
    "${editor_args[@]}" "${OUTPUT_PATH}"
    chmod 600 "${OUTPUT_PATH}"
    echo "Secret file ready at ${OUTPUT_PATH} (mode 600)."
    exit 0
fi

if [[ ! -t 0 ]]; then
    echo "ERROR: Refusing to read a secret from non-interactive stdin." >&2
    echo "Run this script from a terminal so the secret is not captured in shell history." >&2
    exit 1
fi

IFS= read -r -s -p "${PROMPT}: " secret_value
printf '\n'
IFS= read -r -s -p "Confirm ${PROMPT}: " secret_confirm
printf '\n'

if [[ "${secret_value}" != "${secret_confirm}" ]]; then
    unset secret_value secret_confirm
    echo "ERROR: Secret values did not match." >&2
    exit 1
fi

umask 077
install -m 600 /dev/null "${OUTPUT_PATH}"
printf '%s\n' "${secret_value}" > "${OUTPUT_PATH}"
chmod 600 "${OUTPUT_PATH}"
unset secret_value secret_confirm

echo "Secret written to ${OUTPUT_PATH} (mode 600)."
