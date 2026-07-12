# Repo-Local Skills MCP Server

`splunk-cisco-skills` exposes this repository's checked-in skills to MCP
clients. It is separate from the official Splunk MCP Server app configured by
`skills/splunk-mcp-server-setup`: this server discovers and plans repository
automation, while the official server queries a Splunk deployment.

## Safe default registration

The committed Claude Code and Cursor configs, and the Codex registration
helper, set:

```text
SPLUNK_SKILLS_MCP_ENABLE_EXECUTION=1
SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION=0
SPLUNK_SKILLS_MCP_ALLOW_MUTATION=0
```

That profile allows typed Cisco dry-runs. It does not authorize validation,
apply, or arbitrary script execution because phase names are not trusted as a
side-effect boundary. Never flip
the two `0` values on the shared registration; use a separate, reviewed,
single-operator process if mutation is intentionally required.

Register Codex with:

```bash
bash agent/register-codex-splunk-cisco-skills-mcp.sh
```

The launcher and registrations use Python isolated mode (`-I`) and prefer a
trusted repo `.venv`.

## Tool groups

- Discovery: `search_skills`, `get_skill_manifest`, `list_skill_files`,
  `read_skill_file`, `list_cisco_products`, and `resolve_cisco_product`.
- Planning: `plan_cisco_product_setup`, `plan_skill_script`, and
  `secret_file_instructions`.
- Execution: `execute_cisco_product_setup` and `execute_skill_script`.
- Operations: `credential_status` and `get_server_status`.

Product resolution and discovery never execute repository code. Generic
script manifests expose only `setup.sh`, `validate.sh`, and optional
`doctor.sh`, and do not label validators or doctors as inherently read-only.

## Authorization gates

| Operation | execution | generic | mutation | confirmation |
|---|---:|---:|---:|---:|
| Discovery and pure resolution | no | no | no | no |
| Product dry-run planning | yes | no | no | no |
| Any typed product execution | yes | no | yes | yes |
| Any generic script execution | yes | yes | yes | yes |

Execution also requires an unexpired random plan hash, an unchanged skill-tree
snapshot, unchanged executable/interpreter digests, and unchanged secure-file
metadata. Plans are in-memory, single-use capabilities.

## Boundary

This is a bounded, supervised local executor, not an OS sandbox. Keep it on
stdio, attach only trusted single-operator clients, pass secrets through
owner-only files, and review dry-run output out of band before enabling any
mutation gate. See `SECURITY.md` for the complete trust model.
