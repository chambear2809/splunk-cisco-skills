"""Fresh service-account creation must elevate the entire conditional command."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_missing_service_user_creation_is_privileged():
    source = (ROOT / "skills/splunk-enterprise-host-setup/scripts/setup.sh").read_text()
    function = source.split("ensure_service_user_exists() {", 1)[1].split("\n}\n", 1)[0]
    script = """
source skills/shared/lib/credential_helpers.sh
source skills/shared/lib/host_bootstrap_helpers.sh
EXECUTION_MODE=local
SERVICE_USER=validation_user
SPLUNK_HOME=/opt/test
hbs_target_sudo_prefix() { printf 'sudo'; }
sudo() { PRIVILEGED=yes "$@"; }
id() { return 1; }
useradd() { [[ "$PRIVILEGED" == yes ]]; }
export -f sudo id useradd
hbs_run_target_cmd() { bash -c "$2"; }
log() { printf '%s\n' "$*" >&2; }
""" + "ensure_service_user_exists() {" + function + "\n}\nensure_service_user_exists\n"
    result = subprocess.run(["bash", "-c", script], cwd=ROOT, text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
