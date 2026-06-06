# Security Content Update Reference

Primary app: `DA-ESS-ContentUpdate` (Splunkbase `3449`).

## Readiness Scope

- Confirm Enterprise Security is installed and current enough for the target
  ESCU release.
- Install ESCU on the ES search tier or through the managed ES Cloud workflow.
- Review Analytic Story Detail and content inventory before enabling searches.
- Treat correlation-search activation as an ES configuration decision, not as
  an automatic install side effect.

## Handoffs

- App install package: `splunk-app-install`
- ES correlation-search, risk, notable, and content readiness:
  `splunk-enterprise-security-config`
- CIM/data-model coverage for content prerequisites:
  `splunk-cim-data-model-setup`
