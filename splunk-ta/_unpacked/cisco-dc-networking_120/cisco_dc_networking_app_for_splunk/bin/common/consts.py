APP_NAME = "cisco_dc_networking_app_for_splunk"
ND_API_CALL_COUNT = 100
TIMEOUT = 180
LOGIN = "login"
ND_CHKPT_COLLECTION = "cisco_dc_nd_checkpointing"
ACI_CHKPT_COLLECTION = "cisco_dc_aci_checkpointing"
ND_startTs = "1970-01-01T00:00:00Z"
API_RETRY_COUNT = 3

ACI_DATA_PAGE_LIMIT = 2000
# Nexus 9k
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S%z"
# Command-to-component mapping
COMMAND_TO_COMPONENT_MAPPING = {
    "show hostname": "nxhostname",
    "show module": "nxinventory",
    "show inventory": "nxinventory",
    "show environment temperature": "nxtemperature",
    "show interface": "nxinterface",
    "show cdp neighbors detail": "nxneighbor",
    "show interface transceiver details": "nxtransceiver",
    "show environment power": "nxpower",
    "show system resource": "nxresource",
    "show version": "nxversion"
}

NUM_NDI_THREAD = 200

MAX_THREADS_MULTI_ACC = 16
