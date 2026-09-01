"""End-to-end MCP stdio protocol coverage for the repo-local agent server."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from skills.shared.skill_catalog import load_catalog

try:
    from mcp import MCPError, ClientSession, StdioServerParameters, types as mcp_types
    from mcp.client.stdio import stdio_client
except (
    ModuleNotFoundError
):  # pragma: no cover - requirements-agent.txt supplies MCP in CI
    ClientSession = None  # type: ignore[assignment,misc]
    StdioServerParameters = None  # type: ignore[assignment,misc]
    mcp_types = None  # type: ignore[assignment]
    MCPError = Exception  # type: ignore[assignment,misc]
    stdio_client = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "agent/run-splunk-cisco-skills-mcp.py"


@unittest.skipIf(ClientSession is None, "requires requirements-agent.txt")
class AgentMCPProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def assert_invalid_tool_request(
        self,
        client: ClientSession,
        name: str,
        arguments: dict[str, object],
        *,
        expected_message: str = "Invalid tool arguments",
        absent_values: tuple[str, ...] = (),
    ) -> MCPError:
        with self.assertRaises(MCPError) as raised:
            await client.call_tool(name, arguments)

        error = raised.exception.error
        self.assertEqual(error.code, mcp_types.INVALID_PARAMS)
        self.assertIn(expected_message, error.message)
        serialized = str(error.model_dump(mode="json"))
        for value in absent_values:
            self.assertNotIn(value, serialized)
            self.assertNotIn(value, str(raised.exception))
        return raised.exception

    @asynccontextmanager
    async def session(
        self,
        *,
        enable_execution: bool = False,
        allow_generic_execution: bool = False,
        allow_mutation: bool = False,
    ) -> AsyncIterator[ClientSession]:
        env = os.environ.copy()
        env["SPLUNK_CISCO_SKILLS_MCP_NO_VENV"] = "1"
        env.pop("SPLUNK_SKILLS_MCP_ENABLE_EXECUTION", None)
        env.pop("SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION", None)
        env.pop("SPLUNK_SKILLS_MCP_ALLOW_MUTATION", None)
        if enable_execution:
            env["SPLUNK_SKILLS_MCP_ENABLE_EXECUTION"] = "1"
        if allow_generic_execution:
            env["SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION"] = "1"
        if allow_mutation:
            env["SPLUNK_SKILLS_MCP_ALLOW_MUTATION"] = "1"

        params = StdioServerParameters(
            command=sys.executable,
            args=["-I", str(RUNNER)],
            cwd=str(REPO_ROOT),
            env=env,
        )
        with tempfile.TemporaryFile(mode="w+") as errlog:
            self.errlog = errlog
            async with stdio_client(params, errlog=errlog) as (
                read_stream,
                write_stream,
            ):
                async with ClientSession(read_stream, write_stream) as client:
                    self.initialized = await client.initialize()
                    yield client

    async def test_initialize_advertises_stable_server_contract(self) -> None:
        async with self.session() as _client:
            initialized = self.initialized
            self.assertEqual(initialized.server_info.name, "splunk-cisco-skills")
            self.assertEqual(initialized.server_info.version, "1.1.0")
            self.assertNotEqual(initialized.protocol_version, "2025-03-26")
            self.assertIn(
                "SPLUNK_SKILLS_MCP_ENABLE_EXECUTION=1", initialized.instructions
            )
            self.assertIn(
                "SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION=1",
                initialized.instructions,
            )
            self.assertFalse(initialized.capabilities.tools.list_changed)
            self.assertFalse(initialized.capabilities.resources.subscribe)
            self.assertFalse(initialized.capabilities.prompts.list_changed)

    async def test_tool_schemas_are_strict_and_publish_constraints(self) -> None:
        async with self.session() as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}

        self.assertEqual(
            set(tools),
            {
                "list_skills",
                "search_skills",
                "get_skill_manifest",
                "list_skill_files",
                "read_skill_file",
                "credential_status",
                "list_cisco_products",
                "resolve_cisco_product",
                "secret_file_instructions",
                "plan_cisco_product_setup",
                "plan_skill_script",
                "execute_cisco_product_setup",
                "execute_skill_script",
                "get_server_status",
            },
        )
        for tool in tools.values():
            with self.subTest(tool=tool.name):
                self.assertIs(tool.input_schema.get("additionalProperties"), False)

        product_plan = tools["plan_cisco_product_setup"].input_schema["properties"]
        self.assertEqual(
            product_plan["phase"]["enum"],
            ["full", "install", "configure", "validate"],
        )
        self.assertEqual(product_plan["timeout_seconds"]["minimum"], 1)
        self.assertGreaterEqual(product_plan["timeout_seconds"]["maximum"], 1)
        self.assertEqual(
            product_plan["set_values"]["anyOf"][0]["maxProperties"],
            256,
        )
        self.assertEqual(
            product_plan["set_values"]["anyOf"][0]["additionalProperties"]["maxLength"],
            16384,
        )
        self.assertEqual(
            product_plan["set_values"]["anyOf"][0]["propertyNames"]["maxLength"],
            255,
        )
        plan_hash = tools["execute_skill_script"].input_schema["properties"]["plan_hash"]
        self.assertEqual(plan_hash["pattern"], "^[0-9a-f]{64}$")

        self.assertEqual(
            tools["execute_skill_script"].input_schema["properties"]["confirm"]["type"],
            "boolean",
        )
        search = tools["search_skills"].input_schema["properties"]
        self.assertEqual(search["limit"]["minimum"], 1)
        self.assertEqual(search["limit"]["maximum"], 100)
        self.assertIn("canonical", tools["search_skills"].description)
        self.assertIn("exact legacy name", tools["search_skills"].description)
        self.assertIn("canonical", tools["list_skills"].description)
        read = tools["read_skill_file"].input_schema["properties"]
        self.assertEqual(read["offset"]["minimum"], 0)
        self.assertEqual(read["max_bytes"]["minimum"], 1)
        self.assertEqual(read["max_bytes"]["maximum"], 262144)

    async def test_unknown_and_out_of_range_arguments_are_tool_errors(self) -> None:
        sentinel = "protocol-test-secret-value-do-not-echo"
        async with self.session() as client:
            await self.assert_invalid_tool_request(
                client,
                "definitely-not-a-tool",
                {"api_token": sentinel},
                expected_message="Unknown tool name",
                absent_values=(sentinel,),
            )
            await self.assert_invalid_tool_request(
                client,
                "plan_skill_script",
                {
                    "skill": "cisco-product-setup",
                    "script": "resolve_product.sh",
                    "args": ["--help"],
                    "api_token": sentinel,
                },
                absent_values=(sentinel,),
            )
            await self.assert_invalid_tool_request(
                client,
                "plan_skill_script",
                {
                    "skill": "cisco-product-setup",
                    "script": "resolve_product.sh",
                    "timeout_seconds": 0,
                },
            )

    async def test_boolean_integer_and_string_arguments_are_strict(self) -> None:
        async with self.session() as client:
            cases = (
                (
                    "execute_skill_script",
                    {"plan_hash": "0" * 64, "confirm": "true"},
                ),
                (
                    "execute_skill_script",
                    {"plan_hash": "0" * 64, "confirm": 1},
                ),
                (
                    "plan_skill_script",
                    {
                        "skill": "cisco-product-setup",
                        "script": "resolve_product.sh",
                        "timeout_seconds": "1",
                    },
                ),
                (
                    "plan_skill_script",
                    {
                        "skill": "cisco-product-setup",
                        "script": "resolve_product.sh",
                        "timeout_seconds": True,
                    },
                ),
                (
                    "plan_skill_script",
                    {
                        "skill": 123,
                        "script": "resolve_product.sh",
                    },
                ),
            )
            for name, arguments in cases:
                with self.subTest(tool=name, arguments=arguments):
                    await self.assert_invalid_tool_request(client, name, arguments)

    async def test_status_and_product_resolution_work_with_execution_off(self) -> None:
        old_values = {
            name: os.environ.get(name)
            for name in (
                "SPLUNK_SKILLS_MCP_ENABLE_EXECUTION",
                "SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION",
                "SPLUNK_SKILLS_MCP_ALLOW_MUTATION",
            )
        }
        try:
            for name in old_values:
                os.environ[name] = "1"
            async with self.session() as client:
                status = await client.call_tool("get_server_status", {})
                resolved = await client.call_tool(
                    "resolve_cisco_product",
                    {"query": "Cisco ACI"},
                )
                ambiguous = await client.call_tool(
                    "resolve_cisco_product",
                    {"query": "ASA"},
                )
        finally:
            for name, value in old_values.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

        self.assertFalse(status.is_error)
        self.assertEqual(status.structured_content["server"]["version"], "1.1.0")
        self.assertEqual(
            status.structured_content["gates"],
            {
                "execution_enabled": False,
                "generic_execution_enabled": False,
                "mutation_enabled": False,
            },
        )
        self.assertFalse(resolved.is_error)
        self.assertEqual(resolved.structured_content["status"], "resolved")
        self.assertEqual(resolved.structured_content["matches"][0]["id"], "cisco_aci")
        self.assertFalse(ambiguous.is_error)
        self.assertEqual(ambiguous.structured_content["status"], "ambiguous")
        self.assertEqual(
            [item["id"] for item in ambiguous.structured_content["matches"]],
            ["cisco_asa_ftd_syslog", "cisco_secure_firewall"],
        )

    async def test_discovery_paginates_and_rejects_file_traversal(self) -> None:
        async with self.session() as client:
            first = await client.call_tool("search_skills", {"limit": 1})
            self.assertFalse(first.is_error)
            first_payload = first.structured_content
            self.assertGreater(first_payload["total"], 1)
            self.assertIsNotNone(first_payload["next_cursor"])

            second = await client.call_tool(
                "search_skills",
                {"limit": 1, "cursor": first_payload["next_cursor"]},
            )
            listing = await client.call_tool(
                "list_skill_files",
                {
                    "skill": "cisco-product-setup",
                    "kind": "instructions",
                    "limit": 1,
                },
            )
            bounded_read = await client.call_tool(
                "read_skill_file",
                {
                    "skill": "cisco-product-setup",
                    "path": "SKILL.md",
                    "max_bytes": 64,
                },
            )
            traversal = await client.call_tool(
                "read_skill_file",
                {
                    "skill": "cisco-product-setup",
                    "path": "../README.md",
                },
            )
            script_read = await client.call_tool(
                "read_skill_file",
                {
                    "skill": "cisco-product-setup",
                    "path": "scripts/setup.sh",
                },
            )

        self.assertFalse(second.is_error)
        self.assertNotEqual(
            first_payload["skills"][0]["skill"],
            second.structured_content["skills"][0]["skill"],
        )
        self.assertFalse(listing.is_error)
        self.assertEqual(listing.structured_content["files"][0]["path"], "SKILL.md")
        self.assertFalse(bounded_read.is_error)
        self.assertLessEqual(
            len(bounded_read.structured_content["text"].encode("utf-8")),
            64,
        )
        self.assertTrue(traversal.is_error)
        self.assertIn("path", traversal.content[0].text.lower())
        self.assertTrue(script_read.is_error)
        self.assertIn("curated", script_read.content[0].text.lower())

    async def test_legacy_catalog_view_describes_canonical_only_traversal(self) -> None:
        catalog = load_catalog()
        canonical_count = sum(not record.deprecated for record in catalog.skills)
        async with self.session() as client:
            result = await client.call_tool("list_skills", {})

        self.assertFalse(result.is_error)
        payload = result.structured_content
        note = payload["compatibility_note"]
        self.assertEqual(payload["total"], canonical_count)
        self.assertEqual(
            len(catalog.skills) - payload["total"], len(catalog.aliases)
        )
        self.assertIn("canonical skills", note)
        self.assertIn("exact legacy-name search", note)
        self.assertIn("not the complete manifest identity set", note)
        self.assertNotIn("complete traversal", note)

    async def test_prompts_are_advertised_and_reinforce_approval_boundaries(
        self,
    ) -> None:
        async with self.session() as client:
            prompts = {
                prompt.name: prompt for prompt in (await client.list_prompts()).prompts
            }
            product_prompt = await client.get_prompt(
                "plan_cisco_product_workflow",
                {"product": "Cisco ACI", "phase": "validate"},
            )
            script_prompt = await client.get_prompt(
                "review_skill_script_plan",
                {"skill": "cisco-product-setup", "script": "setup.sh"},
            )

        self.assertEqual(
            set(prompts),
            {"plan_cisco_product_workflow", "review_skill_script_plan"},
        )
        product_text = product_prompt.messages[0].content.text
        self.assertIn("explicit operator approval", product_text)
        self.assertIn("literal Boolean true", product_text)
        self.assertIn("untrusted", product_text)
        script_text = script_prompt.messages[0].content.text
        self.assertIn("generic-execution and mutation gates", script_text)
        self.assertIn("explicitly approved", script_text)

    async def test_prompt_validation_is_sanitized_and_uses_invalid_params(self) -> None:
        sentinel = "protocol-test-secret-value-do-not-echo"
        async with self.session() as client:
            with self.assertRaises(MCPError) as raised:
                await client.get_prompt(
                    "plan_cisco_product_workflow",
                    {"product": "Cisco ACI", "phase": sentinel},
                )
            self.errlog.flush()
            self.errlog.seek(0)
            stderr = self.errlog.read()

        error = raised.exception.error
        self.assertEqual(error.code, mcp_types.INVALID_PARAMS)
        self.assertEqual(
            error.message,
            "Invalid prompt arguments; review the published arguments.",
        )
        self.assertNotIn(sentinel, str(error.model_dump(mode="json")))
        self.assertNotIn(sentinel, stderr)

    async def test_unknown_and_unavailable_resources_use_not_found_errors(self) -> None:
        sentinel = "protocol-test-secret-value-do-not-echo"
        async with self.session() as client:
            for uri in (
                f"skills://{sentinel}/not-a-resource",
                "skills://definitely-not-a-skill/instructions",
                "skills://%2E%2E/instructions",
            ):
                with self.subTest(uri=uri), self.assertRaises(MCPError) as raised:
                    await client.read_resource(uri)  # type: ignore[arg-type]

                error = raised.exception.error
                self.assertEqual(error.code, mcp_types.INVALID_PARAMS)
                self.assertIn("Resource not found", error.message)
                self.assertNotIn(sentinel, str(error.model_dump(mode="json")))

    async def test_execution_gate_error_does_not_consume_plan(self) -> None:
        async with self.session() as client:
            planned = await client.call_tool(
                "plan_skill_script",
                {
                    "skill": "cisco-product-setup",
                    "script": "resolve_product.sh",
                    "args": ["--help"],
                },
            )
            self.assertFalse(planned.is_error)
            self.assertFalse(planned.structured_content["read_only"])
            plan_hash = planned.structured_content["plan_hash"]

            first = await client.call_tool(
                "execute_skill_script",
                {"plan_hash": plan_hash, "confirm": True},
            )
            second = await client.call_tool(
                "execute_skill_script",
                {"plan_hash": plan_hash, "confirm": True},
            )

        self.assertTrue(first.is_error)
        self.assertIn("Subprocess execution is disabled", first.content[0].text)
        self.assertTrue(second.is_error)
        self.assertIn("Subprocess execution is disabled", second.content[0].text)

    async def test_generic_execution_requires_its_explicit_gate(self) -> None:
        async with self.session(enable_execution=True) as client:
            planned = await client.call_tool(
                "plan_skill_script",
                {
                    "skill": "cisco-product-setup",
                    "script": "resolve_product.sh",
                    "args": ["--help"],
                },
            )
            blocked = await client.call_tool(
                "execute_skill_script",
                {"plan_hash": planned.structured_content["plan_hash"], "confirm": True},
            )

        self.assertTrue(blocked.is_error)
        self.assertIn(
            "Generic skill-script execution is disabled", blocked.content[0].text
        )

    async def test_generic_execution_still_requires_mutation_gate(self) -> None:
        async with self.session(
            enable_execution=True,
            allow_generic_execution=True,
        ) as client:
            planned = await client.call_tool(
                "plan_skill_script",
                {
                    "skill": "cisco-product-setup",
                    "script": "resolve_product.sh",
                    "args": ["--help"],
                },
            )
            blocked = await client.call_tool(
                "execute_skill_script",
                {"plan_hash": planned.structured_content["plan_hash"], "confirm": True},
            )

        self.assertTrue(blocked.is_error)
        self.assertIn("Mutating execution is disabled", blocked.content[0].text)

    async def test_nonzero_execution_sets_is_error_and_plan_is_single_use(self) -> None:
        async with self.session(
            enable_execution=True,
            allow_generic_execution=True,
            allow_mutation=True,
        ) as client:
            planned = await client.call_tool(
                "plan_skill_script",
                {
                    "skill": "cisco-product-setup",
                    "script": "resolve_product.sh",
                    "args": ["--definitely-invalid"],
                },
            )
            plan_hash = planned.structured_content["plan_hash"]
            failed = await client.call_tool(
                "execute_skill_script",
                {"plan_hash": plan_hash, "confirm": True},
            )
            replay = await client.call_tool(
                "execute_skill_script",
                {"plan_hash": plan_hash, "confirm": True},
            )

        self.assertTrue(failed.is_error)
        self.assertFalse(failed.structured_content["ok"])
        self.assertNotEqual(failed.structured_content["returncode"], 0)
        self.assertTrue(replay.is_error)
        self.assertIn("Unknown plan_hash", replay.content[0].text)


@unittest.skipIf(ClientSession is None, "requires requirements-agent.txt")
class AgentMCPRawStdioTests(unittest.TestCase):
    def test_batch_required_protocol_version_is_not_negotiated(self) -> None:
        initialize = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "protocol-test", "version": "1.0"},
            },
        }
        env = os.environ.copy()
        env["SPLUNK_CISCO_SKILLS_MCP_NO_VENV"] = "1"
        process = subprocess.Popen(
            [sys.executable, "-I", str(RUNNER)],
            cwd=REPO_ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        frame = json.dumps(initialize, separators=(",", ":")).encode() + b"\n"
        stdout, stderr = process.communicate(input=frame, timeout=20)

        self.assertEqual(process.returncode, 0, msg=stderr.decode(errors="replace"))
        response = json.loads(stdout.splitlines()[0])
        self.assertNotEqual(
            response["result"]["protocolVersion"],
            "2025-03-26",
        )

    def test_raw_transport_bounds_and_sanitizes_invalid_frames(self) -> None:
        sentinel = b"raw-transport-secret-do-not-echo"
        frames = [
            b'{"jsonrpc":"2.0","id":1,"method":"tools/list","x":"\xff'
            + sentinel
            + b'"}\n',
            b'{"jsonrpc":"2.0","id":2,"method":' + sentinel + b"\n",
            b'{"jsonrpc":"2.0","id":3,"id":4,"method":"tools/list"}\n',
            b"[]\n",
            b'{"jsonrpc":"2.0","id":9,"method":"tools/call","params":"'
            + sentinel
            + b'"}\n',
            b'{"jsonrpc":"2.0","id":7,"method":"unknown/method"}\n',
            b'{"jsonrpc":"2.0","id":8,"method":"tools/list","pad":"'
            + b"x" * (1024 * 1024)
            + sentinel
            + b'"}\n',
        ]
        env = os.environ.copy()
        env["SPLUNK_CISCO_SKILLS_MCP_NO_VENV"] = "1"
        process = subprocess.Popen(
            [sys.executable, "-I", str(RUNNER)],
            cwd=REPO_ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = process.communicate(input=b"".join(frames), timeout=20)

        self.assertEqual(process.returncode, 0, msg=stderr.decode(errors="replace"))
        responses = [json.loads(line) for line in stdout.splitlines()]
        self.assertEqual(
            [item["error"]["code"] for item in responses],
            [-32700, -32700, -32600, -32600, -32602, -32601, -32700],
        )
        self.assertEqual(responses[4]["id"], 9)
        self.assertEqual(responses[5]["id"], 7)
        self.assertNotIn(sentinel, stdout)
        self.assertNotIn(sentinel, stderr)


if __name__ == "__main__":
    unittest.main()
