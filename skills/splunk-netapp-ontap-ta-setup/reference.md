# NetApp ONTAP Supported Add-ons Reference

Package source of truth:

| Selector | App | Splunkbase | Verified |
| --- | --- | --- | --- |
| `ontap` | `Splunk_TA_ontap` | `3418` | `3.2.0` |
| `extractions` | `TA-ONTAP-FieldExtractions` | `5615` | `3.0.3` |
| `indexes` | `SA-ONTAPIndex` | `5616` | `3.0.3` |

`SA-ONTAPIndex` defines the `ontap` index.

## Package-Derived Source Types

Representative ONTAP source types include `ontap:perf`, `ontap:volume`,
`ontap:aggr`, `ontap:disk`, `ontap:system`, `ontap:lun`, `ontap:ems`, and
`ontap:syslog`.

The field-extractions package also includes Hydra troubleshooting source types:
`hydra_access`, `hydra_gatekeeper`, `hydra_gateway`, `hydra_scheduler`, and
`hydra_worker`.

## Guardrails

- Treat ONTAP collection as a scheduler/worker topology, not as a Universal
  Forwarder rollout.
- Keep `Splunk_TA_ontap`, `TA-ONTAP-FieldExtractions`, and `SA-ONTAPIndex`
  package versions aligned.
- Validate `ta_ontap_collection_scheduler` and `ta_ontap_collection_worker`
  stanzas plus Hydra internal logs before escalating data-readiness issues.
