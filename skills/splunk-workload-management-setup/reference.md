# Splunk Workload Management Reference

Workload Management is a Splunk Enterprise feature for allocating CPU and
memory resources to search, ingest, and miscellaneous workload categories. It
also supports workload rules for search placement and monitoring, plus admission
rules that can filter searches before they run.

## Prerequisites

- Splunk Enterprise on Linux.
- Linux cgroups configured for the target Splunk version and operating system.
- Splunk Enterprise 9.4 and higher supports cgroups v1 and v2, with automatic
  cgroup version detection on supported Linux systems.
- For cgroups v2 on Linux with systemd, Splunk should run as a systemd-managed
  service.

## Rendered Files

| File | Purpose |
|------|---------|
| `workload_pools.conf` | Workload categories and pools |
| `workload_rules.conf` | Workload placement, monitoring, and admission rules |
| `workload_policy.conf` | Admission-rule global enablement |
| `preflight.sh` | Splunk CLI and workload status checks |
| `apply.sh` | Installs the rendered app and optionally enables workload management |
| `status.sh` | Shows workload status, pools, and rules |

## Rule Notes

Workload rules support predicates such as `app`, `role`, `user`, `index`,
`search_type`, `search_mode`, `search_time_range`, and `runtime`.

Monitoring actions such as `alert`, `abort`, and `move` require a `runtime`
condition. The `move` action also requires a destination `workload_pool`; alert
and abort rules do not.
Admission rules are stored in `workload_rules.conf` under
`[search_filter_rule:<rule_name>]`. Global admission-rule enablement is stored
in `workload_policy.conf` under `[search_admission_control]`.

The rendered all-time admission guardrail supports `action = filter`. Splunk
also has a queue action for admission rules, but the configuration reference
limits queue to `adhoc_search_percentage` predicates with `search_type=adhoc`;
this skill does not render that specialized queue rule in v1.

## Official References

- Workload Management overview:
  <https://help.splunk.com/en/splunk-enterprise/administer/manage-workloads/10.2/workload-management-overview/about-workload-management>
- Set up Linux for Workload Management:
  <https://help.splunk.com/en/splunk-enterprise/administer/manage-workloads/10.2/set-up-linux-for-workload-management/set-up-linux-for-workload-management>
- Configure cgroups v2:
  <https://help.splunk.com/en/splunk-enterprise/administer/manage-workloads/10.2/set-up-linux-for-workload-management/configure-cgroups-v2-in-splunk-enterprise>
- Configure workload pools:
  <https://help.splunk.com/en/splunk-enterprise/administer/manage-workloads/10.2/configure-workload-management/configure-workload-pools>
- Configure workload rules:
  <https://help.splunk.com/en/splunk-enterprise/administer/manage-workloads/10.2/configure-workload-management/configure-workload-rules>
- Configure admission rules:
  <https://help.splunk.com/en/splunk-enterprise/administer/manage-workloads/10.2/configure-workload-management/configure-admission-rules-to-prefilter-searches>
