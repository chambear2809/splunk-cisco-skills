# AWS / EKS / Splunk Observability Staging Gate

`validate-aws-eks-o11y.sh` is a read-only, fail-closed acceptance runner for an
existing AWS/EKS staging environment. It verifies the expected AWS identity,
an `ACTIVE` EKS cluster, kube-context endpoint/CA/AWS-exec identity binding,
supported one-minor
`kubectl`/API-server version skew, authorization, and a
fully rolled-out staging workload, the rendered Collector workloads and image
digests, OpenTelemetry webhook/CR/injection/rollback state, the requested APM
service, and the AWS integration API. Lambda APM and Splunk Platform-to-O11y
endpoint reachability checks are optional and run only when their rendered
directory variables are configured; they are reported as non-acceptance
diagnostics rather than configured-state evidence.

Start from `aws-eks-o11y.env.example`, export the reviewed values through your
shell or CI environment, and run:

```bash
scripts/staging/validate-aws-eks-o11y.sh \
  --report artifacts/aws-eks-o11y-staging-report.json
```

The runner never sources an environment file. The O11y token stays in a
single-link, non-symlink, mode-`0600` file and is never included in the JSON
report. `SPLUNK_VERIFY_SSL=false` is refused. The report itself is atomically
published with mode `0600`; optional unconfigured checks appear as `skipped`,
and configured optional diagnostics may fail without changing acceptance.
Those failures are counted in `optional_diagnostics_failed` and their
credential-shaped output is redacted before it is shown. The token file may
end in one LF or CRLF, matching the shared secret-file writer; internal or
additional whitespace is refused.

The runner calls `sts:GetCallerIdentity`, which AWS does not require an IAM
allow for; the role's identity policy needs only `eks:DescribeCluster`.
The AWS integration check then requires the detailed Splunk read-back to expose
the exact customer `roleArn` and calls `/integration/validate/{id}`. If a realm
redacts `roleArn`, the gate fails closed because it cannot prove account/role
binding; do not replace that evidence with a name-only match.
The Kubernetes identity gets separate namespace Roles. The Collector namespace
Role can read Operator pod logs, the exact webhook Service/Endpoints, the
backup ConfigMap, and Instrumentation resources. The staging workload Role can
read only pods and workload controllers; it has no pod-log, ConfigMap, or
Secret access. Consequently `STAGING_NAMESPACE` and `COLLECTOR_NAMESPACE` must
be different. The cluster-scoped Role can read only `/version` and the exact
MutatingWebhookConfiguration. Collector validation deliberately avoids Helm
commands and does not read `sh.helm.release.v1` Secrets.

## Manual GitHub gate

The `AWS EKS O11y staging acceptance` workflow renders clean desired-state
packets and invokes this runner. Create a GitHub environment named
`aws-eks-o11y-staging`, require reviewers, restrict it to the protected branch,
and add two environment secrets:

- `AWS_STAGING_ROLE_ARN`: a dedicated GitHub OIDC role.
- `SPLUNK_O11Y_TOKEN`: a short-lived User API session token for an Observability
  Cloud administrator. The gate uses the documented integration credential
  validation endpoint as well as the read-only APM topology endpoint; rotate or
  revoke this token after the acceptance window.

The workflow pins every action to a full commit, installs the repo-audited
`kubectl` v1.35.1, and verifies its Linux AMD64 SHA-256. It also applies an
inline AWS session policy that permits only `eks:DescribeCluster` on the
selected cluster, materializes the O11y token as a mode-`0600` file, and
removes that file in an `always()` cleanup step.

The deterministic AWS packet expects an existing integration named
`<eks-cluster-name>-staging` backed by
`arn:aws:iam::<account>:role/SplunkObservabilityStagingRole`; name-only or
different-role integrations deliberately fail the gate.

## AWS trust and EKS access

Configure the GitHub OIDC provider with audience `sts.amazonaws.com`. The role
trust must use exact `StringEquals` conditions for both the audience and the
environment subject; replace these placeholders:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::__ACCOUNT_ID__:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": "repo:__OWNER__/__REPOSITORY__:environment:aws-eks-o11y-staging"
        }
      }
    }
  ]
}
```

If the repository uses GitHub's immutable owner/repository ID subject format,
substitute the exact ID-based environment subject emitted for this repository.
Do not widen the trust to `repo:*` or a repository-wide wildcard.

The role's identity policy needs `eks:DescribeCluster` only for the staging
cluster ARN. Do not attach an administrator policy; the workflow's inline
session policy is a second boundary, not a substitute for a narrow role.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "eks:DescribeCluster",
      "Resource": "arn:aws:eks:__REGION__:__ACCOUNT_ID__:cluster/__CLUSTER__"
    }
  ]
}
```

Create an EKS `STANDARD` access entry for the role and map it to Kubernetes
group `aws-eks-o11y-staging-validator`. Do not associate an EKS admin or
Secret-reader access policy. An EKS administrator can then review and replace
the four placeholders in `aws-eks-o11y-rbac.template.yaml`:

- `__COLLECTOR_NAMESPACE__` and `__STAGING_NAMESPACE__` must be different.
- Build the Operator name from the Collector release: use the release unchanged
  when it already contains `operator`; otherwise append `-operator`. If that
  value exceeds 31 characters, use its first 22 characters (trim a trailing
  `-`), a hyphen, and the first eight lowercase hex characters of its SHA-256.
- Set `__OPERATOR_WEBHOOK_NAME__` to `<operator-name>-mutation` and
  `__OPERATOR_WEBHOOK_SERVICE_NAME__` to `<operator-name>-webhook`.

The rendered auto-instrumentation `metadata.json` publishes these exact values
under `operator_resources`, which should be copied rather than guessed. Apply
`aws-eks-o11y-rbac.template.yaml`. The template grants only the read verbs used
by the gate, scoped to the collector and workload namespaces where possible;
it cannot read Kubernetes Secrets. Its cluster-scoped permission is restricted
to that exact MutatingWebhookConfiguration name. The webhook check also proves
the pinned pod-admission contract, CA bundle, Service route, ready 9443/TCP
Endpoints, Operator pod readiness, and clean recent logs; it does not perform a
synthetic TLS admission request.

```bash
aws eks create-access-entry \
  --region __REGION__ \
  --cluster-name __CLUSTER__ \
  --principal-arn __AWS_STAGING_ROLE_ARN__ \
  --type STANDARD \
  --kubernetes-groups aws-eks-o11y-staging-validator
```

Access-entry and RBAC creation stay outside the workflow because they are
one-time administrative mutations. References:

- <https://docs.aws.amazon.com/eks/latest/userguide/access-policies.html>
- <https://docs.aws.amazon.com/eks/latest/userguide/creating-access-entries.html>
- <https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws>
- <https://kubernetes.io/releases/version-skew-policy/>

## Clean local rendering

`render-aws-eks-o11y.py` creates the Collector, auto-instrumentation, and AWS
integration review packets without calling AWS, Kubernetes, or Splunk APIs.
It refuses unsafe token files and stale output directories. The manual workflow
uses this renderer before every live gate, so results cannot accidentally rely
on old local output.
