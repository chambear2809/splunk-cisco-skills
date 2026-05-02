#!/usr/bin/env python3
"""Render Splunk Federated Search assets."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import stat
from pathlib import Path


GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "federated.conf.template",
    "indexes.conf",
    "server.conf",
    "preflight.sh",
    "apply-search-head.sh",
    "apply-shc-deployer.sh",
    "status.sh",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk Federated Search assets.")
    parser.add_argument("--mode", choices=("standard", "transparent"), default="standard")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--splunk-home", default="/opt/splunk")
    parser.add_argument("--app-name", default="ZZZ_cisco_skills_federated_search")
    parser.add_argument("--provider-name", default="remote_provider")
    parser.add_argument("--remote-host-port", required=True)
    parser.add_argument("--service-account", required=True)
    parser.add_argument("--password-file", default="")
    parser.add_argument("--app-context", default="search")
    parser.add_argument("--use-fsh-knowledge-objects", choices=("true", "false"), default="false")
    parser.add_argument("--federated-index-name", default="remote_main")
    parser.add_argument(
        "--dataset-type",
        choices=("index", "metricindex", "savedsearch", "lastjob", "datamodel"),
        default="index",
    )
    parser.add_argument("--dataset-name", default="main")
    parser.add_argument("--shc-replication", choices=("true", "false"), default="true")
    parser.add_argument("--max-preview-generation-duration", default="0")
    parser.add_argument("--max-preview-generation-inputcount", default="0")
    parser.add_argument("--restart-splunk", choices=("true", "false"), default="true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def shell_quote(value: object) -> str:
    return shlex.quote(str(value))


def bool_value(value: str) -> bool:
    return value.lower() == "true"


def no_newline(value: str, option: str) -> None:
    if "\n" in value or "\r" in value:
        die(f"{option} must not contain newlines.")


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def make_script(body: str) -> str:
    return "#!/usr/bin/env bash\nset -euo pipefail\n\n" + body.lstrip()


def clean_render_dir(render_dir: Path) -> None:
    for rel in GENERATED_FILES:
        candidate = render_dir / rel
        if candidate.is_file() or candidate.is_symlink():
            candidate.unlink()


def validate(args: argparse.Namespace) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_]+", args.provider_name or ""):
        die("--provider-name must contain only letters, numbers, and underscores.")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", args.app_name or ""):
        die("--app-name must contain only letters, numbers, underscore, dot, colon, or hyphen.")
    if not re.fullmatch(r"[^:\s]+:[0-9]{1,5}", args.remote_host_port or ""):
        die("--remote-host-port must look like host:management_port.")
    port = int(args.remote_host_port.rsplit(":", 1)[1])
    if port < 1 or port > 65535:
        die("--remote-host-port must include a port between 1 and 65535.")
    if not re.fullmatch(r"[A-Za-z0-9_.@:-]+", args.service_account or ""):
        die("--service-account contains unsupported characters.")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", args.app_context or ""):
        die("--app-context must contain only letters, numbers, underscore, dot, colon, or hyphen.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,2047}", args.federated_index_name or ""):
        die("--federated-index-name must start with a lowercase letter or number and contain lowercase letters, numbers, underscores, or hyphens.")
    if "kvstore" in args.federated_index_name:
        die("--federated-index-name must not contain 'kvstore'.")
    for value, option in (
        (args.max_preview_generation_duration, "--max-preview-generation-duration"),
        (args.max_preview_generation_inputcount, "--max-preview-generation-inputcount"),
    ):
        if not re.fullmatch(r"[0-9]+", value or ""):
            die(f"{option} must be a nonnegative integer.")
    if args.mode == "standard" and not args.dataset_name:
        die("--dataset-name is required for standard mode federated indexes.")
    if args.mode == "standard" and bool_value(args.use_fsh_knowledge_objects):
        die("--use-fsh-knowledge-objects true is valid only for transparent mode providers.")
    for value, option in (
        (args.remote_host_port, "--remote-host-port"),
        (args.service_account, "--service-account"),
        (args.password_file, "--password-file"),
        (args.dataset_name, "--dataset-name"),
    ):
        no_newline(value, option)


def render_federated_template(args: argparse.Namespace) -> str:
    lines = [
        "# Rendered by splunk-federated-search-setup. Review before applying.",
        "# Password is substituted from --password-file by apply scripts.",
        f"[provider://{args.provider_name}]",
        "type = splunk",
        f"hostPort = {args.remote_host_port}",
        f"serviceAccount = {args.service_account}",
        "password = __FEDERATED_SERVICE_ACCOUNT_PASSWORD_FROM_FILE__",
        f"mode = {args.mode}",
    ]
    if args.mode == "standard":
        lines.extend(
            [
                f"appContext = {args.app_context}",
                "useFSHKnowledgeObjects = 0",
            ]
        )
    else:
        lines.append("useFSHKnowledgeObjects = 1")
    lines.extend(
        [
            "",
            "[general]",
            f"max_preview_generation_duration = {args.max_preview_generation_duration}",
            f"max_preview_generation_inputcount = {args.max_preview_generation_inputcount}",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def render_indexes(args: argparse.Namespace) -> str:
    if args.mode == "transparent":
        return "# Transparent mode federated providers do not use federated indexes.\n"
    return "\n".join(
        [
            "# Rendered by splunk-federated-search-setup. Review before applying.",
            f"[federated:{args.federated_index_name}]",
            f"federated.provider = {args.provider_name}",
            f"federated.dataset = {args.dataset_type}:{args.dataset_name}",
            "",
        ]
    )


def render_server(args: argparse.Namespace) -> str:
    if not bool_value(args.shc_replication) or args.mode != "standard":
        return "# No SHC federated index replication setting requested.\n"
    return "\n".join(
        [
            "# Rendered for search head cluster deployer use before creating federated indexes.",
            "[shclustering]",
            "conf_replication_include.indexes = true",
            "",
        ]
    )


def render_readme(args: argparse.Namespace, password_path: str) -> str:
    index_note = (
        f"\nStandard mode federated index: `federated:{args.federated_index_name}` maps to "
        f"`{args.dataset_type}:{args.dataset_name}`.\n"
        if args.mode == "standard"
        else "\nTransparent mode does not use federated indexes or `federated:` search syntax.\n"
    )
    return f"""# Splunk Federated Search Rendered Assets

Mode: `{args.mode}`
Provider: `{args.provider_name}`
Remote management endpoint: `{args.remote_host_port}`

Files:

- `federated.conf.template`
- `indexes.conf`
- `server.conf`
- `preflight.sh`
- `apply-search-head.sh`
- `apply-shc-deployer.sh`
- `status.sh`

The service account password is never rendered. Apply scripts read it from:

`{password_path}`
{index_note}
For Splunk Enterprise search head clusters in standard mode, push `server.conf`
from the deployer before creating federated indexes so the federated index
definitions replicate to members.
"""


def default_password_path(args: argparse.Namespace, render_dir: Path) -> str:
    if args.password_file:
        return str(Path(args.password_file).expanduser())
    return str(render_dir / f".{args.provider_name}.service-account-password")


def render_preflight(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    return make_script(
        f"""splunk_home={splunk_home}
test -x "${{splunk_home}}/bin/splunk"
"${{splunk_home}}/bin/splunk" btool federated list --debug >/dev/null || true
"${{splunk_home}}/bin/splunk" btool indexes list --debug >/dev/null || true
"""
    )


def render_apply(args: argparse.Namespace, password_path: str, shc: bool) -> str:
    splunk_home = shell_quote(args.splunk_home)
    app_name = shell_quote(args.app_name)
    password_file = shell_quote(password_path)
    base = "${splunk_home}/etc/shcluster/apps" if shc else "${splunk_home}/etc/apps"
    server_copy = (
        'cp server.conf "${target_dir}/server.conf"\n'
        if shc and bool_value(args.shc_replication) and args.mode == "standard"
        else ""
    )
    restart = (
        '"${splunk_home}/bin/splunk" restart\n'
        if bool_value(args.restart_splunk) and not shc
        else 'echo "Review rendered changes and restart or push bundle as appropriate."\n'
    )
    return make_script(
        f"""splunk_home={splunk_home}
app_name={app_name}
password_file={password_file}

if [[ ! -s "${{password_file}}" ]]; then
  echo "ERROR: Service account password file is missing or empty: ${{password_file}}" >&2
  exit 1
fi

target_dir="{base}/${{app_name}}/local"
mkdir -p "${{target_dir}}"
python3 - "${{password_file}}" federated.conf.template "${{target_dir}}/federated.conf" <<'PY'
from pathlib import Path
import sys

password_path = Path(sys.argv[1])
template_path = Path(sys.argv[2])
target_path = Path(sys.argv[3])
password = password_path.read_text(encoding="utf-8").strip()
if not password:
    raise SystemExit(f"ERROR: password file is empty: {{password_path}}")
target_path.write_text(
    template_path.read_text(encoding="utf-8").replace(
        "__FEDERATED_SERVICE_ACCOUNT_PASSWORD_FROM_FILE__", password
    ),
    encoding="utf-8",
)
PY
chmod 600 "${{target_dir}}/federated.conf"
cp indexes.conf "${{target_dir}}/indexes.conf"
{server_copy}{restart}"""
    )


def render_status(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    provider = shell_quote(args.provider_name)
    return make_script(
        f"""splunk_home={splunk_home}
provider={provider}
"${{splunk_home}}/bin/splunk" btool federated list "provider://${{provider}}" --debug 2>/dev/null | grep -v -E '(^|[[:space:]])password[[:space:]]*=' || true
"${{splunk_home}}/bin/splunk" btool indexes list "federated:{args.federated_index_name}" --debug 2>/dev/null || true
"""
    )


def render(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / "federated-search"
    password_path = default_password_path(args, render_dir)
    assets: list[str] = []
    if not args.dry_run:
        clean_render_dir(render_dir)
        files = {
            "README.md": render_readme(args, password_path),
            "metadata.json": json.dumps(
                {
                    "mode": args.mode,
                    "provider_name": args.provider_name,
                    "remote_host_port": args.remote_host_port,
                    "service_account": args.service_account,
                    "app_context": args.app_context,
                    "federated_index_name": args.federated_index_name if args.mode == "standard" else "",
                    "dataset_type": args.dataset_type if args.mode == "standard" else "",
                    "dataset_name": args.dataset_name if args.mode == "standard" else "",
                    "max_preview_generation_duration": args.max_preview_generation_duration,
                    "max_preview_generation_inputcount": args.max_preview_generation_inputcount,
                    "password_file": password_path,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "federated.conf.template": render_federated_template(args),
            "indexes.conf": render_indexes(args),
            "server.conf": render_server(args),
            "preflight.sh": render_preflight(args),
            "apply-search-head.sh": render_apply(args, password_path, shc=False),
            "apply-shc-deployer.sh": render_apply(args, password_path, shc=True),
            "status.sh": render_status(args),
        }
        for rel, content in files.items():
            write_file(render_dir / rel, content, executable=rel.endswith(".sh"))
            assets.append(rel)
    return {
        "target": "federated-search",
        "mode": args.mode,
        "output_dir": str(output_dir),
        "render_dir": str(render_dir),
        "assets": assets,
        "dry_run": args.dry_run,
        "commands": {
            "preflight": [["./preflight.sh"]],
            "apply": [["./apply-search-head.sh"], ["./apply-shc-deployer.sh"]],
            "status": [["./status.sh"]],
        },
    }


def main() -> int:
    args = parse_args()
    validate(args)
    payload = render(args)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.dry_run:
        print(f"Would render Federated Search assets under {payload['render_dir']}")
    else:
        print(f"Rendered Federated Search assets under {payload['render_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
