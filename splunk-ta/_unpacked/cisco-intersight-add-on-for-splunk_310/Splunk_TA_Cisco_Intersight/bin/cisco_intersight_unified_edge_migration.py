#!/usr/bin/env python
"""
Cisco Intersight Unified Edge Migration Command.

This custom Splunk command migrates Unified Edge (UCSXECMC) inventory data
for existing installations. It fetches fresh data for specific APIs, compares
with existing KVStore data, and ingests only missing/new Unified Edge items.
"""

# This import is required to resolve the absolute paths of supportive modules
import import_declare_test  # pylint: disable=unused-import

import sys
import time
import json
import traceback
import copy
from splunklib.modularinput.event_writer import EventWriter
from splunklib.searchcommands import (
    dispatch,
    GeneratingCommand,
    Configuration,
    Option
)
from typing import Iterator, Dict, Any, List
from intersight_helpers.logger_manager import setup_logging
from intersight_helpers.rest_helper import RestHelper
from intersight_helpers.event_ingestor import EventIngestor
from intersight_helpers.constants import InventoryApis
from intersight_helpers.kvstore_helper import upsert_to_kvstore
from intersight_helpers.kvstore import KVStoreManager
from splunk.clilib import cli_common
from splunk import rest
from inventory import INVENTORY

logger = setup_logging("ta_intersight_unified_edge_migration")

# Get inventory configurations
inventory_config = getattr(InventoryApis, "inventory_config", {})
multi_api_inventory_config = getattr(InventoryApis, "multi_api_inventory_config", {})


@Configuration()
class CiscoIntersightUnifiedEdgeMigration(GeneratingCommand):
    """
    Custom Splunk generating command to migrate Unified Edge inventory data.

    This command fetches fresh data for specific APIs, compares with existing
    KVStore collections, and ingests only missing Unified Edge items.
    """

    # Optional parameter to specify the saved search name for auto-disable functionality
    saved_search_name = Option(
        doc='Name of the saved search to disable after successful migration',
        require=False
    )

    # Class-level tracking variables
    total_events_processed = 0
    total_events_ingested = 0
    migration_successful = False
    migration_required = False

    # APIs that need Unified Edge migration
    # These are the 5 APIs from inventory_config and multi_api_inventory_config
    MIGRATION_APIS = {
        "server/Profiles": {
            "source": "multi_api_inventory_config",
            "parent_key": "compute",
            "kvstore_collection": "cisco_intersight_server_profiles"
        },
        "chassis/Profiles": {
            "source": "multi_api_inventory_config",
            "parent_key": "compute",
            "kvstore_collection": "cisco_intersight_chassis_profiles"
        },
        "fabric/SwitchProfiles": {
            "source": "multi_api_inventory_config",
            "parent_key": "fabric",
            "kvstore_collection": "cisco_intersight_fabric_switchprofiles"
        },
        "fabric/SwitchClusterProfiles": {
            "source": "multi_api_inventory_config",
            "parent_key": "fabric",
            "kvstore_collection": "cisco_intersight_fabric_switchclusterprofiles"
        }
    }

    # Prerequisite migration that must be completed before Unified Edge migration
    INDEX_TO_KVSTORE_MIGRATION_NAME_INVENTORY = "splunk_ta_cisco_intersight_index_to_kvstore_migration_inventory"
    INDEX_TO_KVSTORE_MIGRATION_NAME_INVENTORY_COMPUTE = (
        "splunk_ta_cisco_intersight_index_to_kvstore_migration_inventory_compute"
    )

    def read_conf_stanzas(self, conf_name):
        """
        Read all stanzas from a .conf file and returns a dict.

        Returns:
            dict: Dictionary of stanzas with their configurations
        """
        try:
            conf_dict = cli_common.getConfStanzas(conf_name)
            return conf_dict
        except Exception as e:
            logger.error(
                "message=conf_read | Error reading {}.conf: {}".format(conf_name, e)
            )
            return {}

    def is_saved_search_enabled(self, session_key: str, saved_search_name: str) -> bool:
        """
        Check if a saved search is enabled.

        Args:
            session_key: The session key for authentication
            saved_search_name: Name of the saved search to check

        Returns:
            bool: True if enabled, False if disabled or not found
        """
        try:
            endpoint = f"/servicesNS/nobody/Splunk_TA_Cisco_Intersight/saved/searches/{saved_search_name}"

            # Get the saved search configuration
            response, content = rest.simpleRequest(
                endpoint,
                method='GET',
                sessionKey=session_key,
                getargs={'output_mode': 'json'},
                raiseAllErrors=False
            )

            if response['status'] == '200':
                search_config = json.loads(content)

                # Check the disabled field in the entry
                if 'entry' in search_config and len(search_config['entry']) > 0:
                    disabled = search_config['entry'][0].get('content', {}).get('disabled', '0')

                    # disabled='0' means enabled, disabled='1' means disabled
                    is_enabled = (disabled in {'0', 0})

                    logger.info(
                        "message=is_saved_search_enabled | Saved search '%s' is %s",
                        saved_search_name,
                        "enabled" if is_enabled else "disabled"
                    )
                    return is_enabled
                else:
                    logger.warning(
                        "message=is_saved_search_enabled | No entry found for saved search: %s",
                        saved_search_name
                    )
                    return False
            else:
                logger.warning(
                    "message=is_saved_search_enabled | Failed to get saved search: %s. "
                    "Status: %s. Assuming it's disabled.",
                    saved_search_name,
                    response['status']
                )
                return False

        except Exception as e:
            logger.error(
                "message=is_saved_search_enabled | Exception occurred while checking "
                "saved search: %s. Error: %s. Assuming it's disabled.",
                saved_search_name,
                str(e)
            )
            return False

    def disable_saved_search(self, session_key: str, saved_search_name: str) -> bool:
        """
        Disable a saved search after successful migration.

        Args:
            session_key: The session key for authentication
            saved_search_name: Name of the saved search to disable

        Returns:
            bool: True if successfully disabled, False otherwise
        """
        try:
            endpoint = f"/servicesNS/nobody/Splunk_TA_Cisco_Intersight/saved/searches/{saved_search_name}"

            # Update the saved search to disable it
            response, content = rest.simpleRequest(
                endpoint,
                method='POST',
                sessionKey=session_key,
                postargs={
                    'disabled': '1'
                },
                raiseAllErrors=False
            )

            if response['status'] == '200':
                logger.info(
                    "message=disable_saved_search | Successfully disabled saved search: %s",
                    saved_search_name
                )
                return True
            else:
                logger.error(
                    "message=disable_saved_search | Failed to disable saved search: %s. "
                    "Status: %s, Content: %s",
                    saved_search_name,
                    response['status'],
                    content
                )
                return False

        except Exception as disable_error:
            logger.error(
                "message=disable_saved_search | Exception occurred while disabling "
                "saved search: %s. Error: %s",
                saved_search_name,
                str(disable_error)
            )
            return False

    def get_kvstore_data(self, session_key: str, collection_name: str) -> Dict[str, Dict[str, Any]]:
        """
        Get all data from a KVStore collection indexed by Moid.

        Args:
            session_key: The session key for authentication
            collection_name: Name of the KVStore collection

        Returns:
            dict: Dictionary of existing items indexed by Moid
        """
        try:
            kvstore_manager = KVStoreManager(session_key=session_key)
            # Get all data from collection (with pagination support)
            existing_data = kvstore_manager.get(collection_name)

            # Index by Moid for fast lookup
            moid_index = {}
            for item in existing_data:
                moid = item.get("Moid")
                if moid:
                    moid_index[moid] = item

            logger.info(
                "message=get_kvstore_data | Retrieved %d items from collection: %s",
                len(moid_index),
                collection_name
            )
            return moid_index

        except Exception as e:
            logger.error(
                "message=get_kvstore_data | Error retrieving data from collection %s: %s",
                collection_name,
                str(e)
            )
            return {}

    def compare_and_get_new_items(
        self,
        api_items: List[Dict[str, Any]],
        kvstore_items: Dict[str, Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Compare API items with KVStore items and return new/missing items.

        Args:
            api_items: Items fetched from Intersight API
            kvstore_items: Existing items from KVStore indexed by Moid

        Returns:
            list: List of new items not present in KVStore
        """
        new_items = []

        for item in api_items:
            moid = item.get("Moid")
            if moid and moid not in kvstore_items:
                new_items.append(item)

        logger.info(
            "message=compare_and_get_new_items | Found %d new items out of %d API items",
            len(new_items),
            len(api_items)
        )
        return new_items

    def fetch_api_data(
        self,
        intersight_rest_helper: RestHelper,
        api_endpoint: str,
        config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Fetch fresh data from an API endpoint (ignoring checkpoint).

        Args:
            intersight_rest_helper: RestHelper instance
            api_endpoint: The API endpoint to fetch data from
            config: API configuration

        Returns:
            list: List of items fetched from the API
        """
        try:
            logger.info(
                "message=fetch_api_data | Fetching data from API: %s",
                api_endpoint
            )

            # Create a copy of config to avoid modifying the original
            fetch_config = copy.deepcopy(config)

            # Fetch data without checkpoint and without event ingestor (fresh fetch, no ingestion)
            fetch_kwargs = {
                "inventory_checkpoint_dict": {"time": None, "status": True},
                "inventory": api_endpoint,
                "config": fetch_config,
                "event_ingestor": None,  # Don't ingest, just return data
                "add_modtime_filter": False  # Don't filter by modification time
            }

            # This will return the raw data without ingesting
            result = intersight_rest_helper.fetch_and_ingest_inventory_data(fetch_kwargs)

            logger.info(
                "message=fetch_api_data | Fetched %d items from API: %s",
                len(result),
                api_endpoint
            )
            return result

        except Exception as e:
            logger.error(
                "message=fetch_api_data | Error fetching data from API %s: %s",
                api_endpoint,
                str(e)
            )
            logger.error(traceback.format_exc())
            return []

    def process_migration_for_api(
        self,
        process_migration_for_api_dict: Dict[str, Any]
    ) -> int:
        """
        Process migration for a single API endpoint.

        Args:
            process_migration_for_api_dict: Dictionary containing process migration for API details

            session_key: Splunk session key
            intersight_rest_helper: RestHelper instance
            event_ingestor: EventIngestor instance
            logger: Logger instance
            api_endpoint: The API endpoint to process
            api_info: Information about the API

        Returns:
            int: Number of items migrated
        """
        try:
            session_key = process_migration_for_api_dict.get("session_key")
            intersight_rest_helper = process_migration_for_api_dict.get("intersight_rest_helper")
            event_ingestor = process_migration_for_api_dict.get("event_ingestor")
            api_endpoint = process_migration_for_api_dict.get("api_endpoint")
            api_info = process_migration_for_api_dict.get("api_info")
            logger.info(
                "message=process_migration_for_api | Starting migration for API: %s",
                api_endpoint
            )

            # Get API configuration
            if api_info["source"] == "inventory_config":
                config = inventory_config.get(api_endpoint, {})
            else:
                parent_key = api_info["parent_key"]
                config = multi_api_inventory_config.get(parent_key, {}).get(api_endpoint, {})

            if not config:
                logger.warning(
                    "message=process_migration_for_api | No configuration found for API: %s",
                    api_endpoint
                )
                return 0, False

            # Step 1: Fetch fresh data from API (ignoring checkpoint)
            api_items = self.fetch_api_data(
                intersight_rest_helper,
                config.get("endpoint", api_endpoint) if api_info["source"] == "inventory_config" else api_endpoint,
                config
            )

            if not api_items:
                logger.info(
                    "message=process_migration_for_api | No items fetched from API: %s",
                    api_endpoint
                )
                return 0, True

            # Step 2: Get existing data from KVStore
            kvstore_collection = api_info["kvstore_collection"]
            existing_items = self.get_kvstore_data(session_key, kvstore_collection)

            # Step 3: Compare and get new items
            new_items = self.compare_and_get_new_items(api_items, existing_items)

            if not new_items:
                logger.info(
                    "message=process_migration_for_api | No new Unified Edge items to migrate for API: %s",
                    api_endpoint
                )
                return 0, True

            # Step 5: Ingest new items to index
            logger.info(
                "message=process_migration_for_api | Ingesting %d new Unified Edge items for API: %s",
                len(new_items),
                api_endpoint
            )

            # Call the specific ingestion function based on config
            ingest_func_name = config.get("ingest_func", "ingest_target")
            if hasattr(event_ingestor, ingest_func_name):
                ingest_func = getattr(event_ingestor, ingest_func_name)
                # Call the ingestion function
                _ = ingest_func(new_items)
                logger.info(
                    "message=process_migration_for_api | Ingested %d events using %s",
                    len(new_items),
                    ingest_func_name
                )
            else:
                logger.error(
                    "message=process_migration_for_api | Ingestion function %s not found in EventIngestor",
                    ingest_func_name
                )
                return 0, False

            # Step 6: Upsert new items to KVStore
            logger.info(
                "message=process_migration_for_api | Upserting %d new items to KVStore collection: %s",
                len(new_items),
                kvstore_collection
            )

            # Upsert to KVStore using the helper function
            # Group items by ObjectType for batch upserting
            items_by_type = {}
            for item in new_items:
                object_type = item.get("ObjectType", item.get("ClassId", ""))
                if object_type:
                    if object_type not in items_by_type:
                        items_by_type[object_type] = []
                    items_by_type[object_type].append(item)

            # Upsert each group
            for object_type, items in items_by_type.items():
                upsert_to_kvstore(
                    session_key=session_key,
                    events=items,
                    object_type=object_type
                )

            logger.info(
                "message=process_migration_for_api | Successfully migrated %d items for API: %s",
                len(new_items),
                api_endpoint
            )
            return len(new_items), True

        except Exception as e:
            logger.error(
                "message=process_migration_for_api | Error processing migration for API %s: %s",
                api_endpoint,
                str(e)
            )
            logger.error(traceback.format_exc())
            return 0, False

    def generate(self) -> Iterator[Dict[str, Any]]:
        """
        Generate migration results.

        This method is called by Splunk to execute the command. It processes
        each configured inventory input and migrates Unified Edge data.

        Yields:
            dict: Status events for the migration process
        """
        try:
            session_key = self._metadata.searchinfo.session_key
            logger.info("message=generate | Unified Edge migration started")

            # Check if index-to-kvstore migration is still running
            if (
                self.is_saved_search_enabled(session_key, self.INDEX_TO_KVSTORE_MIGRATION_NAME_INVENTORY_COMPUTE)
            ) or (
                self.is_saved_search_enabled(session_key, self.INDEX_TO_KVSTORE_MIGRATION_NAME_INVENTORY)
            ):
                logger.info(
                    "message=generate | Index-to-KVStore migration (%s) or (%s) is still enabled/running. "
                    "Deferring Unified Edge migration to next schedule.",
                    self.INDEX_TO_KVSTORE_MIGRATION_NAME_INVENTORY_COMPUTE,
                    self.INDEX_TO_KVSTORE_MIGRATION_NAME_INVENTORY
                )
                yield {
                    "_time": time.time(),
                    "migration_status": "deferred",
                    "reason": "Index-to-KVStore migration is still running",
                    "message": "Unified Edge migration deferred until Index-to-KVStore migration completes"
                }
                return

            logger.info(
                "message=generate | Index-to-KVStore migration is disabled. "
                "Proceeding with Unified Edge migration."
            )

            # Read all inventory input configurations
            conf_stanzas = self.read_conf_stanzas("inputs")

            # Track if any migration was performed
            final_migration_performed = True
            total_migrated = 0

            # Process each inventory input stanza
            for stanza_name, stanza_content in conf_stanzas.items():
                # Skip non-inventory stanzas
                if 'inventory' not in stanza_name:
                    continue

                # Check if inventory is enabled
                inventory_types = stanza_content.get('inventory', '')
                if not inventory_types:
                    continue

                logger.info(
                    "message=generate | Processing inventory input: %s",
                    stanza_name
                )

                try:
                    # Prepare input items for INVENTORY class
                    inv_class = INVENTORY()
                    start_time = time.time()

                    input_items = [{"count": 1}]

                    stanza_content["stanza_name"] = stanza_name
                    stanza_content["name"] = stanza_name.split("://")[1]
                    stanza_content["session_key"] = session_key

                    input_items.append(stanza_content)

                    # Get account info
                    account_info = inv_class.get_account_info(input_items)
                    input_items[1].update(account_info)

                    # Create REST helper and event ingestor
                    intersight_rest_helper = RestHelper(input_items[1], logger)
                    event_ingestor = EventIngestor(
                        input_items[1],
                        EventWriter(),
                        logger,
                        intersight_rest_helper.ckpt_account_name,
                        custom_index_method=True
                    )

                    # Process each API that needs migration
                    for api_endpoint, api_info in self.MIGRATION_APIS.items():
                        # Check if this API is enabled in the input
                        should_process = False

                        if api_info["source"] == "inventory_config":
                            # For inventory_config (e.g., target)
                            if api_endpoint in inventory_types:
                                should_process = True
                        else:
                            # For multi_api_inventory_config (e.g., server/Profiles)
                            parent_key = api_info["parent_key"]
                            if parent_key in inventory_types:
                                # Check if specific endpoint is enabled
                                endpoint_config_key = f"{parent_key}_endpoints"
                                enabled_endpoints = stanza_content.get(endpoint_config_key, "")
                                if enabled_endpoints:
                                    enabled_list = enabled_endpoints.split(",")
                                    if "All" in enabled_list or api_endpoint in enabled_list:
                                        should_process = True

                        if should_process:
                            process_migration_for_api_dict = {
                                "session_key": session_key,
                                "intersight_rest_helper": intersight_rest_helper,
                                "event_ingestor": event_ingestor,
                                "api_endpoint": api_endpoint,
                                "api_info": api_info
                            }
                            migrated_count, any_migration_performed = self.process_migration_for_api(
                                process_migration_for_api_dict
                            )

                            total_migrated += migrated_count
                            if not any_migration_performed:
                                final_migration_performed = False

                    # Log API call statistics
                    total_time_taken = time.time() - start_time
                    logger.info(
                        "message=api_statistics | Input: %s, API calls: %d, Time: %.2fs",
                        stanza_name,
                        intersight_rest_helper.api_call_count,
                        total_time_taken
                    )

                except Exception as e:
                    logger.error(
                        "message=generate | Error processing input %s: %s",
                        stanza_name,
                        str(e)
                    )
                    logger.error(traceback.format_exc())

            # Log final migration results
            logger.info(
                "message=generate | Unified Edge migration completed. Total items migrated: %d",
                total_migrated
            )

            # Generate status event
            yield {
                "_time": time.time(),
                "migration_status": "completed",
                "total_items_migrated": total_migrated,
                "migration_performed": final_migration_performed
            }

            # Disable the saved search if migration was successful
            if final_migration_performed:
                logger.info(
                    "message=generate | Migration successful, disabling saved search: %s",
                    self.saved_search_name
                )
                if self.disable_saved_search(session_key, self.saved_search_name):
                    logger.info(
                        "message=generate | Successfully disabled saved search: %s",
                        self.saved_search_name
                    )
                else:
                    logger.warning(
                        "message=generate | Failed to disable saved search: %s",
                        self.saved_search_name
                    )
            else:
                # No migration needed, still disable the search
                logger.info(
                    "message=generate | Migration failed, keeping saved search enabled: %s",
                    self.saved_search_name
                )

        except Exception as e:
            logger.error(
                "message=generate | Error in Unified Edge migration: %s",
                str(e)
            )
            logger.error(traceback.format_exc())
            yield {
                "_time": time.time(),
                "migration_status": "failed",
                "error": str(e)
            }


if __name__ == "__main__":
    dispatch(CiscoIntersightUnifiedEdgeMigration, sys.argv, sys.stdin, sys.stdout, __name__)
