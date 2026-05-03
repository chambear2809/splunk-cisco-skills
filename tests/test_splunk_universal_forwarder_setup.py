from __future__ import annotations

import hashlib
import getpass
import json
import os
import subprocess
import tarfile
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP = REPO_ROOT / "skills/splunk-universal-forwarder-setup/scripts/setup.sh"
RENDERER = REPO_ROOT / "skills/splunk-universal-forwarder-setup/scripts/render_assets.py"


def sha512_hex(value: str) -> str:
    return hashlib.sha512(value.encode("utf-8")).hexdigest()


def write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    path.chmod(0o755)


def write_mock_curl(path: Path) -> None:
    write_executable(
        path,
        r"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

state = json.loads(Path(os.environ["MOCK_CURL_STATE"]).read_text())
args = sys.argv[1:]
output = None
url = None
skip = False
for index, arg in enumerate(args):
    if skip:
        skip = False
        continue
    if arg == "-o" and index + 1 < len(args):
        output = args[index + 1]
        skip = True
        continue
    if arg == "-K" and index + 1 < len(args):
        skip = True
        continue
    if arg.startswith("http"):
        url = arg
if not url:
    raise SystemExit(2)
if os.environ.get("CURL_LOG"):
    with open(os.environ["CURL_LOG"], "a", encoding="utf-8") as fh:
        fh.write(url + "\n")
if url in state.get("fail", []):
    raise SystemExit(22)
if output:
    Path(output).write_text(state.get("files", {}).get(url, ""), encoding="utf-8")
else:
    sys.stdout.write(state.get("text", {}).get(url, ""))
""",
    )


def uf_link(version: str, platform: str, filename: str, arch: str) -> str:
    url = f"https://download.splunk.com/products/universalforwarder/releases/{version}/{platform}/{filename}"
    return (
        f'<a data-arch="{arch}" data-filename="{filename}" data-link="{url}" '
        f'data-sha512="{url}.sha512" data-version="{version}" href="#">Download</a>'
    )


def download_fixture_html(version: str = "10.2.3") -> str:
    build = "4d61cf8a5c0c"
    legacy = "6360f015cdfb"
    rows = [
        uf_link(version, "linux", f"splunkforwarder-{version}-{build}-linux-amd64.tgz", "x86_64"),
        uf_link(version, "linux", f"splunkforwarder-{version}-{build}-linux-amd64.deb", "x86_64"),
        uf_link(version, "linux", f"splunkforwarder-{version}-{build}.x86_64.rpm", "x86_64"),
        uf_link(version, "linux", f"splunkforwarder-{version}-{build}-linux-arm64.tgz", "arm64"),
        uf_link(version, "linux", f"splunkforwarder-{version}-{build}-linux-arm64.deb", "arm64"),
        uf_link(version, "linux", f"splunkforwarder-{version}-{build}.aarch64.rpm", "arm64"),
        uf_link(version, "linux", f"splunkforwarder-{version}-{legacy}-linux-ppc64le.tgz", "ppc64le"),
        uf_link(version, "linux", f"splunkforwarder-{version}-{legacy}.ppc64le.rpm", "ppc64le"),
        uf_link(version, "linux", f"splunkforwarder-{version}-{legacy}-linux-s390x.tgz", "s390x"),
        uf_link(version, "linux", f"splunkforwarder-{version}-{legacy}.s390x.rpm", "s390x"),
        uf_link(version, "windows", f"splunkforwarder-{version}-{legacy}-windows-x86.msi", "x86"),
        uf_link(version, "windows", f"splunkforwarder-{version}-{build}-windows-x64.msi", "x86_64"),
        uf_link(version, "osx", f"splunkforwarder-{version}-{build}-darwin-intel.tgz", "x86_64"),
        uf_link(version, "osx", f"splunkforwarder-{version}-{build}-darwin-intel.dmg", "x86_64"),
        uf_link(version, "osx", f"splunkforwarder-{version}-{build}-darwin-universal2.tgz", "universal2"),
        uf_link(version, "osx", f"splunkforwarder-{version}-{build}-darwin-universal2.dmg", "universal2"),
        uf_link(version, "freebsd", f"splunkforwarder-{version}-{legacy}-freebsd14-amd64.tgz", "x86_64"),
        uf_link(version, "freebsd", f"splunkforwarder-{version}-{legacy}-freebsd14-amd64.txz", "x86_64"),
        uf_link(version, "freebsd", f"splunkforwarder-{version}-{legacy}-freebsd13-amd64.tgz", "x86_64"),
        uf_link(version, "solaris", f"splunkforwarder-{version}-{legacy}-solaris-amd64.tar.Z", "x86_64"),
        uf_link(version, "solaris", f"splunkforwarder-{version}-{legacy}-solaris-amd64.p5p", "x86_64"),
        uf_link(version, "solaris", f"splunkforwarder-{version}-{legacy}-solaris-sparc.tar.Z", "sparc"),
        uf_link(version, "solaris", f"splunkforwarder-{version}-{legacy}-solaris-sparc.p5p", "sparc"),
        uf_link(version, "aix", f"splunkforwarder-{version}-{legacy}-aix-powerpc.tgz", "powerpc"),
    ]
    return "<h1>Splunk Universal Forwarder 10.2.3</h1>\n" + "\n".join(rows)


class UniversalForwarderSetupTests(unittest.TestCase):
    def run_script(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(args),
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_latest_resolver_parses_current_package_matrix_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            state_file = tmp_path / "state.json"
            write_mock_curl(bin_dir / "curl")
            page_url = "https://example.invalid/uf"
            state_file.write_text(json.dumps({"text": {page_url: download_fixture_html()}}), encoding="utf-8")
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "MOCK_CURL_STATE": str(state_file),
                    "HBS_UNIVERSAL_FORWARDER_DOWNLOAD_PAGE_URL": page_url,
                }
            )

            cases = [
                ("linux", "amd64", "tgz", "linux-amd64.tgz", "local-ssh"),
                ("linux", "arm64", "deb", "linux-arm64.deb", "local-ssh"),
                ("linux", "ppc64le", "rpm", "ppc64le.rpm", "local-ssh"),
                ("linux", "s390x", "tgz", "linux-s390x.tgz", "local-ssh"),
                ("windows", "x86", "msi", "windows-x86.msi", "render-only"),
                ("windows", "x64", "msi", "windows-x64.msi", "render-only"),
                ("macos", "intel", "tgz", "darwin-intel.tgz", "local-ssh"),
                ("macos", "universal2", "dmg", "darwin-universal2.dmg", "download-only"),
                ("freebsd", "amd64", "txz", "freebsd14-amd64.txz", "unsupported-v1"),
                ("solaris", "sparc", "tar-z", "solaris-sparc.tar.Z", "unsupported-v1"),
                ("aix", "powerpc", "tgz", "aix-powerpc.tgz", "unsupported-v1"),
            ]
            for target_os, arch, package_type, filename_part, apply_state in cases:
                with self.subTest(target_os=target_os, arch=arch, package_type=package_type):
                    result = self.run_script(
                        "bash",
                        "-c",
                        (
                            "source skills/shared/lib/credential_helpers.sh; "
                            "source skills/shared/lib/host_bootstrap_helpers.sh; "
                            f"hbs_resolve_latest_universal_forwarder_download_metadata {target_os} {arch} {package_type}"
                        ),
                        env=env,
                    )
                    self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
                    metadata = json.loads(result.stdout)
                    self.assertIn(filename_part, metadata["filename"])
                    self.assertEqual(metadata["v1_apply"], apply_state)
                    self.assertEqual(metadata["version"], "10.2.3")

    def test_latest_resolver_auto_defaults_cover_non_core_platforms(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            state_file = tmp_path / "state.json"
            write_mock_curl(bin_dir / "curl")
            page_url = "https://example.invalid/uf"
            state_file.write_text(json.dumps({"text": {page_url: download_fixture_html()}}), encoding="utf-8")
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "MOCK_CURL_STATE": str(state_file),
                    "HBS_UNIVERSAL_FORWARDER_DOWNLOAD_PAGE_URL": page_url,
                }
            )

            cases = [
                ("freebsd", "auto", "freebsd14-amd64.tgz"),
                ("solaris", "auto", "solaris-amd64.tar.Z"),
                ("aix", "auto", "aix-powerpc.tgz"),
            ]
            for target_os, package_type, filename_part in cases:
                with self.subTest(target_os=target_os):
                    result = self.run_script(
                        "bash",
                        "-c",
                        (
                            "source skills/shared/lib/credential_helpers.sh; "
                            "source skills/shared/lib/host_bootstrap_helpers.sh; "
                            f"hbs_resolve_latest_universal_forwarder_download_metadata {target_os} auto {package_type}"
                        ),
                        env=env,
                    )
                    self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
                    metadata = json.loads(result.stdout)
                    self.assertIn(filename_part, metadata["filename"])
                    self.assertEqual(metadata["v1_apply"], "unsupported-v1")

    def test_windows_renderer_keeps_secret_values_out_of_scripts_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            secret_file = tmp_path / "password.txt"
            secret_file.write_text("SuperSecretPassword123!", encoding="utf-8")
            result = self.run_script(
                "python3",
                str(RENDERER),
                "--output-dir",
                str(tmp_path / "rendered"),
                "--target-os",
                "windows",
                "--package-type",
                "msi",
                "--package-path",
                r"C:\Temp\splunkforwarder.msi",
                "--admin-password-file",
                str(secret_file),
                "--enroll",
                "enterprise-indexers",
                "--server-list",
                "idx01.example.com:9997,idx02.example.com:9997",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            rendered = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (tmp_path / "rendered/universal-forwarder").iterdir()
                if path.is_file()
            )
            self.assertNotIn("SuperSecretPassword123!", rendered)
            self.assertNotIn("SPLUNKPASSWORD", rendered)
            self.assertIn("LAUNCHSPLUNK=0", rendered)
            self.assertIn("Quote-ProcessArgument $PackagePath", rendered)
            self.assertIn("'INSTALLDIR=' + (Quote-ProcessArgument $SplunkHome)", rendered)
            self.assertIn("user-seed.conf", rendered)

    def test_windows_setup_render_defaults_to_render_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "bash",
                str(SETUP),
                "--phase",
                "render",
                "--target-os",
                "windows",
                "--source",
                "local",
                "--file",
                r"C:\Temp\splunkforwarder-10.2.3-4d61cf8a5c0c-windows-x64.msi",
                "--output-dir",
                str(Path(tmpdir) / "rendered"),
                "--dry-run",
                "--json",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertIn("install-universal-forwarder.ps1", payload["files"])
            self.assertEqual(payload["metadata"]["v1_apply"], "render-only")

    def test_non_core_and_dmg_apply_dry_runs_are_plannable(self) -> None:
        cases = [
            ("freebsd", "auto"),
            ("solaris", "tar-z"),
            ("aix", "tgz"),
            ("macos", "dmg"),
        ]
        for target_os, package_type in cases:
            with self.subTest(target_os=target_os, package_type=package_type):
                result = self.run_script(
                    "bash",
                    str(SETUP),
                    "--phase",
                    "install",
                    "--target-os",
                    target_os,
                    "--package-type",
                    package_type,
                    "--dry-run",
                    "--json",
                )
                self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["workflow"], "splunk-universal-forwarder-setup")

    def test_renderer_marks_unsupported_and_download_only_apply_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "python3",
                str(RENDERER),
                "--output-dir",
                str(Path(tmpdir) / "rendered"),
                "--target-os",
                "freebsd",
                "--package-type",
                "txz",
                "--package-path",
                "/tmp/splunkforwarder-10.2.3-6360f015cdfb-freebsd14-amd64.txz",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = Path(tmpdir) / "rendered/universal-forwarder"
            metadata = json.loads((render_dir / "metadata.json").read_text(encoding="utf-8"))
            script = (render_dir / "apply-universal-forwarder.sh").read_text(encoding="utf-8")
            self.assertEqual(metadata["v1_apply"], "unsupported-v1")
            self.assertIn("unsupported in v1", script)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "python3",
                str(RENDERER),
                "--output-dir",
                str(Path(tmpdir) / "rendered"),
                "--target-os",
                "macos",
                "--package-type",
                "dmg",
                "--package-path",
                "/tmp/splunkforwarder-10.2.3-4d61cf8a5c0c-darwin-universal2.dmg",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            script = (Path(tmpdir) / "rendered/universal-forwarder/apply-universal-forwarder.sh").read_text(encoding="utf-8")
            self.assertIn("download/verify only", script)

    def test_renderer_accepts_bracketed_ipv6_enrollment_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "python3",
                str(RENDERER),
                "--output-dir",
                str(Path(tmpdir) / "rendered"),
                "--target-os",
                "linux",
                "--enroll",
                "enterprise-indexers",
                "--server-list",
                "[2001:db8::10]:9997,idx01.example.com:9997",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            outputs = (Path(tmpdir) / "rendered/universal-forwarder/outputs.conf").read_text(encoding="utf-8")
            self.assertIn("[2001:db8::10]:9997,idx01.example.com:9997", outputs)

    def test_setup_rendered_apply_script_preserves_operator_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            package = tmp_path / "splunkforwarder-10.2.3-4d61cf8a5c0c-linux-amd64.tgz"
            password_file = tmp_path / "password"
            package.write_text("not-a-real-package", encoding="utf-8")
            password_file.write_text("SuperSecretPassword123!", encoding="utf-8")
            result = self.run_script(
                "bash",
                str(SETUP),
                "--phase",
                "render",
                "--target-os",
                "linux",
                "--source",
                "local",
                "--file",
                str(package),
                "--output-dir",
                str(tmp_path / "rendered"),
                "--enroll",
                "deployment-server",
                "--deployment-server",
                "ds01.example.com:8089",
                "--client-name",
                "web01",
                "--admin-password-file",
                str(password_file),
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            script = (tmp_path / "rendered/universal-forwarder/apply-universal-forwarder.sh").read_text(encoding="utf-8")
            self.assertIn(str(SETUP), script)
            self.assertIn("--phase all", script)
            self.assertIn("--source local", script)
            self.assertIn("--package-type tgz", script)
            self.assertIn("--deployment-server ds01.example.com:8089", script)
            self.assertIn("--client-name web01", script)
            self.assertIn(str(package), script)
            self.assertIn(str(password_file), script)
            self.assertNotIn("SuperSecretPassword123!", script)

    def test_direct_renderer_supported_apply_script_is_review_only_without_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "python3",
                str(RENDERER),
                "--output-dir",
                str(Path(tmpdir) / "rendered"),
                "--target-os",
                "linux",
                "--package-type",
                "tgz",
                "--package-path",
                "/tmp/splunkforwarder-10.2.3-4d61cf8a5c0c-linux-amd64.tgz",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            script = (Path(tmpdir) / "rendered/universal-forwarder/apply-universal-forwarder.sh").read_text(encoding="utf-8")
            self.assertIn("No automated apply command was rendered", script)
            self.assertNotIn("exec bash skills/splunk-universal-forwarder-setup/scripts/setup.sh --phase all", script)

    def test_renderer_rejects_empty_server_list_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "python3",
                str(RENDERER),
                "--output-dir",
                str(Path(tmpdir) / "rendered"),
                "--target-os",
                "linux",
                "--enroll",
                "enterprise-indexers",
                "--server-list",
                "idx01.example.com:9997,,idx02.example.com:9997",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must not contain empty entries", result.stdout + result.stderr)

    def test_setup_rejects_invalid_target_arch_in_safe_phases(self) -> None:
        result = self.run_script(
            "bash",
            str(SETUP),
            "--phase",
            "render",
            "--target-os",
            "linux",
            "--target-arch",
            "not-a-real-arch",
            "--dry-run",
            "--json",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not valid for target OS 'linux'", result.stdout + result.stderr)

    def test_renderer_rejects_package_path_type_mismatch_without_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "python3",
                str(RENDERER),
                "--output-dir",
                str(Path(tmpdir) / "rendered"),
                "--target-os",
                "linux",
                "--package-type",
                "rpm",
                "--package-path",
                "/tmp/splunkforwarder-10.2.3-4d61cf8a5c0c-linux-amd64.deb",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not match detected package type deb", result.stdout + result.stderr)

    def test_setup_rejects_wrong_package_type_for_target_os_in_render(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "bash",
                str(SETUP),
                "--phase",
                "render",
                "--target-os",
                "linux",
                "--source",
                "local",
                "--file",
                "/tmp/splunkforwarder-10.2.3-4d61cf8a5c0c-windows-x64.msi",
                "--output-dir",
                str(Path(tmpdir) / "rendered"),
                "--dry-run",
                "--json",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Package type 'msi' is not valid for target OS 'linux'", result.stdout + result.stderr)

    def test_download_latest_verifies_sha512_and_writes_uf_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            state_file = tmp_path / "state.json"
            credentials_file = tmp_path / "credentials"
            curl_log = tmp_path / "curl.log"
            credentials_file.write_text("", encoding="utf-8")
            write_mock_curl(bin_dir / "curl")
            package_name = "splunkforwarder-10.2.3-4d61cf8a5c0c-linux-amd64.tgz"
            package_url = f"https://download.splunk.com/products/universalforwarder/releases/10.2.3/linux/{package_name}"
            sha_url = f"{package_url}.sha512"
            package_path = REPO_ROOT / "splunk-ta" / package_name
            metadata_path = REPO_ROOT / "splunk-ta/.latest-splunk-universal-forwarder-linux-amd64-tgz.json"
            package_path.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
            self.addCleanup(lambda: package_path.unlink(missing_ok=True))
            self.addCleanup(lambda: metadata_path.unlink(missing_ok=True))
            state_file.write_text(
                json.dumps(
                    {
                        "text": {
                            "https://example.invalid/uf": download_fixture_html(),
                            sha_url: f"{sha512_hex('uf-package')}  {package_name}\n",
                        },
                        "files": {package_url: "uf-package"},
                    }
                ),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "MOCK_CURL_STATE": str(state_file),
                    "CURL_LOG": str(curl_log),
                    "SPLUNK_CREDENTIALS_FILE": str(credentials_file),
                    "HBS_UNIVERSAL_FORWARDER_DOWNLOAD_PAGE_URL": "https://example.invalid/uf",
                }
            )
            result = self.run_script(
                "bash",
                str(SETUP),
                "--phase",
                "download",
                "--target-os",
                "linux",
                "--target-arch",
                "amd64",
                "--package-type",
                "tgz",
                "--source",
                "remote",
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertTrue(package_path.exists())
            self.assertTrue(metadata_path.exists())
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["sha512"], sha512_hex("uf-package"))
            self.assertIn(sha_url, curl_log.read_text(encoding="utf-8"))

    def test_explicit_package_type_must_match_detected_file_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package = Path(tmpdir) / "splunkforwarder-10.2.3-4d61cf8a5c0c-linux-amd64.deb"
            package.write_text("not-a-real-deb", encoding="utf-8")
            result = self.run_script(
                "bash",
                str(SETUP),
                "--phase",
                "download",
                "--target-os",
                "linux",
                "--source",
                "local",
                "--file",
                str(package),
                "--package-type",
                "rpm",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not match detected package type deb", result.stdout + result.stderr)

    def test_setup_rejects_dmg_apply_with_clear_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package = Path(tmpdir) / "splunkforwarder-10.2.3-4d61cf8a5c0c-darwin-universal2.dmg"
            package.write_text("not-a-real-dmg", encoding="utf-8")
            result = self.run_script(
                "bash",
                str(SETUP),
                "--phase",
                "install",
                "--target-os",
                "macos",
                "--source",
                "local",
                "--file",
                str(package),
                "--package-type",
                "dmg",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Use --package-type tgz for automated apply", result.stdout + result.stderr)

    def test_setup_rejects_uf_over_enterprise_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            splunk_home = tmp_path / "splunk"
            (splunk_home / "bin").mkdir(parents=True)
            write_executable(
                splunk_home / "bin/splunk",
                """#!/usr/bin/env bash
                echo 'Splunk 10.2.3 (build abc)'
                """,
            )
            package = tmp_path / "splunkforwarder-10.2.3-4d61cf8a5c0c-linux-amd64.tgz"
            package.write_text("not-needed", encoding="utf-8")
            env = os.environ.copy()
            env["SPLUNK_LOCAL_SUDO"] = "false"
            result = self.run_script(
                "bash",
                str(SETUP),
                "--phase",
                "install",
                "--target-os",
                "linux",
                "--source",
                "local",
                "--file",
                str(package),
                "--package-type",
                "tgz",
                "--splunk-home",
                str(splunk_home),
                "--service-user",
                getpass.getuser(),
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing to install UF over Splunk Enterprise", result.stdout + result.stderr)

    def test_same_version_existing_uf_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            splunk_home = tmp_path / "splunkforwarder"
            (splunk_home / "bin").mkdir(parents=True)
            write_executable(
                splunk_home / "bin/splunk",
                """#!/usr/bin/env bash
                if [[ "$1" == "version" ]]; then
                  echo 'Splunk Universal Forwarder 10.2.3 (build abc)'
                else
                  echo 'splunkd is running'
                fi
                """,
            )
            (splunk_home / "etc").mkdir()
            (splunk_home / "etc/splunk.version").write_text("PRODUCT=splunkforwarder\n", encoding="utf-8")
            package = tmp_path / "splunkforwarder-10.2.3-4d61cf8a5c0c-linux-amd64.tgz"
            package.write_text("not-needed", encoding="utf-8")
            env = os.environ.copy()
            env["SPLUNK_LOCAL_SUDO"] = "false"
            result = self.run_script(
                "bash",
                str(SETUP),
                "--phase",
                "install",
                "--target-os",
                "linux",
                "--source",
                "local",
                "--file",
                str(package),
                "--package-type",
                "tgz",
                "--splunk-home",
                str(splunk_home),
                "--service-user",
                getpass.getuser(),
                env=env,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("already matches requested package; skipping install", result.stdout)

    def test_unsafe_archive_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            package = tmp_path / "splunkforwarder-10.2.3-4d61cf8a5c0c-linux-amd64.tgz"
            with tarfile.open(package, "w:gz") as archive:
                info = tarfile.TarInfo("../evil")
                payload = b"bad"
                info.size = len(payload)
                import io

                archive.addfile(info, io.BytesIO(payload))
            password_file = tmp_path / "password"
            password_file.write_text("abcdefgh", encoding="utf-8")
            env = os.environ.copy()
            env["SPLUNK_LOCAL_SUDO"] = "false"
            result = self.run_script(
                "bash",
                str(SETUP),
                "--phase",
                "install",
                "--target-os",
                "linux",
                "--source",
                "local",
                "--file",
                str(package),
                "--package-type",
                "tgz",
                "--splunk-home",
                str(tmp_path / "opt/splunkforwarder"),
                "--service-user",
                getpass.getuser(),
                "--admin-password-file",
                str(password_file),
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Unsafe package archive member", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
