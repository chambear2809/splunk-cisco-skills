import os
import stat
import subprocess
import sys


HELPER = "skills/splunk-enterprise-host-setup/scripts/splunk_cli_auth_pty.py"


def _fake_cli(tmp_path):
    cli = tmp_path / "splunk"
    cli.write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, sys\n"
        "if sys.argv[1] == 'logout': pathlib.Path(os.environ['FAKE_CACHE'], 'logout_args').open('a').write(' '.join(sys.argv)+'\\n'); raise SystemExit(0)\n"
        "if sys.argv[1] == 'login':\n"
        " print('Username:', end='', flush=True); user = input()\n"
        " print('Password:', end='', flush=True); password = input()\n"
        " if user != 'admin' or password != 'secret': raise SystemExit(9)\n"
        " suffix = 'target' if '-uri' in sys.argv else 'new'; token = pathlib.Path(os.environ['FAKE_CACHE'], 'authToken_'+suffix); token.write_text('token'); token.chmod(0o600)\n"
        " raise SystemExit(0)\n"
    )
    cli.chmod(0o700)
    return cli


def _run(tmp_path, cli, password, command="true"):
    pw = tmp_path / "password"
    pw.write_text(password)
    pw.chmod(stat.S_IRUSR | stat.S_IWUSR)
    cache = tmp_path / "cache"
    cache.mkdir()
    cache.chmod(0o700)
    env = dict(os.environ, FAKE_CACHE=str(cache))
    return subprocess.run(
        [sys.executable, HELPER, "--splunk", str(cli), "--username", "admin",
         "--password-file", str(pw), "--cache-dir", str(cache),
         "--command", command], env=env, capture_output=True, text=True
    ), cache


def test_pty_login_succeeds_and_removes_only_new_cache(tmp_path):
    result, cache = _run(tmp_path, _fake_cli(tmp_path), "secret")
    assert result.returncode == 0, result.stderr
    assert not list(cache.glob("authToken_*"))
    assert b"secret" not in result.stdout.encode() + result.stderr.encode()


def test_existing_cache_is_preserved_and_no_login_is_attempted(tmp_path):
    cli = _fake_cli(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    cache.chmod(0o700)
    existing = cache / "authToken_existing"
    existing.write_text("token")
    existing.chmod(0o600)
    pw = tmp_path / "password"
    pw.write_text("secret\n")
    pw.chmod(0o600)
    result = subprocess.run(
        [sys.executable, HELPER, "--splunk", str(cli), "--username", "admin",
         "--password-file", str(pw), "--cache-dir", str(cache),
         "--command", "true"], env=dict(os.environ, FAKE_CACHE=str(cache)),
        capture_output=True, text=True
    )
    assert result.returncode == 0
    assert existing.read_text() == "token"


def test_native_service_cache_traversal_permissions_are_accepted(tmp_path):
    cli = _fake_cli(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    cache.chmod(0o710)
    existing = cache / "authToken_existing"
    existing.write_text("token")
    existing.chmod(0o600)
    pw = tmp_path / "password"
    pw.write_text("secret\n")
    pw.chmod(0o600)
    result = subprocess.run(
        [sys.executable, HELPER, "--splunk", str(cli), "--username", "admin",
         "--password-file", str(pw), "--cache-dir", str(cache), "--command", "true"],
        capture_output=True, text=True
    )
    assert result.returncode == 0


def test_cache_group_read_permission_fails_closed(tmp_path):
    cli = _fake_cli(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    cache.chmod(0o740)
    pw = tmp_path / "password"
    pw.write_text("secret\n")
    pw.chmod(0o600)
    result = subprocess.run(
        [sys.executable, HELPER, "--splunk", str(cli), "--username", "admin",
         "--password-file", str(pw), "--cache-dir", str(cache), "--command", "true"],
        capture_output=True, text=True
    )
    assert result.returncode != 0


def test_nonzero_authenticated_command_preserves_existing_cache(tmp_path):
    cli = _fake_cli(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    cache.chmod(0o700)
    token = cache / "authToken_existing"
    token.write_text("token")
    token.chmod(0o600)
    pw = tmp_path / "password"
    pw.write_text("secret\n")
    pw.chmod(0o600)
    result = subprocess.run(
        [sys.executable, HELPER, "--splunk", str(cli), "--username", "admin",
         "--password-file", str(pw), "--cache-dir", str(cache), "--command", "false"],
        capture_output=True, text=True
    )
    assert result.returncode != 0
    assert token.read_text() == "token"


def test_target_uri_login_creates_and_cleans_target_session(tmp_path):
    cli = _fake_cli(tmp_path)
    pw = tmp_path / "password"
    pw.write_text("secret\n")
    pw.chmod(0o600)
    cache = tmp_path / "cache"
    cache.mkdir()
    cache.chmod(0o700)
    result = subprocess.run(
        [sys.executable, HELPER, "--splunk", str(cli), "--username", "admin",
         "--password-file", str(pw), "--cache-dir", str(cache),
         "--login-uri", "https://member.example.com:8089", "--command", "true"],
        env=dict(os.environ, FAKE_CACHE=str(cache)), capture_output=True, text=True
    )
    assert result.returncode == 0
    assert not list(cache.glob("authToken_*"))
    logout_args = (cache / "logout_args").read_text()
    assert "-uri https://member.example.com:8089" in logout_args
    assert "splunk logout" in logout_args


def test_failed_target_login_cleans_partial_token_with_existing_local_cache(tmp_path):
    cli = _fake_cli(tmp_path)
    pw = tmp_path / "password"
    pw.write_text("wrong\n")
    pw.chmod(0o600)
    cache = tmp_path / "cache"
    cache.mkdir()
    cache.chmod(0o700)
    local = cache / "authToken_local_8089"
    local.write_text("local")
    local.chmod(0o600)
    result = subprocess.run(
        [sys.executable, HELPER, "--splunk", str(cli), "--username", "admin",
         "--password-file", str(pw), "--cache-dir", str(cache),
         "--login-uri", "https://member.example.com:8089", "--command", "true"],
        env=dict(os.environ, FAKE_CACHE=str(cache)), capture_output=True, text=True
    )
    assert result.returncode != 0
    assert local.exists()
    assert not (cache / "authToken_target").exists()


def test_invalid_target_uri_fails_closed(tmp_path):
    cli = _fake_cli(tmp_path)
    result, cache = _run(tmp_path, cli, "secret")
    # A malformed additional URI is rejected before any target login.
    pw = tmp_path / "password"
    pw.chmod(0o600)
    result = subprocess.run(
        [sys.executable, HELPER, "--splunk", str(cli), "--username", "admin",
         "--password-file", str(pw), "--cache-dir", str(cache),
         "--login-uri", "https://member.example.com/path", "--command", "true"],
        env=dict(os.environ, FAKE_CACHE=str(cache)), capture_output=True, text=True
    )
    assert result.returncode != 0


def test_bad_password_file_fails_closed(tmp_path):
    cli = _fake_cli(tmp_path)
    password = tmp_path / "password"
    password.write_text("secret\n")
    password.chmod(0o644)
    cache = tmp_path / "cache"
    cache.mkdir()
    result = subprocess.run(
        [sys.executable, HELPER, "--splunk", str(cli), "--username", "admin",
         "--password-file", str(password), "--cache-dir", str(cache),
         "--command", "true"], capture_output=True, text=True
    )
    assert result.returncode != 0


def test_symlink_password_file_fails_closed(tmp_path):
    cli = _fake_cli(tmp_path)
    real = tmp_path / "real"
    real.write_text("secret\n")
    real.chmod(0o600)
    password = tmp_path / "password"
    password.symlink_to(real)
    cache = tmp_path / "cache"
    cache.mkdir()
    cache.chmod(0o700)
    result = subprocess.run(
        [sys.executable, HELPER, "--splunk", str(cli), "--username", "admin",
         "--password-file", str(password), "--cache-dir", str(cache),
         "--command", "true"], capture_output=True, text=True
    )
    assert result.returncode != 0


def test_failed_login_cleans_token_created_before_failure(tmp_path):
    cli = _fake_cli(tmp_path)
    result, cache = _run(tmp_path, cli, "wrong")
    assert result.returncode != 0
    assert not list(cache.glob("authToken_*"))


def test_authenticated_command_timeout_fails_closed(tmp_path):
    cli = _fake_cli(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()
    cache.chmod(0o700)
    (cache / "authToken_existing").write_text("token")
    pw = tmp_path / "password"
    pw.write_text("secret\n")
    pw.chmod(0o600)
    result = subprocess.run(
        [sys.executable, HELPER, "--splunk", str(cli), "--username", "admin",
         "--password-file", str(pw), "--cache-dir", str(cache), "--timeout", "0.1",
         "--command", "sleep 2"], capture_output=True, text=True
    )
    assert result.returncode != 0
