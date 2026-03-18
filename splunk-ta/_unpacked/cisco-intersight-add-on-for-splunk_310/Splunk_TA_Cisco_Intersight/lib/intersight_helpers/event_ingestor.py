# pylint: disable=too-many-lines

"""Module containing the EventIngestor class used to ingest events from Intersight."""
import json
import logging
import traceback
import requests
from collections import defaultdict
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from splunk.clilib import cli_common
from splunklib import (
    modularinput as smi,
    client
)

from import_declare_test import ta_name  # pylint: disable=unused-import
from intersight_helpers.constants import (
    SOURCE_SOURCETYPE_DICT, Endpoints, INV_NETWORK_ENDPOINTS_MAPPING, INV_POOL_ENDPOINTS_MAPPING
)
from intersight_helpers.kvstore_helper import upsert_to_kvstore
from intersight_helpers.ingest_helper import (
    ingest_alarms, ingest_audit_records, ingest_metrics_data,
    process_events_for_ingestion, modify_host_eth_interface_data
)
from intersight_helpers import conf_helper


def pop(pop_list: List[str], data: Dict[str, any], logger: logging.Logger) -> Dict[str, any]:
    """
    Remove specified keys from a dictionary.

    This function attempts to remove each key in the `pop_list` from the `data` dictionary.
    If a key is not found, it logs a debug message. If any other error occurs, it logs an error message.

    Args:
        pop_list (List[str]): List of keys to remove from the dictionary.
        data (Dict): The dictionary to remove the keys from.
        logger (logging.Logger): Logger to output any errors to.

    Returns:
        Dict: The dictionary with the specified keys removed, or the same dictionary if an error occurred.
    """
    # Return the data unchanged if it is None or empty
    if not data:
        return data

    try:
        for thepop in pop_list:
            try:
                # Attempt to remove the key from the dictionary
                data.pop(thepop)
            except KeyError:
                # Log a debug message if the key is not found
                logger.debug(f'message=failed_pop | Failed to pop {thepop}')
        return data
    except Exception as e:
        # Log an error message if any other exception occurs
        logger.error(f'message=failed_pop | An error occurred: {str(e)}')
        return data


def larger_datetime(new: str, state: str, logger: logging.Logger) -> str:
    """
    Compare two Intersight timestamps and returns the newer one.

    Args:
        new (str): The new Intersight timestamp to compare.
        state (str): The current checkpoint timestamp.
        logger (logging.Logger): Logger to send any errors to.

    Returns:
        str: The newer timestamp.

    Raises:
        ValueError: If either timestamp is invalid.
    """
    def strptime(i_time):
        """
        Parse a string into a datetime object.

        Args:
            i_time (str): The Intersight timestamp to parse.

        Returns:
            datetime: The parsed datetime object.

        Raises:
            ValueError: If the timestamp is invalid.
        """
        try:
            # Times with a fraction of a second, like 2022-07-07T20:01:38.747Z
            # i.e. most times
            p_time = datetime.strptime(i_time, "%Y-%m-%dT%H:%M:%S.%f%z")
            return p_time
        except ValueError:
            # Times without a fraction of a second, like 2022-07-08T20:07:23Z
            p_time = datetime.strptime(i_time, "%Y-%m-%dT%H:%M:%S%z")
            return p_time

    # Here we check to see if the latest event is newer than our state checkpoint, if so we update it.
    try:
        if strptime(state) < strptime(new):
            return new
        else:
            return state
    except ValueError:
        logger.error(
            "message=larger_datetime_error | Checkpoint "
            f"value was unable to be updated with {new} : {traceback.format_exc()}"
        )
        return state


def get_management_port():
    """Fetch the management port from the splunk_ta_cisco_intersight_settings.conf file."""
    conf = cli_common.getConfStanza('splunk_ta_cisco_intersight_settings', 'splunk_rest_host')
    # mgmtHostPort is usually in the form '127.0.0.1:8089'
    mgmt_host_port = conf.get('splunk_rest_port')
    if mgmt_host_port:
        # Extract port
        return mgmt_host_port
    else:
        # Default port if not set
        return "8089"


class EventIngestor:
    """Event Ingestor of Intersight."""

    def __init__(  # pylint: disable=too-many-positional-arguments
        self, intersight_config: dict,
        event_writer: smi.EventWriter,
        logger: logging.Logger,
        ckpt_account_name: str,
        custom_index_method=False
    ):
        """
        Configure Event Ingestor.

        Parameters:
            intersight_config (dict): Configuration for Intersight API.
            event_writer (EventWriter): Event writer for writing events.
            logger (logging.Logger): Logger for logging messages.
            ckpt_account_name (str): Name of the checkpoint account.
        """
        self.config = intersight_config
        self.ew = event_writer
        self.logger = logger
        self.session_key = intersight_config.get("session_key")
        self.account_name = ckpt_account_name
        self.custom_index_method = custom_index_method

    def ingest_audit_records(self, events: List[Dict]) -> Tuple[int, str, bool]:
        """
        Ingest AAA Audit Record Events.

        This function ingests AAA Audit Records from Intersight and writes them to the configured index.

        Parameters:
            events (List[Dict]): List of AAA Audit Records to ingest.

        Returns:
            Tuple[int, str, bool]: Tuple containing the event count, the last modified time of the ingested events,
            and a boolean indicating if the ingestion was successful.
        """
        return ingest_audit_records(self, events)

    def ingest_alarms(self, events: List[Dict]) -> Tuple[int, int, str, bool]:
        """
        Ingest Alarms Events.

        This function ingests Alarms from Intersight and writes them to the configured index.
        It also updates the KV Store with the latest alarm information.

        Parameters:
            events (List[Dict]): List of Alarms to ingest.

        Returns:
            Tuple[int, int, str, bool]: Tuple containing the event count, the skip count,
            the last modified time of the ingested events, and a boolean indicating if the
            ingestion was successful.
        """
        return ingest_alarms(self, events)

    def ingest_advisories(self, events: List[Dict]) -> Tuple[int, str]:
        """
        Ingest Advisories Events.

        This function ingests Advisories from Intersight and writes them to the configured index.
        Parameters:
            events (List[Dict]): List of Advisories to ingest.
        Returns:
            Tuple[int, str]: Tuple containing the event count and the last modified time of the ingested events.
        """
        self.logger.info(
            "message=ingest_advisories |"
            " Started ingesting advisories data.")
        index_name = self.config.get('index').strip()
        event_count = 0
        modtime = None
        pop_fields = {
            "*": ["ClassId"],
            "root": ['Ancestors',
                     'DeviceRegistration', 'DomainGroupMoid',
                     'SharedScope'],
            "Advisory": [
                'AccountMoid', 'Ancestors', 'Actions', 'ApiDataSources', 'Organization',
                'Recommendation'
            ]
        }
        process_and_ingest_events_args = {
            "events": events,
            "pop_fields": pop_fields,
            "object_type": "tam.AdvisoryInstance",
            "index_name": index_name,
            "source_sourcetype_ref": "tam/AdvisoryInstances"
        }
        event_count, modtime = self.process_and_ingest_events(
            process_and_ingest_events_args
        )
        return event_count, modtime

    def ingest_advisories_infos(self, events: List[Dict]) -> Tuple[int, str]:
        """
        Ingest Advisories Infos Events.

        Parameters:
            events (List[Dict]): List of Advisories Infos to ingest.
        Returns:
            Tuple[int, str]: Tuple containing the event count and the last modified time of the ingested events.
        """
        self.logger.info(
            "message=ingest_advisories_infos |"
            " Started ingesting advisories infos data.")
        index_name = self.config.get('index').strip()
        event_count = 0
        modtime = None
        pop_fields = {
            "*": ["ClassId"]
        }
        process_and_ingest_events_args = {
            "events": events,
            "pop_fields": pop_fields,
            "object_type": "tam.AdvisoryInfo",
            "index_name": index_name,
            "source_sourcetype_ref": "tam/AdvisoryInfos"
        }
        event_count, modtime = self.process_and_ingest_events(
            process_and_ingest_events_args
        )
        return event_count, modtime

    def ingest_advisories_defintions(self, events: List[Dict]) -> Tuple[int, str]:
        """
        Ingest Advisories Definitions Events.

        Parameters:
            events (List[Dict]): List of Advisories Definitions to ingest.

        Returns:
            Tuple[int, str]: Tuple containing the event count and the last modified time of the ingested events.
        """
        self.logger.info(
            "message=ingest_advisories_definitions |"
            " Started ingesting advisories definitions data.")
        index_name = self.config.get('index').strip()
        event_count = 0
        modtime = None
        pop_fields = {
            "*": ["ClassId"]
        }
        process_and_ingest_events_args = {
            "events": events,
            "pop_fields": pop_fields,
            "object_type": "tam.AdvisoryDefinition",
            "index_name": index_name,
            "source_sourcetype_ref": "tam/AdvisoryDefinitions"
        }
        event_count, modtime = self.process_and_ingest_events(
            process_and_ingest_events_args
        )

        return event_count, modtime

    def ingest_security_advisories(self, events: List[Dict]) -> Tuple[int, str]:
        """
        Ingest Security Advisories Events.

        Parameters:
            events (List[Dict]): List of Security Advisories to ingest.
        Returns:
            Tuple[int, str]: Tuple containing the event count and the last modified time of the ingested events.
        """
        self.logger.info(
            "message=ingest_security_advisories |"
            " Started ingesting security advisories data.")
        index_name = self.config.get('index').strip()
        event_count = 0
        modtime = None
        pop_fields = {
            "*": ["ClassId"]
        }
        process_and_ingest_events_args = {
            "events": events,
            "pop_fields": pop_fields,
            "object_type": "tam.SecurityAdvisory",
            "index_name": index_name,
            "source_sourcetype_ref": "tam/SecurityAdvisories"
        }
        event_count, modtime = self.process_and_ingest_events(
            process_and_ingest_events_args
        )
        return event_count, modtime

    def ingest_contract(self, events: List[Dict]) -> Tuple[int, str]:
        """
        Ingest Contract Events.

        Parameters:
            events (List[Dict]): List of contracts to ingest.
        Returns:
            Tuple[int, str]: Tuple containing the event count and the last modified time of the ingested events.
        """
        self.logger.info(
            "message=ingest_contract |"
            " Started ingesting contract data.")
        index_name = self.config.get('index').strip()
        event_count = 0
        modtime = None
        pop_fields = {
            "*": ["ClassId"],
            "root": [
                'Ancestors', 'Contract', 'EndCustomer', 'EndUserGlobalUltimate',
                'Product', 'ResellerGlobalUltimate',
                'SharedScope'
            ]
        }
        process_and_ingest_events_args = {
            "events": events,
            "pop_fields": pop_fields,
            "object_type": "asset.DeviceContractInformation",
            "index_name": index_name,
            "source_sourcetype_ref": "contract"
        }
        event_count, modtime = self.process_and_ingest_events(
            process_and_ingest_events_args
        )
        return event_count, modtime

    def ingest_network(self, events: List[Dict]) -> Tuple[int, str]:
        """
        Ingest Network Events.

        Parameters:
            events (List[Dict]): List of networks to ingest.
        Returns:
            Tuple[int, str]: Tuple containing the event count and the last modified time of the ingested events.
        """
        self.logger.info(
            "message=ingest_network |"
            " Started ingesting network data.")
        index_name = self.config.get('index').strip()
        event_count = 0
        modtime = None
        pop_fields = {
            "*": ["ClassId"],
            "root": ["Ancestors", "FaultSummary", "SharedScope"]
        }
        process_and_ingest_events_args = {
            "events": events,
            "pop_fields": pop_fields,
            "object_type": "network.Element",
            "index_name": index_name,
            "source_sourcetype_ref": "network"
        }
        event_count, modtime = self.process_and_ingest_events(
            process_and_ingest_events_args
        )
        return event_count, modtime

    def ingest_target(self, events: List[Dict]) -> Tuple[int, str]:
        """
        Ingest Target Events.

        Parameters:
            events (List[Dict]): List of target events to ingest.
        Returns:
            Tuple[int, str]: Tuple containing the event count and the last modified time of the ingested events.
        """
        self.logger.info(
            "message=ingest_target |"
            " Started ingesting target data.")
        # Get the index name from the configuration
        index_name = self.config.get('index').strip()
        event_count = 0
        modtime = None
        pop_fields = {
            "*": ["ClassId"],
            "root": [
                'Account', 'Ancestors', 'Connections', 'Parent', 'DomainGroupMoid',
                'ClassId',
                'SharedScope'
            ]
        }
        process_and_ingest_events_args = {
            "events": events,
            "pop_fields": pop_fields,
            "object_type": "asset.Target",
            "index_name": index_name,
            "source_sourcetype_ref": "target"
        }
        event_count, modtime = self.process_and_ingest_events(
            process_and_ingest_events_args
        )
        return event_count, modtime

    def ingest_inventory_objects(self, events: List[Dict]) -> Tuple[int, str]:
        """
        Ingest Inventory Object Events.

        Parameters:
            events (List[Dict]): List of inventory object events to ingest.
        Returns:
            Tuple[int, str]: Tuple containing the event count and the last modified time of the ingested events.
        """
        self.logger.info(
            "message=ingest_inventory_objects | Started ingesting inventory object data."
        )
        # Get the index name from the configuration
        index_name = self.config.get('index').strip()
        event_counts = 0
        modtime = None
        # 1. Group events by ObjectType
        grouped_events = defaultdict(list)
        for data in events:
            object_type = data.get("ObjectType")
            if object_type:
                grouped_events[object_type].append(data)
        # 2. Upsert each group to its respective collection
        for object_type, group in grouped_events.items():
            self.logger.info(
                "message=ingest_inventory_objects_data | Iterating events for ObjectType: {}".format(
                    object_type
                )
            )
            pop_fields = {
                "*": ["ClassId"],
                "root": []
            }
            process_and_ingest_events_args = {
                "events": group,
                "pop_fields": pop_fields,
                "object_type": object_type,
                "index_name": index_name,
                "source_sourcetype_ref": Endpoints.SEARCH_ITEMS
            }
            event_count, modtime = self.process_and_ingest_events(
                process_and_ingest_events_args
            )
            event_counts += event_count
        return event_counts, modtime

    def ingest_compute_hclstatus(self, events: List[Dict]) -> Tuple[int, str]:
        """
        Ingest Compute Cond HCLStatus Event.

        Parameters:
            events (List[Dict]): List of HCLStatus events to ingest.

        Returns:
            Tuple[int, str]: Tuple containing the event count and the last modified time of the ingested events.
        """
        self.logger.info(
            "message=ingest_compute_hclstatus |"
            " Started ingesting Compute Cond HCLStatus data."
        )
        # Get the index name from the configuration
        index_name = self.config.get('index').strip()
        event_count = 0
        modtime = None
        pop_fields = {
            "*": ["ClassId"],
            "root": []
        }
        process_and_ingest_events_args = {
            "events": events,
            "pop_fields": pop_fields,
            "object_type": "cond.HclStatus",
            "index_name": index_name,
            "source_sourcetype_ref": "cond/HclStatuses"
        }
        event_count, modtime = self.process_and_ingest_events(
            process_and_ingest_events_args
        )
        return event_count, modtime

    def ingest_equipment_chasses(self, events: List[Dict]) -> Tuple[int, Optional[str]]:
        """Ingest Compute EquipmentChasses Events.

        This function processes and ingests event data related to Compute EquipmentChasses
        from Intersight and writes them to the configured index.

        Parameters:
            events (List[Dict]): List of EquipmentChasses events to ingest.

        Returns:
            Tuple[int, Optional[str]]: Tuple containing the event count and the last modified time
                                       of the ingested events.
        """
        self.logger.info(
            "message=ingest_equipment_chasses |"
            " Started ingesting Compute EquipmentChasses data.")

    # Get the index name from the configuration
        index_name = self.config.get('index').strip()
        event_count = 0
        modtime = None
        pop_fields = {
            # Global fields to remove from all dictionaries
            '*': ['ClassId'],

            # Fields to remove from the root level
            'root': [
                'Ancestors', 'DomainGroupMoid', 'FaultSummary',
                'InventoryDeviceInfo', 'Sasexpanders', 'StorageEnclosures',
                'LocatorLed',
                'SharedScope', 'VirtualDriveContainer'
            ]
        }

        process_and_ingest_events_args = {
            "events": events,
            "pop_fields": pop_fields,
            "object_type": "equipment.Chassis",
            "index_name": index_name,
            "source_sourcetype_ref": "equipment/Chasses"
        }
        event_count, modtime = self.process_and_ingest_events(
            process_and_ingest_events_args
        )

        return event_count, modtime

    def ingest_server_profiles(self, events: List[Dict]) -> Tuple[int, str]:
        """
        Ingest Compute ServerProfiles Events.

        This function processes and ingests ServerProfiles data from Intersight,
        removing unnecessary fields and adding metadata before writing them to the configured index.

        Parameters:
            events (List[Dict]): List of ServerProfiles events to ingest.

        Returns:
            Tuple[int, str]: Tuple containing the event count and the last modified time of the ingested events.
        """
        self.logger.info(
            "message=ingest_server_profiles |"
            " Started ingesting Compute ServerProfiles data.")
        index_name = self.config.get('index').strip()
        event_count = 0
        modtime = None
        pop_fields = {
            # Global fields to remove from all dictionaries.
            "*": ["ClassId"]
        }

        process_and_ingest_events_args = {
            "events": events,
            "pop_fields": pop_fields,
            "object_type": "server.Profile",
            "index_name": index_name,
            "source_sourcetype_ref": "server/Profiles"
        }
        event_count, modtime = self.process_and_ingest_events(
            process_and_ingest_events_args
        )

        return event_count, modtime

    def ingest_chassis_profiles(self, events: List[Dict]) -> Tuple[int, str]:
        """
        Ingest Compute ChassisProfiles Events.

        This function processes and ingests ChassisProfiles data from Intersight,
        removing unnecessary fields and adding metadata before writing them to the configured index.

        Parameters:
            events (List[Dict]): List of ChassisProfiles events to ingest.

        Returns:
            Tuple[int, str]: Tuple containing the event count and the last modified time of the ingested events.
        """
        self.logger.info(
            "message=ingest_chassis_profiles |"
            " Started ingesting Compute ChassisProfiles data.")
        index_name = self.config.get('index').strip()
        event_count = 0
        modtime = None
        pop_fields = {
            # Global fields to remove from all dictionaries.
            "*": ["ClassId"]
        }

        process_and_ingest_events_args = {
            "events": events,
            "pop_fields": pop_fields,
            "object_type": "chassis.Profile",
            "index_name": index_name,
            "source_sourcetype_ref": "chassis/Profiles"
        }
        event_count, modtime = self.process_and_ingest_events(
            process_and_ingest_events_args
        )

        return event_count, modtime

    def ingest_fabric_switchprofiles(self, events: List[Dict]) -> Tuple[int, str]:
        """
        Ingest Fabric SwitchProfiles Events.

        Parameters:
            events (List[Dict]): List of SwitchProfiles events to ingest.

        Returns:
            Tuple[int, str]: Tuple containing the event count and the last modified time of the ingested events.
        """
        self.logger.info(
            "message=ingest_fabric_switchprofiles |"
            " Started ingesting Fabric SwitchProfiles data.")
        index_name = self.config.get('index').strip()
        event_count = 0
        modtime = None
        pop_fields = {
            # Global fields to remove from all dictionaries.
            "*": ["ClassId"]
        }
        process_and_ingest_events_args = {
            "events": events,
            "pop_fields": pop_fields,
            "object_type": "fabric.SwitchProfile",
            "index_name": index_name,
            "source_sourcetype_ref": "fabric/SwitchProfiles"
        }
        event_count, modtime = self.process_and_ingest_events(
            process_and_ingest_events_args
        )
        return event_count, modtime

    def ingest_fabric_switchclusterprofiles(self, events: List[Dict]) -> Tuple[int, str]:
        """
        Ingest Fabric SwitchClusterProfiles Events.

        Parameters:
            events (List[Dict]): List of SwitchClusterProfiles events to ingest.

        Returns:
            Tuple[int, str]: Tuple containing the event count and the last modified time of the ingested events.
        """
        # Log the start of the ingestion process
        self.logger.info(
            "message=ingest_fabric_switchclusterprofiles |"
            " Started ingesting Fabric SwitchClusterProfiles data.")
        # Retrieve the index name from the configuration
        index_name = self.config.get('index').strip()
        event_count = 0
        modtime = None
        pop_fields = {
            # Global fields to remove from all dictionaries.
            "*": ["ClassId"]
        }
        process_and_ingest_events_args = {
            "events": events,
            "pop_fields": pop_fields,
            "object_type": "fabric.SwitchClusterProfile",
            "index_name": index_name,
            "source_sourcetype_ref": "fabric/SwitchClusterProfiles"
        }
        event_count, modtime = self.process_and_ingest_events(
            process_and_ingest_events_args
        )

        return event_count, modtime

    def ingest_account_license_data(self, events: List[Dict]) -> Tuple[int, str]:
        """
        Ingest Account License Data Events.

        Parameters:
            events (List[Dict]): List of Account License Data events to ingest.

        Returns:
            Tuple[int, str]: Tuple containing the event count and the last modified time of the ingested events.
        """
        # Log the start of the ingestion process
        self.logger.info(
            "message=ingest_account_license_data |"
            " Started ingesting Account License Data data.")
        # Retrieve the index name from the configuration
        index_name = self.config.get('index').strip()
        event_count = 0
        modtime = None
        pop_fields = {
            # Global fields to remove from all dictionaries.
            "*": ["ClassId"],

            # Fields to remove from the root level.
            "root": ["AgentData", "Ancestors"]
        }
        process_and_ingest_events_args = {
            "events": events,
            "pop_fields": pop_fields,
            "object_type": "license.AccountLicenseData",
            "index_name": index_name,
            "source_sourcetype_ref": "license/AccountLicenseData"
        }
        event_count, modtime = self.process_and_ingest_events(
            process_and_ingest_events_args
        )

        return event_count, modtime

    def ingest_license_infos(self, events: List[Dict]) -> Tuple[int, str]:
        """
        Ingest License Infos Data Events.

        Parameters:
            events (List[Dict]): List of License Infos events to ingest.

        Returns:
            Tuple[int, str]: Tuple containing the event count and the last modified time of the ingested events.
        """
        self.logger.info(
            "message=ingest_license_infos |"
            " Started ingesting License Infos data.")
        index_name = self.config.get('index').strip()
        event_count = 0
        modtime = None
        pop_fields = {
            # Global fields to remove from all dictionaries.
            "*": ["ClassId"],
            # Fields to remove from the root level.
            "root": []
        }
        process_and_ingest_events_args = {
            "events": events,
            "pop_fields": pop_fields,
            "object_type": "license.LicenseInfo",
            "index_name": index_name,
            "source_sourcetype_ref": "license/LicenseInfos"
        }
        event_count, modtime = self.process_and_ingest_events(
            process_and_ingest_events_args
        )
        return event_count, modtime

    def ingest_metrics_data(self, metrics_data: List[Dict], metrics_name: str, is_custom_input=False) -> int:
        """
        Ingest telemetry data from Intersight into a Splunk index.

        Args:
            metrics_data (List[Dict]): List of metric data dictionaries to ingest.
            metrics_name (str): Name of the metrics data source.

        Returns:
            int: Total count of successfully ingested events.
        """
        return ingest_metrics_data(self, metrics_data, metrics_name, is_custom_input)

    def create_kvstore_collection(self, session_key, collection_name, app_name="Splunk_TA_Cisco_Intersight"):
        """Create KVStore collection dynamically and update collections.conf + transforms.conf."""
        try:
            kv_conf_stanza = conf_helper.get_conf_file(
                file="splunk_ta_cisco_intersight_settings",
                stanza="splunk_rest_host",
                session_key=session_key,
            )
            # Construct the server URI from the host and port in the configuration
            host = kv_conf_stanza.get("splunk_rest_host_url")
            port = kv_conf_stanza.get("splunk_rest_port")
            server_uri = f"https://{host}:{port}"

            # Determine authentication method based on host
            # For localhost/127.0.0.1, use session_key; for remote hosts, use username/password
            is_localhost = host in ["localhost", "127.0.0.1"]

            if is_localhost:
                # Use session_key authentication for local Splunk instance
                self.logger.info("Using session_key authentication for localhost KVStore operations")
                auth = None
                headers = {
                    "Authorization": f"Splunk {session_key}"
                }
            else:
                # Use basic auth with username/password for remote Splunk instance
                self.logger.info(f"Using username/password authentication for remote host: {host}")
                username = kv_conf_stanza.get("splunk_username")
                password = kv_conf_stanza.get("splunk_password")
                if not username or not password:
                    raise Exception(
                        "Splunk REST credentials (splunk_username/splunk_password) are not configured "
                        "for remote host access."
                    )
                auth = (username, password)
                headers = None

            # 1. Create KVStore collection
            url = f"{server_uri}/servicesNS/nobody/{app_name}/storage/collections/config"
            payload = {"name": collection_name}
            r = requests.post(url, auth=auth, headers=headers, data=payload, verify=False, timeout=30)
            if r.status_code not in [200, 201]:
                raise Exception(f"Failed to create KVStore collection: {r.status_code}, {r.text}")
            self.logger.info(f"KVStore collection '{collection_name}' created successfully.")

            # 2. Create/update transforms.conf stanza
            url_transforms = f"{server_uri}/servicesNS/nobody/{app_name}/configs/conf-transforms"
            payload_trans = {
                "name": collection_name,
                "external_type": "kvstore",
                "collection": collection_name,
                "fields_list": "_key"
            }
            r = requests.post(url_transforms, auth=auth, headers=headers, data=payload_trans, verify=False, timeout=30)
            if r.status_code not in [200, 201]:
                self.logger.warning(f"transforms.conf update failed: {r.status_code}, {r.text}")
            else:
                self.logger.info(f"transforms.conf updated for {collection_name}")

        except Exception as e:
            raise Exception(f"Error creating/updating KVStore collection '{collection_name}': {e}")

    def process_and_ingest_events(
        self, process_and_ingest_events_args: Dict
    ) -> Tuple[int, str]:
        """
        Process events in a single pass and ingest them to both KVStore and Splunk index.

        Parameters:
            process_and_ingest_events_args (Dict): Arguments dictionary containing:
                events (List[Dict]): List of events to process and ingest.
                pop_fields (Dict): Dictionary of fields to remove from each event.
                object_type (str): Object type of the events.
                index_name (str): Name of the Splunk index to ingest the events to.
                source_sourcetype_ref (str): Source sourcetype reference of the events.

        Returns:
            Tuple[int, str]: Tuple containing the event count and last modified time.
        """
        ingest_kvstore_status = False
        ingest_splunk_index_status = False
        event_count = 0
        modtime = None

        events = process_and_ingest_events_args.get("events")
        pop_fields = process_and_ingest_events_args.get("pop_fields")
        object_type = process_and_ingest_events_args.get("object_type")
        index_name = process_and_ingest_events_args.get("index_name")
        source_sourcetype_ref = process_and_ingest_events_args.get("source_sourcetype_ref")

        try:
            # Process events in a single pass
            kvstore_events, splunk_events, modtime = process_events_for_ingestion(
                events=events,
                account_name=self.account_name,
                pop_fields=pop_fields,
                logger=self.logger
            )
        except Exception as e:
            self.logger.error(
                "message=ingest_data_logic | Error:{} occurred while processing events "
                "for ingestion for objectType='{}'".format(e, object_type)
            )
            raise e

        # 1. Update KVStore
        if kvstore_events:
            self.logger.info(
                "message=ingest_data_logic |"
                " Upserting {} events for objectType='{}' to KVStore".format(
                    len(kvstore_events), object_type)
            )
            try:
                if source_sourcetype_ref == "custom_input":
                    collection_name = ("Cisco_Intersight_custom_" + "_".join(object_type.split("."))).lower()
                else:
                    collection_name = ("Cisco_Intersight_" + "_".join(object_type.split("."))).lower()

                try:
                    if source_sourcetype_ref == "custom_input":
                        upsert_to_kvstore(
                            self.session_key,
                            kvstore_events,
                            object_type,
                            collection_name=collection_name
                        )
                    else:
                        upsert_to_kvstore(
                            self.session_key,
                            kvstore_events,
                            object_type
                        )
                except Exception as e:
                    self.logger.warning(
                        f"{e} not found. Creating it now0..."
                    )
                    if "could not find collection named" in str(e).lower():
                        self.logger.warning(
                            f"KVStore collection '{collection_name}' not found. Creating it now..."
                        )
                        self.create_kvstore_collection(
                            self.session_key,
                            collection_name,
                            app_name=ta_name
                        )
                        # retry upsert after collection creation
                        if source_sourcetype_ref == "custom_input":
                            upsert_to_kvstore(
                                self.session_key,
                                kvstore_events,
                                object_type,
                                collection_name=collection_name
                            )
                        else:
                            upsert_to_kvstore(
                                self.session_key,
                                kvstore_events,
                                object_type
                            )
                    else:
                        raise e

                ingest_kvstore_status = True
            except Exception as e:
                self.logger.error(
                    "message=ingest_data_logic | Error:{} occurred while ingesting event for "
                    "objectType='{}' in Splunk KVstore.".format(e, object_type)
                )
                raise e
        else:
            self.logger.info(
                "message=ingest_data_logic |"
                " No events for objectType='{}' to be ingested to KVStore".format(object_type)
            )

        # 2. Write events to Splunk
        if splunk_events:
            self.logger.info(
                "message=ingest_data_logic |"
                " Ingesting {} events for objectType='{}' to Splunk Index".format(
                    len(splunk_events), object_type))
            for event in splunk_events:
                try:
                    if not self.custom_index_method:
                        if source_sourcetype_ref == "custom_input":
                            splunk_event = smi.Event(
                                data=json.dumps(event),
                                sourcetype=process_and_ingest_events_args.get("users_sourcetype"),
                                source="".join(object_type.split(".")),
                                index=index_name
                            )
                        else:
                            splunk_event = smi.Event(
                                data=json.dumps(event),
                                sourcetype=SOURCE_SOURCETYPE_DICT.get(source_sourcetype_ref).get("sourcetype"),
                                source=SOURCE_SOURCETYPE_DICT.get(source_sourcetype_ref).get("source"),
                                index=index_name
                            )
                        self.ew.write_event(splunk_event)
                    else:
                        splunk_service = client.connect(
                            token=self.session_key, app=ta_name,
                            port=get_management_port())
                        myindex = splunk_service.indexes[index_name]
                        splunk_event = json.dumps(event)
                        myindex.submit(
                            splunk_event,
                            sourcetype=SOURCE_SOURCETYPE_DICT.get(
                                source_sourcetype_ref).get("sourcetype"),
                            source=SOURCE_SOURCETYPE_DICT.get(source_sourcetype_ref).get("source")
                        )
                    event_count += 1
                except Exception as e:
                    self.logger.error(
                        "message=ingest_data_logic | Error:{} while ingesting event for "
                        "objectType='{}' with Moid='{}' in Splunk Index.".format(
                            e, object_type, event.get('Moid', None)
                        )
                    )
                    raise e
            ingest_splunk_index_status = True
        else:
            self.logger.info(
                "message=ingest_data_logic |"
                " No events for objectType='{}' to be ingested to Splunk Index".format(object_type)
            )

        self.logger.info(
            "message=ingest_data_logic |"
            " Status of data collection for objectType='{}' -"
            " KVStore: {}, Splunk: {}".format(
                object_type,
                ingest_kvstore_status,
                ingest_splunk_index_status
            )
        )
        return event_count, modtime

    def ingest_inv_network_objects(self, events: List[Dict]) -> Tuple[int, str]:
        """
        Ingest Inventory network objects information from Intersight into a splunk index.

        This function takes a list of port information dictionaries and
        writes them into the specified Splunk index.

        Args:
            events (List[Dict]): List of port information dictionaries to ingest.

        Returns:
            Tuple[int, str]: Tuple containing the total count of successfully ingested events
            and the last modified time of the ingested events.
        """
        self.logger.info(
            "message=ingest_inv_network_objects |"
            " Started ingesting Inventory network Objects.")
        index_name = self.config.get('index').strip()
        event_counts = 0
        modtime = None
        # 1. Group events by ObjectType
        grouped_events = defaultdict(list)
        for data in events:
            object_type = data.get("ObjectType")
            if object_type:
                grouped_events[object_type].append(data)
        # 2. Upsert each group to its respective collection
        for object_type, group in grouped_events.items():
            self.logger.info(
                "message=ingest_inv_network_objects_data | Iterating events for ObjectType: {}".format(
                    object_type
                )
            )
            pop_fields = {
                # Global fields to remove from all dictionaries.
                "*": ["ClassId"],
                # Fields to remove from the root level.
                "root": []
            }
            # Modify Host Ethernetinterfaces data to remove unwanted fields.
            if object_type == "adapter.HostEthInterface":
                group = modify_host_eth_interface_data(group, self.logger)
            process_and_ingest_events_args = {
                "events": group,
                "pop_fields": pop_fields,
                "object_type": object_type,
                "index_name": index_name,
                "source_sourcetype_ref": INV_NETWORK_ENDPOINTS_MAPPING[
                    object_type]
            }
            event_count, modtime = self.process_and_ingest_events(
                process_and_ingest_events_args
            )
            event_counts += event_count
        return event_counts, modtime

    def ingest_inv_pools(self, events: List[Dict]) -> Tuple[int, str]:
        """
        Ingest Inventory pool objects information from Intersight into a splunk index.

        This function takes a list of pool information dictionaries and
        writes them into the specified Splunk index.

        Args:
            events (List[Dict]): List of pool information dictionaries to ingest.

        Returns:
            Tuple[int, str]: Tuple containing the total count of successfully ingested events
            and the last modified time of the ingested events.
        """
        self.logger.info(
            "message=ingest_inv_pools |"
            " Started ingesting Inventory pools.")
        index_name = self.config.get('index').strip()
        event_counts = 0
        modtime = None
        # 1. Group events by ObjectType
        grouped_events = defaultdict(list)
        for data in events:
            object_type = data.get("ObjectType")
            if object_type:
                grouped_events[object_type].append(data)
        # 2. Upsert each group to its respective collection
        for object_type, group in grouped_events.items():
            self.logger.info(
                "message=ingest_inv_pools_data | Iterating events for ObjectType: {}".format(
                    object_type
                )
            )
            pop_fields = {
                # Global fields to remove from all dictionaries.
                "*": ["ClassId"]
            }
            process_and_ingest_events_args = {
                "events": group,
                "pop_fields": pop_fields,
                "object_type": object_type,
                "index_name": index_name,
                "source_sourcetype_ref": INV_POOL_ENDPOINTS_MAPPING[object_type]
            }
            event_count, modtime = self.process_and_ingest_events(
                process_and_ingest_events_args
            )
            event_counts += event_count

        return event_counts, modtime

    def ingest_custom_input_data(self, events: List[Dict], obj_type) -> Tuple[int, str]:
        """Ingest custom_input data from Intersight into a Splunk index.

        Sourcetype and source are generated dynamically based on ObjectType.
        """
        self.logger.info("message=ingest_custom_input_data | Started ingesting custom_input data.")
        index_name = self.config.get('index').strip()
        event_count = 0
        modtime = None
        pop_fields = {
            "*": ["ClassId"]
        }

        # Generate dynamic sourcetype based on ObjectType
        object_type = events[0].get("ObjectType", obj_type) if events else "custom_input"
        custom_sourcetype = "cisco:intersight:custom:inventory"

        process_and_ingest_events_args = {
            "events": events,
            "pop_fields": pop_fields,
            "object_type": object_type,
            "index_name": index_name,
            "source_sourcetype_ref": "custom_input",
            "users_sourcetype": custom_sourcetype
        }
        event_count, modtime = self.process_and_ingest_events(
            process_and_ingest_events_args
        )
        return event_count, modtime
