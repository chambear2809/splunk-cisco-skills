"""End-to-end MCP stdio protocol coverage for the repo-local agent server."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ModuleNotFoundError:  # pragma: no cover - requirements-agent.txt supplies MCP in CI
    ClientSession = None  # type: ignore[assignment,misc]
    StdioServerParameters = None  # type: ignore[assignment,misc]
    stdio_client = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "agent/run-splunk-cisco-skills-mcp.py"


@unittest.skipIf(ClientSession is None, "requires requirements-agent.txt")
class AgentMCPProtocolTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def session(
        self,
        *,
        enable_execution: bool = False,
        allow_mutation: bool = False,
    ) -> AsyncIterator[ClientSession]:
        env = os.environ.copy()
        env["SPLUNK_CISCO_SKILLS_MCP_NO_VENV"] = "1"
        env.pop("SPLUNK_SKILLS_MCP_ENABLE_EXECUTION", None)
        env.pop("SPLUNK_SKILLS_MCP_ALLOW_MUTATION", None)
        if enable_execution:
            env["SPLUNK_SKILLS_MCP_ENABLE_EXECUTION"] = "1"
        if allow_mutation:
            env["SPLUNK_SKILLS_MCP_ALLOW_MUTATION"] = "1"

        params = StdioServerParameters(
            command=sys.executable,
            args=[str(RUNNER)],
            cwd=str(REPO_ROOT),
            env=env,
        )
        with tempfile.TemporaryFile(mode="w+") as errlog:
            async with stdio_client(params, errlog=errlog) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as client:
                    self.initialized = await client.initialize()
                    yield client

    async def test_initialize_advertises_stable_server_contract(self) -> None:
        async with self.session() as _client:
            initialized = self.initialized
            self.assertEqual(initialized.serverInfo.name, "splunk-cisco-skills")
            self.assertEqual(initialized.serverInfo.version, "1.0.0")
            self.assertIn("SPLUNK_SKILLS_MCP_ENABLE_EXECUTION=1", initialized.instructions)
            self.assertFalse(initialized.capabilities.tools.listChanged)
            self.assertFalse(initialized.capabilities.resources.subscribe)

    async def test_tool_schemas_are_strict_and_publish_constraints(self) -> None:
        async with self.session() as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}

        self.assertEqual(
            set(tools),
            {
                "list_skills",
                "credential_status",
                "list_cisco_products",
                "resolve_cisco_product",
                "secret_file_instructions",
                "plan_cisco_product_setup",
                "plan_skill_script",
                "execute_cisco_product_setup",
                "execute_skill_script",
            },
        )
        for tool in tools.values():
            with self.subTest(tool=tool.name):
                self.assertIs(tool.inputSchema.get("additionalProperties"), False)

        product_plan = tools["plan_cisco_product_setup"].inputSchema["properties"]
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
        plan_hash = tools["execute_skill_script"].inputSchema["properties"]["plan_hash"]
        self.assertEqual(plan_hash["pattern"], "^[0-9a-f]{64}$")

    async def test_unknown_and_out_of_range_arguments_are_tool_errors(self) -> None:
        async with self.session() as client:
            unknown = await client.call_tool(
                "plan_skill_script",
                {
                    "skill": "cisco-product-setup",
                    "script": "resolve_product.sh",
                    "args": ["--help"],
                    "timeot_seconds": 1,
                },
            )
            bad_timeout = await client.call_tool(
                "plan_skill_script",
                {
                    "skill": "cisco-product-setup",
                    "script": "resolve_product.sh",
                    "timeout_seconds": 0,
                },
            )

        self.assertTrue(unknown.isError)
        self.assertIn("timeot_seconds", unknown.content[0].text)
        self.assertTrue(bad_timeout.isError)
        self.assertIn("timeout_seconds", bad_timeout.content[0].text)

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
            self.assertFalse(planned.isError)
            self.assertFalse(planned.structuredContent["read_only"])
            plan_hash = planned.structuredContent["plan_hash"]

            first = await client.call_tool(
                "execute_skill_script",
                {"plan_hash": plan_hash, "confirm": True},
            )
            second = await client.call_tool(
                "execute_skill_script",
                {"plan_hash": plan_hash, "confirm": True},
            )

        self.assertTrue(first.isError)
        self.assertIn("Subprocess execution is disabled", first.content[0].text)
        self.assertTrue(second.isError)
        self.assertIn("Subprocess execution is disabled", second.content[0].text)

    async def test_generic_execution_also_requires_mutation_gate(self) -> None:
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
                {"plan_hash": planned.structuredContent["plan_hash"], "confirm": True},
            )

        self.assertTrue(blocked.isError)
        self.assertIn("Mutating execution is disabled", blocked.content[0].text)

    async def test_nonzero_execution_sets_is_error_and_plan_is_single_use(self) -> None:
        async with self.session(enable_execution=True, allow_mutation=True) as client:
            planned = await client.call_tool(
                "plan_skill_script",
                {
                    "skill": "cisco-product-setup",
                    "script": "resolve_product.sh",
                    "args": ["--definitely-invalid"],
                },
            )
            plan_hash = planned.structuredContent["plan_hash"]
            failed = await client.call_tool(
                "execute_skill_script",
                {"plan_hash": plan_hash, "confirm": True},
            )
            replay = await client.call_tool(
                "execute_skill_script",
                {"plan_hash": plan_hash, "confirm": True},
            )

        self.assertTrue(failed.isError)
        self.assertFalse(failed.structuredContent["ok"])
        self.assertNotEqual(failed.structuredContent["returncode"], 0)
        self.assertTrue(replay.isError)
        self.assertIn("Unknown plan_hash", replay.content[0].text)


if __name__ == "__main__":
    unittest.main()
