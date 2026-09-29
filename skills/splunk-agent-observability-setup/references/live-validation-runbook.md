# Live validation runbook

Use this runbook only when the user explicitly requests end-to-end validation
against a live Splunk Agent Observability tenant and a disposable runtime. It
proves the selected telemetry and Agent Control path. When the requested scope
is every AO object or policy, also work through every applicable row in
`object-action-matrix.json` using the coverage gate below. Record other
features as read-only, configuration-only, gated, or support handoff when that
is the strongest available evidence; never report a row as created because a
feature or API reference mentions it.

## Full object and policy coverage gate

For a full-product claim, create a validation ledger from every row of
`object-action-matrix.json` before mutation. Include the object ID, deployment,
requested operation, current tenant entitlement, exact interface and schema,
permission/collaborator check, unique test name, created ID, read-back proof,
runtime or data proof where relevant, cleanup method, and cleanup result. A row
must be marked one of `verified_live`, `documented_not_live_tested`,
`deployment_excluded`, `no_user_create_operation`, or `blocked`; an unknown or
401 response is `blocked`, never `verified_live`. Keep the ledger free of tokens,
prompt contents, and employee data.

Exercise the applicable SaaS object families in dependency order: project and
Agent Stream; synthetic trace/session/spans; dataset, content/version, prompt,
experiment and group/ranking; evaluator and stream assignment; annotation
queue/field/record and feedback; Agent Control global policy and stream clone;
alert, saved view, dashboard/section/widget, and Run Insights; provider and
Tokenomics settings; and requested identity/sharing/key settings. Check each
operation's exact `create`, `update`, `delete`, and `verify` entry before using
it. Use isolated net-new resources and capture read-back proof. For entries
marked `not-documented`, inspect the actual tenant interface; if it does not
expose a supported operation, retain that gap in the report rather than trying
an inferred route. On-premises-only objects such as custom code evaluators and
Luna Studio training are `deployment_excluded` in a SaaS validation, not passed.
The organization-wide Delete By Metadata job is a destructive operation, not
a create-all object. Exclude it from coverage creation; only a separately
scoped deletion request with an exact filter and match count can authorize it.

Agent Control policy coverage is dimensional: check each tenant-exposed
evaluator type (`list`, `regex`, `json`, `sql`, supported custom/Luna), `pre` and
`post` stages, relevant step scope and selector, `deny`/`steer`/`observe` action,
and `and`/`or`/`not` conditions when available. A single deterministic deny
case below proves only that case. Use synthetic inputs for each requested
policy and verify its runtime result, not merely its saved configuration.
Record cost or external-provider gates separately; do not call an LLM or import
real data just to mark a ledger row complete.

## Preflight and access

1. Identify the deployment, realm/API endpoint, edition/entitlement, current
   release, target EKS context/namespace, and exact validation scope. Use a
   unique timestamped project, Agent Stream, control, and workload label. Check
   that those exact names are unused before creating anything.
2. For SaaS, use `SPLUNK_AO_REALM` and an Observability Cloud token with INGEST
   and the required Agent Observability API roles/capabilities. A single
   combined token may be set as `SPLUNK_AO_O11Y_TOKEN`; if separate tokens are
   used, set `SPLUNK_AO_O11Y_TOKEN` for telemetry and
   `SPLUNK_AO_O11Y_API_TOKEN` for CRUD. A UI user's role does not prove that the
   token has the matching capabilities. Consult [SaaS credentials and
   capabilities](../reference.md#official-source-index).
3. Confirm both the token capability and the resource collaborator role:
   `o11y_create_project` for project creation; `o11y_log_data_project_shared`
   plus project Owner/Editor for telemetry; `o11y_read_control`,
   `o11y_create_control`, `o11y_update_control`, and `o11y_delete_control` for
   global control CRUD; `o11y_update_control_bindings_project_shared` and
   `o11y_use_control_runtime_project_shared` plus project Owner/Editor for
   stream binding/runtime; and `o11y_delete_project_shared` for deleting an
   owned test project. Check the current capability page for any other action.
   The public matrix does not list a separate Agent Stream creation
   capability; do not invent one.
4. Do not put token values in chat, a manifest, command arguments, a shell
   environment prefix, or logs. Use a protected local secret file or approved
   secret manager, then reference an existing Kubernetes Secret with
   `secretKeyRef`. Never render Secret data with `kubectl get secret -o yaml`.
   If the protected file writer adds a final line ending, strip only trailing
   CR/LF from the in-process environment value before SDK initialization; do
   not print the value or rewrite it into a manifest.
   If a credential was disclosed, stop using it and have its owner revoke or
   rotate it before continuing.
5. Do not create a placeholder Kubernetes `Secret` manifest. If validation
   needs an EKS Secret, create it directly from a protected file with
   `kubectl create secret generic <unique-name> --context <context> --namespace
   <namespace> --from-file=<key>=<protected-file>`. This command sends the file
   to the Kubernetes API but does not print its contents. Remove the local file
   after Kubernetes confirms creation.

If the project API returns 401, or the target feature/permission is unavailable,
stop before creating more resources. Record the sanitized error and access layer
that needs attention. Do not retry with another secret unless the user has
authorized it.

## Telemetry proof

1. Use the documented `splunk-ao` SDK contract for the installed version.
   Initializing a missing project or Agent Stream can create it, so first
   confirm the unique target names are new. Capture IDs when the SDK resolves
   them. Some SDK/version paths accept names for telemetry but leave numeric IDs
   unset; that alone does not prove initialization or ingestion failed. For
   Agent Control, resolve project and Agent Stream IDs with documented SDK read
   methods if the logger does not expose them. Stop before control
   creation/runtime if either ID cannot be resolved.
   The Agent Control setup page says the logger resolves IDs from names, but
   `splunk-ao==0.4.0` leaves the SaaS logger ID fields unset for name-only
   routing. Check the installed SDK behavior instead of using null IDs as an
   ingestion failure signal.
2. Run one bounded Kubernetes Job in the selected validation namespace. Use a
   single execution (`backoffLimit: 0`), a deadline, CPU/memory limits, a
   finished-job TTL, a unique validation label, a read-only root filesystem,
   and no service-account token unless the workload needs Kubernetes API
   access. Do not alter the production OTel collector or its Secret.
   With a read-only root filesystem, set `SPLUNK_AO_HOME_DIR` to a writable
   mounted temporary directory; SDK config initialization creates that path.
   For SaaS with `splunk-ao==0.4.0`, use `SPLUNK_AO_REALM` and the
   `SPLUNK_AO_O11Y_*` token variables. Do not also set the standalone
   `SPLUNK_AO_API_KEY` or `SPLUNK_AO_API_URL`: the SDK rejects a mixed
   deployment configuration. Agent Control can separately receive the same
   protected SaaS token through `AGENT_CONTROL_API_KEY` and
   `AGENT_CONTROL_API_KEY_HEADER=X-SF-Token`.
3. Emit synthetic-only data: one session, one trace, and a deterministic tool
   span with a unique validation marker on the trace root. Do not call a hosted
   model, provider, customer tool, or real MCP server. Log only package
   versions, IDs, status, and sanitized errors; never dump environment
   variables or prompt/response bodies. The current logger API supports this
   shape:

   ```python
   from splunk_ao import SplunkAOLogger

   logger = SplunkAOLogger(project=project_name, agent_stream=stream_name)
   logger.start_session(
       name="ao-validation-session",
       external_id=validation_id,
       metadata={"validation_id": validation_id},
   )
   logger.start_trace(
       input="synthetic AO validation",
       name="ao-validation",
       metadata={"validation_id": validation_id},
   )
   logger.add_tool_span(
       input='{"case":"allow"}',
       output="synthetic success",
       name="ao-validation-tool",
       metadata={"validation_id": validation_id},
   )
   logger.conclude(output="synthetic success")
   logger.flush()
   ```

4. Verify the trace appears in the exact project and Agent Stream in the AO
   UI or a documented read API. Check the run identifier, parent and child span
   relationship, unique marker, and timestamp. SDK initialization or a Job
   exit code alone does not prove ingestion.

## Agent Control proof

1. Install the documented Agent Control dependency set for the current AO
   release: `splunk-ao[openai]>=0.2.1`, `agent-control-sdk>=8.5.0`,
   `agent-control-evaluators>=8.5.0`, and
   `agent-control-evaluator-galileo>=8.5.0`. A deterministic list/regex test
   does not need to invoke the Galileo evaluator or an external model.
2. Create a uniquely named control using the documented AO UI or a currently
   documented management interface. Configure the `list` evaluator to match
   the synthetic block marker at the pre stage, set selector path to `input`,
   and choose the `Deny` action. For the built-in `list` evaluator, use
   `values: ["AO_VALIDATION_BLOCK"]`, `logic: "any"`, `match_on: "match"`,
   `match_mode: "contains"`, and `case_sensitive: true`. The current SDK wraps
   a tool argument in an input payload; a `*` selector with exact matching did
   not match the marker in live validation. Built-in evaluator names
   include `list` and `regex`; `string` is not an evaluator name. Use the current
   UI/docs for field names and configuration; do not invent an evaluator schema.
3. Attach it only to the validation Agent Stream. Attaching a control creates
   a stream-bound clone. Record the global control ID and any clone ID the
   interface actually exposes; do not assume a clone ID or deletion endpoint
   exists. Do not use a production stream.
4. Configure the documented SaaS runtime endpoint
   `https://<realm-host>/ao/agent-control`, API-key header `X-SF-Token`, JWT
   runtime mode, and runtime-token header `X-Agent-Control-Runtime-Token`.
   Use Agent Control SDK 8.5.0 or later. The public setup page does not document
   how a tenant obtains the runtime JWT; follow its current sample and record a
   docs/access gap if the sample cannot initialize runtime auth. Do not
   substitute the ingest token as a runtime JWT. Initialize the logger and
   Agent Control SDK against the same project/Agent Stream, and use the resolved
   Agent Stream ID as the control target.
5. Decorate a local deterministic function; it must not call an LLM or an
   external tool. By default `@control()` registers an `llm` step. To test a
   `tool` step, set the function's `.name` or `.tool_name` metadata before
   applying `@control()` and use a control scoped to `tool`. The AO UI guide
   documents stages, selector, action, execution environment, and evaluator
   configuration; do not assume it exposes a step-type field. Submit one safe
   marker and one exact deny marker. Require the safe call to complete and the
   blocked call to raise the documented `ControlViolationError`. Capture only
   case labels, outcomes, and sanitized exception names. A practical fixture is:

   ```python
   from agent_control import ControlViolationError, control

   def synthetic_step(value: str) -> str:
       return "synthetic-success"

   synthetic_step.name = "synthetic_step"
   synthetic_step.tool_name = "synthetic_step"
   synthetic_step = control()(synthetic_step)

   assert synthetic_step("AO_VALIDATION_ALLOW") == "synthetic-success"
   try:
       synthetic_step("AO_VALIDATION_BLOCK")
   except ControlViolationError:
       blocked = True
   else:
       blocked = False
   assert blocked
   ```

   Configure the pre-stage evaluator to deny only the block marker. Verify the
   function call count or sanitized outcomes so the denial proves that the
   function did not run.
6. Verify both outcomes in the Agent Control view and the corresponding trace
   evidence. A saved control or stream attachment alone does not prove runtime
   enforcement. If the documented SaaS runtime credential cannot be resolved,
   mark enforcement unverified rather than substituting an undocumented auth
   flow.

## Cleanup and evidence

When the user authorized cleanup for this validation, delete only exact
resources created by this run, in dependency order:

1. Stop the Job. Remove the stream binding using a verified UI/API action.
   Delete the stream-bound clone only when a documented action exposes it; then
   delete the validation global control using its recorded ID.
   The generic Agent Control server reference lists attach/detach and control
   CRUD routes, but verify their AO tenant path, auth, and clone semantics before
   using them. Do not assume its default local-server URL is the SaaS URL.
2. Delete only the validation trace(s). Prefer a documented filter for the
   unique trace marker; otherwise use the dedicated validation stream ID as the
   narrowest supported filter and confirm its trace count before deletion. Then
   delete the validation Agent Stream and project by recorded IDs. Follow
   documented deletion semantics and verify absence.
3. Delete the validation Job, ConfigMap, and validation-only Kubernetes Secret
   (never the existing collector Secret). Remove local manifests/scripts and
   protected token files created for this run. If a new validation API token
   was issued solely for this test, deactivate that exact token after dependent
   workloads are stopped; retain pre-existing tokens. Splunk Observability
   Cloud organization access tokens cannot be deleted, only deactivated.
4. Verify the exact AO objects and Kubernetes resources are gone. Do not use
   broad or organization-wide deletion operations for cleanup.
   `agent_control.init()` also registers an Agent Control agent name. The
   tenant's current public OpenAPI exposes agent GET/PATCH but no agent delete.
   Before a strict zero-residue test, use an already registered test agent if
   appropriate, or obtain a supported removal path for a new registration.
   Do not assume deleting an AO project removes the Agent Control agent record;
   check it explicitly and report any remaining registration.
   If the full object gate created datasets, prompts, experiments, evaluators,
   annotation queues, alerts, dashboards, integrations, users/keys, or other
   settings, delete or revert each exact recorded test object in reverse
   dependency order. If an object has no supported delete path, do not create
   it solely for validation unless its owner has accepted the residual object;
   report that row as `documented_not_live_tested` or `blocked` instead.

Report the cluster/namespace, package versions, project/stream/control IDs (and
clone IDs only if exposed), observed trace and allow/deny evidence, cleanup
verification, any capability or entitlement gap, and which matrix rows were
only read-only, configuration-checked, gated, or handed off.

## References

- [AO first-trace quickstart](https://agent-observability-docs.splunk.com/getting-started/quickstart)
- [AO Logger API](https://agent-observability-docs.splunk.com/sdk-api/logging/splunk-ao-logger)
- [AO SaaS capabilities](https://agent-observability-docs.splunk.com/saas/capabilities)
- [AO organization keys](https://agent-observability-docs.splunk.com/references/faqs/find-keys)
- [Agent Control prerequisites](https://agent-observability-docs.splunk.com/concepts/agent-control/overview)
- [Built-in Agent Control evaluators](https://docs.agentcontrol.dev/concepts/evaluators/built-in-evaluators)
- [Create a control](https://agent-observability-docs.splunk.com/how-to-guides/agent-control/create-a-control)
- [Initialize and configure Agent Control](https://agent-observability-docs.splunk.com/how-to-guides/agent-control/initialize-and-configure-agent-control)
- [Agent Control SDK: decorate LLM and tool calls](https://docs.agentcontrol.dev/how-to/decorate-llm-tool-calls)
- [Agent Control server API reference](https://docs.agentcontrol.dev/core/reference)
