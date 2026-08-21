# Splunk Attack Analyzer Reference

`last_verified: 2026-07-02`

## Splunkbase

| Component | App name | App ID | Package pattern |
|---|---|---:|---|
| Splunk Add-on for Splunk Attack Analyzer | `Splunk_TA_SAA` | `6999` | `splunk-add-on-for-splunk-attack-analyzer_*` |
| Splunk App for Splunk Attack Analyzer | `Splunk_App_SAA` | `7000` | `splunk-app-for-splunk-attack-analyzer_*` |

Both researched versions were `1.3.0`, unrestricted, and Cloud compatible for
Splunk platform versions `9.4` through `10.5`.

The `10.5` entry is used here for the repository's current Splunk Cloud target.
Self-managed Splunk Enterprise remains on the `10.4.1` default, so this
cross-product listing must not be presented as Enterprise `10.5` validation.

## Configuration

- Default events index: `saa`
- Dashboard macro: `saa_indexes`
- Minimum documented polling interval: 300 seconds
- Add-on source types after completed-jobs input creation include
  `splunk:aa:job`, `splunk:aa:job:resource`, and `splunk:aa:job:task`.
- Enterprise Security adaptive response is optional and requires licensed ES
  plus the target correlation search decision.

## Sources

- https://splunkbase.splunk.com/app/6999
- https://splunkbase.splunk.com/app/7000
- https://help.splunk.com/en/security-offerings/splunk-attack-analyzer/splunk-add-on-for-splunk-attack-analyzer/1.2/install-and-configure-the-splunk-add-on-for-splunk-attack-analyzer/configure-the-splunk-add-on-for-splunk-attack-analyzer
- https://help.splunk.com/en/security-offerings/splunk-attack-analyzer/splunk-app-for-splunk-attack-analyzer/1.2/install-and-configure-the-splunk-app-for-splunk-attack-analyzer/configure-macros-in-the-splunk-app-for-splunk-attack-analyzer
