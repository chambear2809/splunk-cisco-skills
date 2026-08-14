# Training and storage contract

## Object storage

| Provider | Supported auth modes | Conditional Secret |
|---|---|---|
| `gcp` | `workload_identity`, `oidc`, `service_account` | `luna-finetune-oidc` or `luna-finetune-gcp-sa` |
| `aws` | `irsa`, `static`, `sts` | `luna-finetune-aws-credentials` or `luna-finetune-aws-sts` |
| `azure` | `managed_identity`, `connection_string`, `sas` | `luna-finetune-azure-connection` or `luna-finetune-azure-sas` |
| `minio` | exact chart/CSE-approved S3-compatible mode | Customer-provided Secret contract |

Use a dedicated bucket/container for training configurations, generated
datasets, and output models. Validate a scoped write/read/delete cycle without
printing object-store credentials.

## Training

`training.platform.provider` is `kubernetes` or `vertex_ai`. Kubernetes Jobs can
run locally or on a remote cluster. A remote target requires
`luna-finetune-remote-cluster-token` key `token`, a pinned HTTPS API server,
namespace, scoped ServiceAccount/RBAC, and independent target identity evidence.

GPU Kubernetes Jobs require a non-empty node selector, `nvidia.com/gpu` resource
type, positive count, matching taints/tolerations, device-plugin capacity, and
pinned training/data-generation images. Backend and UI must not request GPUs.

Vertex AI requires a GCP project, location, pipeline name/root, pinned training
and data-generation images, storage/IAM access, and approved Google API egress.
It is incompatible with a strict no-egress environment unless private supported
endpoints are documented and validated.
