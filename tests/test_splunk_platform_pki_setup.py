"""Real OpenSSL regressions for private platform PKI generation."""

import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "skills/splunk-platform-pki-setup/scripts/setup.sh"
RENDERER = ROOT / "skills/splunk-platform-pki-setup/scripts/render_assets.py"


def test_private_ca_and_web_leaf_strict_chain(tmp_path: Path) -> None:
    """Default optional DN fields and all generated certs pass strict verify."""
    out = tmp_path / "rendered"
    subprocess.run(
        [
            "bash", str(SETUP), "--phase", "render", "--mode", "private",
            "--target", "core5", "--single-sh-fqdn", "localhost",
            "--enable-mtls", "none", "--splunk-version", "10.6.0",
            "--output-dir", str(out), "--json",
        ], check=True, capture_output=True, text=True,
    )
    home = tmp_path / "splunk"
    (home / "bin").mkdir(parents=True)
    openssl = subprocess.run(["sh", "-c", "command -v openssl"], check=True,
                             capture_output=True, text=True).stdout.strip()
    wrapper = home / "bin/splunk"
    wrapper.write_text(f"#!/usr/bin/env bash\nshift 2\nexec {openssl} \"$@\"\n")
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
    passwords = tmp_path / "passwords"
    passwords.mkdir()
    for name, value in (("root", "root"), ("intermediate", "intermediate"), ("leaf", "leaf")):
        path = passwords / name
        path.write_text(value + "\n")
        path.chmod(0o600)
    ca = out / "platform-pki/pki/private-ca"
    signed = tmp_path / "signed"
    env = {**os.environ, "SPLUNK_HOME": str(home), "OUT_DIR": str(signed)}
    env.update(PKI_ROOT_CA_KEY_PASSWORD_FILE=str(passwords / "root"))
    subprocess.run(["bash", str(ca / "create-root-ca.sh")], cwd=ca, env=env, check=True,
                   capture_output=True, text=True)
    env.update(PKI_INTERMEDIATE_CA_KEY_PASSWORD_FILE=str(passwords / "intermediate"))
    subprocess.run(["bash", str(ca / "create-intermediate-ca.sh")], cwd=ca, env=env,
                   check=True, capture_output=True, text=True)
    env.update(PKI_LEAF_KEY_PASSWORD_FILE=str(passwords / "leaf"))
    subprocess.run(
        ["bash", str(ca / "sign-server-cert.sh"), "--name", "web-localhost",
         "--san", "DNS:localhost,IP:127.0.0.1"], cwd=ca, env=env, check=True,
        capture_output=True, text=True,
    )
    leaf = signed / "web-localhost.pem"
    bundle = signed / "cabundle.pem"
    subprocess.run([openssl, "verify", "-x509_strict", "-CAfile", str(bundle), str(leaf)],
                   check=True, capture_output=True, text=True)
    details = subprocess.run([openssl, "x509", "-in", str(leaf), "-noout", "-text"],
                             check=True, capture_output=True, text=True).stdout
    assert "DNS:localhost" in details and "IP Address:127.0.0.1" in details
    assert "TLS Web Server Authentication" in details
    assert "TLS Web Client Authentication" in details
    assert "ST =" not in (ca / "openssl-root.cnf").read_text()
    assert "L  =" not in (ca / "openssl-root.cnf").read_text()


def test_leaf_installer_repairs_only_new_install_subdir_permissions(tmp_path: Path) -> None:
    """A restrictive root umask must not strand a newly created myssl parent.

    Existing install directories are deliberately left for an operator to
    repair; the generated installer must fail closed instead of silently
    changing an existing target's permissions.
    """
    out = tmp_path / "rendered"
    subprocess.run(
        [
            "python3", str(RENDERER), "--mode", "private", "--target", "core5",
            "--single-sh-fqdn", "localhost", "--enable-mtls", "none",
            "--splunk-version", "10.6.0", "--output-dir", str(out),
        ], check=True, capture_output=True, text=True,
    )
    installer = (out / "platform-pki/pki/install/install-leaf.sh").read_text()
    assert 'INSTALL_ROOT="$SPLUNK_HOME/etc/auth/$INSTALL_SUBDIR"' in installer
    assert 'mkdir "$INSTALL_ROOT"' in installer
    assert 'chmod 0750 "$INSTALL_ROOT"' in installer
    assert 'set_splunk_owner "$INSTALL_ROOT"' in installer
    assert 'service_can_traverse() {' in installer
    assert 'if ! service_can_traverse; then' in installer
    # The existing target check precedes DEST creation, so an inaccessible
    # pre-existing parent cannot be repaired implicitly by mkdir -p/chown.
    assert installer.index('if ! service_can_traverse; then') < installer.index('DEST="$INSTALL_ROOT/$HOST"')
