# pylint: disable=too-many-lines

"""
KVStore helper functions for Cisco Intersight Splunk Add-on.

This module contains utility functions for handling KVStore operations,
JSON processing, and object type mappings for Cisco Intersight data.
"""

from typing import Dict, List, Union
from intersight_helpers.constants import Endpoints, CollectionConstants
from intersight_helpers.kvstore import KVStoreManager
from intersight_helpers.logger_manager import setup_logging
import datetime
from intersight_helpers.conf_helper import get_credentials_by_account_moid
from intersight_helpers.rest_helper import RestHelper
from splunk import rest
import json
from import_declare_test import ta_name

# Module-level logger for consistent logging
logger = setup_logging("ta_intersight_inventory")


def get_field_names_from_collection_data(collection_data):
    """
    Extract field names from the collections API response.

    Args:
        collection_data (dict): The parsed JSON response from the collections API

    Returns:
        set: Set of field names (without the 'field.' prefix)
    """
    field_names = {}

    try:
        # Check if we have the expected structure
        if not isinstance(collection_data, dict) or 'entry' not in collection_data:
            return field_names

        # Get the first entry (should be our collection)
        entries = collection_data.get('entry', [])
        if not entries:
            return field_names

        # Get the content of the first entry
        content = entries[0].get('content', {})
        if not isinstance(content, dict):
            return field_names

        # Extract all keys that start with 'field.'
        for key, value in content.items():
            if key.startswith('field.'):
                # Remove the 'field.' prefix and add to our set
                field_name = key[6:]  # Remove 'field.' prefix
                if field_name:
                    field_names[field_name] = value

    except Exception as e:
        logger.error("Error extracting field names: {}".format(str(e)), exc_info=True)

    return field_names


def read_transforms_conf(session_key, collection_name, app_name):
    """
    Read the transforms.conf file for a specific collection.

    Args:
        session_key: Splunk session key
        collection_name: Name of the KVStore collection
        app_name: Name of the Splunk app

    Returns:
        dict: Dictionary containing the collection configuration
    """
    server_uri = rest.makeSplunkdUri()
    transforms_endpoint = f'{server_uri}servicesNS/nobody/{app_name}/configs/conf-transforms/{collection_name}'
    response, content = rest.simpleRequest(
        transforms_endpoint,
        sessionKey=session_key,
        method='GET',
        getargs={'output_mode': 'json'},
        raiseAllErrors=True
    )
    if response.status != 200:
        logger.error(
            "message=read_transforms_conf | Failed to get transforms "
            "config for collection {}. Status: {}, Response: {}".format(
                collection_name, response.status, content))
        raise  # pylint: disable=E0704  # This bare raise is expected here.

    return json.loads(content)


def update_transforms_config(session_key, collection_name, new_fields, app_name):
    """
    Update transforms.conf to include all fields for searchability.

    Args:
        session_key: Splunk session key
        collection_name: Name of the KVStore collection
        new_fields: Set of new field names to add
        app_name: Name of the Splunk app
    """
    server_uri = rest.makeSplunkdUri()
    transforms_endpoint = f'{server_uri}servicesNS/nobody/{app_name}/configs/conf-transforms/{collection_name}'

    # Get existing transforms configuration
    try:
        transforms_data = read_transforms_conf(session_key, collection_name, app_name)
        existing_config = transforms_data.get('entry', [{}])[0].get('content', {})
    except Exception as e:
        logger.error(
            "message=update_transforms_config | Failed to get transforms "
            "config for collection {}. Error {}".format(collection_name, str(e)))
        return

    # Prepare the payload with existing and new fields
    payload = {
        'external_type': 'kvstore',
        'collection': collection_name,
    }

    fields_list = set(existing_config['fields_list'].replace(" ", "").split(","))

    # Add new fields
    if not new_fields.issubset(fields_list):
        new_fields_list = ", ".join(sorted(set(fields_list) | set(new_fields)))
        payload['fields_list'] = new_fields_list
    else:
        logger.info(
            "message=update_transforms_config | No new fields to add in transforms.conf for "
            "collection {} | skipping update".format(collection_name))
        return

    logger.debug(
        "message=update_transforms_config | transforms payload for "
        "collection {}. Payload: {}".format(collection_name, payload))

    # Update transforms.conf
    response, content = rest.simpleRequest(
        transforms_endpoint,
        sessionKey=session_key,
        method='POST',
        getargs={'output_mode': 'json'},
        postargs=payload,
        raiseAllErrors=True
    )

    if response.status == 200:
        reload_conf_file(session_key, 'transforms', app_name)
        logger.info(
            "message=update_transforms_config | Successfully updated and reloaded"
            " transforms.conf with new fields for collection {}".format(
                collection_name))
    else:
        logger.error(
            "message=update_transforms_config | Failed to update transforms.conf for collection {} | "
            "Status: {}, Response: {}".format(collection_name, response.status, content))


def read_collections_conf(session_key, collection_name, app_name):
    """
    Read the collections.conf file for a specific collection.

    Args:
        session_key: Splunk session key
        collection_name: Name of the KVStore collection
        app_name: Name of the Splunk app

    Returns:
        dict: Dictionary containing the collection configuration
    """
    server_uri = rest.makeSplunkdUri()
    collection_api = f'{server_uri}servicesNS/nobody/{app_name}/configs/conf-collections/{collection_name}'
    response, content = rest.simpleRequest(
        collection_api,
        sessionKey=session_key,
        method='GET',
        getargs={'output_mode': 'json'},
        raiseAllErrors=True
    )
    if response.status != 200:
        logger.error(
            "message=read_collections_conf | Failed to get collections "
            "config for collection {}. Status: {}, Response: {}".format(
                collection_name, response.status, content))
        raise  # pylint: disable=E0704  # This bare raise is expected here.
    return json.loads(content)


def reload_conf_file(session_key, conf_file, app_name):
    """
    Reload a specific configuration file.

    Args:
        session_key: Splunk session key
        conf_file: Name of the configuration file to reload
        app_name: Name of the Splunk app
    """
    server_uri = rest.makeSplunkdUri()
    reload_api = f'{server_uri}servicesNS/nobody/{app_name}/configs/conf-{conf_file}/_reload'
    try:
        # Reload the configuration file
        response, content = rest.simpleRequest(
            reload_api,
            sessionKey=session_key,
            method='GET',
            getargs={'output_mode': 'json'},
            raiseAllErrors=True
        )

        if response.status != 200:
            logger.error("Failed to reload configuration file {} | Status: {} | Response: {}".format(
                conf_file, response.status, content))

    except Exception as e:
        logger.error("Error reloading configuration file: {}".format(str(e)), exc_info=True)
        raise


def update_collections_conf(session_key, collection_name, app_name, payload):
    """
    Update the collections.conf file for a specific collection.

    Args:
        session_key: Splunk session key
        collection_name: Name of the KVStore collection
        app_name: Name of the Splunk app
        payload: Dictionary containing the collection configuration
    """
    server_uri = rest.makeSplunkdUri()
    collection_api = f'{server_uri}servicesNS/nobody/{app_name}/configs/conf-collections/{collection_name}'
    try:
        # Update the collection configuration
        response, content = rest.simpleRequest(
            collection_api,
            sessionKey=session_key,
            method='POST',
            getargs={'output_mode': 'json'},
            postargs=payload,
            raiseAllErrors=True
        )

        if response.status == 200:
            reload_conf_file(session_key, 'collections', app_name)
            logger.info(
                "message=update_collections_conf | Successfully updated and reloaded"
                " collections.conf for collection {}".format(collection_name))
            return True
        else:
            logger.error("Failed to update collection {} | Status: {} | Response: {}".format(
                collection_name, response.status, content))
            return False

    except Exception as e:
        logger.error("Error updating collection configuration: {}".format(str(e)), exc_info=True)
        raise


def update_kvstore_schema(session_key, collection_name, events):
    """
    Update the schema of a KVStore collection based on the provided events.

    Args:
        session_key: Splunk session key
        collection_name: Name of the KVStore collection
        events: List of events to update the schema with
    """
    logger.info(
        "message=update_kvstore_schema | Begin verification of collection schema"
        " for collection {}".format(collection_name))

    # 1. Get current schema from collections.conf
    try:
        collections_data = read_collections_conf(session_key, collection_name, ta_name)
    except Exception as e:
        logger.error(
            "message=update_kvstore_schema | Failed to get collections "
            "config for collection {}. Error {}".format(collection_name, str(e)))
        return
    existing_mapping_in_kvstore = get_field_names_from_collection_data(collections_data)
    existing_fields_in_kvstore = set(k for k in existing_mapping_in_kvstore)

    # 2. Get fields from events
    event_fields = set()
    for event in events:
        event_fields.update(event.keys())

    # 3. Get new fields to add and ignore _key which is internal
    # field to Splunk.
    new_fields = (event_fields - {"_key"}) - existing_fields_in_kvstore

    if not new_fields:
        logger.info(
            "message=update_kvstore_schema | No new fields to add to KVStore "
            "collection {}".format(collection_name))
        return
    else:
        payload = {}
        # Add existing fields to payload
        for field, value_type in existing_mapping_in_kvstore.items():
            payload[f'field.{field}'] = value_type

        # Add new fields to payload
        for field in new_fields:
            if field in ["_key"]:
                continue
            payload[f'field.{field}'] = 'string'  # Default type is string

        logger.debug(
            "message=update_kvstore_schema | KVStore update payload for "
            "collection {}: {}".format(collection_name, payload))
        update_status = update_collections_conf(session_key, collection_name, ta_name, payload)
        if update_status:
            logger.info(
                "message=update_kvstore_schema | Successfully updated collection {} "
                "with {} new fields".format(collection_name, len(new_fields)))

            # Update transforms.conf to make the new fields searchable
            update_transforms_config(
                session_key=session_key,
                collection_name=collection_name,
                new_fields=new_fields,
                app_name=ta_name
            )
        else:
            logger.error(
                "message=update_kvstore_schema | Failed to update collection {} "
                "with {} new fields".format(collection_name, len(new_fields)))

        logger.info(
            "message=update_kvstore_schema | Completed verifying KVStore schema "
            "for collection {}".format(collection_name))


def upsert_to_kvstore(session_key, events: list, object_type: str, collection_name=None) -> None:
    """
    Handle upserting processed events into the appropriate KV Store collection.

    Args:
        session_key (str): Splunk session key for KVStoreManager.
        events (list): List of events to be processed and upserted.
        object_type (str): Cisco Intersight object type string (e.g., "license.LicenseInfo").
        collection_name: If caller has passed collection_name.

    Returns:
        None
    """
    if collection_name:
        collection = collection_name
    else:
        collection = objecttype_to_collection(object_type)
    if not collection:
        return

    kvstore_manager = KVStoreManager(session_key=session_key)
    processed_events = process_json_input(events)
    update_kvstore_schema(session_key, collection, processed_events)
    kvstore_manager.upsert(processed_events, collection)
    logger.info(
        "message=ingest_data_logic | Upserted %d events for objectType='%s' to KVStore",
        len(processed_events), object_type
    )


def objecttype_to_collection(object_type: str) -> str:
    """
    Map a given Cisco Intersight ObjectType string to the corresponding KV Store collection name.

    Args:
        object_type (str): The ObjectType string (e.g., "equipment.Fan", "compute.PhysicalSummary").

    Returns:
        str: The name of the corresponding KV Store collection.
             Returns None if no mapping is found.
    """
    mapping_dict = CollectionConstants.INVENTORY_MAPPINGS
    collection_name = mapping_dict.get(object_type.lower(), {}).get("collection")
    if not collection_name:
        logger.error(
            "message=ingest_data_logic | No KVStore collection found for "
            "objectType: {}".format(object_type)
        )
    return collection_name


def sanitize_keys(obj):
    """Recursively sanitize keys in a dict/list by replacing '.' with '_' and removing '$'.

    Args:
        obj: Dictionary or list to sanitize

    Returns:
        Sanitized object with cleaned keys
    """
    if isinstance(obj, dict):
        new_dict = {}
        for key, value in obj.items():
            safe_key = key.replace(".", "_").replace("$", "")
            new_dict[safe_key] = sanitize_keys(value)
        return new_dict
    elif isinstance(obj, list):
        return [sanitize_keys(item) for item in obj]
    else:
        return obj


def flatten_json_structure(data: Union[Dict, List], prefix: str = "") -> Dict:
    """
    Flatten nested JSON but keep lists wrapped in a dict. Use underscores as separators.

    Drop keys ending with 'classid' or 'link'. Replace nulls with '-'.
    Adds splunk_managed_last_seen (from ModTime) and splunk_managed_lifecycle (default 'PRESENT') fields.
    """
    if isinstance(data, dict):

        for key, value in data.items():

            # Skip classid or link fields
            if key in ("ClassId"):
                continue

            data[key] = sanitize_keys(value)

            if isinstance(value, list):
                data[key] = {key: value}

        # Add splunk-specific fields only at the root level (no prefix)
        if not prefix:
            data["splunk_managed_last_seen"] = data.get("ModTime")
            data["splunk_managed_lifecycle"] = "PRESENT"
    else:
        raise ValueError("Expected a dictionary or list of dictionaries")


def process_json_input(json_input: Union[Dict, List[Dict]]) -> List[Dict]:
    """
    Flattens one or more JSON objects for Splunk KV Store.

    - Removes keys ending in 'classid' or 'link'
    - Wraps lists in dicts
    - Replaces nulls with '-'
    """
    flattened = []

    if isinstance(json_input, dict):
        json_input = [json_input]

    for obj in json_input:
        if not isinstance(obj, dict):
            continue

        top_level_moid = obj.get("Moid", "-")
        account_moid = obj.get("AccountMoid", "-")
        flatten_json_structure(obj)
        obj["_key"] = f"{account_moid}_{top_level_moid}"
        flattened.append(obj)

    return flattened


def get_stale_records(session_key: str, collection_name: str, retention_days: int = 1) -> List[Dict]:
    """
    Identify stale records in a KVStore collection based on splunk_managed_last_seen timestamp.

    Fetches only Moid, splunk_account_name, and _key fields for multi-account processing.

    Args:
        session_key (str): Splunk session key for KVStoreManager.
        collection_name (str): Name of the KVStore collection to check.
        retention_days (int): Number of days to consider a record stale (default: 1).

    Returns:
        List[Dict]: List of stale records with Moid, splunk_account_name, and _key fields.
    """
    try:
        kvstore_manager = KVStoreManager(session_key=session_key)

        # Calculate cutoff date
        cutoff_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=retention_days)
        cutoff_timestamp = cutoff_date.isoformat() + 'Z'
        # Query for records with splunk_managed_last_seen older than cutoff and still PRESENT
        query_filter = {
            "splunk_managed_last_seen": {"$lt": cutoff_timestamp},
            "splunk_managed_lifecycle": "PRESENT"
        }

        # Include account_name for fallback matching
        fields_to_fetch = ["Moid", "AccountMoid", "account_name", "_key"]

        stale_records = kvstore_manager.get(
            collection_name, fields=fields_to_fetch, query=query_filter
        )
        # Filter to ensure we have all required fields (Moid, AccountMoid, _key)
        # Note: account_name is optional for backward compatibility
        valid_records = [
            record for record in stale_records
            if record.get('Moid') and record.get('AccountMoid') and record.get('_key')
        ]

        logger.info(
            "Found %d valid stale records (with Moid, AccountMoid, and key) in collection %s "
            "older than %d days (total found: %d)",
            len(valid_records), collection_name, retention_days, len(stale_records)
        )

        return valid_records

    except Exception as e:
        logger.error("Error fetching stale records from %s: %s", collection_name, str(e))
        return []


def group_records_by_account_and_collection(
    stale_records: List[Dict], collection_name: str
) -> tuple:
    """
    Group stale records by AccountMoid and collection for multi-account processing.

    Also extracts account_name from records for fallback matching when AccountMoid is incorrect.

    Args:
        stale_records (List[Dict]): List of stale records with Moid, AccountMoid, account_name, and _key fields.
        collection_name (str): Name of the KVStore collection.

    Returns:
        tuple: (grouped_data, account_names_map)
            - grouped_data: Dict[str, Dict[str, List[Dict]]] - Nested dictionary grouped
            by AccountMoid -> collection_name -> records
            - account_names_map: Dict[str, str] - Mapping of AccountMoid to account_name for fallback
    """
    grouped_data = {}
    account_names_map = {}  # Map AccountMoid to account_name for fallback

    for record in stale_records:
        account_moid = record.get('AccountMoid')
        account_name = record.get('account_name')

        if not account_moid:
            continue

        if account_moid not in grouped_data:
            grouped_data[account_moid] = {}

        if collection_name not in grouped_data[account_moid]:
            grouped_data[account_moid][collection_name] = []

        grouped_data[account_moid][collection_name].append(record)

        # Store account_name for this AccountMoid if available
        if account_name and account_moid not in account_names_map:
            account_names_map[account_moid] = account_name

    logger.info(
        "Grouped %d records by %d AccountMoids for collection %s (%d with account_name)",
        len(stale_records), len(grouped_data), collection_name, len(account_names_map)
    )

    return grouped_data, account_names_map


def batch_verify_moids_via_api(moids: List[str], api_endpoint: str,
                               rest_helper, batch_size: int = 100) -> List[str]:
    """
    Verify existence of Moids in Intersight via API calls in batches using rest_helper.

    Args:
        moids (List[str]): List of Moids to verify.
        api_endpoint (str): Intersight API endpoint for the object type.
        rest_helper: RestHelper instance for making API calls.
        batch_size (int): Number of Moids to check per API call (default: 100).

    Returns:
        List[str]: List of Moids that still exist in Intersight.
    """
    existing_moids = []

    try:
        # Process Moids in batches
        for i in range(0, len(moids), batch_size):
            batch_moids = moids[i:i + batch_size]

            # Create filter for batch of Moids
            moid_filter = "Moid IN ('{}')".format("','".join(batch_moids))

            # Make API call using rest_helper
            try:
                if api_endpoint == Endpoints.HCL_STATUSES:
                    params = {'$filter': moid_filter, '$select': 'Moid, ManagedObject'}
                else:
                    params = {'$filter': moid_filter, '$select': 'Moid'}
                response = rest_helper.get(endpoint=api_endpoint, params=params)

                if response and 'Results' in response:
                    # Extract Moids from response
                    batch_existing = [item.get('Moid') for item in response['Results'] if item.get('Moid')]
                    existing_moids.extend(batch_existing)

                    logger.info(
                        "Batch verification: %d/%d Moids found in Intersight",
                        len(batch_existing), len(batch_moids)
                    )

            except Exception as batch_error:
                logger.error("Error verifying batch of Moids: %s", str(batch_error))
                continue

    except Exception as e:
        logger.error("Error in batch verification process: %s", str(e))

    return existing_moids


def update_moids_last_seen(session_key: str, collection_name: str, existing_moids: List[str]) -> int:
    """
    Update splunk_managed_last_seen timestamp for existing (PRESENT) Moids.

    This refreshes their last seen time to prevent immediate re-checking.

    Args:
        session_key (str): Splunk session key for KVStoreManager.
        collection_name (str): Name of the KVStore collection.
        existing_moids (List[str]): List of Moids that still exist in Intersight.

    Returns:
        int: Number of records updated.
    """
    if not existing_moids:
        return 0

    try:
        kvstore_manager = KVStoreManager(session_key=session_key)
        updated_count = 0
        current_timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat() + 'Z'

        logger.info(
            "Updating last_seen timestamp for %d existing Moids in collection %s",
            len(existing_moids), collection_name
        )

        # Process each Moid individually to avoid any URL length or parameter issues
        batch_updates = []
        batch_size = 50  # Process updates in batches

        for i, moid in enumerate(existing_moids):
            try:
                # Query for this specific Moid - fetch ALL fields to preserve them
                query_dict = {"Moid": moid}

                # Call get method with explicit positional arguments (no fields restriction)
                records = kvstore_manager.get(collection_name, None, query_dict)

                # Add to updates if record found
                for record in records:
                    if record.get("Moid") == moid:
                        # Preserve the entire record and only update the timestamp
                        updated_record = record.copy()  # Create a copy to preserve all fields
                        updated_record["splunk_managed_last_seen"] = current_timestamp

                        batch_updates.append(updated_record)
                        break  # Only need first match

            except Exception as moid_error:
                logger.error(
                    "Error querying Moid %s: %s",
                    moid, str(moid_error)
                )
                continue

            # Process batch when we reach batch_size or end of list
            if len(batch_updates) >= batch_size or i == len(existing_moids) - 1:
                if batch_updates:
                    try:
                        kvstore_manager.upsert(batch_updates, collection_name)
                        updated_count += len(batch_updates)
                        logger.debug(
                            "Updated %d records in batch (processed %d/%d Moids)",
                            len(batch_updates), i + 1, len(existing_moids)
                        )
                        batch_updates = []  # Reset for next batch
                    except Exception as batch_error:
                        logger.error(
                            "Error updating batch at Moid %d: %s",
                            i + 1, str(batch_error)
                        )
                        batch_updates = []  # Reset and continue

        logger.info(
            "Successfully updated last_seen timestamp for %d records in collection %s",
            updated_count, collection_name
        )
        return updated_count

    except Exception as e:
        logger.error(
            "Error updating last_seen for existing Moids in %s: %s",
            collection_name, str(e)
        )
        return 0


def mark_moids_as_absent(session_key: str, collection_name: str,
                         absent_moids: List[str]) -> int:
    """
    Mark specified Moids as ABSENT in the KVStore collection.

    Args:
        session_key (str): Splunk session key for KVStoreManager.
        collection_name (str): Name of the KVStore collection.
        absent_moids (List[str]): List of Moids to mark as ABSENT.

    Returns:
        int: Number of records successfully updated.
    """
    updated_count = 0

    try:
        kvstore_manager = KVStoreManager(session_key=session_key)

        for moid in absent_moids:
            try:
                # Query to find the record by Moid using get method
                query = {"Moid": moid}
                records = kvstore_manager.get(collection_name, query=query)

                if records:
                    record = records[0]
                    record_key = record.get('_key')

                    if record_key:
                        # Update the record with ABSENT status
                        # Use upsert with the existing record data plus the update
                        updated_record = record.copy()
                        updated_record["splunk_managed_lifecycle"] = "ABSENT"
                        updated_record["splunk_managed_last_seen"] = datetime.datetime.now(
                            datetime.timezone.utc
                        ).isoformat() + 'Z'

                        # Upsert the updated record (this will update the existing record)
                        kvstore_manager.upsert([updated_record], collection_name)
                        updated_count += 1

                        logger.info("Marked Moid %s as ABSENT in %s", moid, collection_name)

            except Exception as record_error:
                logger.error("Error updating Moid %s: %s", moid, str(record_error))
                continue

    except Exception as e:
        logger.error("Error marking Moids as ABSENT: %s", str(e))

    logger.info("Successfully marked %d records as ABSENT in %s", updated_count, collection_name)
    return updated_count


def mark_moids_as_account_not_found(
    session_key: str, collection_name: str, moids: List[str]
) -> int:
    """
    Mark specified Moids as AccountNotFound in the KVStore collection.

    This is used when the account credentials are invalid or the account no longer exists.

    Args:
        session_key (str): Splunk session key for KVStoreManager.
        collection_name (str): Name of the KVStore collection.
        moids (List[str]): List of Moids to mark as AccountNotFound.

    Returns:
        int: Number of records successfully updated.
    """
    updated_count = 0

    try:
        kvstore_manager = KVStoreManager(session_key=session_key)

        for moid in moids:
            try:
                # Query to find the record by Moid using get method
                query = {"Moid": moid}
                records = kvstore_manager.get(collection_name, query=query)

                if records:
                    record = records[0]
                    record_key = record.get('_key')

                    if record_key:
                        # Update the record with AccountNotFound status
                        # Use upsert with the existing record data plus the update
                        updated_record = record.copy()
                        updated_record["splunk_managed_lifecycle"] = "AccountNotFound"
                        # Upsert the updated record (this will update the existing record)
                        kvstore_manager.upsert([updated_record], collection_name)
                        updated_count += 1

                        logger.info("Marked Moid %s as AccountNotFound in %s", moid, collection_name)

            except Exception as record_error:
                logger.error("Error updating Moid %s to AccountNotFound: %s", moid, str(record_error))
                continue

    except Exception as e:
        logger.error("Error marking Moids as AccountNotFound: %s", str(e))

    logger.info("Successfully marked %d records as AccountNotFound in %s", updated_count, collection_name)
    return updated_count


def update_account_info_in_kvstore(
    session_key: str, collection_name: str, moids: List[str],
    correct_account_moid: str, correct_account_name: str
) -> int:
    """
    Update AccountMoid and account_name fields for records that have incorrect values.

    This is used when try_all_accounts fallback successfully identifies the correct account.

    Args:
        session_key (str): Splunk session key for KVStoreManager.
        collection_name (str): Name of the KVStore collection.
        moids (List[str]): List of Moids to update.
        correct_account_moid (str): The correct AccountMoid to set.
        correct_account_name (str): The correct account_name to set.

    Returns:
        int: Number of records updated.
    """
    updated_count = 0

    logger.info(
        "Attempting to update %d records in collection %s with AccountMoid: %s, account_name: %s. Moids: %s",
        len(moids), collection_name, correct_account_moid, correct_account_name, moids
    )

    if not moids:
        logger.warning("No Moids provided to update. Returning 0.")
        return 0

    try:
        kvstore_manager = KVStoreManager(session_key)
        logger.info("KVStoreManager initialized successfully")

        for i, moid in enumerate(moids):
            logger.info("Processing Moid %d/%d: %s", i + 1, len(moids), moid)
            try:
                # Get the existing record
                query = json.dumps({"Moid": moid})
                logger.info("Querying collection %s for Moid: %s", collection_name, moid)
                records = kvstore_manager.query(collection_name, query=query)

                if records:
                    record = records[0]
                    logger.info(
                        "Found record for Moid %s. Current AccountMoid: %s, current account_name: %s",
                        moid, record.get('AccountMoid'), record.get('account_name')
                    )

                    # Update with correct account information
                    updated_record = record.copy()
                    old_account_moid = updated_record.get("AccountMoid")
                    old_account_name = updated_record.get("account_name")

                    updated_record["AccountMoid"] = correct_account_moid
                    updated_record["account_name"] = correct_account_name

                    logger.info(
                        "Upserting record for Moid %s to collection %s...",
                        moid, collection_name
                    )

                    # Upsert the updated record
                    logger.info("Calling kvstore_manager.upsert for Moid: %s", moid)
                    kvstore_manager.upsert([updated_record], collection_name)
                    logger.info("Upsert completed for Moid: %s", moid)

                    updated_count += 1
                    logger.info("Incremented updated_count to: %d", updated_count)

                    logger.info(
                        "Successfully updated Moid %s: AccountMoid [%s → %s], account_name [%s → %s]",
                        moid, old_account_moid, correct_account_moid,
                        old_account_name, correct_account_name
                    )
                else:
                    logger.warning(
                        "No record found in collection %s for Moid: %s (query returned empty)",
                        collection_name, moid
                    )

            except Exception as record_error:
                logger.exception(
                    "Exception while updating account info for Moid %s in collection %s: %s",
                    moid, collection_name, str(record_error)
                )
                continue

    except Exception as e:
        logger.exception(
            "Exception in update_account_info_in_kvstore for collection %s: %s",
            collection_name, str(e)
        )

    logger.info(
        "========== UPDATE SUMMARY ==========\n"
        "Collection: %s\n"
        "Total Moids to update: %d\n"
        "Successfully updated: %d\n"
        "Failed: %d\n"
        "=====================================",
        collection_name, len(moids), updated_count, len(moids) - updated_count
    )

    if updated_count == 0 and len(moids) > 0:
        logger.error(
            "CRITICAL: 0 records updated out of %d. Check logs above for errors or warnings. "
            "The records may not exist in KVStore or there may be permission issues.",
            len(moids)
        )

    return updated_count


def process_lifecycle_tracking(
    session_key: str, retention_days: int = 1, track_types: List[str] = None, custom_mappings: Dict = None
):
    """Process lifecycle tracking for all or specified KVStore collections with multi-account support.

    Now supports dynamic collections created by custom inputs.

    Groups records by AccountMoid and creates RestHelper instances per account.

    Args:
        session_key (str): Splunk session key for KVStoreManager.
        retention_days (int): Number of days to consider a record stale (default: 7).
        track_types (List[str]): List of object types to track (None for all).
        custom_mappings (Dict): Custom input mappings from inputs.conf

    Returns:
        Dict[str, Dict[str, int]]: Summary of processing results per AccountMoid and collection.
    """
    results = {}
    rest_helper_cache = {}  # Cache RestHelper instances by AccountMoid
    track_types_lower = []

    if track_types:
        track_types_lower = [t.lower() for t in track_types]

    # Get predefined mappings
    inventory_mapping = CollectionConstants.INVENTORY_MAPPINGS.copy()

    # Add custom input mappings if provided
    if custom_mappings:
        logger.info("Adding %d custom input mappings to lifecycle tracking", len(custom_mappings))
        inventory_mapping.update(custom_mappings)

    logger.info("Begin process_lifecycle_tracking with %d total mappings", len(inventory_mapping))

    # Rest of the function remains the same...
    for objecttype, mapping in inventory_mapping.items():
        if track_types and objecttype.lower() not in track_types_lower:
            logger.info("Skipping objecttype %s", objecttype)
            continue

        collection_name = mapping["collection"]
        api_endpoint = mapping["api_endpoint"]

        # Step 1: Get stale records (with account info)
        stale_records = get_stale_records(session_key, collection_name, retention_days)
        logger.info("Found %d stale records for collection %s", len(stale_records), collection_name)

        if not stale_records:
            results[collection_name] = {}
            continue

        # Step 2: Group records by account and collection
        grouped_records, account_names_map = group_records_by_account_and_collection(
            stale_records, collection_name)

        if not grouped_records:
            results[collection_name] = {}
            continue

        # Step 3: Process each AccountMoid group
        collection_results = {}

        for account_moid, account_collections in grouped_records.items():
            account_name = account_names_map.get(account_moid)
            logger.info("Validating collections for AccountMoid %s (account_name: %s)", account_moid, account_name)
            try:
                # Get or create RestHelper for this AccountMoid
                if account_moid not in rest_helper_cache:
                    try:
                        # Try to get credentials by AccountMoid, with account_name as fallback
                        account_config = get_credentials_by_account_moid(
                            account_moid, session_key, account_name=account_name)
                        # Add session_key to config for RestHelper Splunk API calls
                        account_config["session_key"] = session_key
                        rest_helper = RestHelper(
                            intersight_config=account_config,
                            logger=logger
                        )

                        rest_helper_cache[account_moid] = rest_helper

                        if account_name:
                            logger.info(
                                "Created RestHelper for AccountMoid: %s (matched via account_name: %s)",
                                account_moid, account_name
                            )
                        else:
                            logger.info("Created RestHelper for AccountMoid: %s", account_moid)
                    except Exception as e:
                        logger.error("Failed to create RestHelper for AccountMoid %s: %s", account_moid, str(e))
                        logger.info("Marking all stale records for AccountMoid %s as AccountNotFound", account_moid)

                        # Mark all records for this account as AccountNotFound
                        total_marked = 0
                        for coll_name, records in account_collections.items():
                            record_moids = [record.get('Moid') for record in records if record.get('Moid')]
                            if record_moids:
                                marked_count = mark_moids_as_account_not_found(
                                    session_key, coll_name, record_moids
                                )
                                total_marked += marked_count
                                logger.info(
                                    "Marked %d records as AccountNotFound in collection %s for AccountMoid %s",
                                    marked_count, coll_name, account_moid
                                )

                        collection_results[account_moid] = total_marked
                        continue

                rest_helper = rest_helper_cache[account_moid]

                # Process records for this AccountMoid
                for coll_name, records in account_collections.items():
                    record_moids = [record.get('Moid') for record in records if record.get('Moid')]
                    if not record_moids:
                        # Don't overwrite existing count, just skip this collection
                        logger.debug("No valid Moids for collection %s, account %s", coll_name, account_moid)
                        continue

                    # Step 4: Verify Moids via API using account-specific rest_helper
                    existing_moids = batch_verify_moids_via_api(
                        record_moids, api_endpoint, rest_helper
                    )

                    # Step 5: Update last_seen timestamp for existing (PRESENT) Moids
                    refreshed_count = 0
                    if existing_moids:
                        refreshed_count = update_moids_last_seen(
                            session_key, coll_name, existing_moids
                        )

                    # Step 6: Find Moids that no longer exist
                    absent_moids = list(set(record_moids) - set(existing_moids))

                    # Step 7: Mark non-existing Moids as ABSENT
                    absent_count = 0
                    if absent_moids:
                        absent_count = mark_moids_as_absent(
                            session_key, coll_name, absent_moids
                        )

                    # Accumulate processed count (don't overwrite if processing multiple collections)
                    current_count = collection_results.get(account_moid, 0)
                    collection_results[account_moid] = current_count + refreshed_count + absent_count

                    logger.info(
                        "AccountMoid %s, Collection %s: %d are PRESENT, %d are ABSENT (total for account so far: %d)",
                        account_moid, coll_name, len(existing_moids), len(absent_moids),
                        collection_results[account_moid]
                    )

            except Exception as account_error:
                logger.error("Error processing AccountMoid %s: %s", account_moid, str(account_error))
                collection_results[account_moid] = -1

        results[collection_name] = collection_results

    # Log summary
    total_accounts = len(rest_helper_cache)
    total_collections = len(results)
    total_processed = sum(
        sum(account_results.values() if isinstance(account_results, dict) else [account_results])
        for account_results in results.values()
        if isinstance(account_results, dict)
    )

    logger.info(
        "========== LIFECYCLE TRACKING SUMMARY ==========\n"
        "Total accounts processed: %d\n"
        "Total collections processed: %d\n"
        "Total records processed: %d\n"
        "Collections breakdown: %s\n"
        "=================================================",
        total_accounts, total_collections, total_processed,
        {coll: sum(acc_res.values()) if isinstance(acc_res, dict) else acc_res
         for coll, acc_res in results.items()}
    )
