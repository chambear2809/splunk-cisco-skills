# OpenShift Security Context Constraints

OpenShift Security Context Constraints (SCCs) can prevent the Splunk OTel
collector agent from using the host access required by enabled receivers and
hostPath log mounts. The umbrella renders `openshift/scc.sh` as an explicit,
review-required helper.

## Exact Helper Behavior

The current helper does not create a custom SCC. It grants two built-in SCCs
to one ServiceAccount:

```bash
#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${1:-splunk-otel}"
RELEASE="${2:-splunk-otel-collector}"
oc adm policy add-scc-to-user anyuid -z "${RELEASE}" -n "${NAMESPACE}"
oc adm policy add-scc-to-user privileged -z "${RELEASE}" -n "${NAMESPACE}"
```

The positional arguments are the collector namespace and ServiceAccount name.
The defaults assume both the Helm release and its ServiceAccount are named
`splunk-otel-collector` in namespace `splunk-otel`.

`privileged` is a broad cluster permission. Review the rendered script, the
actual chart ServiceAccount, enabled host receivers, and organizational
OpenShift policy before running it. If the platform team requires a narrower
custom SCC, treat that as an external security handoff; this skill does not
render one.

## Apply

After rendering and confirming the target identity:

```bash
bash splunk-observability-cisco-ai-pod-rendered/openshift/scc.sh \
  splunk-otel splunk-otel-collector
```

Use the namespace and ServiceAccount that the reviewed collector release will
actually use. The command requires an authenticated `oc` session with
permission to grant SCC use.

## Verification

After the collector is deployed, verify the ServiceAccount and SCC selected by
OpenShift:

```bash
oc -n splunk-otel get pods \
  -l app.kubernetes.io/name=splunk-otel-collector \
  -o custom-columns=NAME:.metadata.name,SA:.spec.serviceAccountName,SCC:.metadata.annotations.openshift\\.io/scc

oc adm policy who-can use scc/anyuid
oc adm policy who-can use scc/privileged
```

Confirm that only the intended ServiceAccount received the grants. Pod labels
vary by chart version, so adjust the selector after inspecting the release if
the first command returns no pods.

## Removal

Remove both grants when the collector no longer needs them:

```bash
oc adm policy remove-scc-from-user anyuid \
  -z splunk-otel-collector -n splunk-otel
oc adm policy remove-scc-from-user privileged \
  -z splunk-otel-collector -n splunk-otel
```

The helper creates no `splunk-otel-collector` SCC object, so do not run
`oc delete scc splunk-otel-collector` as part of this skill's cleanup.

## Related OpenShift Overlay Settings

When `--distribution openshift` is selected, the umbrella also renders these
collector values:

- `agent.config.receivers.kubeletstats.insecure_skip_verify: true`
- `cloudProvider: ""`
- `certmanager.enabled: false`
- operator, operator CRDs, and gateway disabled

Those settings are independent of SCC grants. Review them against the actual
cluster topology, especially existing certificate-management and operator
ownership, before applying the composed overlay.
