#!/usr/bin/env python3
"""Regression tests for Splunk MCP Server setup shell scripts."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from tests.regression_helpers import REPO_ROOT, ShellScriptRegressionBase, write_executable


class MCPRegressionTests(ShellScriptRegressionBase):
    def test_mcp_loaders_follow_shared_tls_policy(self):
        loader_paths = [
            "skills/cisco-catalyst-ta-setup/scripts/load_mcp_tools.sh",
            "skills/cisco-dc-networking-setup/scripts/load_mcp_tools.sh",
            "skills/cisco-enterprise-networking-setup/scripts/load_mcp_tools.sh",
            "skills/cisco-intersight-setup/scripts/load_mcp_tools.sh",
            "skills/cisco-meraki-ta-setup/scripts/load_mcp_tools.sh",
            "skills/cisco-thousandeyes-setup/scripts/load_mcp_tools.sh",
        ]

        for rel_path in loader_paths:
            with self.subTest(script=rel_path):
                script_text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
                self.assertIn("splunk_export_python_tls_env", script_text)
                self.assertNotIn("ssl.CERT_NONE", script_text)
                self.assertNotIn("check_hostname = False", script_text)


    def test_sanitize_response_reads_bodies_from_stdin_instead_of_process_args(self):
        script_text = (REPO_ROOT / "skills/shared/lib/rest_helpers.sh").read_text(encoding="utf-8")

        self.assertIn('3<<<"${resp}"', script_text)
        self.assertIn("os.fdopen(3", script_text)
        self.assertNotIn('python3 - "${max_lines}" "${resp}"', script_text)
        self.assertNotIn("text = sys.argv[2]", script_text)


    def test_splunk_mcp_setup_passes_response_body_directly_to_sanitize_response(self):
        script_text = (
            REPO_ROOT / "skills/splunk-mcp-server-setup/scripts/setup.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('sanitize_response "${body}" 10 >&2', script_text)
        self.assertNotIn('printf \'%s\\n\' "${body}" | sanitize_response 10 >&2', script_text)


    def test_splunk_mcp_validate_normalizes_boolean_expectations(self):
        script_text = (
            REPO_ROOT / "skills/splunk-mcp-server-setup/scripts/validate.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("normalize_boolean_if_possible()", script_text)
        self.assertIn(
            'SERVER_REQUIRE_ENCRYPTED_TOKEN_NORMALIZED="$(normalize_boolean_if_possible "${SERVER_REQUIRE_ENCRYPTED_TOKEN}")"',
            script_text,
        )
        self.assertIn(
            'assert_equal "require_encrypted_token" "${EXPECT_REQUIRE_ENCRYPTED_TOKEN}" "${SERVER_REQUIRE_ENCRYPTED_TOKEN_NORMALIZED}"',
            script_text,
        )


    def test_splunk_mcp_rendered_client_name_is_json_and_shell_safe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            home_dir = tmp_path / "home"
            home_dir.mkdir()
            output_dir = tmp_path / "rendered"
            codex_log = tmp_path / "codex-log.json"
            marker_path = tmp_path / "client-name-marker"
            client_name = f'bad"name$(touch {marker_path})'

            write_executable(
                bin_dir / "codex",
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path

                Path(os.environ["CODEX_LOG"]).write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
                """,
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["CODEX_LOG"] = str(codex_log)
            env["HOME"] = str(home_dir)

            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--mcp-url",
                "https://splunk.example:8089/services/mcp",
                "--output-dir",
                str(output_dir),
                "--client-name",
                client_name,
                "--no-register-codex",
                "--no-configure-cursor",
                "--no-configure-claude",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)

            rendered_config = json.loads((output_dir / ".cursor/mcp.json").read_text(encoding="utf-8"))
            self.assertIn(client_name, rendered_config["mcpServers"])
            self.assertEqual(
                rendered_config["mcpServers"][client_name]["command"],
                "node",
            )
            self.assertEqual(len(rendered_config["mcpServers"][client_name]["args"]), 1)
            self.assertIn("run-splunk-mcp.js", rendered_config["mcpServers"][client_name]["args"][0])

            register_result = subprocess.run(
                ["bash", str(output_dir / "register-codex-mcp.sh")],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(
                register_result.returncode,
                0,
                msg=register_result.stdout + register_result.stderr,
            )
            self.assertFalse(marker_path.exists(), "client-name command substitution should not execute")

            codex_args = json.loads(codex_log.read_text(encoding="utf-8"))
            self.assertEqual(codex_args[:3], ["mcp", "add", client_name])
            self.assertEqual(codex_args[3], "--")
            self.assertEqual(codex_args[4], "node")
            self.assertTrue(codex_args[5].startswith(str(home_dir / ".codex" / "mcp-bridges")))
            self.assertTrue(codex_args[5].endswith("/run-splunk-mcp.js"))


    def test_splunk_mcp_rendered_env_file_is_shell_safe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            output_dir = tmp_path / "rendered"
            token_file = tmp_path / "splunk.token"
            mcp_remote_log = tmp_path / "mcp-remote-log.json"
            url_marker = tmp_path / "url-marker"
            token_marker = tmp_path / "token-marker"
            mcp_url = f"https://splunk.example:8089/services/mcp?target=$(touch {url_marker})"
            token_value = f"tok en'\"$(touch {token_marker})\\tail"

            token_file.write_text(token_value, encoding="utf-8")
            token_file.chmod(0o600)

            write_executable(
                bin_dir / "mcp-remote",
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path

                payload = {
                    "args": sys.argv[1:],
                    "token": os.environ.get("SPLUNK_MCP_TOKEN"),
                    "url": os.environ.get("SPLUNK_MCP_URL"),
                }
                Path(os.environ["MCP_REMOTE_LOG"]).write_text(json.dumps(payload), encoding="utf-8")
                """,
            )

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["MCP_REMOTE_LOG"] = str(mcp_remote_log)

            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--mcp-url",
                mcp_url,
                "--bearer-token-file",
                str(token_file),
                "--output-dir",
                str(output_dir),
                "--no-register-codex",
                "--no-configure-cursor",
                "--no-configure-claude",
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)

            wrapper_result = subprocess.run(
                ["bash", str(output_dir / "run-splunk-mcp.sh")],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(
                wrapper_result.returncode,
                0,
                msg=wrapper_result.stdout + wrapper_result.stderr,
            )
            self.assertFalse(url_marker.exists(), "MCP URL command substitution should not execute")
            self.assertFalse(token_marker.exists(), "token command substitution should not execute")

            mcp_remote_payload = json.loads(mcp_remote_log.read_text(encoding="utf-8"))
            mcp_remote_args = mcp_remote_payload["args"]
            self.assertEqual(mcp_remote_args[0], mcp_url)
            self.assertEqual(mcp_remote_payload["token"], token_value)
            self.assertEqual(mcp_remote_payload["url"], mcp_url)
            self.assertEqual(
                mcp_remote_args[1:3],
                ["--header", "Authorization: Bearer ${SPLUNK_MCP_TOKEN}"],
            )
            self.assertNotIn(token_value, json.dumps(mcp_remote_args))

            node_path = shutil.which("node")
            if not node_path:
                self.skipTest("node is required to exercise the rendered JS wrapper")
            mcp_remote_log.unlink()
            js_wrapper_result = subprocess.run(
                [node_path, str(output_dir / "run-splunk-mcp.js")],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(
                js_wrapper_result.returncode,
                0,
                msg=js_wrapper_result.stdout + js_wrapper_result.stderr,
            )
            mcp_remote_payload = json.loads(mcp_remote_log.read_text(encoding="utf-8"))
            mcp_remote_args = mcp_remote_payload["args"]
            self.assertEqual(mcp_remote_args[0], mcp_url)
            self.assertEqual(mcp_remote_payload["token"], token_value)
            self.assertEqual(mcp_remote_payload["url"], mcp_url)
            self.assertEqual(
                mcp_remote_args[1:3],
                ["--header", "Authorization: Bearer ${SPLUNK_MCP_TOKEN}"],
            )
            self.assertNotIn(token_value, json.dumps(mcp_remote_args))


    def test_splunk_mcp_validate_uses_root_protected_resource_endpoint(self):
        script_text = (
            REPO_ROOT / "skills/splunk-mcp-server-setup/scripts/validate.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('/.well-known/oauth-protected-resource', script_text)
        self.assertNotIn('/services/.well-known/oauth-protected-resource', script_text)


    def test_mcp_setup_merges_existing_cursor_workspace_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            home_dir = tmp_path / "home"
            workspace_dir = tmp_path / "cursor-workspace"
            output_dir = tmp_path / "rendered"
            token_file = tmp_path / "splunk.token"
            cursor_dir = workspace_dir / ".cursor"
            cursor_dir.mkdir(parents=True)
            home_dir.mkdir()

            token_file.write_text("encrypted-token-value", encoding="utf-8")
            token_file.chmod(0o600)
            (cursor_dir / "mcp.json").write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "existing": {
                                "type": "stdio",
                                "command": "/bin/echo",
                                "args": ["hello"],
                            }
                        },
                        "notes": {"keep": True},
                    }
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["HOME"] = str(home_dir)

            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--mcp-url",
                "https://splunk.example.invalid:8089/services/mcp",
                "--bearer-token-file",
                str(token_file),
                "--output-dir",
                str(output_dir),
                "--cursor-workspace",
                str(workspace_dir),
                "--client-name",
                "splunk-merge",
                "--no-register-codex",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

            workspace_json = json.loads((cursor_dir / "mcp.json").read_text(encoding="utf-8"))
            self.assertEqual(workspace_json["notes"], {"keep": True})
            self.assertEqual(workspace_json["mcpServers"]["existing"]["command"], "/bin/echo")
            self.assertEqual(workspace_json["mcpServers"]["splunk-merge"]["command"], "node")
            self.assertEqual(len(workspace_json["mcpServers"]["splunk-merge"]["args"]), 1)
            self.assertEqual(
                Path(workspace_json["mcpServers"]["splunk-merge"]["args"][0]).resolve(),
                (output_dir / "run-splunk-mcp.js").resolve(),
            )
            self.assertEqual(workspace_json["mcpServers"]["splunk-merge"]["type"], "stdio")


    def test_mcp_setup_uses_workspace_relative_cursor_command_when_bundle_is_inside_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            home_dir = tmp_path / "home"
            workspace_dir = tmp_path / "cursor-workspace"
            output_dir = workspace_dir / "rendered"
            token_file = tmp_path / "splunk.token"
            home_dir.mkdir()
            workspace_dir.mkdir()

            token_file.write_text("encrypted-token-value", encoding="utf-8")
            token_file.chmod(0o600)

            env = os.environ.copy()
            env["HOME"] = str(home_dir)

            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--mcp-url",
                "https://splunk.example.invalid:8089/services/mcp",
                "--bearer-token-file",
                str(token_file),
                "--output-dir",
                str(output_dir),
                "--cursor-workspace",
                str(workspace_dir),
                "--client-name",
                "splunk-relative",
                "--no-register-codex",
                env=env,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

            workspace_json = json.loads((workspace_dir / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
            self.assertEqual(workspace_json["mcpServers"]["splunk-relative"]["command"], "node")
            self.assertEqual(
                workspace_json["mcpServers"]["splunk-relative"]["args"],
                ["${workspaceFolder}/rendered/run-splunk-mcp.js"],
            )
            self.assertEqual(workspace_json["mcpServers"]["splunk-relative"]["type"], "stdio")


    def test_mcp_setup_rejects_invalid_cursor_workspace_config_after_render(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            home_dir = tmp_path / "home"
            workspace_dir = tmp_path / "cursor-workspace"
            output_dir = tmp_path / "rendered"
            token_file = tmp_path / "splunk.token"
            cursor_dir = workspace_dir / ".cursor"
            cursor_dir.mkdir(parents=True)
            home_dir.mkdir()

            token_file.write_text("encrypted-token-value", encoding="utf-8")
            token_file.chmod(0o600)
            (cursor_dir / "mcp.json").write_text("{invalid json\n", encoding="utf-8")

            env = os.environ.copy()
            env["HOME"] = str(home_dir)

            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--mcp-url",
                "https://splunk.example.invalid:8089/services/mcp",
                "--bearer-token-file",
                str(token_file),
                "--output-dir",
                str(output_dir),
                "--cursor-workspace",
                str(workspace_dir),
                "--client-name",
                "splunk-invalid-cursor",
                "--no-register-codex",
                env=env,
            )

            self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
            self.assertIn("not valid JSON", result.stdout + result.stderr)
            self.assertTrue((output_dir / "run-splunk-mcp.sh").exists())
            self.assertTrue((output_dir / ".cursor" / "mcp.json").exists())


    def test_mcp_setup_defaults_cursor_workspace_to_current_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            home_dir = tmp_path / "home"
            workspace_dir = tmp_path / "cursor-workspace"
            output_dir = tmp_path / "rendered"
            token_file = tmp_path / "splunk.token"
            home_dir.mkdir()
            workspace_dir.mkdir()

            token_file.write_text("encrypted-token-value", encoding="utf-8")
            token_file.chmod(0o600)

            env = os.environ.copy()
            env["HOME"] = str(home_dir)

            result = subprocess.run(
                [
                    "bash",
                    str(REPO_ROOT / "skills/splunk-mcp-server-setup/scripts/setup.sh"),
                    "--render-clients",
                    "--mcp-url",
                    "https://splunk.example.invalid:8089/services/mcp",
                    "--bearer-token-file",
                    str(token_file),
                    "--output-dir",
                    str(output_dir),
                    "--client-name",
                    "splunk-default-workspace",
                    "--no-register-codex",
                ],
                cwd=workspace_dir,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            workspace_json = json.loads((workspace_dir / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
            self.assertEqual(workspace_json["mcpServers"]["splunk-default-workspace"]["command"], "node")
            self.assertEqual(len(workspace_json["mcpServers"]["splunk-default-workspace"]["args"]), 1)
            self.assertEqual(
                Path(workspace_json["mcpServers"]["splunk-default-workspace"]["args"][0]).resolve(),
                (output_dir / "run-splunk-mcp.js").resolve(),
            )


    def test_mcp_setup_repeated_runs_update_codex_registration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            home_dir = tmp_path / "home"
            output_dir_one = tmp_path / "rendered-one"
            output_dir_two = tmp_path / "rendered-two"
            token_file = tmp_path / "splunk.token"
            home_dir.mkdir()

            write_executable(
                bin_dir / "codex",
                """\
                #!/usr/bin/env python3
                import json, os, sys
                store = os.path.join(os.environ.get("HOME", "/tmp"), ".codex-mock-store")
                os.makedirs(store, exist_ok=True)
                args = sys.argv[1:]
                if len(args) >= 4 and args[0] == "mcp" and args[1] == "add":
                    name = args[2]
                    cmd = args[4] if len(args) > 4 else ""
                    cmd_args = args[5:] if len(args) > 5 else []
                    data = {"name": name, "transport": {"type": "stdio", "command": cmd, "args": cmd_args}}
                    with open(os.path.join(store, name + ".json"), "w") as f:
                        json.dump(data, f)
                elif len(args) >= 3 and args[0] == "mcp" and args[1] == "get":
                    name = args[2]
                    path = os.path.join(store, name + ".json")
                    if not os.path.exists(path):
                        print(f"Error: server '{name}' not found", file=sys.stderr)
                        sys.exit(1)
                    with open(path) as f:
                        data = json.load(f)
                    print(json.dumps(data))
                else:
                    print(f"mock codex: unsupported args: {args}", file=sys.stderr)
                    sys.exit(1)
                """,
            )

            token_file.write_text("encrypted-token-value", encoding="utf-8")
            token_file.chmod(0o600)

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["HOME"] = str(home_dir)

            first = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--mcp-url",
                "https://splunk.example.invalid:8089/services/mcp",
                "--bearer-token-file",
                str(token_file),
                "--output-dir",
                str(output_dir_one),
                "--client-name",
                "splunk-repeat",
                "--no-configure-cursor",
                "--no-configure-claude",
                env=env,
            )
            self.assertEqual(first.returncode, 0, msg=first.stdout + first.stderr)

            second = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--mcp-url",
                "https://splunk-two.example.invalid:8089/services/mcp",
                "--bearer-token-file",
                str(token_file),
                "--output-dir",
                str(output_dir_two),
                "--client-name",
                "splunk-repeat",
                "--no-configure-cursor",
                "--no-configure-claude",
                env=env,
            )
            self.assertEqual(second.returncode, 0, msg=second.stdout + second.stderr)

            registered = subprocess.run(
                ["codex", "mcp", "get", "splunk-repeat", "--json"],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(registered.returncode, 0, msg=registered.stdout + registered.stderr)

            data = json.loads(registered.stdout)
            self.assertEqual(data["transport"]["type"], "stdio")
            self.assertEqual(data["transport"]["command"], "node")
            self.assertEqual(len(data["transport"]["args"]), 1)
            self.assertEqual(
                Path(data["transport"]["args"][0]).resolve(),
                (home_dir / ".codex" / "mcp-bridges" / "splunk-repeat" / "run-splunk-mcp.js").resolve(),
            )
            stable_env = (home_dir / ".codex" / "mcp-bridges" / "splunk-repeat" / ".env.splunk-mcp").read_text(
                encoding="utf-8"
            )
            self.assertIn("https://splunk-two.example.invalid:8089/services/mcp", stable_env)


    def test_repo_cursor_config_tracks_workspace_relative_rendered_bundle(self):
        config = json.loads((REPO_ROOT / ".cursor" / "mcp.json").read_text(encoding="utf-8"))

        self.assertEqual(
            config,
            {
                "mcpServers": {
                    "splunk-mcp": {
                        "type": "stdio",
                        "command": "node",
                        "args": ["${workspaceFolder}/splunk-mcp-rendered/run-splunk-mcp.js"],
                    }
                }
            },
        )

    def test_repo_mcp_bridge_wrapper_exists_and_is_not_ignored(self):
        bridge = REPO_ROOT / "splunk-mcp-rendered" / "run-splunk-mcp.js"
        self.assertTrue(bridge.is_file(), "repo MCP configs must point at an available JS bridge")

        result = subprocess.run(
            ["git", "check-ignore", "--quiet", str(bridge.relative_to(REPO_ROOT))],
            cwd=REPO_ROOT,
            check=False,
        )
        self.assertEqual(result.returncode, 1, "the root MCP bridge must be tracked, not gitignored")

    def test_mcp_setup_writes_claude_mcp_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            workspace_dir = tmp_path / "workspace"
            workspace_dir.mkdir()
            output_dir = tmp_path / "rendered"

            env = os.environ.copy()
            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--mcp-url",
                "https://splunk.example:8089/services/mcp",
                "--output-dir",
                str(output_dir),
                "--client-name",
                "splunk-claude-test",
                "--no-register-codex",
                "--no-configure-cursor",
                "--cursor-workspace",
                str(workspace_dir),
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)

            claude_config_path = workspace_dir / ".mcp.json"
            self.assertTrue(claude_config_path.exists(), ".mcp.json should be written to workspace")

            config = json.loads(claude_config_path.read_text(encoding="utf-8"))
            self.assertIn("splunk-claude-test", config["mcpServers"])
            self.assertEqual(config["mcpServers"]["splunk-claude-test"]["type"], "stdio")

    def test_mcp_setup_merges_existing_claude_mcp_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            workspace_dir = tmp_path / "workspace"
            workspace_dir.mkdir()
            output_dir = tmp_path / "rendered"

            existing_config = {
                "mcpServers": {
                    "other-server": {
                        "type": "stdio",
                        "command": "/usr/local/bin/other-mcp",
                        "args": [],
                    }
                }
            }
            (workspace_dir / ".mcp.json").write_text(
                json.dumps(existing_config, indent=2), encoding="utf-8"
            )

            env = os.environ.copy()
            result = self.run_script(
                "skills/splunk-mcp-server-setup/scripts/setup.sh",
                "--render-clients",
                "--mcp-url",
                "https://splunk.example:8089/services/mcp",
                "--output-dir",
                str(output_dir),
                "--client-name",
                "splunk-merged",
                "--no-register-codex",
                "--no-configure-cursor",
                "--cursor-workspace",
                str(workspace_dir),
                env=env,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, msg=output)

            config = json.loads((workspace_dir / ".mcp.json").read_text(encoding="utf-8"))
            self.assertIn("other-server", config["mcpServers"], "existing entry should be preserved")
            self.assertIn("splunk-merged", config["mcpServers"], "new entry should be added")

    def test_repo_claude_mcp_config_tracks_rendered_bundle(self):
        config = json.loads((REPO_ROOT / ".mcp.json").read_text(encoding="utf-8"))

        self.assertEqual(
            config,
            {
                "mcpServers": {
                    "splunk-mcp": {
                        "type": "stdio",
                        "command": "node",
                        "args": ["./splunk-mcp-rendered/run-splunk-mcp.js"],
                    }
                }
            },
        )
