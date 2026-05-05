"""FastMCP stdio server exposing this repository as agent tools."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import core


READ_LOCAL = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}
READ_OPEN = {"readOnlyHint": True, "idempotentHint": False, "openWorldHint": True}
WRITE_OPEN = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": False,
    "openWorldHint": True,
}

mcp = FastMCP("splunk-cisco-skills")


def _json_resource(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


@mcp.resource(
    "skills://catalog",
    mime_type="application/json",
    annotations=READ_LOCAL,
)
def skills_catalog() -> str:
    """Return the local skill catalog with scripts and optional files."""
    return _json_resource(core.list_skills())


@mcp.resource(
    "skills://{skill}/instructions",
    mime_type="text/markdown",
    annotations=READ_LOCAL,
)
def skill_instructions(skill: str) -> str:
    """Return a skill's SKILL.md instructions."""
    return core.read_skill_file(skill, "instructions")


@mcp.resource(
    "skills://{skill}/reference",
    mime_type="text/markdown",
    annotations=READ_LOCAL,
)
def skill_reference(skill: str) -> str:
    """Return a skill's reference.md file or aggregated references/*.md files."""
    return core.read_skill_file(skill, "reference")


@mcp.resource(
    "skills://{skill}/template",
    mime_type="text/plain",
    annotations=READ_LOCAL,
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
def list_cisco_products(state: str | None = None) -> dict[str, Any]:
    """List Cisco product catalog entries, optionally filtered by automation state."""
    return core.list_cisco_products(state=state)


@mcp.tool(annotations=READ_LOCAL)
def resolve_cisco_product(query: str) -> dict[str, Any]:
    """Resolve a Cisco product name, alias, or keyword against the local catalog."""
    return core.resolve_cisco_product(query)


@mcp.tool(annotations=READ_LOCAL)
def secret_file_instructions(
    secret_keys: list[str],
    prefix: str = "/tmp/splunk_skill",
) -> dict[str, Any]:
    """Render safe terminal commands for creating local-only secret files."""
    return core.secret_file_instructions(secret_keys, prefix)


@mcp.tool(annotations=READ_OPEN)
def plan_cisco_product_setup(
    product: str,
    set_values: dict[str, str] | None = None,
    secret_files: dict[str, str] | None = None,
    phase: str = "full",
    timeout_seconds: int = core.DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Dry-run and plan a Cisco product install/configure/validate workflow."""
    return core.plan_cisco_product_setup(
        product=product,
        set_values=set_values,
        secret_files=secret_files,
        phase=phase,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool(annotations=READ_LOCAL)
def plan_skill_script(
    skill: str,
    script: str,
    args: list[str] | None = None,
    timeout_seconds: int = core.DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Plan an allowlisted skill script command without executing it."""
    return core.plan_skill_script(
        skill=skill,
        script=script,
        args=args,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool(annotations=WRITE_OPEN)
def execute_cisco_product_setup(plan_hash: str, confirm: bool = False) -> dict[str, Any]:
    """Execute a previously planned Cisco product setup command after approval."""
    return core.execute_plan(
        plan_hash=plan_hash,
        confirm=confirm,
        expected_kind="cisco_product_setup",
    )


@mcp.tool(annotations=WRITE_OPEN)
def execute_skill_script(plan_hash: str, confirm: bool = False) -> dict[str, Any]:
    """Execute a previously planned skill script command after approval."""
    return core.execute_plan(
        plan_hash=plan_hash,
        confirm=confirm,
        expected_kind="skill_script",
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
