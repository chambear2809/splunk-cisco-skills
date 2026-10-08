"""Focused regressions for host bootstrap portability review."""

import os
import getpass
import socket
import subprocess
import textwrap
from tempfile import TemporaryDirectory
from pathlib import Path
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
UF_VALIDATOR = REPO_ROOT / "skills/splunk-universal-forwarder-setup/scripts/validate.sh"


def test_uf_validation_accepts_debug_prefixed_non_localhost_binding() -> None:
    """Upgrades may preserve a debug-prefixed 0.0.0.0:port web.conf value."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        home = root / "uf"
        (home / "bin").mkdir(parents=True)
        fake = home / "bin" / "splunk"
        fake.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                case "$1" in
                  version) echo 'Universal Forwarder 10.6.0.5' ;;
                  status) echo 'splunkd is running' ;;
                  btool)
                    if [[ "$*" == *"web list"* ]]; then echo '/opt/uf/etc/system/local/web.conf [settings] mgmtHostPort = 0.0.0.0:'"$MOCK_PORT" ;
                    else
                    if [[ "$*" == *httpServer* ]]; then echo 'mgmtMode = tcp'; else echo "port = $MOCK_IPC"; fi
                    fi ;;
                  *) exit 0 ;;
                esac
                """
            ),
            encoding="utf-8",
        )
        fake.chmod(0o755)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.listen(1)
        env = os.environ.copy()
        env.update({"MOCK_PORT": str(port), "MOCK_IPC": str(port + 1), "SPLUNK_CREDENTIALS_FILE": str(root / "credentials")})
        result = subprocess.run(
            ["bash", str(UF_VALIDATOR), "--target-os", "linux", "--splunk-home", str(home), "--service-user", getpass.getuser(), "--mgmt-port", str(port), "--ipc-port", str(port + 1)],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False,
        )
        listener.close()
        assert result.returncode == 0, result.stdout + result.stderr


def test_uf_validation_rejects_wrong_management_port() -> None:
    """A listener alone must not make a mismatched configured port pass."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        home = root / "uf"
        (home / "bin").mkdir(parents=True)
        fake = home / "bin" / "splunk"
        fake.write_text(
            "#!/usr/bin/env bash\ncase \"$1\" in version) echo 'Universal Forwarder 10.6.0.5';; status) echo 'splunkd is running';; btool) if [[ \"$*\" == *'web list'* ]]; then echo 'mgmtHostPort = 127.0.0.1:28089'; else echo 'mgmtMode = tcp'; echo 'port = 28194'; fi;; esac\n",
            encoding="utf-8",
        )
        fake.chmod(0o755)
        result = subprocess.run(
            ["bash", str(UF_VALIDATOR), "--target-os", "linux", "--splunk-home", str(home), "--service-user", getpass.getuser(), "--mgmt-port", "28090", "--ipc-port", "28194"],
            cwd=REPO_ROOT, env={**os.environ, "SPLUNK_CREDENTIALS_FILE": str(root / "credentials")}, capture_output=True, text=True, check=False,
        )
        assert result.returncode != 0
        assert "exact effective port 28090" in result.stdout + result.stderr


def test_renderer_rejects_equal_ports_with_leading_zero_variants() -> None:
    """Numeric port aliases must not bypass the collision guard."""
    renderer = REPO_ROOT / "skills/splunk-universal-forwarder-setup/scripts/render_assets.py"
    with TemporaryDirectory() as tmp:
        result = subprocess.run(
            ["python3", str(renderer), "--output-dir", str(Path(tmp) / "rendered"),
             "--target-os", "linux", "--package-type", "tgz", "--mgmt-port", "08194", "--ipc-port", "8194"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False,
        )
        assert result.returncode != 0
        assert "must be different" in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("mode", "fail_mode", "fail_web", "ipc_output", "expected_rc"),
    [("auto", False, False, "8194", 0), ("tcp", True, False, "8194", 1),
     ("tcp", False, False, "81940", 1), ("tcp-invalid", False, False, "8194", 1),
     ("auto", False, True, "8194", 1), ("tcp", False, False, "8194", 1)],
)
def test_uf_validation_does_not_mask_mode_or_ipc_failures(
    mode: str, fail_mode: bool, fail_web: bool, ipc_output: str, expected_rc: int
) -> None:
    """Auto/UDS is valid; failed btool and numeric-prefix IPC values are not."""
    with TemporaryDirectory() as tmp, socket.socket() as reserved_port:
        reserved_port.bind(("127.0.0.1", 0))
        management_port = str(reserved_port.getsockname()[1])
        root = Path(tmp)
        home = root / "uf"
        (home / "bin").mkdir(parents=True)
        fake = home / "bin" / "splunk"
        fake.write_text(
            "#!/usr/bin/env bash\n"
            "case \"$1\" in\n"
            "version) echo 'Universal Forwarder 10.6.0.5';;\n"
            "status) echo 'splunkd is running';;\n"
            "btool) if [[ \"$*\" == *'web list'* ]]; then echo \"mgmtHostPort = 127.0.0.1:$MOCK_MGMT_PORT\"; [[ \"$MOCK_FAIL_WEB\" == true ]] && exit 7 || true; "
            "elif [[ \"$*\" == *'httpServer'* ]]; then echo \"mgmtMode=$MOCK_MODE\"; [[ \"$MOCK_FAIL_MODE\" == true ]] && exit 7 || true; "
            "else echo \"port = $MOCK_IPC_OUTPUT\"; fi;; esac\n",
            encoding="utf-8",
        )
        fake.chmod(0o755)
        env = {**os.environ, "MOCK_MGMT_PORT": management_port, "MOCK_MODE": mode, "MOCK_FAIL_MODE": str(fail_mode).lower(), "MOCK_FAIL_WEB": str(fail_web).lower(), "MOCK_IPC_OUTPUT": ipc_output,
               "SPLUNK_CREDENTIALS_FILE": str(root / "credentials")}
        result = subprocess.run(
            ["bash", str(UF_VALIDATOR), "--target-os", "linux", "--splunk-home", str(home), "--service-user", getpass.getuser(), "--mgmt-port", management_port, "--ipc-port", "8194"],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False,
        )
        assert (result.returncode == 0) == (expected_rc == 0), result.stdout + result.stderr
