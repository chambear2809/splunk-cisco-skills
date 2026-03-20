# SC4S Kubernetes Templates

These files are the base templates for Helm-managed SC4S deployments.

## Files

- `values.yaml` — main Helm values file
- `namespace.yaml` — optional namespace manifest

## Token Handling

The upstream chart documents `splunk.hec_token` as a Helm value. To avoid
keeping the token in the main `values.yaml`, the render script writes:

- `values.yaml` without a token
- `values.secret.yaml` only when a local HEC token file is supplied
- `helm-install.sh` that uses both files

Keep `values.secret.yaml` local-only.

## Supported Rendered Blocks

- `splunk.hec_url`
- `splunk.hec_verify_tls`
- `replicaCount`
- `sc4s.existingCert`
- `sc4s.vendor_product`
- `sc4s.context_files`
- `sc4s.config_files`
