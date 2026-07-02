"""FastMCP stdio server exposing this repository as agent tools."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from pydantic import Field

from . import core


READ_LOCAL = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}
READ_OPEN = {"readOnlyHint": True, "idempotentHint": False, "openWorldHint": True}
PLAN_LOCAL = {"readOnlyHint": True, "idempotentHint": False, "openWorldHint": False}
WRITE_OPEN = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": False,
    "openWorldHint": True,
}
RESOURCE_LOCAL = {"audience": ["assistant"], "priority": 0.8}
SERVER_VERSION = "1.0.0"
SERVER_INSTRUCTIONS = (
    "Discover and plan Splunk/Cisco repository workflows. Never place credentials in "
    "tool arguments. Subprocess execution is disabled unless the server process has "
    "SPLUNK_SKILLS_MCP_ENABLE_EXECUTION=1; generic script execution is always treated "
    "as mutating and additionally requires SPLUNK_SKILLS_MCP_ALLOW_MUTATION=1."
)

mcp = FastMCP("splunk-cisco-skills", instructions=SERVER_INSTRUCTIONS)
# FastMCP v1 otherwise advertises the SDK package version. This is the local
# server contract version, which should not change merely because the SDK does.
mcp._mcp_server.version = SERVER_VERSION


def _json_resource(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


async def _run_cancellable(operation: Any) -> Any:
    cancellation = core.CommandCancellation()
    try:
        return await anyio.to_thread.run_sync(
            lambda: operation(cancellation),
            abandon_on_cancel=True,
        )
    finally:
        cancellation.cancel()


def _execution_result(payload: dict[str, Any]) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=_json_resource(payload))],
        structuredContent=payload,
        isError=not bool(payload.get("ok")),
    )


TimeoutSeconds = Annotated[int, Field(ge=core.MIN_TIMEOUT_SECONDS, le=core.MAX_TIMEOUT_SECONDS)]
PlanHash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
MappingKey = Annotated[str, Field(min_length=1, max_length=core.MAX_KEY_CHARS)]
MappingValue = Annotated[str, Field(max_length=core.MAX_ARG_CHARS)]
StringMapping = Annotated[
    dict[MappingKey, MappingValue],
    Field(max_length=core.MAX_MAPPING_ENTRIES),
]
SecretKey = Annotated[str, Field(min_length=1, max_length=core.MAX_KEY_CHARS)]
ArgumentValue = Annotated[str, Field(max_length=core.MAX_ARG_CHARS)]


@mcp.resource(
    "skills://catalog",
    mime_type="application/json",
    annotations=RESOURCE_LOCAL,
)
def skills_catalog() -> str:
    """Return the local skill catalog with scripts and optional files."""
    return _json_resource(core.list_skills())


@mcp.resource(
    "skills://{skill}/instructions",
    mime_type="text/markdown",
    annotations=RESOURCE_LOCAL,
)
def skill_instructions(skill: str) -> str:
    """Return a skill's SKILL.md instructions."""
    return core.read_skill_file(skill, "instructions")


@mcp.resource(
    "skills://{skill}/reference",
    mime_type="text/markdown",
    annotations=RESOURCE_LOCAL,
)
def skill_reference(skill: str) -> str:
    """Return a skill's reference.md file or aggregated references/*.md files."""
    return core.read_skill_file(skill, "reference")


@mcp.resource(
    "skills://{skill}/template",
    mime_type="text/plain",
    annotations=RESOURCE_LOCAL,
)
def skill_template(skill: str) -> str:
    """Return a skill's template.example file or aggregated templates/* files."""
    return core.read_skill_file(skill, "template")


@mcp.tool(annotations=READ_LOCAL)
def list_skills() -> dict[str, Any]:
    """List all repo skills, descriptions, optional files, and script names."""
    return core.list_skills()


@mcp.tool(annotations=READ_LOCAL)
def credential_status() -> dict[str, Any]:
    """Check only credential-file existence and permissions, never values."""
    return core.credential_status()


@mcp.tool(annotations=READ_LOCAL)
def list_cisco_products(
    state: Literal[
        "automated",
        "partial",
        "manual_gap",
        "no_plans_available",
        "unsupported_legacy",
        "unsupported_roadmap",
    ]
    | None = None,
) -> dict[str, Any]:
    """List Cisco product catalog entries, optionally filtered by automation state."""
    return core.list_cisco_products(state=state)


@mcp.tool(annotations=READ_LOCAL)
async def resolve_cisco_product(
    query: Annotated[str, Field(min_length=1, max_length=4096)],
) -> dict[str, Any]:
    """Resolve a Cisco product name, alias, or keyword against the local catalog."""
    return await _run_cancellable(
        lambda cancellation: core.resolve_cisco_product(
            query,
            cancellation=cancellation,
        )
    )


@mcp.tool(annotations=READ_LOCAL)
def secret_file_instructions(
    secret_keys: Annotated[list[SecretKey], Field(max_length=core.MAX_SECRET_KEYS)],
    prefix: Annotated[str, Field(min_length=1, max_length=4096)] = "/tmp/splunk_skill",
) -> dict[str, Any]:
    """Render safe terminal commands for creating local-only secret files."""
    return core.secret_file_instructions(secret_keys, prefix)


@mcp.tool(annotations=READ_OPEN)
async def plan_cisco_product_setup(
    product: Annotated[str, Field(min_length=1, max_length=4096)],
    set_values: StringMapping | None = None,
    secret_files: StringMapping | None = None,
    phase: Literal["full", "install", "configure", "validate"] = "full",
    timeout_seconds: TimeoutSeconds = core.DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Dry-run and plan a Cisco product install/configure/validate workflow."""
    return await _run_cancellable(
        lambda cancellation: core.plan_cisco_product_setup(
            product=product,
            set_values=set_values,
            secret_files=secret_files,
            phase=phase,
            timeout_seconds=timeout_seconds,
            cancellation=cancellation,
        )
    )


@mcp.tool(annotations=PLAN_LOCAL)
def plan_skill_script(
    skill: Annotated[str, Field(min_length=1, max_length=255)],
    script: Annotated[str, Field(min_length=1, max_length=255)],
    args: Annotated[list[ArgumentValue], Field(max_length=core.MAX_ARG_COUNT)] | None = None,
    timeout_seconds: TimeoutSeconds = core.DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Plan an allowlisted skill script command without executing it."""
    return core.plan_skill_script(
        skill=skill,
        script=script,
        args=args,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool(annotations=WRITE_OPEN)
async def execute_cisco_product_setup(
    plan_hash: PlanHash,
    confirm: bool = False,
) -> CallToolResult:
    """Execute a previously planned Cisco product setup command after approval."""
    payload = await _run_cancellable(
        lambda cancellation: core.execute_plan(
            plan_hash=plan_hash,
            confirm=confirm,
            expected_kind="cisco_product_setup",
            cancellation=cancellation,
        )
    )
    return _execution_result(payload)


@mcp.tool(annotations=WRITE_OPEN)
async def execute_skill_script(
    plan_hash: PlanHash,
    confirm: bool = False,
) -> CallToolResult:
    """Execute a previously planned skill script command after approval."""
    payload = await _run_cancellable(
        lambda cancellation: core.execute_plan(
            plan_hash=plan_hash,
            confirm=confirm,
            expected_kind="skill_script",
            cancellation=cancellation,
        )
    )
    return _execution_result(payload)


def _enforce_strict_tool_arguments() -> None:
    """Reject unknown properties instead of silently applying defaults."""
    for tool in mcp._tool_manager._tools.values():
        tool.fn_metadata.arg_model.model_config["extra"] = "forbid"
        tool.fn_metadata.arg_model.model_rebuild(force=True)
        tool.parameters = tool.fn_metadata.arg_model.model_json_schema()


_enforce_strict_tool_arguments()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
