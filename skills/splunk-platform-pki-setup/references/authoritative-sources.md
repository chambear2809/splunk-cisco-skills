# Authoritative Sources

Frozen list of upstream Splunk doc URLs that anchor every design
decision in this skill. Each entry includes the **last verified
on** date so a future preflight failure can cite a stable source.
The renderer's `preflight.sh` references these URLs in error
messages so the operator can audit "why does the skill require
X" against the upstream spec.

When refreshing: bump the date and reconfirm the doc still says
what the skill assumes. If the doc changed materially, update the
relevant reference and renderer logic.

> Last reviewed: 2026-05-03

## TLS lifecycle

- [Steps for securing your Splunk Enterprise deployment with TLS](https://help.splunk.com/en/splunk-enterprise/administer/manage-users-and-security/10.0/secure-splunk-platform-communications-with-transport-layer-security-certificates/steps-for-securing-your-splunk-enterprise-deployment-with-tls)
- [How to create and sign your own TLS certificates](https://help.splunk.com/en/splunk-enterprise/administer/manage-users-and-security/10.0/secure-splunk-platform-communications-with-transport-layer-security-certificates/how-to-create-and-sign-your-own-tls-certificates)
- [How to prepare TLS certificates for use with the Splunk platform](https://help.splunk.com/en/splunk-enterprise/administer/manage-users-and-security/10.0/secure-splunk-platform-communications-with-transport-layer-security-certificates/how-to-prepare-tls-certificates-for-use-with-the-splunk-platform)
- [How to obtain certificates from a third party for inter-Splunk communication](https://help.splunk.com/en/splunk-enterprise/administer/manage-users-and-security/10.0/secure-splunk-platform-communications-with-transport-layer-security-certificates/how-to-obtain-certificates-from-a-third-party-for-inter-splunk-communication)
- [How to obtain certificates from a third party for Splunk Web](https://help.splunk.com/en/splunk-enterprise/administer/manage-users-and-security/10.0/secure-splunk-platform-communications-with-transport-layer-security-certificates/how-to-obtain-certificates-from-a-third-party-for-splunk-web)
- [Renew existing TLS certificates](https://docs.splunk.com/Documentation/Splunk/9.4.1/Security/RenewExistingCerts)
- [Test and troubleshoot TLS connections](https://help.splunk.com/en/splunk-enterprise/administer/manage-users-and-security/10.0/secure-splunk-platform-communications-with-transport-layer-security-certificates/test-and-troubleshoot-tls-connections)

## Per-component config (anchors every entry in `component-cert-matrix.md`)

- [Configure TLS certificates for inter-Splunk communication](https://help.splunk.com/en/splunk-enterprise/administer/manage-users-and-security/10.0/secure-splunk-platform-communications-with-transport-layer-security-certificates/configure-tls-certificates-for-inter-splunk-communication)
- [Configure Splunk indexing and forwarding to use TLS certificates](https://docs.splunk.com/Documentation/Splunk/latest/Security/ConfigureSplunkforwardingtousesignedcertificates)
- [Configure Splunk Web to use TLS certificates](https://docs.splunk.com/Documentation/Splunk/latest/Security/SecureSplunkWebusingasignedcertificate)
- [Configure mutually authenticated TLS (mTLS) on the Splunk platform](https://help.splunk.com/en/splunk-enterprise/administer/manage-users-and-security/10.2/secure-splunk-platform-communications-with-transport-layer-security-certificates/configure-mutually-authenticated-transport-layer-security-mtls-on-the-splunk-platform)
- [Configure TLS certificate host name validation](https://docs.splunk.com/Documentation/Splunk/latest/Security/EnableTLSCertHostnameValidation)
- [Configure TLS protocol version support](https://help.splunk.com/splunk-enterprise/administer/manage-users-and-security/10.2/secure-splunk-platform-communications-with-transport-layer-security-certificates/configure-tls-protocol-version-support-for-secure-connections-between-splunk-platform-instances)
- [About TLS encryption and cipher suites](https://docs.splunk.com/Documentation/Splunk/latest/Security/AboutTLSencryptionandciphersuites)
- [server.conf reference](https://docs.splunk.com/Documentation/Splunk/latest/admin/serverconf)
- [web.conf reference](https://help.splunk.com/en/data-management/splunk-enterprise-admin-manual/10.0/configuration-file-reference/10.0.1-configuration-file-reference/web.conf)
- [inputs.conf reference](https://help.splunk.com/en/data-management/splunk-enterprise-admin-manual/10.0/configuration-file-reference/10.0.1-configuration-file-reference/inputs.conf)
- [outputs.conf reference](https://help.splunk.com/en/splunk-enterprise/administer/admin-manual/10.0/configuration-file-reference/10.0.1-configuration-file-reference/outputs.conf)
- [authentication.conf reference](https://help.splunk.com/en/data-management/splunk-enterprise-admin-manual/10.0/configuration-file-reference/10.0.3-configuration-file-reference/authentication.conf)

## KV Store

- [Preparing custom certificates for use with KV store](https://docs.splunk.com/Documentation/Splunk/9.4.2/Admin/CustomCertsKVstore)

## Indexer cluster + SHC

- [Configure the indexer cluster with server.conf](https://help.splunk.com/en/splunk-enterprise/administer/manage-indexers-and-indexer-clusters/10.2/configure-the-indexer-cluster/configure-the-indexer-cluster-with-server.conf)
- [Configure peer nodes with server.conf](https://help.splunk.com/en/splunk-enterprise/administer/manage-indexers-and-indexer-clusters/10.0/configure-the-peers/configure-peer-nodes-with-server.conf)
- [Perform a rolling restart of an indexer cluster](https://help.splunk.com/en/splunk-enterprise/administer/manage-indexers-and-indexer-clusters/10.2/manage-the-indexer-cluster/perform-a-rolling-restart-of-an-indexer-cluster)
- [Update common peer configurations and apps](https://docs.splunk.com/Documentation/Splunk/latest/Indexer/Updatepeerconfigurations)
- [Use the deployer to distribute apps and configuration updates](https://docs.splunk.com/Documentation/Splunk/latest/DistSearch/PropagateSHCconfigurationchanges)
- [Set a security key for the search head cluster](https://help.splunk.com/en/splunk-enterprise/administer/distributed-search/9.1/configure-search-head-clustering/set-a-security-key-for-the-search-head-cluster)
- [Search head clustering architecture](https://docs.splunk.com/Documentation/Splunk/latest/DistSearch/SHCarchitecture)

## Auth scheme certificates (separate trust domains)

- [Secure SSO with TLS certificates on Splunk Enterprise](http://docs.splunk.com/Documentation/Splunk/latest/Security/ConfigureSSLforSSO)
- [Configure SAML SSO using configuration files](https://docs.splunk.com/Documentation/Splunk/9.4.2/Security/ConfigureSAMLSSO)
- [Secure LDAP authentication with TLS certificates](https://docs.splunk.com/Documentation/Splunk/9.4.1/Security/LDAPwithcertificates)
- [Configure LDAP using configuration files](https://help.splunk.com/en/splunk-enterprise/administer/manage-users-and-security/9.4/perform-advanced-configuration-of-ldap-authentication-in-splunk-enterprise/configure-ldap-using-configuration-files)

## Splunk.secret + pass4SymmKey + secrets

- [Deploy secure passwords across multiple servers](https://help.splunk.com/en/splunk-enterprise/administer/manage-users-and-security/10.0/install-splunk-enterprise-securely/deploy-secure-passwords-across-multiple-servers)
- [Secure Splunk Enterprise services with pass4SymmKey](https://help.splunk.com/?resourceId=Splunk_Security_Aboutsecuringclusters)
- [Review security configurations and certificates](https://help.splunk.com/en/splunk-enterprise/administer/inherit-a-splunk-deployment/10.2/inherited-deployment-tasks/review-security-configurations-and-certificates)

## Deployment server / agents

- [Secure agents and agent management using certificate authentication](https://docs.splunk.com/Documentation/Splunk/latest/Security/Securingyourdeploymentserverandclients)

## FIPS

- [Secure Splunk Enterprise with FIPS](https://help.splunk.com/en/splunk-enterprise/administer/manage-users-and-security/10.2/establish-and-maintain-compliance-with-fips-and-common-criteria-in-splunk-enterprise/secure-splunk-enterprise-with-fips)
- [Upgrade and migrate your FIPS-mode deployments](https://help.splunk.com/en/splunk-enterprise/administer/install-and-upgrade/10.2/upgrade-or-migrate-splunk-enterprise/upgrade-and-migrate-your-fips-mode-deployments)

## Edge Processor

- [Edge Processor: Obtain TLS certificates for data sources and Edge Processors](https://help.splunk.com/data-management/transform-and-route-data/use-edge-processors-for-splunk-cloud-platform/10.0.2503/get-data-into-edge-processors/obtain-tls-certificates-for-data-sources-and-edge-processors)
- [Edge Processor: TLS and mTLS support (HEC)](https://help.splunk.com/en/data-management/collect-http-event-data/send-hec-data-to-and-from-edge-processor/send-data-from-edge-processor-with-hec/tls-and-mtls-support)
- [Edge Processor: Set up an Edge Processor](https://help.splunk.com/en/data-management/transform-and-route-data/use-edge-processors-for-splunk-enterprise/10.2/administer-edge-processors/set-up-an-edge-processor)

## Splunk Cloud / Universal Forwarder Credentials Package

- [Universal Forwarder Credentials Package](https://help.splunk.com/?resourceId=Forwarder_Forwarder_ConfigSCUFCredentials)
- [Splunk Cloud Admin Config Service (ACS) — HEC tokens](https://help.splunk.com/splunk-cloud-platform/administer/admin-config-service-manual/10.1.2507/administer-splunk-cloud-platform-using-the-admin-config-service-acs-api/manage-http-event-collector-hec-tokens-in-splunk-cloud-platform)
- [About the Admin Config Service (ACS) API](https://help.splunk.com/en/splunk-cloud-platform/administer/admin-config-service-manual)

## Post-install monitoring

- [SSL Certificate Checker (Splunkbase 3172)](https://splunkbase.splunk.com/app/3172)
- [Splunk Common Information Model — Certificates](https://help.splunk.com/en/splunk-enterprise/common-information-model/8.5/data-models/certificates)
- [About proactive Splunk component monitoring (`/server/health/splunkd`)](https://help.splunk.com/en/splunk-enterprise/administer/monitor/10.2/proactive-splunk-component-monitoring-with-the-splunkd-health-report/about-proactive-splunk-component-monitoring)
- [Investigate feature health status changes](https://help.splunk.com/en/splunk-enterprise/administer/monitor/10.2/proactive-splunk-component-monitoring-with-the-splunkd-health-report/investigate-feature-health-status-changes)

## Reference Lantern articles (operator-facing companion docs)

- [Renewing a certificate on a new Splunk Enterprise installation (Lantern)](https://lantern.splunk.com/Manage_Performance_and_Health/Renewing_a_certificate_on_a_new_Splunk_Enterprise_installation)
- [Securing the Splunk platform with TLS (Lantern)](https://lantern.splunk.com/Splunk_Platform/Product_Tips/Administration/Securing_the_Splunk_platform_with_TLS)
