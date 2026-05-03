# Intersight credentials handling

The Intersight receiver authenticates via OAuth2 client credentials with an RSA-signed JWT. You need:

- **API key ID** (UUID-shaped). Public; identifies the API client.
- **API private key** (PEM-encoded RSA private key, typically 2048-bit or 3072-bit). Highly sensitive.

The skill never reads either value. You create a Kubernetes Secret out-of-band; the rendered Deployment mounts it as env vars.

## Create the API client in Intersight

1. Log in to Intersight (https://intersight.com).
2. Navigate to **Settings** -> **API Keys** -> **Generate API Key**.
3. Choose key version 3 (recommended; supports SHA-256 + 3072-bit RSA).
4. Download the private key. Save the displayed key ID.
5. Optional: assign role-based access. The receiver only needs the read-only built-in role.

The private key file looks like:

```
-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA...
...
-----END RSA PRIVATE KEY-----
```

## Create the Kubernetes Secret

```bash
KEY_ID="abcd-1234-..."     # from Intersight UI
PRIVATE_KEY_FILE=/tmp/intersight_private_key.pem    # downloaded from Intersight

kubectl create secret generic intersight-secret \
  --from-literal=keyId="${KEY_ID}" \
  --from-file=key="${PRIVATE_KEY_FILE}" \
  -n intersight-otel
```

Then `shred -u /tmp/intersight_private_key.pem` (the value is in etcd; the file is not needed).

Verify the Secret:

```bash
kubectl -n intersight-otel describe secret intersight-secret
# Should show: Data: keyId 36 bytes, key ~1700 bytes
```

## Mount in the Deployment

The skill renders this block in `manifests/intersight-otel-deployment.yaml`:

```yaml
env:
  - name: INTERSIGHT_KEY_ID
    valueFrom:
      secretKeyRef: { name: intersight-secret, key: keyId }
  - name: INTERSIGHT_KEY
    valueFrom:
      secretKeyRef: { name: intersight-secret, key: key }
```

The collector's ConfigMap references the env vars:

```yaml
receivers:
  cisco_intersight:
    api_key_id: ${env:INTERSIGHT_KEY_ID}
    api_private_key: ${env:INTERSIGHT_KEY}
```

`${env:VAR}` is OTel collector syntax for env var substitution; the value is dereferenced at collector startup.

## Rotation

When you rotate the Intersight API key (recommended every 90 days):

1. Generate a new API key in Intersight (don't delete the old one yet).
2. Update the Secret: `kubectl create secret generic intersight-secret --from-literal=keyId=<new> --from-file=key=<new-key-file> -n intersight-otel -o yaml --dry-run=client | kubectl apply -f -`.
3. Restart the Deployment: `kubectl -n intersight-otel rollout restart deployment/intersight-otel-collector`.
4. Verify scrapes succeed in the collector logs.
5. Delete the old API key in Intersight.

## Security considerations

- The private key grants read access to ALL Intersight inventory in the org. Restrict the Kubernetes Secret access via RBAC: only the `intersight-otel-collector` ServiceAccount should be able to read it.
- Set `imagePullPolicy: Always` on the Deployment so a tampered cached image is replaced on restart.
- Enable Pod Security Standards `restricted` on the namespace to prevent privilege escalation.
- The collector container does NOT need privileged mode, host network, host PID, or any volume mounts beyond ConfigMap + Secret. The skill's rendered Deployment intentionally omits all such elevated permissions.

## SaaS-Connected vs SaaS-Only

For SaaS-Connected (legacy Intersight Connected Virtual Appliance / CVA) deployments, set `spec.base_url: https://<your-cva-fqdn>` in the spec; the renderer adds the override to the ConfigMap. SaaS-Only is `https://intersight.com` (the default).

## Anti-patterns to avoid

- **Inline private key in the rendered ConfigMap**: the renderer fails the validate.sh token-scrub check if any rendered file contains a `BEGIN RSA PRIVATE KEY` block. Always use the Secret.
- **Sharing the same private key across multiple environments**: create separate API keys for prod / staging / dev so a compromised dev key doesn't grant prod access.
- **Storing the private key in a Helm values file**: same scrub-check risk + Helm releases land in etcd in plaintext under the `helm-release` Secret. Use Kubernetes Secrets directly.
