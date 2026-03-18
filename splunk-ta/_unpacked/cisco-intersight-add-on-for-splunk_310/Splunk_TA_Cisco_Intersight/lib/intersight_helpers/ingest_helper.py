"""
This module provides helper functions for ingesting data from Cisco Intersight into Splunk.

It contains the implementation code for ingesting different types of data from Intersight.
"""
import json
import hashlib
from copy import deepcopy
from typing import Dict, List, Tuple, Any
import splunklib.modularinput as smi

from intersight_helpers.constants import CollectionConstants, SOURCE_SOURCETYPE_DICT


def pop(keys: List[str], data: Dict[str, Any], logger) -> Dict[str, Any]:
    """
    Safely remove keys from a dictionary and return the modified dictionary.

    Args:
        keys: List of keys to remove
        data: Dictionary to modify
        logger: Logger instance for error reporting

    Returns:
        Modified dictionary with keys removed
    """
    for key in keys:
        try:
            data.pop(key, None)
        except Exception as e:
            logger.debug(f"Failed to pop key {key}: {e}")
    return data


def dict_to_sha(data: Dict[str, Any]) -> str:
    """
    Convert a dictionary to a SHA-256 hash string.

    Args:
        data: Dictionary to hash

    Returns:
        SHA-256 hash of the dictionary as a string
    """
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def remove_fields_from_nested_obj(
        data: dict, field_mapping: dict, logger=None,
        root=True) -> None:
    """
    Recursively remove specified fields from nested dictionaries and lists.

    Args:
        data: The data structure to process (dict or list)
        field_mapping: Dictionary mapping parent keys to lists of fields to remove
                      Use '*' for global fields to remove from all dictionaries
        logger: Optional logger for debugging
    """
    # Remove global fields (applied to all dictionaries)
    global_fields = field_mapping.get('*', [])
    for field in global_fields:
        try:
            data.pop(field)
        except KeyError:
            pass

        # Remove root level fields
        if root:
            root_fields = field_mapping.get('root', [])
            for field in root_fields:
                try:
                    data.pop(field)
                except KeyError:
                    pass

    # If fields need to check at only root level, no need to
    # check for nested data.
    has_other_keys = any(k not in ('root') for k in field_mapping.keys())
    if not has_other_keys:
        return

    # Process each key in the dictionary
    for key, value in list(data.items()):
        # Remove fields specified for this key
        if key in field_mapping:
            if isinstance(value, dict):
                for field in field_mapping[key]:
                    try:
                        value.pop(field)
                    except KeyError:
                        pass

            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        for field in field_mapping[key]:
                            try:
                                item.pop(field)
                            except KeyError:
                                pass

        # Recursively process nested structures
        if isinstance(value, dict):
            remove_fields_from_nested_obj(
                value, field_mapping, logger, root=False)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    remove_fields_from_nested_obj(
                        item, field_mapping, logger, root=False)


def process_events_for_ingestion(events, account_name, pop_fields, logger):
    """
    Process events for both KVStore and Splunk index ingestion in a single pass.

    Args:
        events: List of events to process
        account_name: Account name to add to events
        pop_fields: Fields to remove from events
        logger: Logger instance

    Returns:
        tuple: (kvstore_events, splunk_events)
            - kvstore_events: Processed events for KVStore
            - splunk_events: Processed events for Splunk index
    """
    kvstore_events = []
    splunk_events = []
    modtime = None

    for event in events:
        modtime = event.get('ModTime', None)
        event_objecttype = event.get("ObjectType", None)
        event_moid = event.get("Moid", None)
        event_accountmoid = event.get("AccountMoid", None)
        required_fields = {
            "modtime": modtime,
            "event_objecttype": event_objecttype,
            "event_moid": event_moid,
            "event_accountmoid": event_accountmoid,
        }

        if any(field is None or field == "" for field in required_fields.values()):
            logger.error(
                "message=process_events_for_ingestion | Skipping this API as the event"
                " does not contain the required fields (AccountMoid, Moid, ObjectType, ModTime)"
            )
            return None, None, None
        processed_event = event.copy()
        remove_fields_from_nested_obj(processed_event, pop_fields, logger)
        processed_event['account_name'] = account_name
        # Create a copy to avoid modifying the original event
        kvstore_event = processed_event.copy()
        kvstore_events.append(kvstore_event)

        # Add updated_at and account_name to Splunk event.
        processed_event['updated_at'] = modtime
        splunk_events.append(processed_event)

    return kvstore_events, splunk_events, modtime


def ingest_audit_records(event_ingestor, events: List[Dict]) -> Tuple[int, str, bool]:
    """
    Ingest AAA Audit Record Events.

    This function ingests AAA Audit Records from Intersight and writes them to the configured index.

    Parameters:
        event_ingestor: The EventIngestor instance to use for ingestion.
        events (List[Dict]): List of AAA Audit Records to ingest.

    Returns:
        Tuple[int, str, bool]: Tuple containing the event count, the last modified time of the ingested events,
        and a boolean indicating if the ingestion was successful.
    """
    try:
        logger = event_ingestor.logger
        logger.info(
            "message=ingest_audit_records |"
            " Started ingesting audit records.")
        index_name = event_ingestor.config.get('index').strip()
        event_count = 0
        modtime = None
        for data in events:
            modtime = data.get('ModTime', None)
            if modtime is None:
                event_objecttype = data["ObjectType"]
                event_moid = data["Moid"]
                logger.warning(
                    "message=ingest_audit_records |"
                    " ModTime is missing in event Moid '{}' of ObjectType '{}'".format(
                        event_moid, event_objecttype))
                continue

            # Pop keys that are not needed
            # These keys are not useful for analysis and are not indexed in Splunk
            data = pop([
                'Account',
                'Ancestors',
                'User',
                'ClassId',
                'DomainGroupMoid',
                'Sessions',
                'SharedScope'
            ], data, logger)
            data["updated_at"] = modtime
            data["account_name"] = event_ingestor.account_name
            event = smi.Event(
                data=json.dumps(data),
                sourcetype=SOURCE_SOURCETYPE_DICT.get("audit").get("sourcetype"),
                source=SOURCE_SOURCETYPE_DICT.get("audit").get("source"),
                index=index_name
            )
            event_ingestor.ew.write_event(event)  # write event into index
            event_count += 1
        return event_count, modtime, True
    except Exception as e:
        logger.error(
            f"message=ingestion_error | Error in ingesting Audit Data. Error: {e}")
        return None, None, False


def ingest_alarms(event_ingestor, events: List[Dict]) -> Tuple[int, int, str, bool]:
    """
    Ingest Alarms Events.

    This function ingests Alarms from Intersight and writes them to the configured index.
    It also updates the KV Store with the latest alarm information.

    Parameters:
        event_ingestor: The EventIngestor instance to use for ingestion.
        events (List[Dict]): List of Alarms to ingest.

    Returns:
        Tuple[int, int, str, bool]: Tuple containing the event count, the skip count,
        the last modified time of the ingested events, and a boolean indicating if the
        ingestion was successful.
    """
    try:
        logger = event_ingestor.logger
        logger.info(
            "message=ingest_alarms |"
            " Started ingesting alarms data.")
        index_name = event_ingestor.config.get('index').strip()
        input_name = event_ingestor.config.get("name", None)

        # Import at function level to avoid cyclic imports
        # pylint: disable=import-outside-toplevel,cyclic-import
        from intersight_helpers.kvstore import KVStoreManager

        kvstore_manager = KVStoreManager(session_key=event_ingestor.session_key)
        kv_intersight_cond_alarms = kvstore_manager.get(
            collection_name=CollectionConstants.COND_ALARMS,
            fields=["Moid", "sha"],
            query={"InputName": input_name}
        )
        current_kv_values = {}
        for alarm in kv_intersight_cond_alarms:
            current_kv_values.update({
                alarm.get('Moid'): {
                    'sha': alarm.get('sha')
                }
            })
        update_kv_values = []
        event_count = 0
        skip_count = 0
        modtime = None
        for data in events:
            modtime = data.get('ModTime', None)
            if modtime is None:
                continue

            moid = data.get('Moid', None)
            # pop keys that not needed
            data = pop([
                'ClassId',
                'DomainGroupMoid',
                'SharedScope'
            ], data, logger)
            temp_data = pop(['LastTransitionTime', 'ModTime'], deepcopy(data), logger)
            sha_event = dict_to_sha(temp_data)

            # skip the ingestion for fault triggered alarms
            if moid in current_kv_values:
                if sha_event == current_kv_values.get(moid, {}).get('sha', None):
                    skip_count += 1
                    logger.debug(
                        "message=skipping_ingestion |"
                        f" Skipping ingestion of alarm {moid} since it is fault triggered."
                    )
                    continue
            data["updated_at"] = modtime
            data["account_name"] = event_ingestor.account_name
            event = smi.Event(
                data=json.dumps(data),
                sourcetype=SOURCE_SOURCETYPE_DICT.get("alarms").get("sourcetype"),
                source=SOURCE_SOURCETYPE_DICT.get("alarms").get("source"),
                index=index_name
            )
            event_ingestor.ew.write_event(event)  # write event into index
            event_count += 1
            kv_key_value = f'{input_name}_{moid}'
            update_kv_values.append({
                "_key": hashlib.md5(kv_key_value.strip().encode()).hexdigest(),
                "Moid": data.get("Moid", None),
                "ModTime": data.get("ModTime", None),
                "Code": data.get("Code", None),
                "sha": sha_event,
                "CreateTime": data.get("CreateTime", None),
                "Severity": data.get("Severity", None),
                "InputName": input_name
            })
        kvstore_manager.upsert(
            collection_name="Cisco_Intersight_cond_alarms",
            items=update_kv_values
        )
        return event_count, skip_count, modtime, True
    except Exception as e:
        logger.error(
            f"message=ingestion_error | Error in ingesting Alarms. Error: {e}")
        return 0, 0, None, False


def ingest_metrics_data(event_ingestor, metrics_data: List[Dict], metrics_name: str, is_custom_input=False) -> int:
    """
    Ingest telemetry data from Intersight into a Splunk index.

    This function takes a list of metric data dictionaries and a name of the
    metrics data source, and writes the data into the specified Splunk index.

    Args:
        event_ingestor: The EventIngestor instance to use for ingestion.
        metrics_data (List[Dict]): List of metric data dictionaries to ingest.
        metrics_name (str): Name of the metrics data source.

    Returns:
        int: Total count of successfully ingested events.
    """
    logger = event_ingestor.logger
    logger.info(
        "message=metric_collection | Started ingesting telemetry data from Intersight."
    )

    index_name = event_ingestor.config.get('index', '').strip()
    if not index_name:
        logger.error(
            "message=metric_collection | Index name is missing in the configuration."
        )
        return 0

    event_count = 0
    for data in metrics_data:
        try:
            # Get the timestamp of the event
            timestamp = data.get('timestamp', None)

            # Add the account name to the event data
            data["account_name"] = event_ingestor.account_name

            # Skip the event if timestamp is missing
            if timestamp is None:
                continue

            data = pop(['ClassId'], data, logger)
            if is_custom_input:
                sourcetype_name = "cisco:intersight:custom:metrics"
            else:
                sourcetype_name = "cisco:intersight:metrics"

            # Create an event object with the processed data
            event = smi.Event(
                data=json.dumps(data),
                sourcetype=sourcetype_name,
                source=metrics_name,
                index=index_name
            )

            # Write the event to the index
            event_ingestor.ew.write_event(event)
            event_count += 1
        except Exception as e:
            # Log the error message
            logger.error(
                f"message=metric_collection | Error writing event | data={data} | error={e}"
            )

    # Log the total count of ingested events
    logger.info(
        f"message=metric_collection | Done ingesting metrics data. | events_ingested={event_count}"
    )
    return event_count


def modify_host_eth_interface_data(
        data: List[Dict], logger) -> List[Dict]:
    """Modify the data for host eth interface.

    Args:
        data (list[Dict[str, Any]]): The data to modify.

    Returns:
        Dict[str, Any]: The modified data.
    """
    for event in data:
        try:
            # Variables to store the connected port channel and switch ID.
            connected_portchannel = ""
            connected_switchid = ""
            if event.get("Vethernet"):
                event["Vethernet"] = {
                    "Description": event["Vethernet"].get("Description"),
                    "Moid": event["Vethernet"].get("Moid"),
                    "ObjectType": event["Vethernet"].get("ObjectType"),
                    "OperState": event["Vethernet"].get("OperState"),
                    "OperReason": event["Vethernet"].get("OperReason"),
                    "PinnedInterface": event["Vethernet"].get("PinnedInterface"),
                    "PinnedInterfaceDn": event["Vethernet"].get("PinnedInterfaceDn"),
                    "NetworkElement": event["Vethernet"].get("NetworkElement"),
                    "BoundInterface": event["Vethernet"].get("BoundInterface")
                }
                # Store only the required fields from the pinned interface.
                if event["Vethernet"].get("PinnedInterface"):
                    event["Vethernet"]["PinnedInterface"] = {
                        "Moid": event["Vethernet"]["PinnedInterface"].get("Moid"),
                        "ObjectType": event["Vethernet"]["PinnedInterface"].get(
                            "ObjectType"),
                        "PortId": event["Vethernet"]["PinnedInterface"].get("PortId"),
                        "SlotId": event["Vethernet"]["PinnedInterface"].get("SlotId")
                    }

                # Store only the required fields from the network element.
                if event["Vethernet"].get("NetworkElement") is not None:
                    event["Vethernet"]["NetworkElement"] = {
                        "SwitchId": event["Vethernet"]["NetworkElement"].get(
                            "SwitchId")
                    }
                    connected_switchid = event["Vethernet"]["NetworkElement"].get(
                        "SwitchId")

                # Store only the required fields from the bound interface.
                if event["Vethernet"].get("BoundInterface"):
                    event["Vethernet"]["BoundInterface"] = {
                        "PortChannelId": event["Vethernet"]["BoundInterface"].get(
                            "PortChannelId")
                    }
                    connected_portchannel = event["Vethernet"]["BoundInterface"].get(
                        "PortChannelId")

            if event.get("AdapterUnit"):
                modified_host_eth_ifs = []
                iom_host_interfaces = set()
                for i in range(len(event["AdapterUnit"].get("ExtEthIfs", []))):
                    ext_ifs = event["AdapterUnit"]["ExtEthIfs"][i]
                    if ext_ifs.get("AcknowledgedPeerInterface") is None:
                        continue

                    port_channelid = ext_ifs.get(
                        "AcknowledgedPeerInterface", {}).get("PortChannelId")
                    switch_id = ext_ifs.get(
                        "AcknowledgedPeerInterface", {}).get("SwitchId")
                    # Skip the interface if it is not connected to the same port
                    # channel and switch.
                    if port_channelid != connected_portchannel or \
                            switch_id != connected_switchid:
                        continue

                    # Add the port channel ID to the set of IOM host interfaces.
                    iom_host_interfaces.add(str(ext_ifs.get(
                        "AcknowledgedPeerInterface", {}).get("PortChannelId")))
                    modified_host_eth_ifs.append({
                        "PortChannelId": ext_ifs.get("AcknowledgedPeerInterface", {}).get(
                            "PortChannelId"),
                        "PortId": ext_ifs.get("AcknowledgedPeerInterface", {}).get(
                            "PortId"),
                        "SlotId": ext_ifs.get("AcknowledgedPeerInterface", {}).get(
                            "SlotId"),
                        "SwitchId": ext_ifs.get("AcknowledgedPeerInterface", {}).get(
                            "SwitchId"),
                        "ObjectType": ext_ifs.get("AcknowledgedPeerInterface", {}).get(
                            "ObjectType"),
                        "Parent": ext_ifs.get("AcknowledgedPeerInterface", {}).get(
                            "Parent")
                    })

                event["AdapterUnit"] = {
                    "AdapterId": event["AdapterUnit"].get("AdapterId"),
                    "ComputeBlade": event["AdapterUnit"].get("ComputeBlade"),
                    "ComputeRackUnit": event["AdapterUnit"].get("ComputeRackUnit"),
                    "ExtEthIfs": modified_host_eth_ifs,
                    "Serial": event["AdapterUnit"].get("Serial")
                }
                event["IOMHostInterfaces"] = ",".join(iom_host_interfaces)

        except Exception as e:
            logger.error(
                "message=modify_host_eth_interface_data | "
                "Error modifying host eth interface data for Moid: {}. Error: {}".format(
                    event.get("Moid"), e
                ))
            raise

    return data
