# Cisco Intersight Add-On for Splunk
Copyright (C) 2025 Splunk Inc. All Rights Reserved.

## OVERVIEW
* The Cisco Intersight Add-On for Splunk allows Splunk software administrators to collect Intersight Audit logs, Intersight Managed Inventory, Alarms and Performance metrics from the Cisco Intersight platform into Splunk. This add-on provides the inputs and CIM-compatible knowledge to use with other Splunk Enterprise apps, such as Splunk Enterprise Security and Splunk IT Service Intelligence. By integrating with multiple Cisco Intersight environments, it enables a unified approach to collect data in a multi-account landscape. 
* This is an enhanced and updated version of the [Cisco Intersight Add-On for Splunk](https://splunkbase.splunk.com/app/6482). 
* Note: Upgrade is supported from v2.0.1 to v3.1.0. Please ensure the version older than v2.0.1 is uninstalled before installing new version.

### RELEASE NOTES 

#### VERSION 3.1.0

##### New Features
1. Support of Custom Input configuration for flexible API Data Collection
2. Support of Cisco Unified Edge environment
3. Add-on UI upgrade to support Splunk UCC version 6.0.1
4. Pool APIs data collection
5. Dashboards to provide comprehensive operational insights:
      1. Inventory Browser (Tree View)
      2. Activity Monitoring
      3. Server Profile Health Monitoring
      4. Alarms Insights
      5. Advisory Insights
      6. Pool Objects Insights
6. Restructured the ‘Intersight Insights’ dashboard into two separate dashboards: ‘Slots Utilization & CPU Metrics Insights’ and ‘Error Metrics Insights’.

##### Fixed Issues
   1. Add-on configuration failed when Proxy server is enabled.
   2. In 'Intersight Insights' dashboard, 'Unused Server slots' panel shows duplicate Slot IDs.
   3. Fibre channel related panels not loading in Network Troubleshooting Dashboard.

#### VERSION 3.0.0

##### New Features
1. Storing latest snapshot of Inventory data to Splunk KVStore.
2. Network Troubleshooting dashboard to provide comprehensive operational insights.
3. Data collection support for CPU Utilization metrics.
4. Support to collect ports and interfaces data as part of inventory data collection.
5. Support to collect data for Advisory Definitions and Security Advisories.
6. Support to configure inputs as part of account configuration.
7. Unified source and sourcetype naming conventions across all data types.
8. Enhanced Alarms input to support data collection for 'Cleared' and 'Info' alarms.
9. Migrated dashboards to Splunk Dashboard Studio.
10. Prebuilt reports.

##### Fixed Issues
1. Not able to collect GPU or Graphics Card details as part of Inventory metadata collection.
2. Account token expiration notification failed to notify for already expired tokens.

#### VERSION 2.0.1

##### New Features
1. Migrated add-on from Splunk Add-on builder to Splunk UCC Framework v5.54.0.
2. OAuth 2.0 authentication as part of account configuration.
3. Metrics data collection support.
4. Enhanced Inventory metadata data collection support.
5. 'Intersight Insights' dashboard for out-of-the-box visibility, with visualizations tailored to common use cases.
6. Saved search to notify users for token expiration.

##### Bug Fixes
1. Alarms data is getting duplicated in the Splunk add-on.


### Functional Specification

- **Add-on Version**: v3.1.0
- **Vendor Products**: 
      - Cisco Intersight SaaS
      - Cisco Intersight Appliance
- **Visible in Splunk Web**: Yes
- **Deployment**: Supported on both Splunk Cloud and Splunk Enterprise environments.

### COMPATIBILITY MATRIX
* Splunk version: Splunk 10.0.x, 9.4.x, 9.3.x
* Python version: Python3.9
* OS Support: Linux, MacOS
* Supported Browsers: Google Chrome, Mozilla Firefox, Safari
* Intersight Product: Intersight SaaS, Intersight Appliance
* API Version: v1

### REQUIREMENTS

* For the system requirements of Splunk Enterprise, please refer to the [Splunk Enterprise Installation Manual - System Requirements](https://docs.splunk.com/Documentation/Splunk/7.1.1/Installation/Systemrequirements).
* Standard Splunk Enterprise configuration of [Splunk Enterprise](https://docs.splunk.com/Documentation/Splunk/latest/Installation/Systemrequirements).


## Installation

### INSTALL
The following options give you an overview of the add-on installation process:

#### Installation via Splunk Web
   1. **Log in to Splunk Web**:  
      Navigate to the Splunk Web home screen and log in to your Splunk instance.

   2. **Find the App**:  
      Go to the Navigation Bar and click on **Apps > Find More Apps**.  
      In the search bar, type `Cisco Intersight Add-On for Splunk`.

   3. **Install the App**:  
      After finding the `Cisco Intersight Add-On for Splunk` in the search results, click **Install**.

   4. **Verify Installation**:  
      Confirm that the add-on appears under **Apps > Manage Apps**.  
      Ensure no errors are displayed during the installation.

#### Manual Installation via Splunkbase
   1. **Download the Add-On**:  
      Visit [Splunkbase](https://splunkbase.splunk.com) and download the `Cisco Intersight Add-On for Splunk` package.

   2. **Install via Splunk Web**:  
      - Log in to Splunk Web and click on the **Manage Apps** icon.  
      - Select **Install app from file**.  
      - Click **Choose File**, navigate to the downloaded `.tar` or `.spl` package, and click **Open**.  
      - Click **Upload** to complete the installation.

   3. **Verify Installation**:  
      Confirm that the add-on appears under **Apps > Manage Apps**.  
      Ensure no errors are displayed during the installation.

   4. **Restart Splunk if prompted**.

See the [Installation walkthroughs](https://splunk.github.io/splunk-add-on-for-servicenow/Install/#installation-walkthroughs) for detailed instructions on how to install the add-on in your specific deployment environment:
1. Single-instance deployment
2. Distributed deployment
3. Splunk Cloud

### Distributed Deployments
Use the following tables to determine where and how to install this add-on in a distributed deployment of Splunk Enterprise or any deployment for which you are using forwarders to get your data in. Depending on your environment, your preferences, and the requirements of the add-on, you may need to install the add-on in multiple places.

#### Where to install this add-on

The Cisco Intersight Add-On for Splunk supports both standalone and distributed deployment architectures. [See Where to install](http://docs.splunk.com/Documentation/AddOns/released/Overview/Wheretoinstall) Splunk add-ons in Splunk Add-ons for more information.

| Splunk Platform Type | Supported | Required | Comments |
|----------------------|-----------|----------|----------|
| Search Heads         | Yes       | Yes      | Install on all search heads where Cisco Intersight knowledge management is required. Best practice is to turn add-on visibility off to prevent data duplication errors. |
| Indexers             | Yes       | No       | Not required; parsing occurs on heavy forwarders. |
| Heavy Forwarders     | Yes       | Yes      | This add-on supports only heavy forwarders for data collection. |
| Universal Forwarders  | No        | No       | Only heavy forwarders are supported for data collection. |

### UPGRADE

#### General upgrade steps
1. Confirm that the `cisco_intersight_index` macro points to the expected Splunk index in which the Inventory related events are ingested.
2. (For distributed Splunk environments only):
Add the Search Head IP address to the **KV Lookup REST Configuration** by navigating to: `Configuration > 'KV Lookup REST'` tab. This ensures that the Search Head(s) can properly query KV Store lookups hosted on the indexer or SHC deployer.
**Note:** This step can be skipped for single-instance deployments or standalone test environments.
3. Temporarily disable all active data inputs to avoid conflicts during migration.
4. Follow Splunk standard guidelines to upgrade the add-on to the latest version.

#### Add-on Upgrade from v3.0.0 to v3.1.0 or v2.0.1 to v3.1.0

1. Follow the `General upgrade steps` section.
2. Navigate to the Cisco Intersight Add-on for Splunk.
3. Review all input configurations (including polling intervals and selected data collection types), as defaults and available options may have changed in this release.
4. Re-enable your data inputs after the migration is complete.

## Software Architecture

The Cisco Intersight Add-On for Splunk is designed to collect data from multiple configured Cisco Intersight accounts, storing checkpoint information in the Splunk KV Store to enable incremental data collection.

This add-on facilitates the collection and ingestion of diverse data such as Audit and Alarms, Inventory, and Metrics events from IMM (Intersight Management Mode), Standalone (Intersight Standalone Mode) and Unified Edge devices into Splunk indexes for comprehensive analysis. It includes pre-built dashboards that enables  data analysis, enhancing monitoring and operational insights.

Default inputs available in the add-on and the Intersight APIs leveraged to collect the data from Cisco Intersight are as follows:

### 1. Audit & Alarms

#### Audit Records  
  - Collects audit trail data from Cisco Intersight.  
  - [View API documentation](https://intersight.com/apidocs/apirefs/All/api/v1/aaa/AuditRecords/get/)

#### Alarms
  - Collects alarms of severity levels **Critical**, **Warning**, **Info** and **Cleared**. Filtering options for Acknowledged and Suppressed alarms are available.  
  - [View API documentation](https://intersight.com/apidocs/apirefs/All/api/v1/cond/Alarms/get/)

### 2. Inventory

#### Compute

##### Inventory Objects (`search/SearchItems`)
- **API Endpoint**: `search/SearchItems`
- **Description**: Collects server metadata and component inventory, including blade/rack/server details, physical summary, and relationships to parent/child objects.
   - Fetches data for the following Intersight Managed Compute objects:  
   - Server metadata (e.g., PhysicalSummary, Transceiver, IoCard, ExpanderModule, FanControl, RackEnclosure, PsuControl, Fru, FanModule, RackEnclosureSlot, ChassisIdentity, SwitchCard, Psu, LocatorLed, Tpm, Fan, MemoryUnit, StoragePhysicalDisk, GraphicsCards, ProcessorUnit, VnicVnicTemplate, StorageItem, StorageVirtualDrive, NetworkElement, NetworkSupervisorCard, Blade Identity)  
   - [View API documentation](https://intersight.com/apidocs/apirefs/All/api/v1/search/SearchItems/get/)

##### Chassis (`equipment.chassis`)
- **API Endpoint**: `equipment/Chasses`
- **Description**: Fetches chassis-related data, including model, serial, and related component information.

##### HCL Status (`cond.hclstatus`)
- **API Endpoint**: `cond/HclStatuses`
- **Description**: Fetches Hardware Compatibility List (HCL) status of Intersight managed servers for compliance and supportability checks.

##### Server Profiles (`server.profile`)
- **API Endpoint**: `server/Profiles`
- **Description**: Fetches profile data for Intersight managed servers, including assigned policies and configuration.

##### Chassis Profiles (`chassis.profile`)
- **API Endpoint**: `chassis/Profiles`
- **Description**: Fetches profile data for Intersight managed chassis, including configuration and applied policies.

#### Network

##### Network Elements (`network.elementsummary`)
- **API Endpoint**: `network/ElementSummaries`
- **Description**: Fetches Intersight managed network elements and their summaries, including model, serial, and topology details.

#### Fabric

##### Fabric Switch Profiles (`fabric.switchprofile`)
- **API Endpoint**: `fabric/SwitchProfiles`
- **Description**: Fetches fabric switch profile data from Intersight managed fabric objects, including switch configuration and status.

##### Fabric Switch Cluster Profiles (`fabric.switchclusterprofile`)
- **API Endpoint**: `fabric/SwitchClusterProfiles`
- **Description**: Fetches fabric switch cluster profile data, including cluster configuration and member switches.

#### Licenses

##### Account License Data (`license.accountlicensedata`)
- **API Endpoint**: `license/AccountLicenseData`
- **Description**: Fetches license information related to Intersight managed accounts, including entitlement and consumption.

##### License Infos (`license.licenseinfo`)
- **API Endpoint**: `license/LicenseInfos`
- **Description**: Collects detailed information about licenses managed in Intersight, including status and expiration.

#### Device Contract Information

##### Device Contract Information (`asset.devicecontractinformation`)
- **API Endpoint**: `asset/DeviceContractInformations`
- **Description**: Fetches contract information for Intersight managed objects, including contract status and expiry.

#### Advisories

##### Advisory Instances (`tam.advisoryinstance`)
- **API Endpoint**: `tam/AdvisoryInstances`
- **Description**: Fetches advisory data applicable to Intersight managed objects, including affected devices and severity.

##### Advisory Infos (`tam.advisoryinfo`)
- **API Endpoint**: `tam/AdvisoryInfos`
- **Description**: Fetches detailed advisory information, including type, impact, and recommended actions.

##### Advisory Definitions (`tam.advisorydefinition`)
- **API Endpoint**: `tam/AdvisoryDefinitions`
- **Description**: Fetches advisory definitions, including categories and remediation steps.

##### Security Advisories (`tam.securityadvisory`)
- **API Endpoint**: `tam/SecurityAdvisories`
- **Description**: Fetches security advisories, including vulnerabilities and mitigation recommendations.

#### Intersight Domains (Targets)

##### Targets (`asset.target`)
- **API Endpoint**: `asset/Targets`
- **Description**: Fetches data on Intersight managed targets, including domain membership and operational status.

#### Ports and Interfaces

##### Ethernet Host Ports (`ether.HostPort`)
- **API Endpoint**: `ether/HostPorts`
- **Description**: Collects Ethernet host port inventory, including parent device details and acknowledged peer interface information for topology mapping.

##### Ethernet Network Ports (`ether.NetworkPort`)
- **API Endpoint**: `ether/NetworkPorts`
- **Description**: Collects Ethernet network port inventory, including parent details and peer interface relationships.

##### Ethernet Physical Ports (`ether.PhysicalPort`)
- **API Endpoint**: `ether/PhysicalPorts`
- **Description**: Collects Ethernet physical port inventory, including parent Dn/ObjectType and peer interface details.

##### Ethernet Port Channels (`ether.PortChannel`)
- **API Endpoint**: `ether/PortChannels`
- **Description**: Collects Ethernet port channel inventory, including parent, model, name, and port membership details.

##### Host FC Interfaces (`adapter.HostFcInterface`)
- **API Endpoint**: `adapter/HostFcInterfaces`
- **Description**: Collects Fibre Channel host interface inventory, including parent, model, and operational state.

##### FC Physical Ports (`fc.PhysicalPort`)
- **API Endpoint**: `fc/PhysicalPorts`
- **Description**: Collects Fibre Channel physical port inventory, including parent Dn/ObjectType and peer relationships.

##### FC Port Channels (`fc.PortChannel`)
- **API Endpoint**: `fc/PortChannels`
- **Description**: Collects Fibre Channel port channel inventory, including parent, model, name, and port membership details.

##### Virtual Fibre Channels (`network.Vfc`)
- **API Endpoint**: `network/Vfcs`
- **Description**: Collects virtual Fibre Channel interface inventory, including mappings to adapters and parent devices.

##### Virtual Ethernet Interfaces (`network.Vethernet`)
- **API Endpoint**: `network/Vethernets`
- **Description**: Collects virtual Ethernet interface inventory, including mappings to adapters and parent devices.

##### Host Ethernet Interfaces (`adapter.HostEthInterface`)
- **API Endpoint**: `adapter/HostEthInterfaces`
- **Description**: Collects host Ethernet interface inventory, including AdapterUnit with ExtEthIfs, acknowledged peer interfaces, and Vethernet mappings with pinned/bound interfaces.

#### Pools

##### FC Pools (`fcpool.Pool`)
- **API Endpoint**: `fcpool/Pools`
- **Description**: Collects metadata of WWN addresses that can be allocated to VHBAs of a server profile.
- [View API documentation](https://intersight.com/apidocs/apirefs/All/api/v1/fcpool/Pools/get)

##### IP Pools (`ippool.Pool`)
- **API Endpoint**: `ippool/Pools`
- **Description**: Collects metadata of IPv4 and/or IPv6 addresses that can be allocated to other configuration entities like server profiles.

##### IQN Pools (`iqnpool.Pool`)
- **API Endpoint**: `iqnpool/Pools`
- **Description**: Collects metadata of iSCSI Qualified Names (IQNs) for use as initiator identifiers by iSCSI vNICs.

##### MAC Pools (`macpool.Pool`)
- **API Endpoint**: `macpool/Pools`
- **Description**: Collects metadata of MAC addresses that can be allocated to VNICs of a server profile.

##### UUID Pools (`uuidpool.Pool`)
- **API Endpoint**: `uuidpool/Pools`
- **Description**: Collects metadata of UUID items that can be allocated to server profiles.

##### Resource Pools (`resourcepool.Pool`)
- **API Endpoint**: `resoucrcepool/Pools`
- **Description**: Collects metadata of resources.


#### KVStore Collections and Source/Sourcetype Mapping
Latest snapshot of Inventory metadata fetched from Cisco Intersight into Splunk is stored in Splunk KVstore. The add-on's pre-built dashboards leverages these KVStores to present data into panels for various use cases.

Below table provides the mapping of Intersight Inventory Objects and the Splunk KVStores in which its metadata is stored.

| Collection Name                                         | ObjectType                      | Source                            | Sourcetype                            |
|-----------------------------------------------------|---------------------------------------|-----------------------------------|---------------------------------------|
| cisco_intersight_adapter_hostethinterfaces          | adapter.HostEthInterface              | adapterHostEthInterface           | cisco:intersight:networkobjects       |
| cisco_intersight_adapter_hostfcinterfaces           | adapter.HostFcInterface               | adapterHostFcInterface            | cisco:intersight:networkobjects       |       
| cisco_intersight_ether_hostports                    | ether.HostPort                        | etherHostPort                     | cisco:intersight:networkobjects       |
| cisco_intersight_ether_networkports                 | ether.NetworkPort                     | etherNetworkPort                  | cisco:intersight:networkobjects       |
| cisco_intersight_ether_physicalports                | ether.PhysicalPort                    | etherPhysicalPort                 | cisco:intersight:networkobjects       |
| cisco_intersight_ether_portchannels                 | ether.PortChannel                     | etherPortChannel                  | cisco:intersight:networkobjects       |
| cisco_intersight_fc_physicalports                   | fc.PhysicalPort                       | fcPhysicalPort                    | cisco:intersight:networkobjects       |
| cisco_intersight_fc_portchannels                    | fc.PortChannel                        | fcPortChannel                     | cisco:intersight:networkobjects       |
| cisco_intersight_network_vethernets                 | network.Vethernet                     | networkVethernet                  | cisco:intersight:networkobjects       |
| cisco_intersight_network_vfcs                       | network.Vfc                           | networkVfc                        | cisco:intersight:networkobjects       |
| cisco_intersight_asset_devicecontractinformations   | asset.DeviceContractInformation       | assetDeviceContractInformation    | cisco:intersight:contracts            |
| cisco_intersight_asset_targets                      | asset.Target                          | assetTarget                       | cisco:intersight:targets              |
| cisco_intersight_compute_bladeidentities            | compute.BladeIdentity                 | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_compute_physicalsummaries          | compute.PhysicalSummary               | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_compute_rackunitidentities         | compute.RackUnitIdentity              | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_cond_hclstatuses                   | cond.HclStatus                        | condHclStatus                     | cisco:intersight:compute              |
| cisco_intersight_equipment_chasses                  | equipment.Chassis                     | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_equipment_chassisidentities        | equipment.ChassisIdentity             | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_equipment_expandermodules          | equipment.ExpanderModule              | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_equipment_fancontrols              | equipment.FanControl                  | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_equipment_fanmodules               | equipment.FanModule                   | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_equipment_fans                     | equipment.Fan                         | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_equipment_frus                     | equipment.Fru                         | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_equipment_iocards                  | equipment.IoCard                      | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_equipment_locatorleds              | equipment.LocatorLed                  | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_equipment_psucontrols              | equipment.PsuControl                  | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_equipment_psus                     | equipment.Psu                         | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_equipment_rackenclosures           | equipment.RackEnclosure               | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_equipment_rackenclosureslots       | equipment.RackEnclosureSlot           | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_equipment_switchcards              | equipment.SwitchCard                  | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_equipment_tpms                     | equipment.Tpm                         | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_equipment_transceivers             | equipment.Transceiver                 | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_graphics_cards                     | graphics.Card                         | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_fabric_elementidentities           | fabric.ElementIdentity                | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_memory_units                       | memory.Unit                           | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_processor_units                    | processor.Unit                        | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_storage_items                      | storage.Item                          | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_storage_physicaldisks              | storage.PhysicalDisk                  | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_storage_virtualdrives              | storage.VirtualDrive                  | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_vnic_vnictemplates                 | vnic.VnicTemplate                     | inventoryObjects                  | cisco:intersight:compute              |
| cisco_intersight_fabric_switchclusterprofiles       | fabric.SwitchClusterProfile           | fabricSwitchClusterProfile        | cisco:intersight:profiles             |
| cisco_intersight_fabric_switchprofiles              | fabric.SwitchProfile                  | fabricSwitchProfile               | cisco:intersight:profiles             |
| cisco_intersight_server_profiles                    | server.Profile                        | serverProfile                     | cisco:intersight:profiles             |
| cisco_intersight_chassis_profiles                   | chassis.Profile                       | chassisProfile                    | cisco:intersight:profiles             |
| cisco_intersight_fcpool_pools                       | fcpool.Pool                           | fcpoolPools                       | cisco:intersight:pools                |
| cisco_intersight_ippool_pools                       | ippool.Pool                           | ippoolPools                       | cisco:intersight:pools                |
| cisco_intersight_iqnpool_pools                      | iqnpool.Pool                          | iqpoolPools                       | cisco:intersight:pools                |
| cisco_intersight_macpool_pools                      | macpool.Pool                          | macpoolPools                      | cisco:intersight:pools                |
| cisco_intersight_resourcepool_pools                 | resourcepool.Pool                     | resourcepoolPools                 | cisco:intersight:pools                |
| cisco_intersight_uuidpool_pools                     | uuidpool.Pool                         | uuidpoolPools                     | cisco:intersight:pools                |
| cisco_intersight_license_accountlicensedata         | license.AccountLicenseData            | licenseAccountLicenseData         | cisco:intersight:licenses             |
| cisco_intersight_license_licenseinfos               | license.LicenseInfo                   | licenseLicenseInfo                | cisco:intersight:licenses             |
| cisco_intersight_network_elements                   | network.Element                       | inventoryObjects                  | cisco:intersight:networkelements      |
| cisco_intersight_network_supervisorcards            | network.ElementSummary                | inventoryObjects                  | cisco:intersight:networkelements      |
| cisco_intersight_tam_advisorydefinitions            | tam.AdvisoryDefinition                | tamAdvisoryDefinition             | cisco:intersight:advisories           |
| cisco_intersight_tam_advisoryinfos                  | tam.AdvisoryInfo                      | tamAdvisoryInfo                   | cisco:intersight:advisories           |
| cisco_intersight_tam_advisoryinstances              | tam.AdvisoryInstance                  | tamAdvisoryInstance               | cisco:intersight:advisories           |
| cisco_intersight_tam_securityadvisories             | tam.SecurityAdvisory                  | tamSecurityAdvisory               | cisco:intersight:advisories           |


#### Lifecycle Management via KVStore

- Life-cycle tracking mechanism is functioning in the add-on to determine the presence or absence of infrastructure assets based on real-time API responses from Cisco Intersight.
- A scheduled saved search runs every 24 hours, iterating across 49 supported object types. For each object type, it performs targeted API calls to retrieve the latest data.
- Assets that are no longer returned by the Intersight API (e.g., due to decommissioning, disconnection, or removal) are automatically marked as Absent in the corresponding KV Store collection.
- This approach ensures the KV Store reflects the current live state of the infrastructure, separate from historical data in the index.
- Enables more accurate capacity planning, compliance tracking, and audit reporting by highlighting inventory changes over time.

#### Historical Data Migration from Index to KVStore
- An inherent saved search is added in the add-on to assist in migrating previously indexed inventory data into the appropriate KV Store collections.
- Migration is triggered automatically upon upgrading the add-on from v2.0.1 to any newer add-on supported version, ensuring backward compatibility for existing users.


### 3. Metrics
  - API used to collect metrics data from Intersight: [View API documentation](https://intersight.com/apidocs/apirefs/All/api/v1/telemetry/TimeSeries/post/)

#### Fan

- **Metric**: `fan-speed`
- **API Details:**
      - Collects fan speed metrics in revolutions per minute (rpm) for a server, chassis, Fabric Interconnect, or PSU for a specific time window.

#### Host Power and Energy

- **Metrics**:
      - `hw.host.power`
      - `hw.host.energy`
- **API Details:**
      - Collects the metrics of energy consumed in joules by the entire physical host for a specific time window.  

#### Network

- **Metrics:**
      - `hw.network.bandwidth.utilization_receive`
      - `hw.network.bandwidth.utilization_transmit`
      - `hw.network.io_receive`
      - `hw.network.io_transmit`
      - `hw.errors_network_receive_crc`
      - `hw.errors_network_receive_all`
      - `hw.errors_network_transmit_all`
      - `hw.errors_network_receive_pause`
      - `hw.errors_network_transmit_pause`
      - `hw.network.packets_receive_ppp`
      - `hw.network.packets_transmit_ppp`
      - `hw.errors_network_receive_runt`
      - `hw.errors_network_receive_too_long`
      - `hw.errors_network_receive_no_buffer`
      - `hw.errors_network_receive_too_short`
      - `hw.errors_network_receive_discard`
      - `hw.errors_network_transmit_discard`
      - `hw.errors_network_transmit_deferred`
      - `hw.errors_network_late_collisions`
      - `hw.errors_network_carrier_sense`
      - `hw.errors_network_transmit_jabber`
- **API Details:**
      - Collects network metrics for Intersight managed objects for a specific time window.  

#### Temperature

- **Metrics**: `hw.temperature`
- **API Details:**
      - Collects temperature metrics in degree Celsius for different server components for a specific time window.  

#### Memory

- **Metrics:**
      - `hw.errors_correctable_ecc_errors`
      - `hw.errors_uncorrectable_ecc_errors`  
- **API Details**
      - Collects memory error metrics for Intersight managed objects for a specific time window.  

#### CPU Utilization
- **Metrics**: `hw.cpu`
- **API Details:**
      - Collects CPU Utilization metrics in percentage for different CPUs for a specific time window.  

---

#### **Note:**
   - For other extra information on Intersight API, you can visit: [Cisco Intersight API reference](https://intersight.com/apidocs/introduction/apidocs/an/)  
   - Replace `https://intersight.com` to your instance's hostname.

---


## CONFIGURATION

### 1. Account Configuration
To set up an account for the Cisco Intersight Add-On:

1. Navigate to: `Apps > Cisco Intersight Add-On for Splunk > Configuration > Account`.
2. Click the **Add** button to create a new account.
3. In the pop-up, provide the following details:
      - **Account Name**: A unique name for the Cisco Intersight account (required).
      - **Intersight Hostname**: The hostname of the Cisco Intersight API (required).
      - **Client ID**: The Client ID for your Cisco Intersight account (required).
      - **Client Secret**: The Client Secret associated with the Client ID (required).
      - **Create Default Inputs**: *(Checkbox)*  
         If checked, the add-on will automatically create default data collection inputs for this account (see below).
4. Click **Add** to save the account details.

Once saved, the account will be listed in the Account tab in table format, provided the credentials are correct.

---

#### Default Inputs Created

If you select **Create Default Inputs**, the following six pre-configured inputs will be created for the account (all are initially disabled):

| Input Name Suffix | Input Type         | Description                                                                 | Interval (sec) | Index    | Notes |
|-------------------|--------------------|-----------------------------------------------------------------------------|----------------|----------|-------|
| `<accountname>_audit_logs`     | audit_alarms       | Collects AAA audit records (audit logs)                                     | 900            | default  | Only audit records enabled |
| `<accountname>_alarms`         | audit_alarms       | Collects alarms (critical, warning, cleared, info, suppressed, acknowledged)         | 900            | default  | Only alarms enabled        |
| `<accountname>_intersight_inventory` | inventory    | Collects all inventory objects (compute, license, contract, target, network, fabric, advisories) | 1800 | default | Inventory except ports     |
| `<accountname>_intersight_pools_inventory` | inventory    | Collects all pools' inventory objects | 1800 | default | Inventory: pools only     |
| `<accountname>_intersight_ports_and_interfaces_inventory` | inventory | Collects only port and interface inventory objects                          | 1800           | default  | Inventory: ports only      |
| `<accountname>_network_metrics` | metrics           | Collects network metrics (Network Interface)               | 900            | default  | Metrics: network           |
| `<accountname>_device_metrics`  | metrics           | Collects device metrics (temperature, CPU utilization, memory, host, fan)   | 900            | default  | Metrics: device            |

**Details:**
- All inputs are created with the new account as the `global_account`.
- All are initially **disabled**.
- You can enable and customize them as needed after creation.

---

### 2. Proxy Server Configuration
   To configure a proxy for the Cisco Intersight Add-On:

   1. Navigate to: `Apps > Cisco Intersight Add-On for Splunk > Configuration > Proxy`.
   2. Enable the proxy by checking the **Enable** checkbox.
   3. Provide the following proxy details:
         - **Proxy Type**: Choose the proxy type (either `http` or `socks5`). Default is `http`.
         - **Host Name**: Enter the proxy server's hostname or IP.
         - **Port**: The port number for the proxy server.
         - **Username**: (Optional) Username for the proxy server.
         - **Password**: (Optional) Password for the proxy server.
   4. Click **Save** to store the proxy settings.

   | Proxy Parameters  | Required?  | Description                                           |
   |-------------------|------------|-------------------------------------------------------|
   | **Enable**        | Optional   | Enable the proxy for Cisco Intersight Add-On.         |
   | **Proxy Type**    | Optional   | Type of proxy (`http` or `socks5`). Default is `http`.|
   | **Host Name**     | Optional   | Hostname or IP of the proxy server.                   |
   | **Port**          | Optional   | Port number of the proxy server.                      |
   | **Username**      | Optional   | Username for proxy authentication (if required).      |
   | **Password**      | Optional   | Password for proxy authentication (if required).      |

### 3. Log Level Configuration
   To configure the logging for Cisco Intersight Add-On:

   1. Navigate to: `Apps > Cisco Intersight Add-On for Splunk > Configuration > Logging`.
   2. Select the appropriate log level from the dropdown menu:
            - **ERROR**: Logs only error-level messages.
            - **WARN**: Logs warning and error messages.
            - **INFO**: Logs informational messages (default level).
            - **DEBUG**: Logs detailed debugging information.
   3. Click **Save** to apply the logging settings.

### 4. KV Lookup Rest Configuration
   The KV Lookup Rest configuration is needed in the `Cisco Intersight Add-On for Splunk` to allow users to store data in KV Store Lookups on a different Splunk instance or when running the KV Store on a non-default management port. This provides flexibility for distributed Splunk environments, enabling better data organization and accessibility across multiple instances.
   
   To configure the Splunk KVStore for Cisco Intersight Add-On:

   1. Navigate to: `Apps > Cisco Intersight Add-On for Splunk > Configuration > KV Lookup Rest`.
   2. Provide the following details:
            - **Splunk Rest Host URL**: The hostname of the Splunk REST API (e.g., `localhost` or an external host). This should be without the `http(s)` scheme. Default is `localhost`.
            - **Port**: The management port for Splunk (default: `8089`).
            - **Splunk Username**: (Optional) Not required if the Splunk REST Host URL is `localhost` or `127.0.0.1`. The user should have at least power role capabilities.
            - **Splunk Password**: (Optional) Not required if the Splunk REST Host URL is `localhost` or `127.0.0.1`.
   3. Click **Save** to store the KVStore configuration.

   | KVStore Parameters        | Required?        | Description                                                                  |
   |---------------------------|------------------|-----------------------------------------------------------------------------|
   | **Splunk Rest Host URL**  | Mandatory        | Enter the Splunk REST host (e.g., `localhost`).                             |
   | **Port**                  | Mandatory        | Enter the management port of Splunk (default: `8089`).                      |
   | **Splunk Username**       | Optional         | Splunk username (not needed for `localhost` or `127.0.0.1`).                |
   | **Splunk Password**       | Optional         | Splunk password (not needed for `localhost` or `127.0.0.1`).                |

**Important Points to take into consideration**
      - The `KV Lookup Rest Configuration` tab should not be updated once the data collection is enabled in the add-on as this may result in data loss or data duplication. It is recommended to create a new input for data collection if the details provided in this tab needs to be updated.
      - If using a **Distributed environment**, Add the Search Head IP address to the **KV Lookup REST Configuration** by navigating to:
Settings > Lookup Tables > KV Lookup REST Configuration.
This ensures that the Search Head(s) can properly query KV Store lookups hosted on the Indexer or SHC Deployer.
Note: This step can be skipped for single-instance deployments or standalone test environments.
      - If using a **Distributed environment**, make sure in `limits.conf` values of `max_documents_per_batch_save` and `max_size_per_batch_save_mb` should be same in all instances.

### 5. Macro and Data Model Configuration

For the dashboards to populate correctly and ensure optimized searches, follow these configuration steps.

#### 5.1 Configure the Macro for Indexing
Ensure that the macro `cisco_intersight_index` matches the index where Cisco Intersight data is stored.

##### Steps to verify and update:
1. Navigate to **Settings → Advanced Search → Search Macros**.
2. Locate **`cisco_intersight_index`**.
3. Ensure the index set in the macro matches the data ingestion index.

#### 5.2 Check Data Model Acceleration
It is recommended to accelerate **Cisco Intersight Data Model** for faster loading of the dashboards.

##### Steps to verify:
1. Navigate to **Settings → Data Models → Cisco Intersight**.
2. Check the **acceleration percentage**.
3. If the acceleration is not **100%**, some data may not be available in dashboards.

#### 5.3 Optimize Data Model Searches with Summaries
For better performance when using an accelerated **Cisco Intersight** Data Model, configure the macro `cisco_intersight_summariesonly` to use summary data.

##### Steps to configure:
1. Navigate to **Settings → Advanced Search → Search Macros**.
2. Locate **`cisco_intersight_summariesonly`**.
3. Update the value from `summariesonly=false` to **`summariesonly=true`**.

By ensuring the above configurations, users can avoid issues related to missing or slow-loading dashboard data.

## Data Inputs

The add-on supports the following data inputs:

### 1. Audits & Alarm Input Configuration
   To configure the **Audits & Alarm** inputs for Cisco Intersight Add-On:

   1. Navigate to: `Apps > Cisco Intersight Add-On for Splunk > Inputs`.
   2. Click the **Create New Input** button.
   3. Select **Audits & Alarm** from the input types.
   4. In the configuration pop-up, fill in the following details:
         - **Input Name**: A unique name for the input (required).
         - **Intersight Account**: Select the previously configured Intersight account from the dropdown (required).
         - **Interval**: Set the data collection interval. (Options: 5 Minutes, 10 Minutes, 15 Minutes, 30 Minutes, 1 Hour) (Default: 15 Minutes) (Required).
         - **Start Day for Data Collection**: Select the starting day for data collection. (Options: Today, 7 Days Ago, Last Month, Last 6 Months)(Default: 7 Days Ago)(Required)
         - **Index**: Choose the desired Splunk index to store the data (required).
         - **Enable AAA Audit Records**: Check this box if you want to collect AAA audit data.
         - **Enable Alarms**: Check this box if you want to collect alarms.
            - **Include Acknowledged Alarms**: This option will appear upon enabling alarms. (Default: Selected)
            - **Include Suppressed Alarms**: This option will appear upon enabling alarms. (Default: Selected)
            - **Include Info Alarms**: This option will appear upon enabling alarms. (Default: Selected)
   5. Click **Add** to save the configuration.

   **Success Criteria**:
      - The configured input should appear in the **Inputs Tab** in a table format.
      - Ensure that data collection starts correctly, and data is indexed as expected.

   ---

### 2. Inventory Input Configuration
   To configure the **Inventory** inputs for Cisco Intersight Add-On:

   1. Navigate to: `Apps > Cisco Intersight Add-On for Splunk > Inputs`.
   2. Click the **Create New Input** button.
   3. Select **Inventory** from the input types.
   4. In the configuration pop-up, fill in the following fields:
         - **Input Name**: A unique name for the input (required).
         - **Intersight Account**: Select the previously configured Intersight account from the dropdown (required).
         - **Interval**: Select the data collection interval.
            (Options: 15 Minutes, 30 Minutes, 1 Hour, 6 Hours, 12 Hours, 24 Hours) (Default: 30 Minutes) (Required).
         - **Index**: Choose the desired Splunk index to store the data (required).
         - **Inventory Options**: Select the desired inventory options (e.g., Compute APIs).
   5. Click **Add** to save the configuration.

   **Success Criteria**:
      - The configured input should appear in the **Inputs Tab** in a table format.
      - Ensure that data collection starts correctly, and data is indexed as expected.

   ---

### 3. Metrics Input Configuration
   To configure the **Metrics** inputs for Cisco Intersight Add-On:

   1. Navigate to: `Apps > Cisco Intersight Add-On for Splunk > Inputs`.
   2. Click the **Create New Input** button.
   3. Select **Metrics** from the input types.
   4. In the configuration pop-up, provide the following details:
         - **Input Name**: A unique name for the input (required).
         - **Intersight Account**: Select the previously configured Intersight account from the dropdown (required).
         - **Interval**: Select the data collection interval from the three options (15 minute, 30 minute, 1 hour) (required).
         - **Index**: Choose the desired Splunk index to store the data (required).
         - **Metrics Data**: Select the specific metrics options as needed.
   5. Click **Add** to save the configuration.

   **Success Criteria**:
      - The configured input should appear in the **Inputs Tab** in a table format.
      - Ensure that data collection starts correctly, and data is indexed as expected.

### Metrics Collection Types

| Metrics Type | Description |
|--------------|-------------|
| Fan          | Collects fan speed metrics. |
| Host Power   | Collects power and energy metrics. |
| Network      | Collects various network metrics. |
| Temperature  | Collects temperature metrics. |
| Memory       | Collects ECC error metrics. |
| CPU Utilization | Collects C0 CPU Utilization metrics. |

   ---

### 4. Custom Input Configuration

The Custom Input feature allows you to collect data from any Cisco Intersight API endpoint that is not covered by the standard inputs. This provides flexibility to gather specialized data based on the specific requirements.

**Important**:
   - **Maximum Custom Inputs**: You can configure up to **10 custom inputs** in the add-on. This limit ensures optimal performance and resource utilization.
   - **Data Expansion Caution**: When using the `$expand` parameter for Inventory APIs, be cautious about expanding too many related objects. Extensive data expansion can:
      - Significantly increase event size
      - Lead to **Broken Pipe errors** during data transmission
      - Impact indexing performance and consume more storage space
      - **Best Practice**: Only expand the specific related objects you need for your use case.

#### Use Cases and Example Configurations

**Common Use Cases:**
   - Gather specialized data specific to your environment (e.g., custom policies, workflows, storage arrays)
   - Monitor custom metrics not included in standard inputs

#### Understanding Custom Input Field Visibility

The Custom Input configuration form dynamically shows/hides fields based on the **API Type** you select:

**When "Inventory / Configuration APIs" is selected:**
   - Visible Fields: `Filter`, `Select`, `Expand`
   - Hidden Fields: `Metrics Name`, `Metrics Type`, `Group By`, `Edit Metrics Fields`, and all metrics field name fields

**When "Telemetry / Metrics APIs" is selected:**
   - Visible Fields: `Metrics Name`, `Metrics Type`, `Group By`, `Edit Metrics Fields` (checkbox)
   - Hidden Fields: `Filter`, `Select`, `Expand`
   - Conditionally Visible: `Sum Field Name`, `Min Field Name`, `Max Field Name`, `Average Field Names`, `Latest Field Name` (only when "Edit Metrics Fields" checkbox is enabled)

#### How to Find API Endpoints and Parameters

Before configuring a Custom Input, you need to identify the correct API endpoint and parameters. Cisco Intersight provides multiple ways to discover this information:

##### 1: Finding Inventory/Configuration API Endpoints

**Step 1: Access Intersight API Reference Documentation**

1. **Navigate to API Documentation**:
      - **SaaS (Global)**: `https://intersight.com/apidocs/apirefs/All/`
      - **SaaS (US East)**: `https://us-east-1.intersight.com/apidocs/apirefs/All/`
      - **SaaS (EU Central)**: `https://eu-central-1.intersight.com/apidocs/apirefs/All/`
      - **Appliance**: `https://<your-appliance-hostname>/apidocs/apirefs/All/`

2. **Browse and Search for Endpoints**:
      - The page displays a comprehensive list of all Intersight API endpoints organized alphabetically
      - Use the search box to filter by keyword (e.g., "blade", "storage", "profile", "policy")
      - Each endpoint listing shows:
         - **Endpoint Path**: The API path (e.g., `compute/Blades`, `storage/PureArrays`)
         - **HTTP Methods**: Supported operations (GET, POST, PATCH, DELETE)
         - **Description**: Brief explanation of what the endpoint provides

**Step 2: Identify API Endpoint Name**

1. **Select an Endpoint**:
      - Click on an endpoint to view its detailed documentation
      - Example: Click on `compute/Blades` to see blade server API details

2. **Note the Endpoint Path**:
      - The detail page shows the full endpoint URL: `/api/v1/compute/Blades`
      - **For Custom Input Configuration**: Use only the relative path without `/api/v1/`
      - **Correct**: `compute/Blades`, `/api/v1/compute/Blades`
      - **Incorrect**: `Blades` or `blades`
      - **Case Sensitivity**: Endpoint paths are case-sensitive
         - Correct: `compute/Blades`, `storage/PureArrays`, `server/Profiles`
         - Incorrect: `compute/blades`, `Storage/PureArrays`, `Server/profiles`

**Step 3: Identify Available Fields for $select Parameter**

The `$select` parameter allows you to retrieve only specific fields, reducing data volume and improving performance.

1. **Locate the Response Schema**:
      - In the endpoint detail page, scroll to the **Response Schema** or **Model** section
      - This section lists all fields returned by the API with their data types and descriptions

2. **Common Fields Across Most Endpoints**:
      - `Moid` - Managed Object ID (unique identifier for the object)
      - `Name` - Object name or hostname
      - `Model` - Hardware model number
      - `Serial` - Serial number
      - `Status` - Current operational status
      - `Vendor` - Vendor/manufacturer name
      - `Dn` - Distinguished Name (hierarchical identifier)
      - `CreateTime` - Object creation timestamp
      - `ModTime` - Last modification timestamp
      - `ObjectType` - Type of the object (e.g., `compute.Blade`)

3. **Endpoint-Specific Fields**:
      - Review the Response Schema to identify fields specific to your endpoint
      - Example for `compute/Blades`:
            - `NumCpus`, `NumCpuCores`, `TotalMemory` - Hardware specs
            - `OperPowerState`, `OperState` - Operational status
            - `ManagementMode` - Management mode (IMM, IntersightStandalone)
      - Example for `storage/PureArrays`:
            - `Capacity`, `UsedCapacity` - Storage capacity metrics
            - `Version` - Software version
            - `Controllers` - Array controllers information

4. **Construct the $select Parameter**:
      - List field names separated by commas (no spaces). **NOTE**: Field names are case-sensitive.
      - **Correct**: `Moid,Name,Model,Serial,Status`
      - **Incorrect**: `Moid, Name, Model` (spaces not allowed), `moid, name, model` (field names are case-sensitive).
      - **Best Practice**: Always include `Moid` and `ObjectType` for proper identification

**Step 4: Identify Expandable Relationships for $expand Parameter**

The `$expand` parameter allows you to include related objects in the response, avoiding additional API calls. For more details on `$expand` parameter, refer - [Intersight API Documentation](https://us-east-1.intersight.com/apidocs/introduction/query/#filter-query-option-filtering-the-resources)
   
   **Caution with $expand**:
      - Each expanded relationship significantly increases response size
      - Expanding too many relationships can cause:
         - **Broken Pipe errors** during data transmission
         - Utilises higher network bandwidth
         - Higher memory consumption
         - Indexing performance degradation
      - **Best Practice**:
         - Only expand relationships you actually need for your use case.
         - Use $select in expanded relationships to fetch only required fields.

**Step 5: Construct Filter Queries for $filter Parameter**

The `$filter` parameter allows you to retrieve only objects matching specific criteria, reducing unnecessary data collection. **NOTE**: Field names are case-sensitive. For more details on `$filter` parameter, refer - [Intersight API Documentation](https://us-east-1.intersight.com/apidocs/introduction/query/#filter-query-option-filtering-the-resources)

**Step 6: Test the API Endpoint (Recommended)**

Before configuring the Custom Input, test your API endpoint with the parameters:

1. **Using Intersight API Documentation "Try it out" Feature**:
      - Some endpoint pages have an interactive "Try it out" button
      - Enter your query parameters ($filter, $select, $expand)
      - Click "Execute" to see the actual API response
      - Verify the response contains expected data

2. **Verify Before Configuration**:
      - Endpoint returns data (not empty)
      - Selected fields appear in response
      - Expanded relationships contain expected nested data
      - Filter reduces results as expected
      - Response size is reasonable (not too large)

##### 2: Finding Telemetry Metrics Information

**Step 1: Identify Metrics Name from Intersight Metrics Explorer**

The most reliable way to find the exact metrics name and understand the query structure is by using the Intersight Metrics Explorer UI and examining its Data Query payload.

1. **Access Metrics Explorer**:
      - Log in to your Cisco Intersight instance
      - Navigate to: `Analyze > Explorer`
      - This is the interactive metrics visualization tool in Intersight

2. **Select a Metric to Visualize**:
      - Click on the **Metric** dropdown at the top
      - Browse through available metrics organized by category. Some examples are:
         - **Fan Metrics**: Fan Speed
         - **Memory Metrics**: ECC Errors (Correctable, Uncorrectable)
         - **Network Metrics**: Bandwidth Utilization, I/O, Errors
         - **Temperature Metrics**: Temperature readings
         - **Power Metrics**: Power consumption, Energy
         - **CPU Metrics**: CPU Utilization
         - **Storage Metrics**: Storage utilization, I/O operations
      - Select a metric you want to collect (e.g., "Fan Speed")

3. **Configure Visualization (Optional)**:
      - Select time range, sub type (Sum, Minimum, Maximum, Average, Latest), and Inventory Dimensions
      - This helps visualize the data before configuring Custom Input

4. **Access the Query Code Section**:
      - Once the metric graph is generated, beneath it, look for the **Query Code** section.
      - This section shows the actual JSON payload sent to the Intersight API to fetch the relevant metrics.
      - This payload contains all the information you need for Custom Input configuration.

5. **Examine the Payload Structure**:
   
   The Data Query payload will look similar to this example:
   
   ```json
   {
      "queryType": "groupBy",
      "dataSource": "PhysicalEntities",
      "granularity": {
         "type": "period",
         "period": "PT12H",
         "timeZone": "Asia/Calcutta",
         "origin": "2025-08-17T10:09:00.000Z"
      },
      "intervals": [
         "2025-08-17T10:09:00.000Z/2025-11-17T10:09:00.000Z"
      ],
      "dimensions": [
         "host.name",
         "id",
         "intersight.domain.id"
      ],
      "filter": {
         "type": "and",
         "fields": [
         {
            "type": "selector",
            "dimension": "id",
            "value": "636d5c566176752d35d2999e"
         },
         {
            "type": "selector",
            "dimension": "instrument.name",
            "value": "hw.fan"
         }
         ]
      },
      "aggregations": [
         {
         "type": "longSum",
         "name": "count",
         "fieldName": "hw.fan.speed_count"
         },
         {
         "type": "longSum",
         "name": "hw.fan.speed-Sum",
         "fieldName": "hw.fan.speed"
         },
         {
         "type": "thetaSketch",
         "name": "endpoint_count",
         "fieldName": "id"
         }
      ],
      "postAggregations": [
         {
         "type": "expression",
         "name": "hw-fan-speed-Avg",
         "expression": "(\"hw.fan.speed-Sum\" / \"count\")"
         }
      ]
   }
   ```

6. **Reference: Common Metrics Names**:
   
   You can find metrics names in the official documentation: [Intersight API Documentation](https://intersight.com/apidocs/introduction/supported-metrics-overview/)
   
   Some example metric names are:

   **Fan Metrics**:
      - `hw.fan.speed` - Fan speed in RPM
   
   **Memory Metrics**:
      - `hw.errors_correctable_ecc_errors` - Correctable ECC errors
      - `hw.errors_uncorrectable_ecc_errors` - Uncorrectable ECC errors
   
   **Network Metrics**:
      - `hw.network.bandwidth.utilization_receive` - Network RX bandwidth utilization
      - `hw.network.bandwidth.utilization_transmit` - Network TX bandwidth utilization
      - `hw.network.io_receive` - Network receive I/O bytes
      - `hw.network.io_transmit` - Network transmit I/O bytes
      - `hw.errors_network_receive_crc` - CRC errors
      - `hw.errors_network_receive_all` - Total receive errors
      - `hw.errors_network_transmit_all` - Total transmit errors

   **NOTE**: For Custom Input Configuration use the metric name format (with dots)
      - **Correct**: `hw.fan.speed`, `hw.errors_correctable_ecc_errors`, `hw.temperature`
      - **Incorrect**: `FanSpeed`, `CpuUtilization`, `Temperature`

**Step 2: Identify Inventory Dimensions (Group By Fields) from Explorer Payload**

Dimensions are the fields you can use to correlate metrics data with Intersight Inventory. The Metrics Explorer payload shows exactly which dimensions are available.

1. **Locate Dimensions in the Payload**:
      - In the Data Query payload, find the `dimensions` array
      - Example from the payload above:
         ```json
            "dimensions": [
               "host.name",
               "id",
               "intersight.domain.id"
            ]
         ```
         - These are the exact dimension names you have to use in the **Group By** field
         - It is recommended to select as many dimension fields as necessary to support the creation of a comprehensive custom dashboard for the collected metrics.

2. **Construct the Group By Field**:
      - Copy dimension names from the payload's `dimensions` array
      - For Custom Input **Group By** field, enter comma-separated dimension names. **NOTE**: Field names are case-sensitive.
      - **Correct**: `host.name,id,intersight.domain.id`
      - **Incorrect**: `host.name, "id"` (no spaces, no qoutes)

3. **Best Practices for Group By**:
      - **Always include** `intersight.domain.id` for multi-domain environments
      - **Include** `host.name` for host-level aggregation and identification
      - **Include component-specific IDs** (`id`, `interface`, `disk_id`) for granular inventory metadata
      - **Avoid too many dimensions** as it increases data volume and cardinality
      - **Match the Explorer payload** - use the same dimensions shown in the working query

**Step 3: Verify Metric Name and Metric field names with Explorer payload**

The add-on automatically generates field names for metrics aggregations based on the metrics name provided. However, you can verify and customize these if needed.

1. **'Edit Metrics Field' checkbox**

   While configuring the inputs, the field names for different metric types (Sum, Minimum, Maximum, Average, Latest) are auto generated. It is recommended to verify these field names with Intersight Explorer query code. (**NOTE**: Field names are case-sensitive).
      - Click on 'Edit Metrics Field' checkbox
      - Field names corresponsing to each metric type will be shown in the Input configuring pop-up.

3. **Verify Field Names with Explorer Payload**:

   In the Data Query payload, find the `aggregations` array:
     ```json
      "aggregations": [
         {
            "type": "longSum",
            "name": "hw_fan_speed_sum",
            "fieldName": "hw_fan_speed"
         },
         {
            "type": "longMin",
            "name": "hw_fan_speed_min",
            "fieldName": "hw_fan_speed_min"
         }
      ]
     ```
   
   - It is recommended to verify the auto-generated field names per metric type in Splunk Input pop-up with `fieldName` key from the payload.
   - **If they match**: No action needed, use auto-generated values
   - **If they differ**: You'll need to manually update the field names in Splunk Input pop-up.

##### Quick Reference Examples

**Example 1: Finding Storage Array Endpoint (Configuring Custom Input for Inventory)**
   - **Goal**: Collect Pure Storage arrays
   - **Method**: [Intersight API Documentation](https://intersight.com/apidocs/apirefs/All/) → Search "PureArrays"
   - **Endpoint**: `storage/PureArrays`
   - **Available Fields** (from Response Schema): `Moid`, `Name`, `Model`, `Serial`, `Version`, `Status`
   - **Example $select**: `Moid,Name,Model,Serial,Status`
   - **Example $expand**: `RegisteredDevice`

**Example 2: Finding Network Bandwidth Metrics (Configuring Custom Input for Metrics)**
   - **Goal**: Collect network receive bandwidth metrics
   - **Method**: 
      - [Intersight API Documentation](https://intersight.com/apidocs/introduction/supported-metrics-overview/) → Network Metrics
      - Intersight UI Metrics Explorer → Select Network metric → View dimensions
   - **Metrics Name**: `hw.network.bandwidth.utilization_receive` (from documentation)
   - **Metrics Type**: `sum,avg` (from documentation)
   - **Group By**: `hostname,interface,intersight.domain.id` (from Metrics Explorer UI)

---

#### Custom Input Quick Reference Summary

**All Configuration Fields Overview:**

| Field Name | Required | Visible When | Field Type | Auto-Generated | Description |
|------------|----------|--------------|------------|----------------|-------------|
| **Input Name** | Yes | Always | Text | No | Unique name for the custom input |
| **Cisco Intersight Account** | Yes | Always | Dropdown | No | Select configured account |
| **Interval** | Yes | Always | Dropdown | No | Data collection interval (Default: 15 min) |
| **Index** | Yes | Always | Dropdown | No | Splunk index for data storage |
| **API Type** | Yes | Always | Dropdown | No | `Inventory / Configuration APIs` or `Telemetry / Metrics APIs` |
| **API Endpoint** | Yes | Always | Text | No | Relative endpoint path (e.g., `/api/v1/compute/Blades`). API is case-sensitive. |
| **Sourcetype** | No | Never (Hidden) | N/A | No | For Inventory: `cisco:intersight:custom:inventory`, For Metrics: `cisco:intersight:custom:metrics` |
| **Filter** | No | Inventory APIs only | Textarea | No | OData $filter parameter. Field names provided are case-sensitive. |
| **Select** | No | Inventory APIs only | Text | No | OData $select parameter (comma-separated fields). Field names provided are case-sensitive. |
| **Expand** | No | Inventory APIs only | Textarea | No | OData $expand parameter. Field names provided are case-sensitive. |
| **Metrics Name** | Yes* | Telemetry APIs only | Text | No | Exact metric name (e.g., `hw.fan.speed`). Metric name provided is case-sensitive. |
| **Metrics Type** | Yes* | Telemetry APIs only | Multi-Select | No | Aggregations: Sum, Minimum, Maximum, Average, Latest |
| **Group By** | No | Telemetry APIs only | Textarea | No | Dimensions (comma-separated). Field names provided are case-sensitive. |
| **Edit Metrics Fields** | No | Telemetry APIs only | Checkbox | No | Enable advanced field name editing |
| **Sum Field Name** | No | When Edit Metrics Fields checked | Text | Yes | Base field for Sum aggregation. Field name provided is case-sensitive. |
| **Min Field Name** | No | When Edit Metrics Fields checked | Text | Yes | Base field for Min aggregation. Field name provided is case-sensitive. |
| **Max Field Name** | No | When Edit Metrics Fields checked | Text | Yes | Base field for Max aggregation. Field name provided is case-sensitive. |
| **Average Field Names** | No | When Edit Metrics Fields checked | Text | Yes | Fields for Avg aggregation (sum,count). Field names provided are case-sensitive. |
| **Latest Field Name** | No | When Edit Metrics Fields checked | Text | Yes | Base field for Latest aggregation. Field name provided is case-sensitive. |

**Key Takeaways:**

1. **Field Visibility is Dynamic**: The form shows different fields based on API Type selection
4. **Metrics Explorer is Key**: Use Intersight Metrics Explorer's Data Query payload to find exact metrics names, dimensions, and field names
5. **Case Sensitivity**: API endpoints and metrics names are case-sensitive
6. **Maximum Limit**: 10 custom inputs maximum per add-on instance

---


## Data Collection 
### Collection Frequencies, Sourcetype, Source Mappings
* The table below provides the default interval at which inputs will collect data from Cisco Intersight:
* The Cisco Intersight Add-On for Splunk assigns all Cisco Intersight data the sourcetypes of cisco:intersight.

| Input Name                          | Default Interval (in seconds) | Splunk Sourcetype                   | Splunk Source                     | CIM Data Models                  |
|-------------------------------------|-------------------------------|-------------------------------------|-----------------------------------|----------------------------------|
| Alarms                              | 900                           | cisco:intersight:alarms             | condAlarm                         | Alerts                           |
| Audit Records                       | 900                           | cisco:intersight:auditRecords       | aaaAuditRecord                    | Authentication, Change           |
| Advisories                          | 1800                          | cisco:intersight:advisories         | tamAdvisoryDefinition             |                                  |
| Advisories                          | 1800                          | cisco:intersight:advisories         | tamAdvisoryInfo                   |                                  |
| Advisories                          | 1800                          | cisco:intersight:advisories         | tamAdvisoryInstance               |                                  |
| Advisories                          | 1800                          | cisco:intersight:advisories         | tamSecurityAdvisory               |                                  |
| Contract                            | 1800                          | cisco:intersight:contracts          | assetDeviceContractInformation    |                                  |
| HCL Statuses                        | 1800                          | cisco:intersight:compute            | condHclStatus                     |                                  |
| Equipment Chasses                   | 1800                          | cisco:intersight:compute            | inventoryObjects                  |                                  |
| Inventory Objects                   | 1800                          | cisco:intersight:compute            | inventoryObjects                  |                                  |
| Network Element Summaries           | 1800                          | cisco:intersight:networkelements            | inventoryObjects                  |                                  |
| License Data                        | 1800                          | cisco:intersight:licenses           | licenseAccountLicenseData         |                                  |
| License Infos                       | 1800                          | cisco:intersight:licenses           | licenseLicenseInfo                |                                  |
| Ethernet Host Ports                 | 1800                          | cisco:intersight:networkobjects     | etherHostPort                     | Network                          |
| Ethernet Network Ports              | 1800                          | cisco:intersight:networkobjects     | etherNetworkPort                  | Network                          |
| Ethernet Physical Ports             | 1800                          | cisco:intersight:networkobjects     | etherPhysicalPort                 | Network                          |
| Ethernet Port Channels              | 1800                          | cisco:intersight:networkobjects     | etherPortChannel                  | Network                          |
| FC Physical Ports                   | 1800                          | cisco:intersight:networkobjects     | fcPhysicalPort                    | Network                          |
| FC Port Channels                    | 1800                          | cisco:intersight:networkobjects     | fcPortChannel                     | Network                          |
| Host Ethernet Interfaces            | 1800                          | cisco:intersight:networkobjects     | adapterHostEthInterface           | Network                          |
| Host FC Interfaces                  | 1800                          | cisco:intersight:networkobjects     | adapterHostFcInterface            | Network                          |
| Virtual Ethernet Interfaces         | 1800                          | cisco:intersight:networkobjects     | networkVethernet                  | Network                          |
| Virtual Fibre Channels              | 1800                          | cisco:intersight:networkobjects     | networkVfc                        | Network                          |
| FC Pool                             | 1800                          | cisco:intersight:pools              | fcpoolPools                       |                                  |
| IP Pool                             | 1800                          | cisco:intersight:pools              | ippoolPools                       |                                  |
| IQN Pool                            | 1800                          | cisco:intersight:pools              | iqnpoolPools                      |                                  |
| MAC Pool                            | 1800                          | cisco:intersight:pools              | macpoolPools                      |                                  |
| UUID Pool                           | 1800                          | cisco:intersight:pools              | uuidpoolPools                     |                                  |
| Resource Pool                       | 1800                          | cisco:intersight:pools              | resourcepoolPools                 |                                  |
| Asset Targets                       | 1800                          | cisco:intersight:targets            | assetTarget                       |                                  |
| Chassis Profiles                    | 1800                          | cisco:intersight:profiles           | chassisProfile                    | Inventory                        |
| Fabric Switch Cluster Profiles      | 1800                          | cisco:intersight:profiles           | fabricSwitchClusterProfile        |                                  |
| Fabric Switch Profiles              | 1800                          | cisco:intersight:profiles           | fabricSwitchProfile               |                                  |
| Server Profiles                     | 1800                          | cisco:intersight:profiles           | serverProfile                     |                                  |
| Metric – CPU Utilization            | 900                           | cisco:intersight:metrics            | cpu_utilization                   | Performance                      |
| Metric – Fan                        | 900                           | cisco:intersight:metrics            | fan                               | Performance                      |
| Metric – Host                       | 900                           | cisco:intersight:metrics            | host                              | Performance                      |
| Metric – Memory                     | 900                           | cisco:intersight:metrics            | memory                            | Performance                      |
| Metric – Network                    | 900                           | cisco:intersight:metrics            | network                           | Performance                      |
| Metric – Temperature                | 900                           | cisco:intersight:metrics            | temperature                       | Performance                      |
| Custom – (Inventory)                | 1800                          | cisco:intersight:custom:inventory   | <objecttype>                      |
| Custom – (Telemetry)                | 1800                          | cisco:intersight:custom:metrics            | <objecttype>                      |


## Reports

### Cisco Intersight: Advisory Details Report
* The report displays the advisory instances for all the account and its details including
the name of the Security Advisory/Advisory Definition, recommendation, description, severity, state, the type (end of life advisory or field notice advisory), domain type (IMM, Standalone or Unified Edge) and Contract Status.

### Cisco Intersight: Advisory Instances in Last 30 days
* The report displays the advisory instances that have been created in the last 30 days for all the account the name of the Security Advisory/Advisory Definition, recommendation, description, severity, state, domain type (IMM, Standalone or Unified Edge) and Contract Status.

### Cisco Intersight: Chassis Slot Utilization
* The report displays slots which are occupied by Server in Chassis along with domain type (IMM, Standalone or Unified Edge) and Contract Status.

### Cisco Intersight: Cisco Compute HCL Report
* The report displays HCL status fields for Particular Server along with domain type (IMM, Standalone or Unified Edge) and Contract Status.

### Cisco Intersight: Intersight Inventory with versions
* The report displays the list of Servers and network elements along with its health, status, version details, domain type (IMM, Standalone or Unified Edge) and Contract Status.

### Cisco Intersight: License Status per account
* The report provide the details of the license linked with the Accounts configured along with its type, status and the expiry time.

### Cisco Intersight: Storage PhysicalDisk lifespan
* The report displays Remained Lifespan of Physical disk along with other details for that Physical disk which are of SSD type or having "NVMe" Protocol.

### Cisco Intersight: View of Servers with Alarms + HCLStatus
* The report displays the Server health overview by presenting the server details along with the alarms generated, domain type (IMM, Standalone or Unified Edge) and Contract Status.

## TROUBLESHOOTING
### General Checks
* If your dashboard is not populating, then below checks should be done:
   - Ensure the index in the macro `cisco_intersight_index` matches the data present in the index. (To open macro go to Settings → Advanced search → Search Macros → cisco_intersight_index).
   - Ensure KV store configuration is done for the same instance you are checking dashboard on.
   - If the data model `Cisco Intersight` is accelerated, ensure that the macro `cisco_intersight_summariesonly` is set to summariesonly=true.
   - If the data model `Cisco Intersight` is accelerated, then check the percentage of acceleration in the data model. If the percentage is not 100%, all data may not load.  (To open data model go to Settings → Data Models → Cisco Intersight)
* 'Inventory Browser' dashboard is not structured after upgrade to v3.1.0
   - As part of upgrade to v3.1.0, certain migration savedsearches are ran to collect the required data in Splunk to support the latest features of the add-on included in v3.1.0. Hence, till the savedsearches are not disabled, newer inventory updates will not be fetched.
   - In order to verify if the savedsearches are ran successfully, search for below logs using SPL. Once the below logs are found, disable the inputs and then re-enable the inputs to begin the data collection workflow.
      - `index=_internal source="*ta_intersight*" "Successfully disabled saved search: splunk_ta_cisco_intersight_unified_edge_migration"`
      - `index=_internal source="*ta_intersight*" "Successfully disabled saved search: splunk_ta_cisco_intersight_index_to_kvstore_migration_inventory"`
      - `index=_internal source="*ta_intersight*" "Successfully disabled saved search: splunk_ta_cisco_intersight_metrics_checkpoint_reset"`
      - `index=_internal source="*ta_intersight*"  "Successfully disabled saved search: splunk_ta_cisco_intersight_inventory_checkpoint_reset"`
* To troubleshoot Cisco Intersight Add-On for Splunk, check `$SPLUNK_HOME/var/log/splunk/ta_intersight_*.log` or user can search `index="_internal" source=*ta_intersight_*.log*` query to see all the logs in UI. Also, user can use `index="_internal" source=*ta_intersight_*.log* ERROR` query to see ERROR logs in the Splunk UI.
* Note that all log files of this App will be generated in `$SPLUNK_HOME/var/log/splunk/` directory.

### KV Store Troubleshooting (Distributed Environment Only)

If dashboards are missing or showing partial data in a distributed setup (Search Head and Indexers are separate), follow the below steps:

1. Go to:  
   `Settings → Lookup Tables → KV Lookup REST Configuration`

2. Ensure the following settings:
      - **Search Head IP address** is added correctly.
      - **Splunk REST Host URL** should be `localhost` or the remote indexer without `http/https`.
      - **Port** should be the Splunk management port (default: `8089`).
      - **Username/Password** are needed only when authenticating against remote REST endpoints.

3. Make sure the Search Head can reach the Indexer’s management port over the network (default is `8089`).

4. Additionally, verify `limits.conf` (if customized) on all involved nodes:
   ```
      [kvstore]
       max_documents_per_batch_save = <your_value>
       max_size_per_batch_save_mb = <your_value>
   ```

**Note**: These KV Store configuration steps are required only for distributed Splunk environments.
For standalone or test setups, these can be skipped.

### Custom Input Troubleshooting

#### Custom Input Not Collecting Data

1. **Verify Input Configuration**:
      - Check that the input is enabled in the Inputs tab
      - Verify the API endpoint is correctly specified (case-sensitive)
      - Ensure the account credentials have necessary permissions

2. **Check Logs**:
   ```
   index="_internal" source="*ta_intersight_custom_input.log*"
   ```
   Look for messages with:
      - `message=custom_input_error` - General errors
      - `message=custom_input_api_detection` - API type detection
      - `message=custom_input_filter_applied` - Filter application

3. **Common Issues**:

   **403 Forbidden Error**:
      - **Cause**: Insufficient permissions, invalid API, or incorrect case sensitivity
      - **Solution**: 
         - Verify OAuth2.0 application permissions in Intersight
         - Check API endpoint exists: `https://<your-intersight>/apidocs/`
         - Ensure correct case (e.g., `/compute/Blades` not `/compute/blades`)
      - **Log Message**: Look for `403` or `permission` in logs

   **404 Not Found Error**:
      - **Cause**: Incorrect API endpoint spelling or case mismatch
      - **Solution**: Verify endpoint in Intersight API documentation
      - **Example**: `/storage/PureArrays` (correct) vs `/storage/purearrays` (incorrect)

   **Broken Pipe Error**:
      - **Cause**: Data payload too large due to excessive `$expand` usage
      - **Solution**: 
      - Reduce number of expanded objects
      - Add `$filter` to limit results
      - Increase collection interval
      - **Log Message**: Look for `Broken Pipe` or `Connection reset`

   **No Data Collected**:
      - **Cause**: API returns empty results
      - **Solution**: 
         - Verify objects exist in Intersight for the endpoint
         - Check if filters are too restrictive
         - Test endpoint in Intersight API docs first

   **KVStore Collection Not Created**:
      - **Cause**: KVStore access issues or input misconfiguration
      - **Solution**: 
         - Verify KVStore is enabled
         - Check KVStore configuration in Settings
         - Review `ta_intersight_custom_input.log` for KVStore errors

4. **Telemetry-Specific Issues**:
      - **No Domains Found**: Ensure inventory input has collected domain data first
      - **Invalid Metrics Name**: Verify metric name exists in Intersight (e.g., `hw.fan.speed`)
      - **Missing Aggregations**: Ensure at least one metrics type (sum/min/max/avg) is selected

5. **Validation Steps**:
   - Test API endpoint in Intersight API documentation before creating input
   - Start with simple configuration (no filters/expansions)
   - Monitor first collection cycle in logs
   - Verify data is being indexed with the configured sourcetype
   - For Inventory APIs: Check KVStore collection created with lifecycle tracking enabled

#### Maximum Custom Inputs Limit

The add-on supports a maximum of **10 custom inputs**. If you reach this limit:
- **Error Message**: "Reached the maximum of 10 custom inputs in the add-on"
- **Solution**: Delete unused custom inputs or consolidate data collection
- **Note**: This limit ensures optimal performance and resource utilization

### Data Collection
* If data collection is not working then ensure that the internet is active (On a proxy machine, if proxy is enabled) and also ensure that the kvstore is enabled.
* Check `ta_intersight*.log*` file for Cisco Intersight Add-On for Splunk for Splunk data collection for any relevant error messages.
* For Custom Inputs specifically, check `ta_intersight_custom_input.log` for detailed error messages and API call information.

## Upgrade and Distribution

The Cisco Intersight Add-On for Splunk will be hosted and distributed via the Splunkbase platform, ensuring centralized and easy upgrades to the latest version.

## Responsibilities

   - **Splunk Team**: Responsible for the development, testing, and release of new versions.
   - **End Users**: Responsible for the manual update of the software within their Splunk environment.

## Support

For support, please refer to the official documentation or contact the support.

   - **Author**: Cisco Systems, Inc  
   - **Support Email**: splunk-intersight-app-support@cisco.com

## Limitations  

* The upcoming version of Cisco Intersight Add-On for Splunk fetches data from Cisco Intersight using Cisco Intersight RESTFul APIs. This approach may introduce minor latency as APIs will be executed at a specific interval. To overcome this limitation, data collection logic of the add-on can be planned to shift to stream based data collection. This mechanism ensures continuous streaming of data and ensures metrics are available in real time. 

## References 

* Intersight API docs - https://us-east-1.intersight.com/apidocs/introduction/overview/

* VMWare Aria Plugin - https://intersight.com/help/saas/resources/VCF_Operations_Management_Pack#about_the_vcf_operations_management_pack_for_cisco_intersight  

## License

This add-on is distributed under the terms of the [Cisco Software License Agreement](https://www.cisco.com/public/sw-license-agreement.html).


## BINARY FILE DECLARATION
* lib/charset_normalizer/md.cpython-310-x86_64-linux-gnu.so - This is a compiled binary for the charset_normalizer library. The source code can be found at [charset-normalizer GitHub](https://github.com/Ousret/charset_normalizer).

* lib/charset_normalizer/md__mypyc.cpython-310-x86_64-linux-gnu.so - This is another compiled binary for the charset_normalizer library. The source code can be found at [charset-normalizer GitHub](https://github.com/Ousret/charset_normalizer).


## UNINSTALL & CLEANUP STEPS
* Disable and Delete Configured Inputs.
* Disable and Delete Configured Accounts.
* Remove $SPLUNK_HOME/etc/apps/Splunk_TA_Cisco_Intersight
* Remove $SPLUNK_HOME/var/log/splunk/ta_intersight*.log**.
* To reflect the cleanup changes in UI, Restart Splunk Enterprise instance
