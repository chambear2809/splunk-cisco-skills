# SC4SNMP Kubernetes Templates

These files are the base templates for Helm-managed SC4SNMP deployments.

They render:

- `namespace.yaml`
- `values.yaml`
- `values.secret.yaml`
- `helm-install.sh` for install or upgrade

The rendered files are intended as an operator starting point and should remain
local-only when they contain secrets.
