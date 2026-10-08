# Splunk Enterprise 10.6 Compatibility

_Generated from `skills/catalog.yaml`, skill frontmatter, `app_registry.json`, and `splunk_platform_versions.json`._

This matrix is the self-managed Enterprise track. Splunk Cloud Platform `10.5.2605` and its Splunkbase `10.5` package evidence remain separate. Cloud compatibility does not qualify Enterprise 10.6 support.
A skill or package without explicit Enterprise 10.6 evidence for its exact default-selected package release remains conditional or blocked. A newer public release does not qualify a different verified pin. Public package metadata is not binary or checksum verification.

Baseline evidence date: `2026-10-05`. Canonical skills audited: `169`. Newly verified skills retain their own dates below.

## Summary

| Status | Skills |
| --- | ---: |
| blocked | 1 |
| conditional | 37 |
| delegated | 6 |
| not-applicable | 66 |
| supported | 59 |

## Complete matrix

| Skill | Enterprise 10.6 status | Verified | Enterprise 10.6 package evidence |
| --- | --- | --- | --- |
| `cisco-product-setup` | delegated | 2026-10-05 | No direct package evidence recorded |
| `cisco-collaboration-setup` | delegated | 2026-10-05 | No direct package evidence recorded |
| `cisco-cloud-control-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `cisco-data-fabric-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `cisco-scan-setup` | supported | 2026-10-05 | 8566 `splunk-cisco-app-navigator` selected `1.0.30` explicitly lists Enterprise 10.6 |
| `cisco-catalyst-ta-setup` | supported | 2026-10-05 | 7538 `TA_cisco_catalyst` selected `3.2.44` explicitly lists Enterprise 10.6 |
| `cisco-catalyst-enhanced-netflow-setup` | supported | 2026-10-05 | 6872 `splunk_app_stream_ipfix_cisco_hsl` selected `2.1.0` explicitly lists Enterprise 10.6 |
| `cisco-appdynamics-setup` | supported | 2026-10-05 | 3471 `Splunk_TA_AppDynamics` selected `3.2.1` explicitly lists Enterprise 10.6 |
| `splunk-appdynamics-setup` | delegated | 2026-10-05 | No direct package evidence recorded |
| `splunk-appdynamics-platform-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-appdynamics-controller-admin-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-appdynamics-agent-management-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-appdynamics-dual-agent-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-appdynamics-apm-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-appdynamics-k8s-cluster-agent-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-appdynamics-infrastructure-visibility-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-appdynamics-machine-agent-otel-collector-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-appdynamics-database-visibility-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-appdynamics-analytics-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-appdynamics-eum-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-appdynamics-synthetic-monitoring-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-appdynamics-log-observer-connect-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-appdynamics-alerting-content-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-appdynamics-dashboards-reports-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-appdynamics-thousandeyes-integration-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-appdynamics-tags-extensions-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-appdynamics-security-ai-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-appdynamics-sap-agent-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `cisco-security-cloud-setup` | supported | 2026-10-05 | 7404 `CiscoSecurityCloud` selected `3.6.10` explicitly lists Enterprise 10.6 |
| `cisco-secure-access-setup` | conditional | 2026-10-05 | 5558 `cisco-cloud-security` selected `1.0.57` explicitly lists Enterprise 10.6; 7569 `TA-cisco-cloud-security-addon` selected `1.0.53` has no explicit Enterprise 10.6 evidence |
| `cisco-webex-setup` | supported | 2026-10-05 | 8365 `ta_cisco_webex_add_on_for_splunk` selected `1.4.3` explicitly lists Enterprise 10.6; 4992 `cisco_webex_meetings_app_for_splunk` selected `2.0.0` explicitly lists Enterprise 10.6 |
| `cisco-ucs-ta-setup` | supported | 2026-10-05 | 2731 `Splunk_TA_cisco-ucs` selected `4.3.3` explicitly lists Enterprise 10.6 |
| `cisco-secure-email-web-gateway-setup` | supported | 2026-10-05 | 1761 `Splunk_TA_cisco-esa` selected `1.7.1` explicitly lists Enterprise 10.6; 1747 `Splunk_TA_cisco-wsa` selected `5.0.0` explicitly lists Enterprise 10.6 |
| `cisco-asa-ta-setup` | supported | 2026-10-05 | 1620 `Splunk_TA_cisco-asa` selected `6.1.2` explicitly lists Enterprise 10.6 |
| `cisco-talos-intelligence-setup` | supported | 2026-10-05 | 7557 `Splunk_TA_Talos_Intelligence` selected `1.0.3` explicitly lists Enterprise 10.6 |
| `cisco-spaces-setup` | supported | 2026-10-05 | 8485 `ta_cisco_spaces` selected `2.0.1` explicitly lists Enterprise 10.6 |
| `cisco-dc-networking-setup` | supported | 2026-10-05 | 7777 `cisco_dc_networking_app_for_splunk` selected `1.2.2` explicitly lists Enterprise 10.6 |
| `cisco-intersight-setup` | supported | 2026-10-05 | 7828 `Splunk_TA_Cisco_Intersight` selected `3.1.1` explicitly lists Enterprise 10.6 |
| `cisco-meraki-ta-setup` | supported | 2026-10-05 | 5580 `Splunk_TA_cisco_meraki` selected `3.4.0` explicitly lists Enterprise 10.6 |
| `cisco-meraki-aam-thousandeyes-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `cisco-enterprise-networking-setup` | supported | 2026-10-05 | 7539 `cisco-catalyst-app` selected `3.2.20` explicitly lists Enterprise 10.6 |
| `cisco-thousandeyes-setup` | supported | 2026-10-05 | 7719 `ta_cisco_thousandeyes` selected `0.8.0` explicitly lists Enterprise 10.6 |
| `cisco-thousandeyes-mcp-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `cisco-isovalent-platform-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `widefield-security-setup` | delegated | 2026-10-05 | No direct package evidence recorded |
| `widefield-okta-integration-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `widefield-saviynt-integration-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `widefield-splunk-siem-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `widefield-google-secops-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `widefield-identity-threat-doctor` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-itsi-setup` | supported | 2026-10-05 | 1841 `SA-ITOA` selected `5.0.2` explicitly lists Enterprise 10.6 |
| `splunk-itsi-config` | supported | 2026-10-05 | 5391 `DA-ITSI-ContentLibrary` selected `2.5.1` explicitly lists Enterprise 10.6 |
| `splunk-enterprise-security-install` | supported | 2026-10-05 | 263 `SplunkEnterpriseSecuritySuite` selected `8.5.1` explicitly lists Enterprise 10.6 |
| `splunk-enterprise-security-config` | conditional | 2026-10-05 | No direct package evidence recorded |
| `splunk-security-portfolio-setup` | delegated | 2026-10-05 | No direct package evidence recorded |
| `splunk-security-essentials-setup` | supported | 2026-10-07 | 3435 `Splunk_Security_Essentials` selected `3.8.3` explicitly lists Enterprise 10.6 |
| `splunk-security-content-update-setup` | supported | 2026-10-05 | 3449 `DA-ESS-ContentUpdate` selected `6.4.0` explicitly lists Enterprise 10.6 |
| `splunk-lookup-file-editing-setup` | supported | 2026-10-05 | 1724 `lookup_editor` selected `4.0.8` explicitly lists Enterprise 10.6 |
| `splunk-infosec-app-setup` | supported | 2026-10-05 | 4240 `infosec_app_for_splunk` selected `1.7.2` explicitly lists Enterprise 10.6 |
| `splunk-pci-compliance-setup` | supported | 2026-10-05 | 1143 `SplunkPCIComplianceSuite` selected `8.6.1` explicitly lists Enterprise 10.6; 2897 `SplunkPCIComplianceSuite_ES` selected `8.6.1` explicitly lists Enterprise 10.6 |
| `splunk-fraud-analytics-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `splunk-asset-risk-intelligence-setup` | supported | 2026-10-05 | 7180 `SplunkAssetRiskIntelligence` selected `1.2.2` explicitly lists Enterprise 10.6; 7214 `Splunk Asset and Risk Intelligence Technical Add-on For Windows` selected `1.2.0` explicitly lists Enterprise 10.6; 7416 `Splunk Asset and Risk Intelligence Technical Add-on For Linux` selected `1.2.0` explicitly lists Enterprise 10.6; 7417 `Splunk Asset and Risk Intelligence Technical Add-on For macOS` selected `1.2.0` explicitly lists Enterprise 10.6 |
| `splunk-attack-analyzer-setup` | supported | 2026-10-05 | 6999 `Splunk_TA_SAA` selected `1.3.0` explicitly lists Enterprise 10.6; 7000 `Splunk_App_SAA` selected `1.3.0` explicitly lists Enterprise 10.6 |
| `splunk-uba-setup` | conditional | 2026-10-05 | 4147 `Splunk-UBA-SA-Kafka` selected `1.4.6` has no explicit Enterprise 10.6 evidence |
| `splunk-ai-assistant-setup` | supported | 2026-10-05 | 7245 `Splunk_AI_Assistant_Cloud` selected `2.2.0` explicitly lists Enterprise 10.6 |
| `splunk-ai-ml-toolkit-setup` | conditional | 2026-10-05 | 2882 `Splunk_SA_Scientific_Python_linux_x86_64` selected `4.3.4` explicitly lists Enterprise 10.6; 2883 `Splunk_SA_Scientific_Python_windows_x86_64` selected `4.3.4` explicitly lists Enterprise 10.6; 2881 `Splunk_SA_Scientific_Python_darwin_x86_64` selected `4.3.4` explicitly lists Enterprise 10.6; 6785 `Splunk_SA_Scientific_Python_darwin_arm64` selected `4.3.4` explicitly lists Enterprise 10.6; 2890 `Splunk_ML_Toolkit` selected `6.0.2` explicitly lists Enterprise 10.6; 4607 `mltk-container` selected `5.2.4` explicitly lists Enterprise 10.6; 6843 `Splunk_App_for_Anomaly_Detection` selected `1.1.2` has no explicit Enterprise 10.6 evidence; 2884 `Splunk_SA_Scientific_Python_linux_x86` selected `1.3` has no explicit Enterprise 10.6 evidence; 6415 `Smart_Alerts_Assistant` selected `0.1.20` has no explicit Enterprise 10.6 evidence |
| `splunk-mcp-server-setup` | supported | 2026-10-05 | 7931 `Splunk_MCP_Server` selected `1.3.1` explicitly lists Enterprise 10.6 |
| `splunk-admin-doctor` | supported | 2026-10-05 | No direct package evidence recorded |
| `splunk-data-source-readiness-doctor` | supported | 2026-10-05 | 6841 `ocsf_cim_addon_for_splunk` selected `1.1.0` explicitly lists Enterprise 10.6 |
| `splunk-supported-addons-setup` | supported | 2026-10-05 | 833 `Splunk_TA_nix` selected `10.3.3` explicitly lists Enterprise 10.6; 3412 `Splunk_TA_Linux` selected `2.1.1` explicitly lists Enterprise 10.6 |
| `splunk-windows-ta-setup` | supported | 2026-10-05 | 742 `Splunk_TA_windows` selected `11.0.2` explicitly lists Enterprise 10.6 |
| `splunk-microsoft-cloud-setup` | supported | 2026-10-05 | 4055 `splunk_ta_o365` selected `6.1.0` explicitly lists Enterprise 10.6 |
| `splunk-aws-ta-setup` | supported | 2026-10-05 | 1876 `Splunk_TA_aws` selected `8.2.2` explicitly lists Enterprise 10.6 |
| `splunk-amazon-kinesis-firehose-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `splunk-okta-ta-setup` | supported | 2026-10-05 | 6553 `Splunk_TA_okta_identity_cloud` selected `5.1.0` explicitly lists Enterprise 10.6 |
| `splunk-gcp-ta-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `splunk-servicenow-ta-setup` | supported | 2026-10-05 | 1928 `Splunk_TA_snow` selected `11.0.2` explicitly lists Enterprise 10.6 |
| `splunk-google-workspace-ta-setup` | supported | 2026-10-05 | 5556 `Splunk_TA_Google_Workspace` selected `4.0.0` explicitly lists Enterprise 10.6 |
| `splunk-microsoft-security-ta-setup` | supported | 2026-10-05 | 6207 `Splunk_TA_MS_Security` selected `4.0.0` explicitly lists Enterprise 10.6 |
| `splunk-microsoft-exchange-ta-setup` | supported | 2026-10-05 | 3225 `TA-Exchange-ClientAccess` selected `4.1.1` explicitly lists Enterprise 10.6; 5663 `SA-ExchangeIndex` selected `4.0.4` explicitly lists Enterprise 10.6 |
| `splunk-microsoft-scom-ta-setup` | supported | 2026-10-05 | 2729 `Splunk_TA_microsoft-scom` selected `4.5.1` explicitly lists Enterprise 10.6 |
| `splunk-sysmon-ta-setup` | supported | 2026-10-05 | 5709 `Splunk_TA_microsoft_sysmon` selected `5.0.1` explicitly lists Enterprise 10.6 |
| `splunk-github-ta-setup` | conditional | 2026-10-05 | 6254 `Splunk_TA_github` selected `4.0.0` has no explicit Enterprise 10.6 evidence |
| `splunk-salesforce-ta-setup` | supported | 2026-10-05 | 3549 `Splunk_TA_salesforce` selected `7.0.0` explicitly lists Enterprise 10.6 |
| `splunk-box-ta-setup` | supported | 2026-10-05 | 2679 `Splunk_TA_box` selected `5.0.1` explicitly lists Enterprise 10.6 |
| `splunk-cyberark-ta-setup` | conditional | 2026-10-05 | 5160 `Splunk_TA_cyberark_epm` selected `5.0.0` has no explicit Enterprise 10.6 evidence; 2891 `Splunk_TA_cyberark` selected `1.2.0` explicitly lists Enterprise 10.6 |
| `splunk-rsa-securid-ta-setup` | supported | 2026-10-05 | 5210 `Splunk_TA_rsa_securid_cas` selected `1.2.3` explicitly lists Enterprise 10.6; 2958 `Splunk_TA_rsa-securid` selected `1.5.0` explicitly lists Enterprise 10.6 |
| `splunk-security-appliance-ta-setup` | supported | 2026-10-05 | 2790 `Splunk_TA_bit9-carbonblack` selected `3.0.0` explicitly lists Enterprise 10.6; 2772 `Splunk_TA_symantec-ep` selected `4.0.1` explicitly lists Enterprise 10.6 |
| `splunk-syslog-web-proxy-ta-setup` | supported | 2026-10-05 | 3186 `Splunk_TA_apache` selected `3.0.0` explicitly lists Enterprise 10.6; 3258 `Splunk_TA_nginx` selected `3.3.2` explicitly lists Enterprise 10.6; 3185 `Splunk_TA_microsoft-iis` selected `2.0.0` explicitly lists Enterprise 10.6; 2911 `Splunk_TA_tomcat` selected `4.0.4` explicitly lists Enterprise 10.6; 3135 `Splunk_TA_haproxy` selected `2.0.0` explicitly lists Enterprise 10.6; 2965 `Splunk_TA_squid` selected `2.1.0` explicitly lists Enterprise 10.6; 2758 `Splunk_TA_bluecoat-proxysg` selected `3.9.0` explicitly lists Enterprise 10.6; 2966 `Splunk_TA_websense-cg` selected `1.1.0` explicitly lists Enterprise 10.6; 5478 `Splunk_TA_checkpoint_log_exporter` selected `1.2.0` explicitly lists Enterprise 10.6; 2680 `Splunk_TA_f5-bigip` selected `7.0.0` explicitly lists Enterprise 10.6; 2770 `Splunk_TA_citrix-netscaler` selected `8.2.5` explicitly lists Enterprise 10.6; 2934 `Splunk_TA_infoblox` selected `2.2.0` explicitly lists Enterprise 10.6 |
| `splunk-vmware-ta-setup` | supported | 2026-10-05 | 3215 `Splunk_TA_vmware` selected `4.2.1` explicitly lists Enterprise 10.6; 5089 `Splunk_TA_vmware_inframon` selected `5.0.1` explicitly lists Enterprise 10.6 |
| `splunk-database-ta-setup` | supported | 2026-10-05 | 2648 `Splunk_TA_microsoft-sqlserver` selected `3.1.0` explicitly lists Enterprise 10.6; 2848 `Splunk_TA_mysql` selected `3.2.0` explicitly lists Enterprise 10.6; 1910 `Splunk_TA_oracle` selected `4.2.0` explicitly lists Enterprise 10.6 |
| `splunk-netapp-ontap-ta-setup` | supported | 2026-10-05 | 3418 `Splunk_TA_ontap` selected `3.2.1` explicitly lists Enterprise 10.6; 5615 `TA-ONTAP-FieldExtractions` selected `3.0.3` explicitly lists Enterprise 10.6; 5616 `SA-ONTAPIndex` selected `3.0.3` explicitly lists Enterprise 10.6 |
| `splunk-spl2-pipeline-kit` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-ingest-processor-setup` | not-applicable | 2026-10-08 | No direct package evidence recorded |
| `splunk-cloud-data-manager-setup` | not-applicable | 2026-10-08 | No direct package evidence recorded |
| `splunk-db-connect-setup` | supported | 2026-10-05 | 2686 `splunk_app_db_connect` selected `4.3.0` explicitly lists Enterprise 10.6; 6149 `Amazon Redshift JDBC Driver Add-on for Splunk DB Connect` selected `1.2.2` explicitly lists Enterprise 10.6; 6150 `Microsoft SQL Server JDBC Driver Add-on for Splunk DB Connect` selected `1.3.2` explicitly lists Enterprise 10.6; 6151 `Oracle JDBC Driver Add-on for Splunk DB Connect` selected `2.2.2` explicitly lists Enterprise 10.6; 6152 `PostgreSQL JDBC Driver Add-on for Splunk DB Connect` selected `1.2.2` explicitly lists Enterprise 10.6; 6153 `Snowflake JDBC Driver Add-on for Splunk DB Connect` selected `1.2.4` explicitly lists Enterprise 10.6; 6154 `MySQL JDBC Driver Add-on for Splunk DB Connect` selected `1.1.3` explicitly lists Enterprise 10.6; 6332 `IBM DB2 JDBC Driver Add-on for Splunk DB Connect` selected `1.1.1` explicitly lists Enterprise 10.6; 7095 `MongoDB JDBC Driver Add-on for Splunk DB Connect` selected `1.3.0` explicitly lists Enterprise 10.6; 8133 `Amazon Athena JDBC Driver Add-on for Splunk DB Connect` selected `1.0.1` explicitly lists Enterprise 10.6 |
| `splunk-app-install` | supported | 2026-10-05 | No direct package evidence recorded |
| `splunk-universal-forwarder-setup` | supported | 2026-10-05 | No direct package evidence recorded |
| `splunk-agent-management-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `splunk-workload-management-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `splunk-hec-service-setup` | supported | 2026-10-05 | No direct package evidence recorded |
| `splunk-platform-restart-orchestrator` | conditional | 2026-10-05 | No direct package evidence recorded |
| `splunk-connect-for-otlp-setup` | conditional | 2026-10-05 | 8704 `splunk-connect-for-otlp` selected `0.4.1` has no explicit Enterprise 10.6 evidence |
| `splunk-federated-search-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `splunk-index-lifecycle-smartstore-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `splunk-kvstore-admin-setup` | supported | 2026-10-05 | No direct package evidence recorded |
| `splunk-cim-data-model-setup` | supported | 2026-10-05 | 1621 `Splunk_SA_CIM` selected `8.5.0` explicitly lists Enterprise 10.6 |
| `splunk-knowledge-objects-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `splunk-ingest-actions-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `splunk-ddaa-archive-setup` | not-applicable | 2026-10-08 | No direct package evidence recorded |
| `splunk-secure-gateway-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `splunk-dashboard-studio-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `splunk-monitoring-console-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `splunk-enterprise-host-setup` | supported | 2026-10-05 | No direct package evidence recorded |
| `splunk-enterprise-kubernetes-setup` | blocked | 2026-10-05 | No direct package evidence recorded |
| `splunk-platform-sizing` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-observability-otel-collector-setup` | supported | 2026-10-05 | 7125 `Splunk_TA_otel` selected `0.158.0` explicitly lists Enterprise 10.6; 8698 `Splunk_TA_otel_linux_x86_64` selected `0.158.0` explicitly lists Enterprise 10.6; 8699 `Splunk_TA_otel_windows_x86_64` selected `0.158.0` explicitly lists Enterprise 10.6 |
| `splunk-observability-ai-agent-monitoring-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `splunk-agent-observability-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-observability-coding-agent-instrumentation-setup` | delegated | 2026-10-05 | No direct package evidence recorded |
| `splunk-observability-codex-instrumentation-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-observability-claude-code-instrumentation-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-observability-database-monitoring-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-observability-k8s-auto-instrumentation-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-observability-k8s-frontend-rum-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-observability-browser-rum-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-observability-mobile-rum-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-observability-cloud-integration-setup` | conditional | 2026-10-05 | 5247 `Splunk_TA_sim` selected `1.3.1` explicitly lists Enterprise 10.6; 5608 `splunk_synthetic_monitoring` selected `1.1.0` has no explicit Enterprise 10.6 evidence |
| `splunk-observability-thousandeyes-integration` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `galileo-on-prem-kubernetes-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `galileo-on-prem-stack-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `galileo-on-prem-agent-control-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `galileo-on-prem-luna-studio-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `galileo-on-prem-air-gap-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `galileo-mcp-server-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `galileo-platform-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `galileo-lemonade-instrumentation-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `lemonade-splunk-otel` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `galileo-agent-control-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-observability-isovalent-integration` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-observability-cisco-nexus-integration` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-observability-cisco-intersight-integration` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-observability-nvidia-gpu-integration` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-observability-cisco-ai-pod-integration` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-observability-aws-integration` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-observability-azure-integration` | not-applicable | 2026-10-05 | 3110 `Splunk_TA_microsoft-cloudservices` selected `6.3.1` explicitly lists Enterprise 10.6; 4882 `microsoft_azure_app` selected `2.1.1` explicitly lists Enterprise 10.6 |
| `splunk-observability-gcp-integration` | not-applicable | 2026-10-05 | 3088 `Splunk_TA_google-cloudplatform` selected `5.1.1` has no explicit Enterprise 10.6 evidence |
| `splunk-observability-aws-lambda-apm-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-observability-dashboard-builder` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-observability-deep-native-workflows` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-observability-native-ops` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-observability-synthetics-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-observability-slo-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-observability-metrics-pipeline-setup` | not-applicable | 2026-10-05 | No direct package evidence recorded |
| `splunk-oncall-setup` | conditional | 2026-10-05 | 3546 `victorops_app` selected `1.0.43` explicitly lists Enterprise 10.6; 4886 `TA-splunk-add-on-for-victorops` selected `2.1.0` explicitly lists Enterprise 10.6; 5863 `splunkoncall` selected `3.0.0` has no explicit Enterprise 10.6 evidence |
| `splunk-stream-setup` | supported | 2026-10-05 | 1809 `splunk_app_stream` selected `8.1.6` explicitly lists Enterprise 10.6; 5238 `Splunk_TA_stream` selected `8.1.6` explicitly lists Enterprise 10.6; 5234 `Splunk_TA_stream_wire_data` selected `8.1.6` explicitly lists Enterprise 10.6 |
| `splunk-stream-windows-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `splunk-connect-for-syslog-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `splunk-connect-for-snmp-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `splunk-license-manager-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `splunk-soar-setup` | supported | 2026-10-05 | 6361 `splunk_app_soar` selected `8.6.0` explicitly lists Enterprise 10.6; 3411 `phantom` selected `8.7.0` explicitly lists Enterprise 10.6 |
| `splunk-edge-processor-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `splunk-indexer-cluster-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `splunk-search-head-cluster-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `splunk-deployment-server-setup` | conditional | 2026-10-05 | No direct package evidence recorded |
| `splunk-cloud-acs-admin-setup` | not-applicable | 2026-10-08 | No direct package evidence recorded |
| `splunk-cloud-acs-allowlist-setup` | not-applicable | 2026-10-08 | No direct package evidence recorded |
| `splunk-enterprise-public-exposure-hardening` | conditional | 2026-10-05 | No direct package evidence recorded |
| `splunk-platform-pki-setup` | conditional | 2026-10-05 | 3172 `ssl_certificate_checker` selected `4.2.0` has no explicit Enterprise 10.6 evidence; 4603 `splunk_health_assistant_addon` selected `2026.5.23` explicitly lists Enterprise 10.6 |
