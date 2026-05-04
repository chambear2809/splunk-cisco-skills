# Troubleshooting

## "I annotated my Deployment but no init container appears"

1. Confirm the annotation is on the **pod template**, not the Deployment:

   ```bash
   kubectl get deploy <name> -n <ns> -o jsonpath='{.spec.template.metadata.annotations}'
   ```

   This should contain `instrumentation.opentelemetry.io/inject-<lang>`. If it does NOT and the Deployment's top-level annotations DO, you hit the single most common authoring bug. Fix with `apply-annotations.sh`.

2. Confirm pods restarted after the annotation was added:

   ```bash
   kubectl -n <ns> get pods -l app=<name> --sort-by=.metadata.creationTimestamp
   ```

   If no pod was created after the annotation, run `kubectl rollout restart <kind>/<name>`.

3. Confirm the operator is running:

   ```bash
   kubectl -n splunk-otel get pods -l app.kubernetes.io/name=operator
   ```

4. Confirm the operator saw the creation event:

   ```bash
   kubectl -n splunk-otel logs -l app.kubernetes.io/name=operator | grep <pod-name>
   ```

## "Init container completed but no traces in APM"

1. Check the init container finished successfully:

   ```bash
   kubectl -n <ns> describe pod <pod> | grep -A5 "opentelemetry-auto-instrumentation"
   ```

   State should be `Terminated: Completed`.

2. Check the app container has the expected env:

   ```bash
   kubectl -n <ns> get pod <pod> -o jsonpath='{.spec.containers[0].env}' | tr ',' '\n'
   ```

   Look for:
   - `OTEL_EXPORTER_OTLP_ENDPOINT`
   - Language-specific: `JAVA_TOOL_OPTIONS=-javaagent:/otel-auto-instrumentation/javaagent.jar`, `NODE_OPTIONS=--require=/otel-auto-instrumentation/autoinstrumentation.node/node_modules/@splunk/otel/instrument`, `PYTHONPATH=/otel-auto-instrumentation/autoinstrumentation-python`, `CORECLR_PROFILER={918728DD-259F-4A6A-AC2B-B85E1B658318}`, `OTEL_GO_AUTO_TARGET_EXE=/app/service`.

3. Confirm the agent is reachable:

   ```bash
   kubectl -n <ns> exec <pod> -- wget -O- -q http://$SPLUNK_OTEL_AGENT:4317 2>&1 | head -5
   ```

   (OTLP gRPC over HTTP/1.1 will say "connection reset" — that's normal, it proves the TCP path is open.)

4. Check the base collector's logs for OTLP receiver traffic:

   ```bash
   kubectl -n splunk-otel logs -l component=otel-collector-agent --tail=100 | grep -i otlp
   ```

## "The webhook keeps failing"

If operator logs show `failed to call webhook`:

```bash
kubectl -n splunk-otel logs -l app.kubernetes.io/name=operator | grep "failed to call webhook"
```

Common causes:

- **Port 9443 firewall**: GKE Private Cluster, EKS with Cilium non-ENI mode. Fix: firewall rule to allow the control plane -> pod 9443, or `operator.hostNetwork: true` in the base chart values.
- **Cert expiry**: if you're using `cert-manager` and the operator cert expired. Fix: recreate via `cmctl renew` or delete/recreate the Certificate.
- **Admission config drift**: if someone ran `kubectl delete mutatingwebhookconfiguration splunk-otel-collector-opentelemetry-operator-mutation` manually. Fix: `helm upgrade` the base collector chart to re-render.

## "kubectl get otelinst shows my CR but pods aren't injected"

Check the CR's endpoint is resolvable from inside the target pod namespace:

```bash
kubectl -n <target-ns> run dns-test --rm -it --image=busybox -- nslookup splunk-otel-collector-agent.splunk-otel.svc.cluster.local
```

Also confirm the CR namespace matches the chart's. If the CR is in `observability` but the chart renders the agent env var into pods pointing at `splunk-otel`, the endpoint `$(SPLUNK_OTEL_AGENT)` won't resolve to anything useful. Fix: render the CR in the same namespace as the base collector release.

## "My Java app has high CPU after enabling profiling"

AlwaysOn Profiling CPU cost depends on `SPLUNK_PROFILER_CALL_STACK_INTERVAL` (default 10000ms = 10s). Lower interval = more CPU. If you see >3% overhead:

1. Raise interval to 30000 (30s).
2. Disable memory profiling: `SPLUNK_PROFILER_MEMORY_ENABLED=false`.

## "OBI DaemonSet is CrashLooping"

```bash
kubectl -n splunk-otel logs ds/splunk-obi -c obi --previous | tail -40
```

Common causes:

- Kernel < 5.8. Fix: upgrade nodes, or disable OBI and use operator injection.
- PSS `restricted`/`baseline` on the splunk-otel namespace. Fix: relax PSS or use a dedicated namespace with `privileged` enforce.
- OpenShift without the SCC binding. Fix: `kubectl apply -f openshift-scc-obi.yaml` (rendered by this skill).
- hostPath mount denied by admission controller. Fix: ensure the namespace allows hostPath or run OBI on a dedicated control-plane node pool.

## "I want to undo everything"

```bash
bash splunk-observability-k8s-auto-instrumentation-rendered/k8s-instrumentation/uninstall.sh \
  --accept-auto-instrumentation \
  --target-all \
  --purge-crs \
  --purge-backup
```

This reverses every annotation from the backup ConfigMap, rolls out all affected workloads, deletes every rendered Instrumentation CR, and deletes the backup ConfigMap. **Do NOT run `helm uninstall` on the base collector before this** — the CR must be deleted first to avoid orphaning.

## "What does the verify script check?"

`verify-injection.sh --target Deployment/<ns>/<name>`:

1. `kubectl describe pod <sample-pod>` — prints pod spec.
2. Asserts `opentelemetry-auto-instrumentation` init container exists.
3. Asserts `OTEL_EXPORTER_OTLP_ENDPOINT` env is set.
4. Prints the rendered language-specific env (`JAVA_TOOL_OPTIONS`, etc.).

This is the diagnostic to run after `apply-annotations.sh` to confirm injection actually happened before looking at APM.
