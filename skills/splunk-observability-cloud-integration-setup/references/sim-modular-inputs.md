# Splunk Infrastructure Monitoring Add-on Modular Input Catalog

The skill ships with a curated catalog of SignalFlow programs that operators
can clone into the Splunk Infrastructure Monitoring Add-on (`Splunk_TA_sim`,
Splunkbase 5247) without writing SignalFlow themselves.

Run `setup.sh --list-sim-templates` to see this list. Render a subset with
`setup.sh --render-sim-templates aws_ec2,kubernetes,os_hosts`.

## Catalog

| Template name      | What it streams                                                                  | Approximate MTS-per-host |
| ------------------ | -------------------------------------------------------------------------------- | ------------------------ |
| `aws_ec2`          | EC2 CPU, network in/out + packet counts, disk read/write bytes + ops, status check | 9                        |
| `aws_lambda`       | Lambda duration, errors, concurrent executions, invocations, throttles            | 5                        |
| `azure`            | Azure VM percentage CPU, network in/out, inbound/outbound flows, disk ops; Functions request, execution count, memory, response time | 16 |
| `gcp`              | GCE CPU utilization, network sent/received packets + bytes, disk read/write bytes + ops; GCF execution times, memory, count, active instances | 14 |
| `containers`       | Docker container CPU usage total + system, memory total + limit, blkio bytes read/write, network tx/rx | 8 |
| `kubernetes`       | Container CPU utilization, memory usage, kubernetes container memory limit, pod network receive/transmit errors | 5 |
| `os_hosts`         | Smart Agent / collectd CPU utilization, memory free/used/buffered/cached/active/inactive/wired, df_complex used/free, vmpage swap in/out, if_octets tx/rx, if_errors rx/tx | 18 |
| `apm_errors`       | Splunk APM service.request.duration p99 + median (error and non-error) and counts, grouped by sf_service / sf_environment / sf_error | 6 |
| `apm_throughput`   | Splunk APM service.request.count rate grouped by sf_service / sf_environment    | 1                        |
| `rum`              | Splunk RUM page_view, client_error, page_view_time p75, resource_request count + time, crash, app_error, cold_start time + count, web vitals (LCP / CLS / FID) | 12 |
| `synthetics`       | Splunk Synthetic Monitoring browser / API / HTTP / SSL / port test results       | varies                   |

## SignalFlow Hard Limits

The Splunk Infrastructure Monitoring Add-on enforces:

- **250,000 metric time series per computation** (per modular input).
- **10,000 MTS per data block metadata** by default (Standard subscription).
- **30,000 MTS per data block metadata** for Enterprise subscription.

The renderer's MTS sizing preflight estimates `entities * metrics_per_template`
and FAILs render when the per-modular-input total exceeds 250,000. The output
file `<rendered>/sim-addon/mts-sizing.md` shows the math per template and per
operator estimate.

## SAMPLE_ Prefix

The Splunk Infrastructure Monitoring Add-on ships with sample programs named
`SAMPLE_AWS_EC2`, `SAMPLE_Kubernetes`, etc. Programs with the `SAMPLE_`
prefix never run unless renamed (or manually enabled), per the add-on
documentation. The renderer always strips `SAMPLE_` when cloning catalog
programs into a runnable modular input.

The renderer rejects any user-supplied modular input name that begins with
`SAMPLE_` (case-insensitive) and emits an actionable error.

## Sizing Best Practices

- All data blocks between pipes should have similar resolution and lag
  characteristics. Best practice is to query metrics with the same
  resolution.
- Avoid wildcard expressions like `cpu*` to match many different metrics —
  this increases the likelihood that metric queries have different
  resolution and lag, requiring extra parameter tuning.
- To understand lag, create a chart in Splunk Observability Cloud with
  `rollup='lag'` for the same metric you want to query.
- Each computation spins a separate thread; no more than 8-10 computations
  per modular input is recommended for typical CPU sizing.
- The `Restart Interval for Modular Input` should be greater than the
  Metric Resolution; minimum 900 seconds (15 minutes), maximum 86400
  seconds (24 hours), default 3600 seconds (1 hour).
- The `Max wait time for delayed data` accepts 2000 ms to 900000 ms
  (2 seconds to 15 minutes); `-1` lets the system auto-compute based on
  lag history.

## Account Configuration

The SIM Add-on uses Splunk Universal Configuration Console (UCC) custom
REST handlers. The skill renders the account configuration as:

| Field                   | Value                                                                |
| ----------------------- | -------------------------------------------------------------------- |
| Account name            | from `sim_addon.account_name`                                        |
| Realm                   | from `realm`                                                         |
| Access Token            | read from the file referenced by `--org-token-file`; never inlined  |
| Job Start Rate          | 60 (Advanced Settings)                                              |
| Event Search Rate       | 30 (Advanced Settings)                                              |
| Default account         | first account is auto-default; the skill confirms                   |
| Data Collection toggle  | from `sim_addon.data_collection_enabled`                            |

## ITSI Content Pack Handoff

When `sim_addon.itsi_content_pack_handoff: true`, the skill renders an
`apply-itsi-content-pack.sh` stub that delegates to `splunk-itsi-config` to
install the Content Pack for Splunk Observability Cloud (3.4). That pack
depends on the SIM Add-on being configured first — which is exactly what
this skill does, so the handoff order is correct.

## Splunk Cloud Victoria Stack HEC Allowlist Handoff

Splunk Cloud Victoria stacks require the search head IP to be in the `hec`
allowlist before the SIM Add-on account can connect to the HEC receiver.
When `sim_addon.victoria_stack_hec_allowlist_handoff: auto`, the skill
detects the Victoria stack from ACS metadata and renders an
`apply-acs-allowlist-hec.sh` stub that delegates to
`splunk-cloud-acs-allowlist-setup --features hec`.
