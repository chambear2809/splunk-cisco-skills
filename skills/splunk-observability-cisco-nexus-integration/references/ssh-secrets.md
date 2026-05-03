# SSH credentials handling

The skill never reads SSH passwords or private keys. Credentials live in a Kubernetes Secret you create out-of-band; the cluster-receiver collector mounts the Secret via env vars (password auth) or volume mount (key auth).

## Password auth (default)

Create the Secret:

```bash
kubectl create secret generic cisco-nexus-ssh \
  --from-literal=username=splunk-otel \
  --from-file=password=/tmp/nexus_password \
  -n splunk-otel
```

The renderer wires `clusterReceiver.extraEnvs` to inject the Secret values:

```yaml
clusterReceiver:
  extraEnvs:
    - name: CISCO_NEXUS_SSH_USERNAME
      valueFrom:
        secretKeyRef:
          name: cisco-nexus-ssh
          key: username
    - name: CISCO_NEXUS_SSH_PASSWORD
      valueFrom:
        secretKeyRef:
          name: cisco-nexus-ssh
          key: password
```

The cisco_os receiver then references the env vars in each device's auth block:

```yaml
auth:
  username: ${env:CISCO_NEXUS_SSH_USERNAME}
  password: ${env:CISCO_NEXUS_SSH_PASSWORD}
```

## Key auth

Set `spec.ssh_secret.key_file_key` (and clear `password_key`):

```yaml
ssh_secret:
  name: cisco-nexus-ssh
  namespace: splunk-otel
  username_key: username
  password_key: ""
  key_file_key: key
```

Create the Secret with the SSH private key:

```bash
kubectl create secret generic cisco-nexus-ssh \
  --from-literal=username=splunk-otel \
  --from-file=key=/path/to/ssh/key \
  -n splunk-otel
```

The renderer mounts the Secret as a volume at `/etc/cisco-nexus-ssh/key` (defaultMode 0400):

```yaml
clusterReceiver:
  extraVolumes:
    - name: cisco-nexus-ssh-key
      secret:
        secretName: cisco-nexus-ssh
        items:
          - key: key
            path: key
        defaultMode: 0400
  extraVolumeMounts:
    - name: cisco-nexus-ssh-key
      mountPath: /etc/cisco-nexus-ssh
      readOnly: true
```

The cisco_os receiver references the path:

```yaml
auth:
  username: ${env:CISCO_NEXUS_SSH_USERNAME}
  key_file: /etc/cisco-nexus-ssh/key
```

## Per-device credentials

If different Nexus devices use different SSH credentials (e.g. a vendor-managed device with a stricter password policy), create one Secret per credential set and use multiple `extraEnvs` blocks with distinct env var names:

```yaml
clusterReceiver:
  extraEnvs:
    - name: NEXUS_PROD_USER
      valueFrom: { secretKeyRef: { name: nexus-prod-ssh, key: username } }
    - name: NEXUS_PROD_PASSWORD
      valueFrom: { secretKeyRef: { name: nexus-prod-ssh, key: password } }
    - name: NEXUS_LAB_USER
      valueFrom: { secretKeyRef: { name: nexus-lab-ssh, key: username } }
    - name: NEXUS_LAB_PASSWORD
      valueFrom: { secretKeyRef: { name: nexus-lab-ssh, key: password } }
```

Then in the cisco_os device list:

```yaml
devices:
  - name: prod-spine-01
    host: 10.0.1.1
    auth:
      username: ${env:NEXUS_PROD_USER}
      password: ${env:NEXUS_PROD_PASSWORD}
  - name: lab-leaf-01
    host: 10.0.2.1
    auth:
      username: ${env:NEXUS_LAB_USER}
      password: ${env:NEXUS_LAB_PASSWORD}
```

The skill does not currently render per-device-credential mappings; hand-edit the overlay.

## Rotation

When you rotate the SSH password (recommended quarterly):

1. Update the Secret: `kubectl create secret generic cisco-nexus-ssh --from-literal=password=new ... -o yaml --dry-run=client | kubectl apply -f -`.
2. Restart the cluster-receiver pod to pick up the new value: `kubectl -n splunk-otel rollout restart deployment/<release>-splunk-otel-collector-k8s-cluster-receiver`.
3. Verify scrapes succeed in the collector logs.

## Anti-patterns to avoid

- **Inline credentials in the rendered overlay**: the renderer fails the validate.sh token-scrub check if any rendered file contains an SSH password or private key. Always use Secret references.
- **Single SSH user for read + write**: create a dedicated read-only user for telemetry scrapes; never reuse a credential that can change device configuration.
- **Storing the password file in a tracked repo**: pass `--from-file=/tmp/nexus_password` and delete `/tmp/nexus_password` after Secret creation. The Secret value persists in etcd; the file does not need to.
