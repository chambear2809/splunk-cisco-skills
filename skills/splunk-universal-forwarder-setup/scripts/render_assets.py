#!/usr/bin/env python3
"""Render Splunk Universal Forwarder bootstrap and enrollment assets."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import stat
from pathlib import Path


GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "deploymentclient.conf",
    "outputs.conf",
    "install-universal-forwarder.ps1",
    "apply-universal-forwarder.sh",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk Universal Forwarder assets.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--target-os", choices=("linux", "macos", "windows", "freebsd", "solaris", "aix"), default="linux")
    parser.add_argument("--target-arch", default="auto")
    parser.add_argument("--package-type", default="auto")
    parser.add_argument("--package-path", default="")
    parser.add_argument("--splunk-home", default="")
    parser.add_argument("--service-user", default="")
    parser.add_argument("--admin-user", default="admin")
    parser.add_argument("--admin-password-file", default="")
    parser.add_argument("--enroll", choices=("none", "deployment-server", "enterprise-indexers", "splunk-cloud"), default="none")
    parser.add_argument("--deployment-server", default="")
    parser.add_argument("--server-list", default="")
    parser.add_argument("--cloud-credentials-package", default="")
    parser.add_argument("--client-name", default="")
    parser.add_argument("--phone-home-interval", default="60")
    parser.add_argument("--tcpout-group", default="default-autolb-group")
    parser.add_argument("--use-ack", choices=("true", "false"), default="true")
    parser.add_argument("--source-command", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def no_newline(value: str, option: str) -> None:
    if "\n" in value or "\r" in value:
        die(f"{option} must not contain newlines.")


def conf_stanza_token(value: str, option: str) -> None:
    no_newline(value, option)
    if "[" in value or "]" in value:
        die(f"{option} must not contain square brackets.")


def positive_int(value: str, option: str) -> int:
    if not re.fullmatch(r"[0-9]+", value or "") or int(value) < 1:
        die(f"{option} must be a positive integer.")
    return int(value)


def host_port(value: str, option: str) -> None:
    no_newline(value, option)
    if not re.fullmatch(r"(?:[^:\s,]+|\[[^\]]+\]):\d+", value or ""):
        die(f"{option} must be HOST:PORT or [IPv6]:PORT.")
    port = int(value.rsplit(":", 1)[1])
    if port < 1 or port > 65535:
        die(f"{option} port must be from 1 to 65535.")


def server_list(value: str, option: str) -> list[str]:
    no_newline(value, option)
    raw_items = value.split(",")
    items = [item.strip() for item in raw_items]
    if not items:
        die(f"{option} must contain at least one HOST:PORT value.")
    if any(not item for item in items):
        die(f"{option} must not contain empty entries.")
    for item in items:
        host_port(item, option)
    return items


def shell_quote(value: object) -> str:
    return shlex.quote(str(value))


def ps_quote(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def default_home(target_os: str) -> str:
    if target_os == "macos":
        return "/Applications/splunkforwarder"
    if target_os == "windows":
        return r"C:\Program Files\SplunkUniversalForwarder"
    return "/opt/splunkforwarder"


def default_service_user(target_os: str) -> str:
    if target_os == "linux":
        return "splunkfwd"
    return ""


def normalized_package_type(value: str, target_os: str) -> str:
    normalized = (value or "auto").lower().lstrip(".")
    aliases = {"tar.gz": "tgz", "tar-gz": "tgz", "z": "tar-z", "tar.z": "tar-z"}
    normalized = aliases.get(normalized, normalized)
    if normalized != "auto":
        return normalized
    return {
        "linux": "tgz",
        "macos": "tgz",
        "windows": "msi",
        "freebsd": "tgz",
        "solaris": "tar-z",
        "aix": "tgz",
    }.get(target_os, "tgz")


def normalized_arch(value: str, target_os: str) -> str:
    raw = (value or "auto").lower().replace("_", "-")
    if raw in {"", "auto"}:
        return {
            "linux": "amd64",
            "macos": "universal2",
            "windows": "x64",
            "freebsd": "freebsd14-amd64",
            "solaris": "amd64",
            "aix": "powerpc",
        }.get(target_os, "amd64")
    aliases = {
        "linux": {"x64": "amd64", "x86-64": "amd64", "aarch64": "arm64"},
        "macos": {"x64": "intel", "x86-64": "intel", "amd64": "intel", "arm64": "universal2", "aarch64": "universal2", "universal": "universal2"},
        "windows": {"amd64": "x64", "x86-64": "x64", "i386": "x86", "i686": "x86", "386": "x86"},
        "freebsd": {"amd64": "freebsd14-amd64", "x64": "freebsd14-amd64", "x86-64": "freebsd14-amd64"},
        "solaris": {"x64": "amd64", "x86-64": "amd64"},
        "aix": {"ppc": "powerpc", "ppc64": "powerpc"},
    }
    return aliases.get(target_os, {}).get(raw, raw)


def validate_arch_for_target(value: str, target_os: str) -> None:
    arch = normalized_arch(value, target_os)
    allowed = {
        "linux": {"amd64", "arm64", "ppc64le", "s390x"},
        "macos": {"intel", "universal2"},
        "windows": {"x64", "x86"},
        "freebsd": {"freebsd13-amd64", "freebsd14-amd64"},
        "solaris": {"amd64", "sparc"},
        "aix": {"powerpc"},
    }[target_os]
    if arch not in allowed:
        die(f"--target-arch {value} is not valid for --target-os {target_os}.")


def detect_package_type_from_path(path: str) -> str:
    lower = Path(path).name.lower()
    if lower.endswith((".tar.gz", ".tgz")):
        return "tgz"
    if lower.endswith(".tar.z") or lower.endswith(".z"):
        return "tar-z"
    for suffix in ("rpm", "deb", "msi", "dmg", "pkg", "txz", "p5p"):
        if lower.endswith("." + suffix):
            return suffix
    return ""


def validate_package_type_for_target(package_type: str, target_os: str) -> None:
    allowed = {
        "linux": {"tgz", "rpm", "deb"},
        "macos": {"tgz", "dmg", "pkg"},
        "windows": {"msi"},
        "freebsd": {"tgz", "txz"},
        "solaris": {"tar-z", "p5p"},
        "aix": {"tgz"},
    }[target_os]
    if package_type not in allowed:
        die(f"--package-type {package_type} is not valid for --target-os {target_os}.")


def v1_apply_state(args: argparse.Namespace) -> str:
    package_type = normalized_package_type(args.package_type, args.target_os)
    if args.target_os == "linux" and package_type in {"tgz", "rpm", "deb"}:
        return "local-ssh"
    if args.target_os == "macos" and package_type == "tgz":
        return "local-ssh"
    if args.target_os == "macos" and package_type == "dmg":
        return "download-only"
    if args.target_os == "windows" and package_type == "msi":
        return "render-only"
    return "unsupported-v1"


def windows_default_path(path: str) -> str:
    if not path:
        return ""
    if re.match(r"^[A-Za-z]:[\\/]", path) or path.startswith("\\\\"):
        return path
    return ".\\" + Path(path).name


def validate(args: argparse.Namespace) -> None:
    positive_int(args.phone_home_interval, "--phone-home-interval")
    for value, option in (
        (args.target_arch, "--target-arch"),
        (args.package_type, "--package-type"),
        (args.package_path, "--package-path"),
        (args.splunk_home, "--splunk-home"),
        (args.service_user, "--service-user"),
        (args.admin_user, "--admin-user"),
        (args.admin_password_file, "--admin-password-file"),
        (args.deployment_server, "--deployment-server"),
        (args.server_list, "--server-list"),
        (args.cloud_credentials_package, "--cloud-credentials-package"),
        (args.client_name, "--client-name"),
        (args.source_command, "--source-command"),
    ):
        no_newline(value, option)
    conf_stanza_token(args.tcpout_group, "--tcpout-group")
    validate_arch_for_target(args.target_arch, args.target_os)
    if args.enroll == "deployment-server":
        host_port(args.deployment_server, "--deployment-server")
    if args.enroll == "enterprise-indexers":
        server_list(args.server_list, "--server-list")
    if args.enroll == "splunk-cloud" and not args.cloud_credentials_package:
        die("--cloud-credentials-package is required for --enroll splunk-cloud.")
    package_type = normalized_package_type(args.package_type, args.target_os)
    detected_package_type = detect_package_type_from_path(args.package_path) if args.package_path else ""
    if args.package_type != "auto" and detected_package_type and detected_package_type != package_type:
        die(f"--package-type {package_type} does not match detected package type {detected_package_type} for {args.package_path}.")
    if args.package_type == "auto" and detected_package_type:
        package_type = detected_package_type
        args.package_type = detected_package_type
    validate_package_type_for_target(package_type, args.target_os)


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def clean_render_dir(render_dir: Path) -> None:
    for rel in GENERATED_FILES:
        candidate = render_dir / rel
        if candidate.is_file() or candidate.is_symlink():
            candidate.unlink()
    scripts_dir = render_dir / "scripts"
    if scripts_dir.is_dir():
        shutil.rmtree(scripts_dir)


def render_deploymentclient(args: argparse.Namespace) -> str:
    lines = [
        "# Rendered by splunk-universal-forwarder-setup. Review before applying.",
        "[deployment-client]",
        f"phoneHomeIntervalInSecs = {positive_int(args.phone_home_interval, '--phone-home-interval')}",
    ]
    if args.client_name:
        lines.append(f"clientName = {args.client_name}")
    lines.extend(
        [
            "",
            "[target-broker:deploymentServer]",
            f"targetUri = {args.deployment_server}",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def render_outputs(args: argparse.Namespace) -> str:
    servers = ",".join(server_list(args.server_list, "--server-list"))
    return "\n".join(
        [
            "# Rendered by splunk-universal-forwarder-setup. Review before applying.",
            "[tcpout]",
            f"defaultGroup = {args.tcpout_group}",
            "",
            f"[tcpout:{args.tcpout_group}]",
            f"server = {servers}",
            f"useACK = {args.use_ack}",
            "autoLBFrequency = 30",
            "forceTimebasedAutoLB = true",
            "",
        ]
    )


def render_windows_script(args: argparse.Namespace) -> str:
    splunk_home = args.splunk_home or default_home("windows")
    package_path = windows_default_path(args.package_path)
    cloud_package = args.cloud_credentials_package
    deployment_server = args.deployment_server
    server_csv = ",".join(server_list(args.server_list, "--server-list")) if args.enroll == "enterprise-indexers" else args.server_list
    client_name = args.client_name
    phone_home = positive_int(args.phone_home_interval, "--phone-home-interval")
    use_ack = args.use_ack
    tcpout_group = args.tcpout_group
    return f"""# Rendered by splunk-universal-forwarder-setup.
# Run from an elevated PowerShell session on the Windows target.
param(
    [string]$PackagePath = {ps_quote(package_path)},
    [string]$SplunkHome = {ps_quote(splunk_home)},
    [string]$AdminUser = {ps_quote(args.admin_user)},
    [string]$AdminPasswordFile = {ps_quote(args.admin_password_file)},
    [ValidateSet('none','deployment-server','enterprise-indexers','splunk-cloud')]
    [string]$Enroll = {ps_quote(args.enroll)},
    [string]$DeploymentServer = {ps_quote(deployment_server)},
    [string]$ServerList = {ps_quote(server_csv)},
    [string]$CloudCredentialsPackage = {ps_quote(cloud_package)},
    [string]$ClientName = {ps_quote(client_name)},
    [int]$PhoneHomeInterval = {phone_home},
    [string]$TcpoutGroup = {ps_quote(tcpout_group)},
    [ValidateSet('true','false')]
    [string]$UseAck = {ps_quote(use_ack)}
)

$ErrorActionPreference = 'Stop'

function Assert-Administrator {{
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {{
        throw 'Run this script from an elevated PowerShell session.'
    }}
}}

function Require-File([string]$Path, [string]$Name) {{
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {{
        throw "$Name not found: $Path"
    }}
}}

function Write-TextFile([string]$Path, [string]$Content) {{
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    if (Test-Path -LiteralPath $Path -PathType Leaf) {{
        Copy-Item -LiteralPath $Path -Destination "$Path.bak.$(Get-Date -Format yyyyMMddHHmmss)" -Force
    }}
    Set-Content -LiteralPath $Path -Value $Content -Encoding ASCII
}}

function Quote-ProcessArgument([string]$Value) {{
    if ($Value -match '"') {{ throw "Process arguments must not contain double quotes: $Value" }}
    return '"' + $Value + '"'
}}

Assert-Administrator
Require-File $PackagePath 'Universal Forwarder MSI package'
Require-File $AdminPasswordFile 'Admin password file'

$password = [IO.File]::ReadAllText($AdminPasswordFile).TrimEnd("`r", "`n")
if ([string]::IsNullOrEmpty($password)) {{ throw 'Admin password file is empty.' }}

$msiLog = Join-Path $env:TEMP 'splunkforwarder-msi.log'
$msiArgs = @(
    '/i', (Quote-ProcessArgument $PackagePath),
    'AGREETOLICENSE=Yes',
    'LAUNCHSPLUNK=0',
    'SERVICESTARTTYPE=auto',
    ('INSTALLDIR=' + (Quote-ProcessArgument $SplunkHome)),
    '/quiet',
    '/L*v', (Quote-ProcessArgument $msiLog)
)
$process = Start-Process -FilePath 'msiexec.exe' -ArgumentList ($msiArgs -join ' ') -Wait -PassThru
if ($process.ExitCode -ne 0) {{ throw "msiexec failed with exit code $($process.ExitCode). See $msiLog." }}

$localDir = Join-Path $SplunkHome 'etc\\system\\local'
$userSeed = Join-Path $localDir 'user-seed.conf'
Write-TextFile $userSeed "[user_info]`nUSERNAME = $AdminUser`nPASSWORD = $password`n"

if ($Enroll -eq 'deployment-server') {{
    if ([string]::IsNullOrWhiteSpace($DeploymentServer)) {{ throw 'DeploymentServer is required.' }}
    $clientLine = if ([string]::IsNullOrWhiteSpace($ClientName)) {{ '' }} else {{ "clientName = $ClientName`n" }}
    Write-TextFile (Join-Path $localDir 'deploymentclient.conf') "[deployment-client]`nphoneHomeIntervalInSecs = $PhoneHomeInterval`n$clientLine`n[target-broker:deploymentServer]`ntargetUri = $DeploymentServer`n"
}}
elseif ($Enroll -eq 'enterprise-indexers') {{
    if ([string]::IsNullOrWhiteSpace($ServerList)) {{ throw 'ServerList is required.' }}
    Write-TextFile (Join-Path $localDir 'outputs.conf') "[tcpout]`ndefaultGroup = $TcpoutGroup`n`n[tcpout:$TcpoutGroup]`nserver = $ServerList`nuseACK = $UseAck`nautoLBFrequency = 30`nforceTimebasedAutoLB = true`n"
}}
elseif ($Enroll -eq 'splunk-cloud') {{
    Require-File $CloudCredentialsPackage 'Splunk Cloud UF credentials package'
}}

$splunkExe = Join-Path $SplunkHome 'bin\\splunk.exe'
& $splunkExe start --accept-license --answer-yes --no-prompt
Remove-Item -LiteralPath $userSeed -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath $localDir -Filter 'user-seed.conf.bak.*' -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue

if ($Enroll -eq 'splunk-cloud') {{
    "$AdminUser`n$password`n" | & $splunkExe install app $CloudCredentialsPackage
    & $splunkExe restart
}}
elseif ($Enroll -in @('deployment-server', 'enterprise-indexers')) {{
    & $splunkExe restart
}}

Write-Host 'Splunk Universal Forwarder bootstrap completed.'
"""


def render_apply_script(args: argparse.Namespace) -> str:
    apply_state = v1_apply_state(args)
    if apply_state == "download-only":
        return "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "",
                "echo 'macOS .dmg packages are download/verify only in this automation. Use --package-type tgz for automated apply.' >&2",
                "exit 2",
                "",
            ]
        )
    if apply_state == "unsupported-v1":
        return "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "",
                f"echo '{args.target_os} packages are recognized by latest resolution, but install/apply is unsupported in v1.' >&2",
                "exit 2",
                "",
            ]
        )
    command = args.source_command or "bash skills/splunk-universal-forwarder-setup/scripts/setup.sh --phase all"
    if not args.source_command:
        return "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "",
                "echo 'No automated apply command was rendered. Re-run setup.sh --phase all with --execution local or --execution ssh after review.' >&2",
                "exit 2",
                "",
            ]
        )
    return "#!/usr/bin/env bash\nset -euo pipefail\n\n" + f"exec {command}\n"


def render_readme(args: argparse.Namespace) -> str:
    apply_state = v1_apply_state(args)
    files = ["`metadata.json`"]
    if args.enroll == "deployment-server":
        files.append("`deploymentclient.conf`")
    if args.enroll == "enterprise-indexers":
        files.append("`outputs.conf`")
    if args.target_os == "windows":
        files.append("`install-universal-forwarder.ps1`")
    else:
        files.append("`apply-universal-forwarder.sh`")
    file_list = "\n".join(f"- {item}" for item in files)
    if apply_state == "local-ssh":
        apply_note = "Automated apply is supported for this target/package combination."
    elif apply_state == "render-only":
        apply_note = "Windows v1 is a rendered PowerShell handoff. Copy the MSI and script to the target, then run from an elevated PowerShell session."
    elif apply_state == "download-only":
        apply_note = "This package type is download/verify only. Use the `.tgz` package for automated macOS apply."
    else:
        apply_note = "This platform is recognized for download metadata, but automated apply is unsupported in v1."
    return f"""# Splunk Universal Forwarder Rendered Assets

Target OS: `{args.target_os}`
Enrollment: `{args.enroll}`
Apply state: `{apply_state}`

Review these files before applying:

{file_list}

{apply_note}

Secrets are not rendered. Provide password material through local files at run
time.
"""


def metadata(args: argparse.Namespace, files: list[str]) -> dict[str, object]:
    return {
        "workflow": "splunk-universal-forwarder-setup",
        "target_os": args.target_os,
        "target_arch": args.target_arch,
        "package_type": args.package_type,
        "package_path": args.package_path,
        "splunk_home": args.splunk_home or default_home(args.target_os),
        "service_user": args.service_user or default_service_user(args.target_os),
        "enroll": args.enroll,
        "deployment_server": args.deployment_server,
        "server_list": server_list(args.server_list, "--server-list") if args.enroll == "enterprise-indexers" else [],
        "client_name": args.client_name,
        "phone_home_interval": positive_int(args.phone_home_interval, "--phone-home-interval"),
        "rendered_files": files,
        "v1_apply": v1_apply_state(args),
        "notes": "No secret values are stored in rendered metadata or scripts.",
    }


def main() -> int:
    args = parse_args()
    validate(args)
    render_dir = Path(args.output_dir).expanduser().resolve() / "universal-forwarder"

    planned_files = ["README.md", "metadata.json"]
    if args.enroll == "deployment-server":
        planned_files.append("deploymentclient.conf")
    if args.enroll == "enterprise-indexers":
        planned_files.append("outputs.conf")
    planned_files.append("install-universal-forwarder.ps1" if args.target_os == "windows" else "apply-universal-forwarder.sh")

    if args.dry_run:
        payload = {"render_dir": str(render_dir), "files": planned_files, "metadata": metadata(args, planned_files)}
        print(json.dumps(payload, indent=2, sort_keys=True) if args.json else f"Would render {len(planned_files)} file(s) to {render_dir}")
        return 0

    clean_render_dir(render_dir)
    write_file(render_dir / "README.md", render_readme(args))
    if args.enroll == "deployment-server":
        write_file(render_dir / "deploymentclient.conf", render_deploymentclient(args))
    if args.enroll == "enterprise-indexers":
        write_file(render_dir / "outputs.conf", render_outputs(args))
    if args.target_os == "windows":
        write_file(render_dir / "install-universal-forwarder.ps1", render_windows_script(args))
    else:
        write_file(render_dir / "apply-universal-forwarder.sh", render_apply_script(args), executable=True)
    write_file(render_dir / "metadata.json", json.dumps(metadata(args, planned_files), indent=2, sort_keys=True) + "\n")

    payload = {"render_dir": str(render_dir), "files": planned_files, "metadata": metadata(args, planned_files)}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Rendered {len(planned_files)} Splunk Universal Forwarder asset(s) to {render_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
