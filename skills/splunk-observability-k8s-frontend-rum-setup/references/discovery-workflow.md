# Discovery Workflow

`setup.sh --discover-frontend-workloads` is a read-only `kubectl` walk that
inventories candidate frontend workloads so the operator can choose injection
modes per workload without writing the spec from scratch.

## What it does

1. Calls `kubectl get svc --all-namespaces` and filters for services that
   expose port 80, 8080, or 3000 (the typical frontend ports).
2. Calls `kubectl get deployment,statefulset,daemonset --all-namespaces` and
   filters for workloads whose containers' images match `nginx`, `httpd`, or
   `node`.
3. Writes:
   - `splunk-observability-k8s-frontend-rum-rendered/discovery/services.yaml`
     with the matched services.
   - `splunk-observability-k8s-frontend-rum-rendered/discovery/workloads.yaml`
     with commented-out starter `workloads:` entries that the operator
     uncomments and edits.
4. Does NOT mutate the cluster. Does NOT call any Splunk API. Does NOT
   require credentials.

## Running it

```bash
bash skills/splunk-observability-k8s-frontend-rum-setup/scripts/setup.sh \
    --discover-frontend-workloads \
    --output-dir splunk-observability-k8s-frontend-rum-rendered
```

When `kubectl` is not on the path or the cluster is unreachable, the
discovery files are still emitted (with placeholder commentary) so the
operator can hand-fill them. This makes the discovery flow safe to run in
hermetic CI contexts.

## Editing the discovered inventory

The starter `workloads.yaml` looks like:

```yaml
# Discovered Deployments / DaemonSets / StatefulSets that look like frontends
# (image patterns: nginx, httpd, node).
# Set per-workload injection_mode to one of:
#   nginx-configmap | ingress-snippet | init-container | runtime-config
workloads: []
# - kind: Deployment
#   namespace: prod
#   name: checkout-web
#   image: nginx:1.27-alpine
#   injection_mode: nginx-configmap
# - kind: Deployment
#   namespace: prod
#   name: status-page
#   image: gcr.io/distroless/static-debian12
#   injection_mode: init-container
```

Uncomment the entries you want to instrument, set the right `injection_mode`,
then re-run with `--inventory-file`:

```bash
bash skills/splunk-observability-k8s-frontend-rum-setup/scripts/setup.sh \
    --render \
    --inventory-file splunk-observability-k8s-frontend-rum-rendered/discovery/workloads.yaml
```

## Image-based mode hints

| Image substring | Suggested mode | Why |
|-----------------|----------------|-----|
| `nginx`, `nginxinc/nginx-unprivileged` | `nginx-configmap` | Mode A.i is built for the official nginx config layout. |
| `httpd` | `init-container` | httpd's `mod_substitute` works but is more fragile than initContainer rewriting. |
| `gcr.io/distroless/`, `cgr.dev/chainguard/`, anything containing `distroless` | `init-container` | Mode C auto-routes through `busybox:1.36` for the rewrite. |
| `node:`, `node-alpine` | `runtime-config` | Most Node.js SSR apps already bundle their RUM SDK; runtime-config delivers the per-env values. |
| `nginx-ingress`, `traefik`, `haproxy` | (skip — these are ingress controllers, not your frontend pod) | Pick one of the other modes against the upstream workload. |

## Read-only safety

The discovery flow uses only `kubectl get`. It never `kubectl apply`s, never
sends data to Splunk, and never reads `Secret` resources (image strings
typically come from the Pod template spec, not from a Secret). Running
discovery requires the same RBAC permissions as `kubectl get pods`.

## When to re-run discovery

- A new frontend workload was deployed and you want to pick up its candidacy.
- You added a new namespace and want to see what's in it.
- You're auditing for drift (workloads instrumented vs workloads still
  candidate).

The skill does not auto-detect drift; that's a deliberate choice to keep the
discovery surface small and predictable.
