# Cisco DC Networking App For Splunk

## Overview

* Nexus Dashboard for the data center stands out as the first comprehensive technology solution in the industry developed by Cisco for network operators to manage day-2 operations in their networks.
* Nexus Dashboard automates troubleshooting and helps with rapid root-cause analysis and early remediation. It also helps infrastructure owners comply with SLA requirements for their users.
* Nexus Dashboard for the data center is supported on Cisco ACI and Cisco NX-OS/DCNM-based deployments.
* Nexus Dashboard collects data on Anomalies, Advisories, Orchestrator (Multi-Site Orchestrator), Flow, Congestion, Protocol and Flow from the Nexus API and parses the fields. Data is mapped with the CIM data models for Enterprise Security use cases.
* ACI is used to gather data from the Application Policy Infrastructure Controller (APIC), index the data, and use it for running searches and building dashboards.
* Nexus 9K provides a scripted input for Splunk that automatically extracts responses of CLI commands from Cisco Nexus 9000 Switches. Moreover, this app gathers Syslog from Cisco Nexus 9000 Switches and provides the same for running searches on data and building dashboards using it.

* Author: Cisco Systems, Inc

* Version: 1.1.0

## Compatibility Matrix

|                                            |                                                           |
|--------------------------------------------|-----------------------------------------------------------|
| Browser                                    | Google Chrome, Mozilla Firefox, Safari                    |
| OS                                         | Linux, Windows                                            |
| Splunk Enterprise Version                  | 10.0.x, 9.4.x, 9.3.x, 9.2.x                                |
| Supported Splunk Deployment                | Splunk Cloud, Splunk Standalone, and Distributed Deployment|
| Nexus Insights version                     | 6.3, 6.1                                                  |
| Nexus Dashboard version                    | 3.3, 4.1.1.0                                             |
| APIC version                               | 5.2, 6.0                                                  |
| NDO version                                | 4.1, 4.2                                                  |
| Nexus 9K version                           | 10.4, 10.3, 9.3                                           |

## Release Notes

### Version 1.2.0
- Added support for collecting Switches and Fabrics for ND.
- Fixed an ingestion time issue in some ND input types.

### Version 1.1.0
- Added support for collecting Congestion, Endpoints, Flows, Protocols, and Custom data for ND.
- Added support for collecting Managed Objects data for ACI.
- Added support for collecting DME-based data with class/object queries for N9K.
- Added support of providing additional query parameters in all the 3 input types - ACI, ND, 9K.
- Added dashboards for Flows, Congestion, Endpoints, and Protocols for ND.
- Added new Syslog dashboards for ND, Orchestrator, ACI and N9K.
- Updated existing dashboard queries to use base search for improved performance and efficiency.
- Added CIM mapping and improved field extraction for better correlation and normalization in Splunk.
- Updated and enhanced field extraction across all data types to improve data quality and usability.
- Added multi-account support, enabling configuration of multiple accounts per input.
- Added new default inputs for ND.

### Version 1.0.2
- Removed the admin user as the owner.

### Version 1.0.1
- Updated default value of verify_ssl to True.

## Recommended System Configuration

- Because this App runs on Splunk Enterprise, all of the [Splunk Enterprise system requirements](https://docs.splunk.com/Documentation/Splunk/latest/Installation/Systemrequirements) apply.

## Account Configuration
For configuring an account for the data collection of API data, follow the below-mentioned steps in the Cisco DC Networking App for Splunk.

### ND Account Configuration
* Navigate to the `Cisco DC Networking App for Splunk`.
* Click on the Configuration Tab.
* Click on the `ND Accounts` tab.
* Click on Add.

| Input Parameters           | Required | Description                                                               | 
|----------------------------|----------|---------------------------------------------------------------------------|
| Account Name               | True     | The unique name to identify an account                                    |
| Hostname(s)/IP Address(es) | True     | Hostname or IP Address of Nexus Dashboard (cluster/standalone ND)         |
| ND Port                    | True     | Port for Nexus Dashboard                                                  |
| ND Authentication Type     | True     | Type of Authentication: Local User Authentication or Remote User Authentication |
| ND Username                | True     | Username for Nexus Dashboard                                              |
| ND Password                | True     | Password for Nexus Dashboard                                              |
| ND Login Domain            | True (when Authentication Type = Remote User Authentication) | Name of the Login Domain for ND                      |
| Enable Proxy               | No       | Whether the Proxy should be enabled or not                                |
| Proxy Type                 | Yes      | Type of the Proxy: HTTP or SOCKS5                                         |
| Proxy URL                  | Yes      | Server Address of Proxy URL                                               |
| Proxy Port                 | Yes      | Port to the Proxy Server                                                  |
| Proxy Username             | No       | Username for the Proxy Server                                             |
| Proxy Password             | No       | Password for the Proxy Server                                             |

* This provides 2 different modes of authentication to collect the ND data in Splunk. The common fields are Hostname(s)/IP Address(es) and ND Port.
  * The different modes are:
    * Local User Authentication
        * The user can configure the app using the default approach, i.e., using Password.
        * To set up ND with Local Based Authentication, follow the steps below:
            * In the 'ND Authentication Type' field, select "Local User Authentication".
            * Enter the Hostname(s)/IP Address(es) of the ND.
            * Enter the port of the ND, Example: 443.
            * Enter the username and password used to log in to the ND.
            * Click on the Save button at the bottom of the page.

    * Remote User Based Authentication
        * The user needs to provide both the Password and the Domain Name of the specified user.
        * To set up ND with Remote User Based Authentication, follow the steps below:
            * In the 'ND Authentication Type' field, select "Remote User Based Authentication".
            * Enter the Hostname(s)/IP Address(es) of the ND.
            * Enter the port of the ND, Example: 443.
            * Enter the username and password used to log in to the ND.
            * Enter the Domain Name of the user.
            * Click on the Save button at the bottom of the page.

### ACI Account Configuration
* Navigate to the `Cisco DC Networking App for Splunk`.
* Click on the Configuration Tab.
* Click on the `ACI Accounts` tab.
* Click on Add.

| Input Parameters           | Required | Description                                                               | 
|----------------------------|----------|---------------------------------------------------------------------------|
| Account Name               | True     | The unique name to identify an account                                    |
| Hostname(s)/IP Address(es) | True     | Hostname or IP Address of APIC (cluster/standalone APIC)                  |
| APIC Port                  | True     | Port for APIC                                                             |
| APIC Authentication Type   | True     | Type of Authentication: Password Based Authentication, Remote User Based Authentication, or Certificate Based Authentication |
| APIC Username              | True     | Username for APIC                                                         |
| APIC Password              | True     | Password for APIC                                                         |
| APIC Login Domain          | True (when APIC Authentication Type = Remote User Based Authentication) | Name of the Login Domain for APIC            |
| Certificate Name           | True (when APIC Authentication Type = Certificate Based Authentication) | Name of the Certificate for APIC               |
| Path of Private Key        | True (when APIC Authentication Type = Certificate Based Authentication) | Path of Private Key for APIC                   |
| Enable Proxy               | No       | Whether the Proxy should be enabled or not                                |
| Proxy Type                 | Yes      | Type of the Proxy: HTTP or SOCKS5                                         |
| Proxy URL                  | Yes      | Server Address of Proxy URL                                               |
| Proxy Port                 | Yes      | Port to the Proxy Server                                                  |
| Proxy Username             | No       | Username for the Proxy Server                                             |
| Proxy Password             | No       | Password for the Proxy Server                                             |

* This provides 3 different modes to configure an ACI account. The common fields are Hostname(s)/IP Address(es) and APIC Port.
  * The different modes are:

    * Password Based Authentication
        * The user can configure the app using the default approach, i.e., using Password.
        * To set up APIC with Password Based Authentication, follow the steps below:
            * In the 'APIC Authentication Type' field, select "Password Based Authentication".
            * Enter the Hostname(s)/IP Address(es) of the APIC.
            * Enter the port of the APIC, Example: 443.
            * Enter the username and password used to log in to the APIC.
            * Click on the Save button at the bottom of the page.

    * Certificate Based Authentication
        * The user needs to provide the Certificate Name (as uploaded on APIC) and the Path of the RSA Private Key (path to the RSA private key, present on Splunk, of the certificate uploaded on APIC) on the setup page to collect data.
        * The procedure to create and configure a custom certificate for certificate-based authentication is given in the link below:
          [Cisco APIC Basic Configuration Guide](https://www.cisco.com/c/en/us/td/docs/switches/datacenter/aci/apic/sw/4-x/basic-configuration/Cisco-APIC-Basic-Configuration-Guide-401/Cisco-APIC-Basic-Configuration-Guide-401_chapter_011.pdf)
        * Convert the Private Key to an RSA Private Key by running the following command in the terminal:
          * `openssl rsa -in <private_key>.key -out <rsa_private_key>.key`

        * To set up APIC with Certificate Based Authentication, follow the steps below:
            * In the 'APIC Authentication Type' field, select "Certificate Based Authentication".
            * Enter the Hostname(s)/IP Address(es) of the APIC.
            * Enter the port of the APIC, Example: 443.
            * Enter the username to log in to the APIC.
            * Enter the Name of the Certificate.
            * Enter the Path of the Private Key, Example: `/opt/splunk/ACI.key`.
            * Click on the Save button at the bottom of the page.

    * Remote User Based Authentication
        * The user needs to provide both the Password and the Domain Name of the specified user.
        * To set up APIC with Remote User Based Authentication, follow the steps below:
            * In the 'APIC Authentication Type' field, select "Remote User Based Authentication".
            * Enter the Hostname(s)/IP Address(es) of the APIC.
            * Enter the port of the APIC, Example: 443.
            * Enter the username and password used to log in to the APIC.
            * Enter the Domain Name of the user.
            * Click on the Save button at the bottom of the page.

### Nexus 9K Account Configuration
* Navigate to the `Cisco DC Networking App for Splunk`.
* Click on the Configuration Tab.
* Click on the `Nexus 9K Accounts` tab.
* Click on Add.

| Input Parameters     | Required | Description                                    | 
|----------------------|----------|------------------------------------------------|
| Account Name         | True     | The unique name to identify an account         |
| Hostname/IP Address  | True     | Hostname or IP Address of Nexus 9K             |
| Nexus 9K Port        | True     | Port for Nexus 9K                              |
| Nexus 9K Username    | True     | Username for Nexus 9K                          |
| Nexus 9K Password    | True     | Password for Nexus 9K                          |
| Enable Proxy         | No       | Whether the Proxy should be enabled or not     |
| Proxy Type           | Yes      | Type of the Proxy: HTTP or SOCKS5              |
| Proxy URL            | Yes      | Server Address of Proxy URL                    |
| Proxy Port           | Yes      | Port to the Proxy Server                       |
| Proxy Username       | No       | Username for the Proxy Server                  |
| Proxy Password       | No       | Password for the Proxy Server                  |

## Logging Setup

For setting up the logging for data collection of API data, follow the steps below in the Cisco DC Networking App for Splunk:

- Go to the App by clicking on `Cisco DC Networking App for Splunk` from the left bar.
- Click on the `Configuration` tab.
- Click on the `Logging` tab under the Configuration tab.
- Select the Log level. Available log levels are Debug, Info, Warning, Error, and Critical.
- Click on `Save`.

## SSL Configuration

1. By default, the API calls from the Cisco DC Networking App for Splunk would be verified by SSL. 
Provide the certificate path in ca_certs_path parameter under additional_parameters stanza. Create a stanza if its not present already.
The configurations are present in file: `$SPLUNK_HOME/etc/apps/cisco_dc_networking_app_for_splunk/default/cisco_dc_networking_app_for_splunk_settings.conf`

    ```ini
    [additional_parameters]
    verify_ssl = True
    ca_certs_path = 
    ```
2. In order to bypass the SSL verification, change the SSL verification to False. To do that, navigate to `$SPLUNK_HOME/etc/apps/cisco_dc_networking_app_for_splunk/local/cisco_dc_networking_app_for_splunk_settings.conf` file and change the verify_ssl parameter value to False.
3. To add a custom SSL certificate to the certificate chain, use the option available in the user interface while configuring a Cisco DC deployment.
4. Restart the Splunk in order for the changes to take effect.

## Input Creation
For creating an input in Cisco DC Networking App for Splunk and start data collection of API data, follow the below-mentioned steps.

### ND Input
* Navigate to the `Cisco DC Networking App for Splunk`.
* Click on the Inputs tab.
* Click on `Create New Input`.
* Select ND from the dropdown.
* Fill in all the necessary details.
* Click on `Save`.

The significance of each field is explained below:

| Input Parameter                | Required | Description                                                                                                                                                            |
|-------------------------------|----------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Name**                      | Yes      | A unique name for the data input.                                                                                                                                      |
| **ND Account**                | Yes      | Select accounts from the dropdown, which is configured on the configuration page.                                                                |
| **Interval**                  | Yes      | Data collection interval in seconds. The minimum value is 60 seconds. Default is 300 seconds.                                                                         |
| **Index**                     | Yes      | The Splunk index where the data will be stored. Ensure the index exists in a distributed environment.                                                                 |
| **Input Type**                | Yes      | Select the type of input: `Anomalies`, `Advisories`, `Orchestrator`, `Congestion`, `Endpoints`, `Flows`, `Protocols`, `Custom`.                                              |
| **Category**                  | Yes (if Input Type is Anomalies or Advisories) | Select the category to filter anomalies or advisories data.                                                                     |
| **Severity**                  | Yes (if Input Type is Anomalies or Advisories) | Select the severity to filter data for anomalies or advisories.                                                                 |
| **Time Range**                | Yes (if Input Type is Anomalies, Advisories, Flows, Endpoints, Protocols) | `For Anomalies and Advisories`: The Time Range for last N hours and must be greater than or equal to 0. If 0 is specified, all events (from the start of time) would be collected. `For Flows, Endpoints, Protocols`: Time Range for data collection starting from N seconds, minutes, hours or days ago until now. The value must be a positive number followed by 's' for seconds, 'm' for minutes, 'h' for hours, or 'd' for days. Example: 5h, 30m, or 1d.  |
| **Class Name(s)**             | Yes (if Input Type is Orchestrator)            | Enter space-separated class names for Orchestrator data collection.                                                             |
| **Fabric Name**              | Yes (if Input Type is Congestion, Flows, Endpoints, Protocols)              | Filter data by fabric name. Limits records to the specified fabric.                                                             |
| **Node Name**                | Yes (if Input Type is Congestion)              | Filter data by node name. Supports multiple comma-separated values. Example: `LEAF_2201, LEAF_2202`.                               |
| **Interface Name**           | Yes (if Input Type is Congestion)              | Filter data by interface name. Supports multiple comma-separated values. Example: `eth1/1, eth1/2`.                                |
| **Scope**                     | No       | Choose a Scope (Interface or Queue) for filtering.                                                                                                               |
| **Additional Query Parameters** | No    | `For Congestion, Flows, Endpoints, Protocols`: Additional Lucene-style filters. Example: nodeName:scalespine-602 OR nodeName:scalespine-601. `For Custom`: Additional query parameters for custom endpoint. Example: siteGroupName=default&siteName=DC-WEST |
| **Time Slice**                | No       | The time interval (in seconds) for collecting flow data. If no interval is specified, data for all events within a 5-second interval will be collected, starting from the specified Time Range up to the current time.                                                                           |
| **Granularity**               | No       | Specify granularity for Congestion Input like `30s`, `5m`, or `1h` for data resolution. Default is `5m`.                                                                                    |
| **Custom Endpoint**           | Yes (If Input Type is Custom)      | Custom API endpoint. Example: `sedgeapi/v1/cisco-nir/api/api/v1/anomalies/details`.                                                                                      |
| **Sourcetype**                | Yes (If Input Type is Custom)      | Provide the sourcetype for Custom Input to collect the data in.                                        |
| **Ingestion Key**             | No       | JSON key used for ingesting data into Splunk for Custom Input. Defaults to `entries` if not specified.                                                                                  |

### ACI Input
* Navigate to the `Cisco DC Networking App for Splunk`.
* Click on the Inputs tab.
* Click on `Create New Input`.
* Select ACI from the dropdown.
* Fill in all the necessary details.
* Click on `Save`.

The significance of each field is explained below:

| Input Parameter                | Required | Description                                                                                                                                     |
|-------------------------------|----------|-------------------------------------------------------------------------------------------------------------------------------------------------|
| **Name**                      | Yes      | A unique name for the data input.                                                                                                               |
| **APIC Account**              | Yes      | Select accounts from the dropdown, which is configured on the configuration page.                                                            |
| **Interval**                  | Yes      | The data collection interval in seconds. Minimum allowed is `60` seconds. Default is `300` seconds.                                             |
| **Index**                     | Yes      | The name of the index where data will be stored in Splunk. Ensure the index exists on the Indexer in a distributed environment.                |
| **Input Type**                | Yes      | Select the type of input: `stats`, `microsegment`, `health`, `fex`, `classInfo`, `authentication`, `managed objects`.                                          |
| **Class Name(s)**             | Yes (Not in case of managed objects)       | Enter space separated Class Name(s).             |
| **Distinguished Name(s)**     | Yes (Only in case of managed objects)       | Enter space separated Distinguished Name(s) for managed objects input.                                             |
| **Additional Query Parameters** | No     | Additional parameters for managed objects and classInfo inputs. Example: rsp-subtree-include=faults&query-target=subtree.                   |

### Nexus 9K Input

#### Modular Input

* Navigate to the `Cisco DC Networking App for Splunk`.
* Click on the Inputs tab.
* Click on `Create New Input`.
* Select Nexus 9K from the dropdown.
* Fill in all the necessary details.
* Click on `Save`.

The significance of each field is explained below:

| Input Parameter                | Required | Description                                                                                                                                     |
|-------------------------------|----------|-------------------------------------------------------------------------------------------------------------------------------------------------|
| **Name**                      | Yes      | A unique name for the data input.                                                                                                               |
| **Nexus 9K Account**          | Yes      | Select accounts from the dropdown, which is configured on the configuration page.                                                            |
| **Interval**                  | Yes      | Time interval of input in seconds. Must be greater than or equal to 60. Default is 300 seconds.                                                 |
| **Index**                     | Yes      | The name of the index where data will be indexed in Splunk. The specified index must exist on the Indexer in a distributed environment.        |
| **Input Type**                | Yes      | Input type for which you want to collect the data.                                                                                  |
| **Component**                 | Yes (If Input Type is CLI)       | Unique component related to the Nexus 9K input.                                                                              |
| **Command**                   | Yes (If Input Type is CLI)       | Specific command to execute for collecting Nexus 9K data.                                                                 |
| **DME Query Type**            | Yes (If Input Type is DME)       | DME Query Type (Class or Managed Object) for DME Class.                                 |
| **Class Name(s)**             | Yes (If DME Query Type is Class)       | Space separated Class Name(s).                                   |
| **Distinguished Name(s)**     | Yes (If DME Query Type is Managed Object)       | Space separated Distinguished Name(s).                                                       |
| **Additional Query Parameters** | No     | Additional query parameters to filter the data. Example: query-target=children&page-size=2000.                                 |

### Syslog

1) **Configure from UI**

  * Go to Settings->Data Inputs and click on UDP
  * Click on New Local UDP to create UDP data input
  * Configure UDP Port=514 for syslog
  * Click on Next button
  * Select Sourcetype=<"cisco:dc:nexus9k:syslog" or "cisco:dc:nd:syslog" or "cisco:dc:mso:syslog" or "cisco:dc:aci:syslog">, App Context=Cisco DC Networking App for Splunk and index = your_index
  * Click on Review button
  * Click on Submit button

  2) **Configure from Backend**

  * Add/Update inputs.conf in $SPLUNK_HOME/etc/apps/cisco_dc_networking_app_for_splunk/local folder
  * Enter below content to inputs.conf
            [udp://514]
            index = <your_index>
            sourcetype = <"cisco:dc:nexus9k:syslog" or "cisco:dc:nd:syslog" or "cisco:dc:mso:syslog" or "cisco:dc:aci:syslog">
            disabled = 0
  * Restart Splunk


## ND Default Inputs

| Input Name             | Sourcetype                | Input Type   | Class Name(s)         | Category | Severity | Time Range     | Time Slice |
|------------------------|---------------------------|--------------|------------------------|----------|----------|------------|---------------------|
| advisories             | cisco:dc:nd:advisories    | Advisories   | -                      | All      | All      | 4          | - |
| anomalies              | cisco:dc:nd:anomalies     | Anomalies    | -                      | All      | All      | 4          | - |
| mso_audit_user         | cisco:dc:nd:mso           | Orchestrator | audit user             | -        | -        | -          |- |
| mso_fabric_policy      | cisco:dc:nd:mso           | Orchestrator | fabric policy                       | -                | -          | -      | - |
| mso_tenant_site_schema | cisco:dc:nd:mso           | Orchestrator | tenant site schema                 | -                | -          | -      | - |
| congestion             | cisco:dc:nd:congestion    | Congestion   | -                        | -          | -      | - | - |
| endpoints              | cisco:dc:nd:endpoints     | Endpoints    | -                      | -        | -               | 1h    | - |
| flows                  | cisco:dc:nd:flows         | Flows        | -                      | -        | -         | 1m    | 5 |
| protocols              | cisco:dc:nd:protocols     | Protocols    | -                      | -        | -           | 1h    | - |

---

## ACI Default Inputs

| Input Name                 | Sourcetype                  | Input Type    | Class Name(s) |
|---------------------------|-----------------------------|----------------|---------------|
| authentication            | cisco:dc:aci:authentication | authentication | aaaSessionLR|
| classInfo_aaaModLR        | cisco:dc:aci:class          | classInfo      | aaaModLR faultRecord eventRecord|
| classInfo_faultInst       | cisco:dc:aci:class          | classInfo      | faultInst topSystem compVm compHv fvCEp fvRsCons fvRsProv fvRsVm fvRsHyper fvnsRtVlanNs fvnsEncapBlk fvRsPathAtt vmmCtrlrP compHostStats1h compRcvdErrPkts1h compTrnsmtdErrPkts1h|
| classInfo_fvRsCEpToPathEp | cisco:dc:aci:class          | classInfo      | fvRsCEpToPathEp dbgEpgToEpgRslt dbgEpToEpRslt dbgAcTrail aaaUser aaaRemoteUser l1PhysIf eqptStorage procEntry procContainer acllogPermitL2Pkt acllogPermitL3Pkt acllogDropL2Pkt acllogDropL3Pkt|
| fex                       | cisco:dc:aci:health         | fex            | eqptExtCh eqptSensor eqptExtChHP eqptExtChFP eqptExtChCard|
| health_fabricHealthTotal  | cisco:dc:aci:health         | health         | fabricHealthTotal eqptFabP eqptLeafP eqptCh eqptLC eqptFt eqptPsu eqptSupC ethpmPhysIf eqptcapacityPolEntry5min infraWiNode|
| health_fvTenant           | cisco:dc:aci:health         | health         | fvTenant fvAp fvEPg fvAEPg fvBD vzFilter vzEntry vzBrCP fvCtx l3extOut fabricNode|
| microsegment              | cisco:dc:aci:class          | microsegment   | fvRsDomAtt fvVmAttr fvIpAttr fvMacAttr|
| stats                     | cisco:dc:aci:stats          | stats          | eqptEgrTotal15min eqptIngrTotal15min fvCEp l2IngrBytesAg15min l2EgrBytesAg15min procCPU15min procMem15min|

---

## Nexus 9K Default Inputs

| Input Name       | Sourcetype           | Component      | Command                           |
|------------------|----------------------|----------------|------------------------------------|
| nxhostname       | cisco:dc:nexus9k     | nxhostname     | show hostname                      |
| nxversion        | cisco:dc:nexus9k     | nxversion      | show version                       |
| nxmodule         | cisco:dc:nexus9k     | nxinventory    | show module                        |
| nxinventory      | cisco:dc:nexus9k     | nxinventory    | show inventory                     |
| nxtemperature    | cisco:dc:nexus9k     | nxtemperature  | show environment temperature       |
| nxinterface      | cisco:dc:nexus9k     | nxinterface    | show interface                     |
| nxneighbor       | cisco:dc:nexus9k     | nxneighbor     | show cdp neighbors detail          |
| nxtransceiver    | cisco:dc:nexus9k     | nxtransceiver  | show interface transceiver details |
| nxpower          | cisco:dc:nexus9k     | nxpower        | show environment power             |
| nxresource       | cisco:dc:nexus9k     | nxresource     | show system resource               |

## Macros

* `cisco_dc_nd_index`
    * If you are using a custom index in the app for ND data collection, then kindly update the `cisco_dc_nd_index` macro in the app.
* `cisco_dc_aci_index`
    * If you are using a custom index in the app for ACI data collection, then kindly update the `cisco_dc_aci_index` macro in the app.
* `cisco_dc_n9k_index`
    * If you are using a custom index in the app for Nexus 9K data collection, then kindly update the `cisco_dc_n9k_index` macro in the app.
* `summariesonly`
    * If you want to visualize only accelerated data, then change this macro to `summariesonly=true`.
    * The default value of the macro is `summariesonly=false`.

## Saved Searches

### Nexus 9K

This app provides saved searches which generate lookup files or provide interface details for Nexus 9K data.

* Saved searches which generate lookup files:
    * hostname - generates `cisco_dc_hostname.csv` file
    * moduleSwHwVersion - generates `cisco_dc_inventory_modinf.csv` file
    * powerStatus - generates `cisco_dc_powerStatus.csv` file
    * temperature - generates `cisco_dc_temperatureLookup.csv` file
    * version - generates `cisco_dc_version.csv` file

* Saved search which provides interface details:
    * Interface_Details - provides details of all the physical interfaces

### ACI

This app provides saved searches that generate lookup files or send email alerts for ACI.

* Saved searches which generate lookup files:
    * APICFabricLookup - generates `cisco_dc_APICNodeLookup.csv` file
    * APICCEPLookup - generates `cisco_dc_APICVMLookup.csv` file
    * MSO Sites Lookups - generates `cisco_dc_mso_site_details.csv` file

* Saved searches which generate alerts:
    * ACI Monitoring Threshold: Tenant Exceeds Warning Threshold Limit
    * ACI Monitoring Threshold: Tenant Exceeds Critical Threshold Limit
    * ACI Monitoring Threshold: Tenant Exceeds Max Threshold Limit
    * ACI Monitoring Threshold: EPG Exceeds Warning Threshold Limit
    * ACI Monitoring Threshold: EPG Exceeds Critical Threshold Limit
    * ACI Monitoring Threshold: EPG Exceeds Max Threshold Limit
    * ACI Monitoring Threshold: Contracts Exceeds Warning Threshold Limit
    * ACI Monitoring Threshold: Contracts Exceeds Critical Threshold Limit
    * ACI Monitoring Threshold: Contracts Exceeds Max Threshold Limit
    * ACI Monitoring Threshold: Filters Exceeds Warning Threshold Limit
    * ACI Monitoring Threshold: Filters Exceeds Critical Threshold Limit
    * ACI Monitoring Threshold: Filters Exceeds Max Threshold Limit
    * ACI Monitoring Threshold: BD Exceeds Warning Threshold Limit
    * ACI Monitoring Threshold: BD Exceeds Critical Threshold Limit
    * ACI Monitoring Threshold: BD Exceeds Max Threshold Limit
    * ACI Monitoring Threshold: L3Out Networks Exceeds Warning Threshold Limit
    * ACI Monitoring Threshold: L3Out Networks Exceeds Critical Threshold Limit
    * ACI Monitoring Threshold: L3Out Networks Exceeds Max Threshold Limit
    * ACI Monitoring Threshold: TCAM Percentage Utilized Exceeds Warning Threshold Limit
    * ACI Monitoring Threshold: TCAM Percentage Utilized Exceeds Critical Threshold Limit
    * ACI Monitoring Threshold: Egress Port Utilization for Leafs/Spines Exceeds Warning Threshold Limit
    * ACI Monitoring Threshold: Egress Port Utilization for Leafs/Spines Exceeds Critical Threshold Limit
    * ACI Monitoring Threshold: Ingress Port Utilization for Leafs/Spines Exceeds Warning Threshold Limit
    * ACI Monitoring Threshold: Ingress Port Utilization for Leafs/Spines Exceeds Critical Threshold Limit
    * ACI Monitoring Threshold: VLAN Pool Exceeds Max Threshold Limit
    * ACI Monitoring Threshold: VLAN Pool Exceeds Critical Threshold Limit

## Custom Command
### NX-API Collector (Custom Search Command Reports)

This app provides a generic NX-API collector which empowers users to utilize the NX-API provided by Nexus 9K and periodically track certain data from the 9K switch. It takes switch CLI commands and converts them into NX-API calls, providing data that can be saved as a dashboard.

Every time the saved dashboard is clicked, Splunk makes a call to the switch using NX-API and fetches current data for that dashboard. Note that this data will not be saved in the Splunk database.

    Note: The custom command can only be executed with admin access.

Please follow the steps below to generate custom command reports:

1. Go to the search option and enter your search in the search bar.
   You have different options for the custom search command:

   * `| ciscodcnxapicollect account="your configured Nexus 9K account" command="your CLI"` (Make sure the account for the device is already configured through the configuration page)

2. Click on Save As and click on Dashboard Panel to store your result in the dashboard.
3. Enter the Dashboard Title. You have to include the keyword "report" in the dashboard title.
4. You can see your dashboard in Custom Reports (in the menu bar).

## Alerts

* Splunk Nexus Dashboard Advisory Alert
    * This alert will be triggered if at any point the severity is critical for advisories data in Nexus Dashboard Server.
    * By default, the alert will be disabled.

* Splunk Nexus Dashboard Anomaly Alert
    * This alert will be triggered if at any point the severity is critical for anomalies data in Nexus Dashboard Server.
    * By default, the alert will be disabled.

## Alerts Configuration

* Enable Alert
    * Go to `Alerts` under `Searches, reports, and alerts` on the navigation bar.
    * Click on Edit for `Splunk Nexus Dashboard Advisory Alert` or `Splunk Nexus Dashboard Anomaly Alert`.
    * In the dropdown, click on `Enable`.

* To set the email ID on which the mail is intended, follow these steps:
    * Go to `Alerts` under `Searches, reports, and alerts` on the navigation bar.
    * Click on Edit for `Splunk Nexus Dashboard Advisory Alert` or `Splunk Nexus Dashboard Anomaly Alert`.
    * In the dropdown, click on `Edit Alert`.
    * Under the `Trigger Action` section, write your Email ID in the `To` field.
    * Click on Save.

## Data Model
### ND
* This data model contains six datasets:
    * Advisories - Maps advisories details from the Nexus Dashboard Environment.
    * Anomalies - Maps anomalies details from the Nexus Dashboard Environment.
    * Flows - Maps flows details from the Nexus Dashboard Environment.
    * Endpoints - Maps endpoints details from the Nexus Dashboard Environment.
    * Congestion - Maps congestions details from the Nexus Dashboard Environment.
    * Protocols - Maps protocols details from the Nexus Dashboard.
* The acceleration for the data model is disabled by default.
* As all the dashboards are populated using data model queries and real-time search doesn't work with the data model, all the real-time search filters are disabled.
* If you want to improve the performance of dashboards, you must enable the acceleration of the data model. Please follow the steps below:
    * On the Splunk menu bar, click on Settings -> Data Models.
    * Filter with Cisco DC Networking App for Splunk.
    * In the "Actions" column, click on Edit and then click Edit Acceleration. This will display the pop-up menu for Edit Acceleration.
    * Check or uncheck the Accelerate checkbox to "Enable" or "Disable" data model acceleration respectively.
    * If acceleration is enabled, select the summary range to specify the acceleration period. The recommended acceleration period is 7 days. The acceleration period can be changed as per user convenience.
    * To save acceleration changes, click on the Save button.
* Warning: Accelerated data models help in improving the performance of the dashboard but they increase disk usage on the indexer.

### ACI
* This app stores the indexed data in accelerated data models and builds dashboards by fetching data from these models. Below is the list of data models created in the app for ACI:
    * Auth - Maps authentication details from the ACI Environment.
    * Health - Maps health and fault information for all the MOs of given classes.
    * Fault - Maps to defects or faults present on APIC.
    * Systems - Maps to general information for all the MOs of given classes.
    * Counters - Maps to general information for all the MOs of given classes.
    * Statistics - Maps to statistical data for all the MOs of given classes.
    * Events - Maps to general information for all the MOs of class=eventrecord.

* If you want to improve the performance of dashboards, you must enable the acceleration of the data model. Please follow the steps below:
    * Go to Settings -> Data Models.
    * Filter with Cisco DC Networking App for Splunk.
    * In the Action tab, click on Edit and then click Edit Acceleration.
    * Check the Acceleration checkbox and select the appropriate summary range. Save it.
    * Warning: Acceleration may increase storage and processing costs.

## Rebuilding Data Model

* In case there is no need to use the already indexed accelerated Data Model, the Data Model can be configured to rebuild from scratch for the specified acceleration period. The Data Model can be rebuilt by following the steps below:
    * On the Splunk menu bar, click on Settings -> Data Models.
    * Filter with Cisco DC Networking App for Splunk.
    * From the list of Data Models, expand the row by clicking the ">" arrow in the first column of the row of Cisco DC Networking App for Splunk Data Models. This will display extra Data Model information in the "Acceleration" section.
    * From the "Acceleration" section, click on the "Rebuild" link.
    * Monitor the status of "Rebuild" in the field "Status" of the "Acceleration" section. Reload the page to get the latest rebuild status.

## Dashboards

### ND Dashboards
1. **Anomalies**
    * The Anomalies Dashboard offers comprehensive visualization of collected anomalies data. It includes various panels such as Sites Anomaly Score over Time, Anomalies by Category, and Anomalies by Severity.

2. **Advisories**
    * The Advisories Dashboard provides visualization of collected advisories data. It includes panels such as Advisories by Category, Advisories by Severity, and detailed advisories information.

3. **Orchestrator**
    * **Orchestrator Overview**: This dashboard gives general information about Orchestrator like Site health, Site location, critical faults, etc.
    * **Sites**: Information about sites associated with Orchestrator and the fault count of various severity levels. Drill-downs are provided in Site Information, Site Health graph, and panels consisting of fault counts, so users can get a detailed view of the same.
    * **Schemas**: Information about schemas configured with Orchestrator. Drill down into No. of Schemas Associated With Orchestrator single pane visualization will show schema details, drill-down on Application Profiles, Bridge Domain, External EPGs, and VRF single pane visualization to get insights about particular health and fault details and drill-down on contracts will show contracts health details.
    * **Tenants**: Graphical representation of tenants associated with sites, schemas, and users. Drill down on table showing Tenant Details for a particular site will redirect to Tenant Details dashboard giving more description about the selected tenant.
    * **Users**: Information about Orchestrator users and their roles.
    * **Policy**: Information about policies configured in Orchestrator. Drill down on Policy SubType Breakdown panel will show details of specific subtype.

4. **Flows**
    * **Flow Overview**: This dashboard visualizes Flows data, Drops, Latencies, and traffics through charts and tables.
    * **Flow Search**: Allows users to search for network flows by specifying criteria such as time, fabric, tenant, VRF, source/destination IP, and ports. Results display detailed flow records, including latency, drop count, drop reasons, and interface details, enabling granular troubleshooting and analysis.
    * **Host Traffics**: Visualizes traffic statistics for individual hosts. Users can select a source IP to view its bandwidth usage (in KBps) over time, with area charts and tables summarizing ingress and egress traffic, helping to identify high-traffic hosts and trends.

5. **Interface Stats**
    * Provides insights into network protocol usage and interface status. The dashboard shows the total number of interfaces, highlights interfaces with anomalies, and presents operational statistics such as admin/operational status, port speed, interface type, and anomaly scores. Visualizations include single-value indicators, pie charts, and bar charts for quick assessment.

6. **Congestion**
    * Monitors network congestion events. Users can filter by counter name, host, fabric, and switch, and view time series charts of congestion counters and event values. The dashboard helps identify when and where congestion is occurring, facilitating proactive network management.

7. **Endpoints**
    * Tracks endpoint (host) statistics across the network. Users can filter by IP and tenant, view current and historical endpoint counts, and analyze endpoint trends over time. The dashboard provides tables and charts to help monitor endpoint growth, distribution, and activity.

8. **Syslog**
    * **ND Syslog**: This dashboard offers information related to Syslog data for ND.
    * **Orchestrator Syslog**: This dashboard offers information related to Syslog data for Orchestrator.

All the Orchestrator dashboards have an Audit Logs panel showing Audit Logs of a particular type. For example, the schemas dashboard has audit logs only of type schema.

### ACI Dashboards
1. **Home**
    * This dashboard provides a high-level overview of APIC and Orchestrator site details, offering key statistics and filters for quick access to essential information.

2. **System Faults**
    * This dashboard offers an overview of help desk ticket statuses and metrics, facilitating efficient issue tracking and resolution.

3. **Events**
    * This dashboard provides a comprehensive view of system events, including logs and alerts, for monitoring and analysis.

4. **Atomic Counters**
    * This dashboard displays metrics and statistics related to tenant activity, focusing on atomic counter data for detailed performance analysis.

5. **Path Degradation**
    * This dashboard provides information on path degradation issues, including packet transmission statistics and node details, to identify and troubleshoot network performance problems.

6. **ACL Logs**
    * This dashboard displays logs related to Access Control Lists (ACLs), including APIC and Orchestrator site details, for monitoring and managing network security policies.

7. **System Threshold**
    * This dashboard provides an overview of threshold monitoring, including statistics and alerts, to ensure system performance and stability.

8. **Fabric Details**
    * This dashboard offers a comprehensive view of fabric infrastructure, including node and link details, to monitor and manage fabric performance and health.

9. **Authentication**
    * This dashboard provides insights into authentication details, including APIC and Orchestrator site information, to monitor and manage user access and security.

10. **Multi Pod**
    * This dashboard offers an overview of multi-pod environments, including site and pod details, to monitor connectivity and performance across multiple locations.

11. **Fabric Extenders Detail**
    * This dashboard provides detailed information on fabric extenders, including status and performance metrics, to ensure optimal operation and connectivity within the network.

12. **Controller Statistics**
    * This dashboard presents statistics and performance metrics for controllers, offering insights into their operational status and health.

13. **Tenant Details**
    * This dashboard provides detailed insights into tenant configurations and activities, including resource usage and performance metrics.

14. **Tenant Utilization**
    * This dashboard displays resource utilization metrics for tenants, helping to monitor and optimize resource allocation and performance.

15. **Microsegmentation**
    * This dashboard provides insights into microsegmentation policies and their enforcement, helping to manage and secure network segments.

16. **VMWare**
    * This dashboard offers an overview of VMware infrastructure, including virtual machine and host metrics, to monitor and manage virtualized environments.

17. **ACI Syslog**
    * This dashboard offers information related to Syslog data for ACI.

### Nexus 9K Dashboards
1. **Home**
    * This dashboard allows users to filter by device and severity, and provides an overview of syslog activity, helping to identify patterns, anomalies, and potential issues in the network environment. It's particularly useful for monitoring, troubleshooting, and maintaining network health and security.

2. **Physical Inventory**
    * Visualizes the physical components of Nexus switches, including Switches, Line Cards, Fabric Modules, Power Supplies, Fan Modules, Supervisor Modules, and System Controllers. This comprehensive view helps in asset management and capacity planning.

3. **Resource Summary**
    * Displays key resource metrics with a Resource Summary Table, Memory Usage Trend Chart, and CPU Idle Trend Chart. This dashboard is crucial for monitoring system performance and identifying potential bottlenecks.

4. **Network Topology**
    * This dashboard provides an interactive, visual representation of the network topology, allowing users to explore the connections between Nexus switches and gather detailed information about each connection and device. It's particularly useful for network administrators to understand the layout and interconnections of their Cisco Nexus network infrastructure.

5. **Power**
    * Offers detailed power usage insights with panels for Device Power Supply Information, Current Summary Usage, Input/Output Power Drawn over time, Device Power Module Usage, and Actual Power Drawn over time. Essential for power management and efficiency monitoring.

6. **All Interfaces Details**
    * Provides a broad view of network traffic with panels showing Interface Statistics, Transmit Statistics, and Receive Statistics, all in Packets Per Second. Allows for quick identification of busy or problematic interfaces.

7. **Single Interface Details**
    * Focuses on individual interface performance, displaying Input Packets History, Input Packet Rate History, Output Packets Summary, and Output Packet Rate History. Ideal for deep-diving into specific interface issues or performance analysis.

8. **CDP Neighbor**
    * Features a comprehensive CDP Neighbor Table, offering visibility into network topology and connected devices. Crucial for network mapping and troubleshooting connectivity issues.

9. **Temperature**
    * Presents a detailed Temperature Table showing current temperatures, thresholds, and historical trends for various modules and sensors. Essential for monitoring environmental conditions and preventing overheating issues.

10. **Auditing**
    * Provides a security-focused view with panels for Unique Devices, Users, Device Logins, Device Logins by User (both table and chart), Failed Device Logins by User (table and chart), Configuration Started by Host, and Configuration Changes by User. Critical for security monitoring, compliance, and change management.

11. **N9K Syslog**
    * This dashboard offers information related to Syslog data for N9K.

# Installation

## Topology and Setting Up Splunk Environment

### Single Machine Setup
Install the app `Cisco DC Networking App For Splunk` on a single machine.

* The app uses the data collected and builds dashboards on it.

### Distributed Clustered Environment Setup
Install the app `Cisco DC Networking App For Splunk` in a distributed clustered environment.

* Install the app on a Search Head or Search Head Cluster and an Indexer, and configure the app on a Heavy Forwarder.

### Cloud Environment
* Users need to raise a ticket to the Splunk support team for the app installation, or users can install the app from the Manage Apps page.

## Upgrade
### General upgrade steps:
* Log in to Splunk Web and navigate to Cisco DC Networking App For Splunk -> Inputs.
* Here disable all configured Inputs.
* Navigate to Apps -> Manage Apps on Splunk menu bar.
* Click Install app from file.
* Click Choose file and select the Cisco DC Networking App For Splunk installation file.
* Check the Upgrade checkbox.
* Click on Upload.
* Restart Splunk if prompted.

### Upgrade to v1.1.0
* Follow the General upgrade steps section.
* NOTE: After the upgrade, if multiple accounts need to be used in a single input, it's recommended to create a new input for that instead of editing the existing input (having a single account) for better performance.

### Upgrade to v1.0.2
* Follow the General upgrade steps section.

### Upgrade to v1.0.1
* Follow the General upgrade steps section.

## Follow the steps below to install the app from the bundle:
* Download the app package.
* From the UI, navigate to Apps -> Manage Apps.
* In the top right corner, select "Install app from file."
* Select `Choose File` and select the app package.
* Select `Upload` and follow the prompts.

OR

* Directly from the `Find More Apps` section provided in the Splunk Home Dashboard.

OR 

* Download the app package.
* Extract the downloaded app package directly into `$SPLUNK_HOME/etc/apps/` folder.

## Uninstallation and Cleanup

This section provides the steps to uninstall the app from a standalone Splunk platform installation.

1. (Optional) If you want to remove data from the Splunk database, you can use the following Splunk CLI clean command to remove indexed data from an app before deleting the app:
    ```sh
    $SPLUNK_HOME/bin/splunk clean eventdata -index <index_name>
    ```

2. Delete the app and its directory. The app and its directory are typically located in the folder `$SPLUNK_HOME/etc/apps/<app_name>` or run the following command in the CLI:
    ```sh
    $SPLUNK_HOME/bin/splunk remove app [app_name] -auth "splunk_username:splunk_password"
    ```

3. You may need to remove user-specific directories created for your app by deleting any files found here: `$SPLUNK_HOME/etc/users/*/<app_name>`.

4. Restart the Splunk platform. You can navigate to Settings -> Server controls and click the restart button in the Splunk web UI, or use the following Splunk CLI command to restart Splunk:
    ```sh
    $SPLUNK_HOME/bin/splunk restart
    ```

# Troubleshooting
## ND

* If you attempt to delete an input and encounter an error such as: `Object id=cisco_nexus_dashboard://"Input name" cannot be deleted in config=inputs.`, this indicates that the input is a default input and cannot be deleted by the user.

* If you get any error messages in the Configuration tab on the UI, check the messages on the config screen. You can also check logs for validation using the query:
    ```sh
    index=_internal source="*cisco_dc_nd_validation.log*"
    ```

* The main app dashboard can take some time before the data is returned to populate some of the panels. To verify that you are receiving all of the expected data, run this search after several minutes:
    ```sh
    index="your_index" | stats count by sourcetype
    ```

* In particular, you should see these sourcetypes:
    * cisco:dc:nd:anomalies
    * cisco:dc:nd:advisories
    * cisco:dc:nd:mso
    * cisco:dc:nd:congestion
    * cisco:dc:nd:flows
    * cisco:dc:nd:endpoints
    * cisco:dc:nd:protocols

* If you don't see these sourcetypes, please check the logs generated in the app log files. Here is a sample search that will show all the logs generated by the app:
    ```sh
    index=_internal source="*cisco_dc_nd_*.log*"
    ```

* If dashboards are not being populated:
    * Check that the "cisco_dc_nd_index" macro is updated if you are using a custom index.
    * Check that the data model is accelerated or that the "summariesonly" macro is updated with `summariesonly=true`.
    * Make sure you have data in the given time range.
    * To check if data is collected, run the query:
      ```sh
      `cisco_dc_nd_index` | stats count by sourcetype
      ```
    * In particular, you should see these sourcetypes:
        * cisco:dc:nd:anomalies
        * cisco:dc:nd:advisories
        * cisco:dc:nd:mso
        * cisco:dc:nd:congestion
        * cisco:dc:nd:flows
        * cisco:dc:nd:endpoints
        * cisco:dc:nd:protocols
    * Try expanding the time range.

## ACI

* If you attempt to delete an input and encounter an error such as: `Object id=cisco_nexus_aci://"Input name" cannot be deleted in config=inputs.`, this indicates that the input is a default input and cannot be deleted by the user.

* If you get any error messages in the Configuration tab on the UI, check the messages on the config screen. You can also check logs for validation using the query:
    ```sh
    index=_internal source="*cisco_dc_aci_validation.log*"
    ```

* The main app dashboard can take some time before the data is returned to populate some of the panels. To verify that you are receiving all of the expected data, run this search after several minutes:
    ```sh
    index="your_index" | stats count by sourcetype
    ```

* In particular, you should see these sourcetypes:
    * cisco:dc:aci:stats
    * cisco:dc:aci:health
    * cisco:dc:aci:class
    * cisco:dc:aci:authentication
    * cisco:dc:aci:managed_object

* If you don't see these sourcetypes, please check the logs generated in the app log files. Here is a sample search that will show all the logs generated by the app:
    ```sh
    index=_internal source="*cisco_dc_aci_*.log*"
    ```

* If the UI fails to load, check the `$SPLUNK_HOME/var/log/splunk/splunkd.log` file for errors.

* If dashboards are not being populated:
    * Check that the "cisco_dc_aci_index" macro is updated if you are using a custom index.
    * Check that the data model is accelerated or that the "summariesonly" macro is updated with `summariesonly=true`.
    * Make sure you have data in the given time range.
    * To check if data is collected, run the query:
      ```sh
      `cisco_dc_aci_index` | stats count by sourcetype
      ```
    * In particular, you should see these sourcetypes:
        * cisco:dc:aci:stats
        * cisco:dc:aci:health
        * cisco:dc:aci:class
        * cisco:dc:aci:authentication
        * cisco:dc:aci:managed_object
    * Try expanding the time range.

## Nexus N9K

* If you attempt to delete an input and encounter an error such as: `Object id=cisco_nexus_9k://"Input name" cannot be deleted in config=inputs.`, this indicates that the input is a default input and cannot be deleted by the user.

* If you get any error messages in the Configuration tab on the UI, check the messages on the config screen. You can also check logs for validation using the query:
    ```sh
    index=_internal source="*cisco_dc_n9k_validation.log*"
    ```

* The main app dashboard can take some time before the data is returned to populate some of the panels. To verify that you are receiving all of the expected data, run this search after several minutes:
    ```sh
    index="your_index" | stats count by sourcetype
    ```

* In particular, you should see these sourcetype:
    * cisco:dc:nexus9k
    * cisco:dc:nexus9k:dme

* If you don't see this sourcetype, please check the logs generated in the app log files. Here is a sample search that will show all the logs generated by the app:
    ```sh
    index=_internal source="*cisco_dc_n9k_*.log*"
    ```

* If dashboards are not being populated:
    * Check that the "cisco_dc_n9k_index" macro is updated if you are using a custom index.
    * Make sure you have data in the given time range.
    * To check if data is collected, run the query:
      ```sh
      `cisco_dc_n9k_index` | stats count by sourcetype
      ```
    * In particular, you should see these sourcetype:
        * cisco:dc:nexus9k
        * cisco:dc:nexus9k:dme
    * Try expanding the time range.

# Binary File Declaration
* md.cpython-39-x86_64-linux-gnu.so - This binary file is provided along with Splunk's UCC framework.
* md__mypyc.cpython-39-x86_64-linux-gnu.so - This binary file is provided along with Splunk's UCC framework.

## Support Information
* Support Offered: Yes
* Email: tac@cisco.com

### Copyright (c) 2025 Cisco Systems, Inc
