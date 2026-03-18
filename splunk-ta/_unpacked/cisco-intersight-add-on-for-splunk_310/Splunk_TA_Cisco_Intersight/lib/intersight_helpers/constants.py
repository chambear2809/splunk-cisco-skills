"""Constants file."""
# This import is required to resolve the absolute paths of supportive modules
# implemented throughout the add-on. The relative imports used in other files
# of the add-on are resolved by importing this module.
import import_declare_test  # noqa: F401  # pylint: disable=unused-import # needed to resolve paths
import re
import json
import hashlib
from datetime import datetime, timezone
PROTOCOL = "https://"
VERIFY_SSL = True
SAAS = re.compile(r"\S*\.?intersight\.com\.?$")
FQDN = re.compile(
    r"^(?!:\/\/)(?=.{1,255}$)((.{1,63}\.){1,127}(?!\d*$)[a-z\d-]+\.?)$")
PAGE_LIMIT = 1000
SOURCETYPE_COMPUTE = "cisco:intersight:compute"
SOURCETYPE_NETAPP = "cisco:intersight:netapp"
SOURCETYPE_PURE = "cisco:intersight:pure"
SOURCETYPE_PROFILE = "cisco:intersight:profiles"
SOURCETYPE_LICENCE = "cisco:intersight:licenses"
SOURCETYPE_PORTS = "cisco:intersight:networkobjects"
SOURCETYPE_POOLS = "cisco:intersight:pools"
SOURCETYPE_NETWORKELEMENTS = "cisco:intersight:networkelements"
TA_ACCOUNT_VALIDATION = "ta_intersight_account_validation"
TA_INTERVAL_VALIDATION = "ta_intersight_interval_validation"
TA_INPUT_VALIDATION = "ta_intersight_input_deletion"
TA_METRICS = "ta_intersight_metrics"
MAX_CUSTOM_INPUTS = 10
TARGET_BASED_APIS = ["asset/targets", "asset/deviceregistrations"]

SOURCE_SOURCETYPE_DICT = {
    "audit": {"source": "aaaAuditRecord", "sourcetype": "cisco:intersight:auditrecords"},
    "alarms": {"source": "condAlarm", "sourcetype": "cisco:intersight:alarms"},
    "tam/AdvisoryInstances": {"source": "tamAdvisoryInstance", "sourcetype": "cisco:intersight:advisories"},
    "tam/AdvisoryInfos": {"source": "tamAdvisoryInfo", "sourcetype": "cisco:intersight:advisories"},
    "tam/AdvisoryDefinitions": {"source": "tamAdvisoryDefinition", "sourcetype": "cisco:intersight:advisories"},
    "tam/SecurityAdvisories": {"source": "tamSecurityAdvisory", "sourcetype": "cisco:intersight:advisories"},
    "contract": {"source": "assetDeviceContractInformation", "sourcetype": "cisco:intersight:contracts"},
    "network": {"source": "inventoryObjects", "sourcetype": SOURCETYPE_NETWORKELEMENTS},
    "target": {"source": "assetTarget", "sourcetype": "cisco:intersight:targets"},
    "search/SearchItems": {"source": "inventoryObjects", "sourcetype": SOURCETYPE_COMPUTE},
    "cond/HclStatuses": {"source": "condHclStatus", "sourcetype": SOURCETYPE_COMPUTE},
    "equipment/Chasses": {"source": "inventoryObjects", "sourcetype": SOURCETYPE_COMPUTE},
    "server/Profiles": {"source": "serverProfile", "sourcetype": SOURCETYPE_PROFILE},
    "chassis/Profiles": {"source": "chassisProfile", "sourcetype": SOURCETYPE_PROFILE},
    "fabric/SwitchProfiles": {"source": "fabricSwitchProfile", "sourcetype": SOURCETYPE_PROFILE},
    "fabric/SwitchClusterProfiles": {"source": "fabricSwitchClusterProfile", "sourcetype": SOURCETYPE_PROFILE},
    "license/AccountLicenseData": {"source": "licenseAccountLicenseData", "sourcetype": SOURCETYPE_LICENCE},
    "license/LicenseInfos": {"source": "licenseLicenseInfo", "sourcetype": SOURCETYPE_LICENCE},
    "storage/NetAppClusters": {"source": "storageNetAppClusters", "sourcetype": SOURCETYPE_NETAPP},
    "storage/NetAppNodes": {"source": "storageNetAppNodes", "sourcetype": SOURCETYPE_NETAPP},
    "storage/NetAppVolumes": {"source": "storageNetAppVolumes", "sourcetype": SOURCETYPE_NETAPP},
    "storage/NetAppStorageVms": {"source": "storageNetAppStorageVms", "sourcetype": SOURCETYPE_NETAPP},
    "convergedinfra/Pods": {"source": "convergedinfraPods", "sourcetype": SOURCETYPE_NETAPP},
    "storage/PureArrays": {"source": "storagePureArrays", "sourcetype": SOURCETYPE_PURE},
    "storage/PureControllers": {"source": "storagePureControllers", "sourcetype": SOURCETYPE_PURE},
    "storage/PureVolumes": {"source": "storagePureVolumes", "sourcetype": SOURCETYPE_PURE},
    "storage/HitachiArrays": {"source": "storageHitachiArrays", "sourcetype": SOURCETYPE_PURE},
    "storage/HitachiControllers": {"source": "storageHitachiControllers", "sourcetype": SOURCETYPE_PURE},
    "storage/HitachiVolumes": {"source": "storageHitachiVolumes", "sourcetype": SOURCETYPE_PURE},
    "ether/HostPorts": {"source": "etherHostPort", "sourcetype": SOURCETYPE_PORTS},
    "ether/NetworkPorts": {"source": "etherNetworkPort", "sourcetype": SOURCETYPE_PORTS},
    "ether/PhysicalPorts": {"source": "etherPhysicalPort", "sourcetype": SOURCETYPE_PORTS},
    "ether/PortChannels": {"source": "etherPortChannel", "sourcetype": SOURCETYPE_PORTS},
    "adapter/HostFcInterfaces": {"source": "adapterHostFcInterface", "sourcetype": SOURCETYPE_PORTS},
    "fc/PhysicalPorts": {"source": "fcPhysicalPort", "sourcetype": SOURCETYPE_PORTS},
    "network/Vfcs": {"source": "networkVfc", "sourcetype": SOURCETYPE_PORTS},
    "network/Vethernets": {"source": "networkVethernet", "sourcetype": SOURCETYPE_PORTS},
    "fc/PortChannels": {"source": "fcPortChannel", "sourcetype": SOURCETYPE_PORTS},
    "adapter/HostEthInterfaces": {"source": "adapterHostEthInterface", "sourcetype": SOURCETYPE_PORTS},
    "fcpool/Pools": {"source": "fcpoolPools", "sourcetype": SOURCETYPE_POOLS},
    "ippool/Pools": {"source": "ippoolPools", "sourcetype": SOURCETYPE_POOLS},
    "iqnpool/Pools": {"source": "iqnpoolPools", "sourcetype": SOURCETYPE_POOLS},
    "macpool/Pools": {"source": "macpoolPools", "sourcetype": SOURCETYPE_POOLS},
    "uuidpool/Pools": {"source": "uuidpoolPools", "sourcetype": SOURCETYPE_POOLS},
    "resourcepool/Pools": {"source": "resourcepoolPools", "sourcetype": SOURCETYPE_POOLS},
}

INV_NETWORK_ENDPOINTS_MAPPING = {
    "ether.HostPort": "ether/HostPorts",
    "ether.NetworkPort": "ether/NetworkPorts",
    "ether.PhysicalPort": "ether/PhysicalPorts",
    "ether.PortChannel": "ether/PortChannels",
    "adapter.HostFcInterface": "adapter/HostFcInterfaces",
    "fc.PhysicalPort": "fc/PhysicalPorts",
    "network.Vfc": "network/Vfcs",
    "network.Vethernet": "network/Vethernets",
    "fc.PortChannel": "fc/PortChannels",
    "adapter.HostEthInterface": "adapter/HostEthInterfaces",
}

INV_POOL_ENDPOINTS_MAPPING = {
    "fcpool.Pool": "fcpool/Pools",
    "ippool.Pool": "ippool/Pools",
    "iqnpool.Pool": "iqnpool/Pools",
    "macpool.Pool": "macpool/Pools",
    "uuidpool.Pool": "uuidpool/Pools",
    "resourcepool.Pool": "resourcepool/Pools"
}


class Endpoints:
    """Intersight Endpoints."""

    INTERSIGHT_SERVER_ADDRESS = '/api/v1/'
    SAAS_ACCOUNT_ENDPOINT = "iam/Accounts?$select=Name,Moid"
    CLIENT_ID_METADATA_ENDPOINT = "iam/AppRegistrations?$select=ExpiryDateTime,IsNeverExpiring,ClientId"
    FQDN_ACCOUNT_ENDPOINT = "iam/UserPreferences"
    AUDIT_RECORDS = "aaa/AuditRecords"
    ALARM_RECORDS = "cond/Alarms"
    ADVISORIES = "tam/AdvisoryInstances"
    ADVISORIES_INFOS = "tam/AdvisoryInfos"
    ADVISORIES_DEFINITIONS = "tam/AdvisoryDefinitions"
    SECURITY_ADVISORIES = "tam/SecurityAdvisories"
    CONTRACT = "asset/DeviceContractInformations"
    NETWORK = "network/ElementSummaries"
    TARGET = "asset/Targets"
    NETAPP = "storage/NetAppClusters"
    METRICS = "telemetry/TimeSeries"
    SEARCH_ITEMS = "search/SearchItems"
    SERVICES_NS = "/servicesNS/nobody/"
    CHASSES = "equipment/Chasses"
    HOST_PORTS = "ether/HostPorts"
    NETWORK_PORTS = "ether/NetworkPorts"
    PHYSICAL_PORTS = "ether/PhysicalPorts"
    PORT_CHANNELS = "ether/PortChannels"
    ADAPTER_HOSTFCINTERFACE = "adapter/HostFcInterfaces"
    FC_PHYSICALPORTS = "fc/PhysicalPorts"
    NETWORK_VFCS = "network/Vfcs"
    NETWORK_VETHERNETS = "network/Vethernets"
    FC_PORTCHANNELS = "fc/PortChannels"
    ADAPTER_HOSTETHINTERFACE = "adapter/HostEthInterfaces"
    ADAPTER_EXTETHINTERFACE = "adapter/ExtEthInterfaces"
    DEVICE_REGISTRATION = "asset/DeviceRegistrations"
    HCL_STATUSES = "cond/HclStatuses"
    LICENSE_INFOS = "license/LicenseInfos"
    ACCOUNT_LICENSE_DATA = "license/AccountLicenseData"
    INVENTORY_NETWORK_PARAMS = "RegisteredDevice($select=ClaimedByUserName,ClaimedTime,"\
        "ConnectionStatusLastChangeTime,ConnectionStatus,CreateTime,ReadOnly,Moid,DeviceHostname,ConnectionStatus)"
    COMPUTE_PHYSICALSUMMARIES_PARAMS = "RegisteredDevice($select=ClaimedByUserName,ClaimedTime,"\
        "ConnectionStatusLastChangeTime,ConnectionStatus,CreateTime,ReadOnly)"
    EQUIPMENT_CHASSES_PARAMS = "Siocs($select=ConnectionPath,ConnectionStatus,Dn,Model,OperState,"\
        "Serial,SystemIoControllerId),Ioms($select=ConnectionPath,ConnectionStatus,Dn,Model,ModuleId,"\
        "OperReason,OperState,Serial,Side,Version,Vid),FanControl($select=Mode),Fanmodules($select=Model,"\
        "OperState,OperReason),PsuControl($select=Redundancy),Psus($select=Model,OperReason,OperState,PsuId,"\
        "PsuInputSrc,PsuWattage,Voltage),ExpanderModules($select=Dn,Model,ModuleId,OperReason,OperState,Serial),"\
        "PowerControlState($select=ExtendedPowerCapacity,AllocatedPower,GridMaxPower,MaxRequiredPower,"\
        "MinRequiredPower,N1MaxPower,N2MaxPower,NonRedundantMaxPower,PowerRebalancing, "\
        "PowerSaveMode),RegisteredDevice($select=Moid,DeviceHostname,ConnectionStatus)"
    NETAPP_CLUSTERS_PARAMS = "RegisteredDevice($select=ClaimedByUserName,ClaimedTime,ConnectionStatusLastChangeTime,"\
        "ConnectionStatus,CreateTime,ReadOnly)"
    PUREARRAYS_PARAMS = "RegisteredDevice($select=ClaimedByUserName,ClaimedTime,ConnectionStatusLastChangeTime,"\
        "ConnectionStatus,CreateTime,ReadOnly)"
    PURE_CONTROLLERS_PARAMS = "RegisteredDevice($select=ClaimedByUserName,ClaimedTime,ConnectionStatusLastChangeTime,"\
        "ConnectionStatus,CreateTime,ReadOnly)"
    HITACHI_ARRAYS_PARAMS = "RegisteredDevice($select=ClaimedByUserName,ClaimedTime,ConnectionStatusLastChangeTime,"\
        "ConnectionStatus,CreateTime,ReadOnly)"
    SEARCH_ITEMS_PARM = "RegisteredDevice($select=Moid,DeviceHostname,ConnectionStatus)"
    TARGET_PARAMS = "RegisteredDevice($select=ConnectionStatus,Moid)"
    CONTRACT_PARAM = "RegisteredDevice($select=Moid,DeviceHostname)"
    HCLSTATUSES_PARAM = "ManagedObject($select=Name,Tags,PlatformType,Dn)"
    SERVER_PROFILES_PARAMS = "AssignedServer($select=Name),PolicyBucket($select=Name,Moid,ObjectType,InbandIpPool,"\
        "OutOfBandIpPool,IqnPool,WwnnPool,WwpnPool,MacPool)"
    SEARCH_ITEMS_FILTER = (
        "ClassId in (compute.PhysicalSummary, equipment.Transceiver, equipment.IoCard, equipment.ExpanderModule, "
        "equipment.FanControl, equipment.RackEnclosure, equipment.PsuControl, equipment.Fru, equipment.FanModule, "
        "equipment.RackEnclosureSlot, equipment.ChassisIdentity, equipment.SwitchCard, equipment.Psu,  "
        "equipment.LocatorLed, equipment.Tpm, equipment.Fan, memory.Unit, storage.PhysicalDisk, graphics.Card, "
        "processor.Unit, vnic.VnicTemplate, storage.Item, storage.VirtualDrive, network.Element, "
        "network.SupervisorCard, compute.BladeIdentity, compute.RackUnitIdentity, fabric.ElementIdentity)"
    )
    SUPPORTED_PLATFORMTYPES = ('UCSFIISM', 'IMCM5', 'IMCRack', 'IMCBlade', 'UCSXECMC')
    SUPPORTED_MODES = ('Intersight', 'IntersightStandalone')
    SUPPORTED_SERVER_OBJECT_TYPES = ["compute.RackUnit", "compute.Blade"]
    HCLSTATUSES_MOID_FILTER = f"ManagementMode in {SUPPORTED_MODES}"
    TARGET_FILTER = f"TargetType in {SUPPORTED_PLATFORMTYPES}"
    SUPPORTED_LICENSE_TIERS = ["Advantage", "Essential"]
    IMM_MODE = "ManagementMode eq 'Intersight'"
    PLATFORM_FILTER = f"PlatformType in {SUPPORTED_PLATFORMTYPES}"
    FCPOOL = "fcpool/Pools"
    IPPOOL = "ippool/Pools"
    IQNPOOL = "iqnpool/Pools"
    MACPOOL = "macpool/Pools"
    UUIDPOOL = "uuidpool/Pools"
    RESOURCEPOOL = "resourcepool/Pools"
    TRANSCEIVERS = "equipment/Transceivers"


class SplunkEndpoints:
    """Splunk Endpoints."""

    SPLUNK_NOTIFICATION_ENDPOINT = "/services/messages"


class Rest:
    """Intersight Rest Constants."""

    STATUS_FORCELIST = list(range(500, 600)) + [429, ]
    REQUEST_TIMEOUT = 60
    CLIENT_ID_EXPIRATION_THRESHOLD = 14
    INTERSIGHT_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class ConfFilename:
    """Splunk_TA_Cisco_Intersight config file names."""

    ACCOUNT_CONF = "splunk_ta_cisco_intersight_account"


class RequiredTime:
    """Calculate required time for data collection."""

    current_time = datetime.now(timezone.utc)
    formatted_current_time = current_time.strftime('%Y-%m-%dT%H:%M:%S.') + f'{current_time.microsecond // 1000:03d}Z'
    current_time = formatted_current_time


class CollectionConstants:
    """List of Constant for KV Store Collections."""

    KEY = "_key"
    ACCOUNT_NAME = "account_name"
    DOMAINS = "Cisco_Intersight_domains"
    FAN = "Cisco_Intersight_fan"
    FAN_MODULE = "Cisco_Intersight_fanmodule"
    CHASSIS = "Cisco_Intersight_chassis"
    NETWORK_ELEMENTS = "Cisco_Intersight_networkelements"
    PHYSICAL_SUMMARY = "Cisco_Intersight_physicalsummary"
    MEMORY_UNIT = "Cisco_Intersight_memoryunit"
    PROCESSOR_UNIT = "Cisco_Intersight_processorunit"
    TRANSCEIVER = "Cisco_Intersight_transceiver"
    GRAPHICSCARD = "Cisco_Intersight_graphicscard"
    COMPUTE_BOARD = "Cisco_Intersight_computeboard"
    ETHER_HOST_PORTS = "Cisco_Intersight_etherhostports"
    ETHER_NETWORK_PORTS = "Cisco_Intersight_ethernetworkports"
    ETHER_PHYSICAL_PORTS = "Cisco_Intersight_etherphysicalports"
    ETHER_PORT_CHANNELS = "Cisco_Intersight_etherportchannels"
    ADAPTER_HOST_FC_INTERFACES = "Cisco_Intersight_adapterhostfcinterfaces"
    FC_PHYSICAL_PORTS = "Cisco_Intersight_fcphysicalports"
    NETWORK_VFCS = "Cisco_Intersight_networkvfcs"
    NETWORK_VETHERNETS = "Cisco_Intersight_networkvethernets"
    FC_PORT_CHANNELS = "Cisco_Intersight_fcportchannels"
    ADAPTER_HOST_ETH_INTERFACES = "Cisco_Intersight_adapterhostethinterfaces"
    ADAPTER_EXT_ETH_INTERFACES = "Cisco_Intersight_adapterextethinterfaces"
    COND_ALARMS = "Cisco_Intersight_cond_alarms"
    CUSTOM_INPUT_MAPPINGS = "cisco_intersight_custom_input_mappings"
    DOMAINID = "DomainId"
    HOSTID = "HostId"

    # ObjectType to collection and API endpoints mapping.
    INVENTORY_MAPPINGS = {
        "asset.devicecontractinformation": {
            "collection": "cisco_intersight_asset_devicecontractinformations",
            "api_endpoint": "asset/DeviceContractInformations"
        },
        "assetdevicecontractinformation": {
            "collection": "cisco_intersight_asset_devicecontractinformations",
            "api_endpoint": "asset/DeviceContractInformations"
        },
        "asset.target": {
            "collection": "cisco_intersight_asset_targets", "api_endpoint": "asset/Targets"
        },
        "assettarget": {
            "collection": "cisco_intersight_asset_targets", "api_endpoint": "asset/Targets"
        },
        "chassis.profile": {
            "collection": "cisco_intersight_chassis_profiles", "api_endpoint": "chassis/Profiles"
        },
        "compute.bladeidentity": {
            "collection": "cisco_intersight_compute_bladeidentities", "api_endpoint": "compute/BladeIdentities"
        },
        "compute.rackunitidentity": {
            "collection": "cisco_intersight_compute_rackunitidentities", "api_endpoint": "compute/RackUnitIdentities"
        },
        "fabric.elementidentity": {
            "collection": "cisco_intersight_fabric_elementidentities", "api_endpoint": "fabric/ElementIdentities"
        },
        "compute.physicalsummary": {
            "collection": "cisco_intersight_compute_physicalsummaries", "api_endpoint": "compute/PhysicalSummaries"
        },
        "cond.hclstatus": {
            "collection": "cisco_intersight_cond_hclstatuses", "api_endpoint": "cond/HclStatuses"
        },
        "equipment.chassis": {
            "collection": "cisco_intersight_equipment_chasses", "api_endpoint": "equipment/Chasses"
        },
        "equipmentchasses": {
            "collection": "cisco_intersight_equipment_chasses", "api_endpoint": "equipment/Chasses"
        },
        "equipment.chassisidentity": {
            "collection": "cisco_intersight_equipment_chassisidentities", "api_endpoint": "equipment/ChassisIdentities"
        },
        "equipment.expandermodule": {
            "collection": "cisco_intersight_equipment_expandermodules", "api_endpoint": "equipment/ExpanderModules"
        },
        "equipment.fan": {
            "collection": "cisco_intersight_equipment_fans", "api_endpoint": "equipment/Fans"
        },
        "equipment.fancontrol": {
            "collection": "cisco_intersight_equipment_fancontrols", "api_endpoint": "equipment/FanControls"
        },
        "equipment.fanmodule": {
            "collection": "cisco_intersight_equipment_fanmodules", "api_endpoint": "equipment/FanModules"
        },
        "equipment.fru": {
            "collection": "cisco_intersight_equipment_frus", "api_endpoint": "equipment/Frus"
        },
        "equipment.iocard": {
            "collection": "cisco_intersight_equipment_iocards", "api_endpoint": "equipment/IoCards"
        },
        "equipment.locatorled": {
            "collection": "cisco_intersight_equipment_locatorleds", "api_endpoint": "equipment/LocatorLeds"
        },
        "equipment.psu": {
            "collection": "cisco_intersight_equipment_psus", "api_endpoint": "equipment/Psus"
        },
        "equipment.psucontrol": {
            "collection": "cisco_intersight_equipment_psucontrols", "api_endpoint": "equipment/PsuControls"
        },
        "equipment.rackenclosure": {
            "collection": "cisco_intersight_equipment_rackenclosures", "api_endpoint": "equipment/RackEnclosures"
        },
        "equipment.rackenclosureslot": {
            "collection": "cisco_intersight_equipment_rackenclosureslots",
            "api_endpoint": "equipment/RackEnclosureSlots"
        },
        "equipment.switchcard": {
            "collection": "cisco_intersight_equipment_switchcards", "api_endpoint": "equipment/SwitchCards"
        },
        "equipment.tpm": {
            "collection": "cisco_intersight_equipment_tpms", "api_endpoint": "equipment/Tpms"
        },
        "equipment.transceiver": {
            "collection": "cisco_intersight_equipment_transceivers", "api_endpoint": "equipment/Transceivers"
        },
        "fabric.switchclusterprofile": {
            "collection": "cisco_intersight_fabric_switchclusterprofiles",
            "api_endpoint": "fabric/SwitchClusterProfiles"
        },
        "fabric.switchprofile": {
            "collection": "cisco_intersight_fabric_switchprofiles", "api_endpoint": "fabric/SwitchProfiles"
        },
        "graphics.card": {
            "collection": "cisco_intersight_graphics_cards", "api_endpoint": "graphics/Cards"
        },
        "license.accountlicensedata": {
            "collection": "cisco_intersight_license_accountlicensedata", "api_endpoint": "license/AccountLicenseData"
        },
        "license.licenseinfo": {
            "collection": "cisco_intersight_license_licenseinfos", "api_endpoint": "license/LicenseInfos"
        },
        "memory.unit": {
            "collection": "cisco_intersight_memory_units", "api_endpoint": "memory/Units"
        },
        "network.element": {
            "collection": "cisco_intersight_network_elements", "api_endpoint": "network/Elements"
        },
        "network.elementsummary": {
            "collection": "cisco_intersight_network_elements", "api_endpoint": "network/ElementSummaries"
        },
        "network.supervisorcard": {
            "collection": "cisco_intersight_network_supervisorcards", "api_endpoint": "network/SupervisorCards"
        },
        "processor.unit": {
            "collection": "cisco_intersight_processor_units", "api_endpoint": "processor/Units"
        },
        "server.profile": {
            "collection": "cisco_intersight_server_profiles", "api_endpoint": "server/Profiles"
        },
        "storage.item": {
            "collection": "cisco_intersight_storage_items", "api_endpoint": "storage/Items"
        },
        "storage.physicaldisk": {
            "collection": "cisco_intersight_storage_physicaldisks", "api_endpoint": "storage/PhysicalDisks"
        },
        "storage.virtualdrive": {
            "collection": "cisco_intersight_storage_virtualdrives", "api_endpoint": "storage/VirtualDrives"
        },
        "tam.advisoryinfo": {
            "collection": "cisco_intersight_tam_advisoryinfos", "api_endpoint": "tam/AdvisoryInfos"
        },
        "tam.advisoryinstance": {
            "collection": "cisco_intersight_tam_advisoryinstances", "api_endpoint": "tam/AdvisoryInstances"
        },
        "tamadvisoryinstance": {
            "collection": "cisco_intersight_tam_advisoryinstances", "api_endpoint": "tam/AdvisoryInstances"
        },
        "tam.advisorydefinition": {
            "collection": "cisco_intersight_tam_advisorydefinitions", "api_endpoint": "tam/AdvisoryDefinitions"
        },
        "tam.securityadvisory": {
            "collection": "cisco_intersight_tam_securityadvisories", "api_endpoint": "tam/SecurityAdvisories"
        },
        "vnic.vnictemplate": {
            "collection": "cisco_intersight_vnic_vnictemplates", "api_endpoint": "vnic/VnicTemplates"
        },
        "ether.hostport": {
            "collection": "cisco_intersight_ether_hostports", "api_endpoint": "ether/HostPorts"
        },
        "ether.networkport": {
            "collection": "cisco_intersight_ether_networkports", "api_endpoint": "ether/NetworkPorts"
        },
        "ether.physicalport": {
            "collection": "cisco_intersight_ether_physicalports", "api_endpoint": "ether/PhysicalPorts"
        },
        "ether.portchannel": {
            "collection": "cisco_intersight_ether_portchannels", "api_endpoint": "ether/PortChannels"
        },
        "adapter.hostfcinterface": {
            "collection": "cisco_intersight_adapter_hostfcinterfaces", "api_endpoint": "adapter/HostFcInterfaces"
        },
        "fc.physicalport": {
            "collection": "cisco_intersight_fc_physicalports", "api_endpoint": "fc/PhysicalPorts"
        },
        "network.vfc": {
            "collection": "cisco_intersight_network_vfcs", "api_endpoint": "network/Vfcs"
        },
        "network.vethernet": {
            "collection": "cisco_intersight_network_vethernets", "api_endpoint": "network/Vethernets"
        },
        "fc.portchannel": {
            "collection": "cisco_intersight_fc_portchannels", "api_endpoint": "fc/PortChannels"
        },
        "adapter.hostethinterface": {
            "collection": "cisco_intersight_adapter_hostethinterfaces", "api_endpoint": "adapter/HostEthInterfaces"
        },
        "fcpool.pool": {
            "collection": "cisco_intersight_fcpool_pools", "api_endpoint": "fcpool/Pools"
        },
        "ippool.pool": {
            "collection": "cisco_intersight_ippool_pools", "api_endpoint": "ippool/Pools"
        },
        "iqnpool.pool": {
            "collection": "cisco_intersight_iqnpool_pools", "api_endpoint": "iqnpool/Pools"
        },
        "macpool.pool": {
            "collection": "cisco_intersight_macpool_pools", "api_endpoint": "macpool/Pools"
        },
        "uuidpool.pool": {
            "collection": "cisco_intersight_uuidpool_pools", "api_endpoint": "uuidpool/Pools"
        },
        "resourcepool.pool": {
            "collection": "cisco_intersight_resourcepool_pools", "api_endpoint": "resourcepool/Pools"
        }
    }


def dict_to_sha(dictionary: dict) -> str:
    """
    Convert a dictionary to a SHA-256 hash string.

    :param dictionary: The dictionary to convert to a SHA-256 hash string
    :type dictionary: dict
    :return: The hexadecimal representation of the SHA-256 hash of the dictionary
    :rtype: str
    """
    dict_str = json.dumps(dictionary, sort_keys=True)
    sha256_hash = hashlib.sha256()  # Create a new SHA-256 hash object
    sha256_hash.update(dict_str.encode('utf-8'))  # Update the hash object with the bytes of the string
    sha256_hex = sha256_hash.hexdigest()  # Get the hexadecimal representation of the hash
    return sha256_hex


class InventoryApis:
    """Inventory data collection Constants."""

    target_wise_inventory = [
        Endpoints.ADVISORIES, Endpoints.HCL_STATUSES, Endpoints.CHASSES,
        Endpoints.SEARCH_ITEMS, Endpoints.CONTRACT, Endpoints.NETWORK, Endpoints.HOST_PORTS,
        Endpoints.NETWORK_PORTS, Endpoints.PHYSICAL_PORTS, Endpoints.PORT_CHANNELS,
        Endpoints.ADAPTER_HOSTFCINTERFACE, Endpoints.FC_PHYSICALPORTS, Endpoints.NETWORK_VFCS,
        Endpoints.NETWORK_VETHERNETS, Endpoints.FC_PORTCHANNELS, Endpoints.ADAPTER_HOSTETHINTERFACE
    ]
    EXPAND_PARM = "$expand"
    FILTER = "$filter"
    inventory_config = {
        "contract": {
            "endpoint": Endpoints.CONTRACT,
            "params": {
                EXPAND_PARM: Endpoints.CONTRACT_PARAM, FILTER: Endpoints.PLATFORM_FILTER,
            },
            "ingest_func": "ingest_contract", "log_name": "Contract",
        },
        "network": {
            "endpoint": Endpoints.NETWORK,
            "params": {
                EXPAND_PARM: Endpoints.INVENTORY_NETWORK_PARAMS, FILTER: Endpoints.IMM_MODE,
            },
            "ingest_func": "ingest_network", "log_name": "Network",
        },
        "target": {
            "endpoint": Endpoints.TARGET,
            "params": {
                EXPAND_PARM: Endpoints.TARGET_PARAMS, FILTER: Endpoints.TARGET_FILTER,
            },
            "ingest_func": "ingest_target", "log_name": "Target",
        },
    }

    multi_api_inventory_config = {
        "advisories": {
            Endpoints.ADVISORIES: {
                "params": {EXPAND_PARM: "AffectedObject($select=Name,PlatformType,ManagementMode,Tags)"},
                "ingest_func": "ingest_advisories", "log_name": "Advisories",
            },
            Endpoints.ADVISORIES_INFOS: {
                "params": {EXPAND_PARM: ""},
                "ingest_func": "ingest_advisories_infos", "log_name": "AdvisoryInfos",
            },
            Endpoints.ADVISORIES_DEFINITIONS: {
                "params": {EXPAND_PARM: ""},
                "ingest_func": "ingest_advisories_defintions", "log_name": "AdvisoryDefinitions",
            },
            Endpoints.SECURITY_ADVISORIES: {
                "params": {EXPAND_PARM: ""},
                "ingest_func": "ingest_security_advisories", "log_name": "SecurityAdvisories",
            }
        },
        "compute": {
            "search/SearchItems": {
                "params": {
                    EXPAND_PARM: Endpoints.SEARCH_ITEMS_PARM,
                    FILTER: Endpoints.SEARCH_ITEMS_FILTER,
                },
                "ingest_func": "ingest_inventory_objects",
                "log_name": "InventoryObjects",
            },
            "equipment/Chasses": {
                "params": {
                    EXPAND_PARM: Endpoints.EQUIPMENT_CHASSES_PARAMS,
                    FILTER: Endpoints.IMM_MODE,
                },
                "ingest_func": "ingest_equipment_chasses",
                "log_name": "EquipmentChasses",
            },
            "server/Profiles": {
                "params": {
                    EXPAND_PARM: Endpoints.SERVER_PROFILES_PARAMS
                },
                "ingest_func": "ingest_server_profiles",
                "log_name": "ServerProfiles",
            },
            "chassis/Profiles": {
                "params": {},
                "ingest_func": "ingest_chassis_profiles",
                "log_name": "ChassisProfiles",
            },
            "cond/HclStatuses": {
                "endpoint": Endpoints.HCL_STATUSES,
                "params": {
                    EXPAND_PARM: Endpoints.HCLSTATUSES_PARAM,
                    FILTER: Endpoints.HCLSTATUSES_MOID_FILTER
                },
                "ingest_func": "ingest_compute_hclstatus",
                "log_name": "HCLStatuses"
            }
        },
        "fabric": {
            "fabric/SwitchProfiles": {
                "params": {},
                "ingest_func": "ingest_fabric_switchprofiles",
                "log_name": "FabricSwitchProfiles",
            },
            "fabric/SwitchClusterProfiles": {
                "params": {},
                "ingest_func": "ingest_fabric_switchclusterprofiles",
                "log_name": "FabricSwitchClusterProfiles",
            },
        },
        "license": {
            "license/AccountLicenseData": {
                "params": {},
                "ingest_func": "ingest_account_license_data",
                "log_name": "AccountLicenseData",
            },
            "license/LicenseInfos": {
                "params": {},
                "ingest_func": "ingest_license_infos",
                "log_name": "LicenseInfos",
            },
        },
        "ports": {
            Endpoints.HOST_PORTS: {
                "params": {
                    EXPAND_PARM: "Parent($select=ObjectType,Description,Model,Serial,Version),"
                    "AcknowledgedPeerInterface($select=PortId,SlotId,PortChannelId,SwitchId)",
                },
                "ingest_func": "ingest_inv_network_objects",
                "log_name": "Ethernet Host Ports",
            },
            Endpoints.NETWORK_PORTS: {
                "params": {
                    EXPAND_PARM: "Parent($select=ObjectType,Description,Model,Serial,Version),"
                    "AcknowledgedPeerInterface($select=PortId,SlotId,PortChannelId,SwitchId)",
                },
                "ingest_func": "ingest_inv_network_objects",
                "log_name": "Ethernet Network Ports",
            },
            Endpoints.PHYSICAL_PORTS: {
                "params": {
                    EXPAND_PARM: "Parent($select=Dn,ObjectType),AcknowledgedPeerInterface($select"
                    "=PortId,SlotId,PortChannelId,SwitchId)",
                },
                "ingest_func": "ingest_inv_network_objects",
                "log_name": "Ethernet Physical Ports",
            },
            Endpoints.PORT_CHANNELS: {
                "params": {
                    EXPAND_PARM: "Parent($select=ObjectType,Description,Dn,Model,Name,NumPorts,Status)",
                },
                "ingest_func": "ingest_inv_network_objects",
                "log_name": "Ethernet Port Channels",
            },
            Endpoints.ADAPTER_HOSTFCINTERFACE: {
                "params": {
                    EXPAND_PARM: "Parent($select=ObjectType,Model,OperState,Dn)",
                },
                "ingest_func": "ingest_inv_network_objects",
                "log_name": "Host FC Interfaces",
            },
            Endpoints.FC_PHYSICALPORTS: {
                "params": {
                    EXPAND_PARM: "Parent($select=Dn,ObjectType)",
                },
                "ingest_func": "ingest_inv_network_objects",
                "log_name": "FC Physical Ports",
            },
            Endpoints.NETWORK_VFCS: {
                "params": {},
                "ingest_func": "ingest_inv_network_objects",
                "log_name": "Virtual Fibre Channels",
            },
            Endpoints.NETWORK_VETHERNETS: {
                "params": {},
                "ingest_func": "ingest_inv_network_objects",
                "log_name": "Virtual Ethernet Interfaces",
            },
            Endpoints.FC_PORTCHANNELS: {
                "params": {
                    EXPAND_PARM: "Parent($select=ObjectType,Description,Dn,Model,Name,NumPorts,Status)",
                },
                "ingest_func": "ingest_inv_network_objects",
                "log_name": "FC Port Channels",
            },
            Endpoints.ADAPTER_HOSTETHINTERFACE: {
                "params": {
                    EXPAND_PARM: "AdapterUnit($expand=ExtEthIfs($expand=AcknowledgedPeerInterface"
                    "($select=PortId,SlotId,PortChannelId,SwitchId,Parent))),Vethernet($expand="
                    "PinnedInterface($select=PortId,SlotId),BoundInterface($select=PortId,"
                    "SlotId,PortChannelId),NetworkElement($select=SwitchId))",
                },
                "ingest_func": "ingest_inv_network_objects",
                "log_name": "Host Ethernet Interfaces",
            },
        },
        "pools": {
            Endpoints.FCPOOL: {
                "params": {EXPAND_PARM: "Organization($select=Name)"},
                "ingest_func": "ingest_inv_pools",
                "log_name": "FC Pool",
            },
            Endpoints.IPPOOL: {
                "params": {EXPAND_PARM: "Organization($select=Name)"},
                "ingest_func": "ingest_inv_pools",
                "log_name": "IP Pool",
            },
            Endpoints.IQNPOOL: {
                "params": {EXPAND_PARM: "Organization($select=Name)"},
                "ingest_func": "ingest_inv_pools",
                "log_name": "IQN Pool",
            },
            Endpoints.MACPOOL: {
                "params": {EXPAND_PARM: "Organization($select=Name)"},
                "ingest_func": "ingest_inv_pools",
                "log_name": "MAC Pool",
            },
            Endpoints.UUIDPOOL: {
                "params": {EXPAND_PARM: "Organization($select=Name)"},
                "ingest_func": "ingest_inv_pools",
                "log_name": "UUID Pool",
            },
            Endpoints.RESOURCEPOOL: {
                "params": {EXPAND_PARM: "Organization($select=Name)"},
                "ingest_func": "ingest_inv_pools",
                "log_name": "Resource Pool",
            }
        }
    }


class MetricsDimensions:
    """Metrics data collection Constants."""

    metrics_checkpoints = {
        "domains": ["domains"],
        "common": ["networkelements", "chassis", "physicalsummary"],
        "fan": ["fanmodule", "fan"],
        "memory": ["memoryunit"],
        "temperature": ["processorunit", "computeboard", "transceiver", "graphicscard"],
        "network": [
            "ethernetworkports", "etherportchannels",
            "adapterhostfcinterfaces", "networkvfcs", "networkvethernets",
            "fcportchannels", "adapterhostethinterfaces", "adapterextethinterfaces"
        ],
        "network_temprature": [
            "etherhostports", "etherphysicalports", "fcphysicalports"
        ]
    }

    inventory_checkpoint_key_24h_apis = {
        "fanmodule": {
            "endpoint": Endpoints.SEARCH_ITEMS,
            "params": {
                "$filter": "ObjectType eq 'equipment.FanModule'",
                "$select": "Moid,Parent,RegisteredDevice,Owners,AccountMoid,Ancestors",
                "$top": PAGE_LIMIT,
                "$inlinecount": "allpages"
            }
        },
        "fan": {
            "endpoint": Endpoints.SEARCH_ITEMS,
            "params": {
                "$filter": "ObjectType eq 'equipment.Fan'",
                "$select": (
                    "AccountMoid,Moid,OperState,Vendor,Ancestors,Parent,Owners,FanId,FanModuleId,Dn"
                ),
                "$top": PAGE_LIMIT,
                "$inlinecount": "allpages"
            }
        }
    }

    inventory_checkpoint_key_1h_apis = {
        "domains": {
            "endpoint": Endpoints.DEVICE_REGISTRATION,
            "params": {
                "$filter": "PlatformType in ('UCSFIISM', 'UCSXECMC') AND Target ne null",
                "$select": "Moid,DeviceHostname,Owners",
                "$top": PAGE_LIMIT,
                "$inlinecount": "allpages"
            }
        },
        "networkelements": {
            "endpoint": Endpoints.SEARCH_ITEMS,
            "params": {
                "$filter": "ObjectType eq 'network.ElementSummary'",
                "$select": (
                    "AccountMoid,Moid,Name,Tags,SourceObjectType,Model,RegisteredDevice,Serial,"
                    "Vendor,ChassisId,Owners"
                ),
                "$top": PAGE_LIMIT,
                "$inlinecount": "allpages"
            }
        },
        "chassis": {
            "endpoint": Endpoints.SEARCH_ITEMS,
            "params": {
                "$filter": "ObjectType eq 'equipment.Chassis'",
                "$select": "AccountMoid,Moid,Name,Tags,Model,RegisteredDevice,Serial,Vendor,ChassisId,Owners",
                "$top": PAGE_LIMIT,
                "$inlinecount": "allpages"
            }
        },
        "physicalsummary": {
            "endpoint": Endpoints.SEARCH_ITEMS,
            "params": {
                "$filter": "ObjectType eq 'compute.PhysicalSummary'",
                "$select": "AccountMoid,Moid,Name,Tags,SourceObjectType,Model,Parent,RegisteredDevice,"
                "Serial,Vendor,ChassisId,Owners,EquipmentChassis.Moid",
                "$top": PAGE_LIMIT,
                "$inlinecount": "allpages"
            }
        },
        "memoryunit": {
            "endpoint": Endpoints.SEARCH_ITEMS,
            "params": {
                "$filter": "ObjectType eq 'memory.Unit' AND Ancestors.ObjectType"
                " in ('compute.Blade','compute.RackUnit')",
                "$select": "AccountMoid,SourceObjectType,Ancestors,Moid,OperState,"
                "Location,RegisteredDevice,Owners",
                "$top": PAGE_LIMIT,
                "$inlinecount": "allpages"
            }
        },
        "computeboard": {
            "endpoint": Endpoints.SEARCH_ITEMS,
            "params": {
                "$filter": "ObjectType eq 'compute.Board' AND Ancestors.ObjectType"
                " in ('compute.Blade','compute.RackUnit')",
                "$select": "Ancestors,RegisteredDevice,Owners,AccountMoid",
                "$top": PAGE_LIMIT,
                "$inlinecount": "allpages"
            }
        },
        "processorunit": {
            "endpoint": Endpoints.SEARCH_ITEMS,
            "params": {
                "$filter": "ObjectType eq 'processor.Unit' AND Ancestors.ObjectType"
                " in ('compute.Blade','compute.RackUnit')",
                "$select": "Ancestors,RegisteredDevice,Owners,AccountMoid",
                "$top": PAGE_LIMIT,
                "$inlinecount": "allpages"
            }
        },
        "transceiver": {
            "endpoint": Endpoints.TRANSCEIVERS,
            "params": {
                "$filter": "Ancestors.ObjectType in ('network.Element')",
                "$select": "Ancestors,RegisteredDevice,Owners,AccountMoid,Serial,Model,Vendor,Parent",
                "$top": PAGE_LIMIT,
                "$inlinecount": "allpages"
            }
        },
        "graphicscard": {
            "endpoint": Endpoints.SEARCH_ITEMS,
            "params": {
                "$filter": "ObjectType eq 'graphics.Card'",
                "$expand": "",
                "$select": "",
                "$top": PAGE_LIMIT,
                "$inlinecount": "allpages"
            }
        },
        "etherhostports": {
            "endpoint": Endpoints.HOST_PORTS,
            "params": {
                "$expand": "Parent($select=Model)",
                "$select": "Moid,Ancestors,AggregatePortId,AccountMoid,Parent,OperState,"
                "AcknowledgedPeerInterface,MacAddress,PortChannelId,PortId,Role,PortType,"
                "ModuleId,SlotId,RegisteredDevice,Owners",
                "$top": PAGE_LIMIT,
                "$inlinecount": "allpages"
            }
        },
        "ethernetworkports": {
            "endpoint": Endpoints.NETWORK_PORTS,
            "params": {
                "$expand": "Parent($select=Model,ModuleId)",
                "$select": "Moid,Ancestors,AggregatePortId,AccountMoid,Parent,OperState,"
                "AcknowledgedPeerInterface,MacAddress,PortChannelId,PortId,Role,PortType,"
                "ModuleId,SlotId,RegisteredDevice,Owners",
                "$top": PAGE_LIMIT,
                "$inlinecount": "allpages"
            }
        },
        "etherphysicalports": {
            "endpoint": Endpoints.PHYSICAL_PORTS,
            "params": {
                "$expand": "",
                "$select": "Moid,Ancestors,AggregatePortId,AccountMoid,Parent,OperState,"
                "AcknowledgedPeerInterface,MacAddress,PortChannelId,PortId,Role,PortType,"
                "ModuleId,SlotId,RegisteredDevice,Owners",
                "$top": PAGE_LIMIT,
                "$inlinecount": "allpages"
            }
        },
        "etherportchannels": {
            "endpoint": Endpoints.PORT_CHANNELS,
            "params": {
                "$expand": "Parent($select=Model)",
                "$select": "Moid,Ancestors,AggregatePortId,AccountMoid,Parent,OperState,"
                "AcknowledgedPeerInterface,MacAddress,PortChannelId,PortId,Role,PortType,"
                "ModuleId,SlotId,RegisteredDevice,Owners",
                "$top": PAGE_LIMIT,
                "$inlinecount": "allpages"
            }
        },
        "adapterhostfcinterfaces": {
            "endpoint": Endpoints.ADAPTER_HOSTFCINTERFACE,
            "params": {
                "$expand": "Parent($select=Model),Ancestors($select=ChassisId,Name)",
                "$select": "Moid,Ancestors,AggregatePortId,AccountMoid,Parent,OperState,AcknowledgedPeerInterface,"
                "MacAddress,PortChannelId,Name,VifId,RegisteredDevice,Owners,SlotId",
                "$top": PAGE_LIMIT,
                "$inlinecount": "allpages"
            }
        },
        "fcphysicalports": {
            "endpoint": Endpoints.FC_PHYSICALPORTS,
            "params": {
                "$expand": "",
                "$select": "Moid,Ancestors,AggregatePortId,AccountMoid,Parent,OperState,AcknowledgedPeerInterface,"
                "MacAddress,PortChannelId,Name,VifId,RegisteredDevice,SlotId,PortId,Owners",
                "$top": PAGE_LIMIT,
                "$inlinecount": "allpages"
            }
        },
        "networkvfcs": {
            "endpoint": Endpoints.NETWORK_VFCS,
            "params": {
                "$filter": "",
                "$expand": "Parent($select=Model),AdapterHostFcInterface($select=Ancestors)",
                "$select": "Moid,AdapterHostFcInterface,Ancestors,AccountMoid,Parent,OperState,VfcId,"
                "AcknowledgedPeerInterface,MacAddress,PortChannelId,Name,AggregatePortId"
                "VifId,fc_uplink,RegisteredDevice,SlotId,PortId,Owners",
                "$top": PAGE_LIMIT,
                "$inlinecount": "allpages"
            }
        },
        "networkvethernets": {
            "endpoint": Endpoints.NETWORK_VETHERNETS,
            "params": {
                "$filter": "",
                "$expand": "Parent($select=Model),AdapterHostEthInterface($select=Ancestors)",
                "$select": "Moid,AdapterHostEthInterface,Ancestors,AccountMoid,Parent,"
                "OperState,AcknowledgedPeerInterface,MacAddress,PortChannelId,Name,VethId,AggregatePortId"
                ",vethernet,RegisteredDevice,SlotId,PortId,Owners",
                "$top": PAGE_LIMIT,
                "$inlinecount": "allpages"
            }
        },
        "fcportchannels": {
            "endpoint": Endpoints.FC_PORTCHANNELS,
            "params": {
                "$expand": "Parent($select=Model),Ancestors($select=ChassisId,Name)",
                "$select": "Moid,Ancestors,AggregatePortId,AccountMoid,Parent,OperState,AcknowledgedPeerInterface,"
                "MacAddress,PortChannelId,PortId,Role,PortType,ModuleId,SlotId,RegisteredDevice,Owners",
                "$top": PAGE_LIMIT,
                "$inlinecount": "allpages"
            }
        },
        "adapterhostethinterfaces": {
            "endpoint": Endpoints.ADAPTER_HOSTETHINTERFACE,
            "params": {
                "$expand": "Parent($select=Model),Ancestors($select=ChassisId,Name)",
                "$select": "Moid,Ancestors,AggregatePortId,AccountMoid,Parent,OperState,AcknowledgedPeerInterface,"
                "MacAddress,PortChannelId,PortId,Role,PortType,ModuleId,SlotId,RegisteredDevice,Owners,VifId,Name",
                "$top": PAGE_LIMIT,
                "$inlinecount": "allpages"
            }
        },
        "adapterextethinterfaces": {
            "endpoint": Endpoints.ADAPTER_EXTETHINTERFACE,
            "params": {
                "$expand": "Parent($select=Model),Ancestors($select=ChassisId,Name)",
                "$select": "Moid,Ancestors,AggregatePortId,AccountMoid,Parent,OperState,AcknowledgedPeerInterface,"
                "MacAddress,PortChannelId,PortId,Role,PortType,ModuleId,SlotId,RegisteredDevice,Owners,VifId,Name,"
                "ExtEthInterfaceId",
                "$top": PAGE_LIMIT,
                "$inlinecount": "allpages"
            }
        }
    }
