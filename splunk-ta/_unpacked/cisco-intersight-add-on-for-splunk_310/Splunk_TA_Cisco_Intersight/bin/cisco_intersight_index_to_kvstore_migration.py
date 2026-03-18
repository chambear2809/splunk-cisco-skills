#!/usr/bin/env python
"""
Cisco Intersight Index to KVStore Migration Command.

This custom Splunk command migrates data from Splunk indexes to KVStore collections
for Cisco Intersight inventory data. It processes events from search results and
upserts them into appropriate KVStore collections based on ObjectType.
"""

# This import is required to resolve the absolute paths of supportive modules
import import_declare_test  # pylint: disable=unused-import

import sys
import time
import json
import traceback
from splunklib.modularinput.event_writer import EventWriter
from splunklib.searchcommands import (
    dispatch,
    EventingCommand,
    Configuration,
    Option
)
from intersight_helpers.conf_helper import delete_checkpoint
from typing import Iterator, Dict, Any
from intersight_helpers.kvstore_helper import upsert_to_kvstore
from intersight_helpers.logger_manager import setup_logging
from intersight_helpers.rest_helper import RestHelper
from intersight_helpers.event_ingestor import EventIngestor
from intersight_helpers.constants import InventoryApis
from splunk.clilib import cli_common
from splunk import rest
from inventory import INVENTORY

logger = setup_logging("ta_intersight_index_to_kvstore_migration")

multi_api_inventory_config = getattr(InventoryApis, "multi_api_inventory_config", {})


@Configuration()
class CiscoIntersightIndexToKVStoreMigration(EventingCommand):
    """
    Custom Splunk eventing command to migrate Cisco Intersight data from indexes to KVStore.

    This command processes Cisco Intersight events from Splunk indexes and migrates them to
    appropriate KVStore collections based on their ObjectType. Uses the _finished flag to
    disable the saved search only after complete command execution.
    """

    # Optional parameter to specify the saved search name for auto-disable functionality
    saved_search_name = Option(
        doc='Name of the saved search to disable after successful migration',
        require=False
    )

    # Class-level tracking variables
    total_events_processed = 0
    migration_successful = False
    migration_required = False
    _events_by_type = {}

    def read_conf_stanzas(self, conf_name):
        """
        Read all stanzas from a .conf file and returns a dict.

        {
            'stanza1': {'key1': 'val1', 'key2': 'val2'},
            'stanza2': {'keyA': 'valA'},
            ...
        }
        """
        try:
            conf_dict = cli_common.getConfStanzas(conf_name)
            return conf_dict
        except Exception as e:
            logger.error(
                "message=conf_read | Error reading {}.conf: {}".format(conf_name, e)
            )
            return {}

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

    def ingest_graphic_card_events(self, stanza_name, stanza_content, endpoint, config):
        """Ingest the graphic card events in the splunk."""
        try:
            inv_class = INVENTORY()

            session_key = self._metadata.searchinfo.session_key
            start_time = time.time()

            input_items = [{"count": 1}]

            stanza_content["stanza_name"] = stanza_name
            stanza_content["name"] = stanza_name.split("://")[1]
            stanza_content["session_key"] = session_key

            input_items.append(stanza_content)

            account_info = inv_class.get_account_info(input_items)
            input_items[1].update(account_info)

            # Create the REST helper and event ingestor objects
            intersight_rest_helper = RestHelper(input_items[1], logger)
            event_ingestor = EventIngestor(
                input_items[1], EventWriter(), logger,
                intersight_rest_helper.ckpt_account_name,
                custom_index_method=True
            )

            target_moids = inv_class.get_target_if_needed(input_items[1], intersight_rest_helper, logger)

            standard_inventory_kwargs = {
                "intersight_rest_helper": intersight_rest_helper,
                "event_ingestor": event_ingestor,
                "logger": logger,
                "target_moids": target_moids
            }

            # Update the standard inventory processing kwargs
            standard_inventory_kwargs["config"] = config
            standard_inventory_kwargs["endpoint"] = endpoint
            standard_inventory_kwargs["checkpoint_key"] = "randomkey"
            standard_inventory_kwargs["session_key"] = session_key

            # Process the standard inventory
            inv_class.process_standard_inventory(standard_inventory_kwargs, is_save_checkpoint=False)

            # Log the API call statistics and total time taken
            total_time_taken = time.time() - start_time
            logger.info(
                "message=intersight_api_count | API call statistics: {}".format(
                    intersight_rest_helper.api_call_count
                )
            )
            logger.info(
                "message=data_collection_end_execution | Data collection completed"
                " and total time taken: {}. ".format(total_time_taken)
            )
        except Exception as e:
            # Log any errors that occurred
            logger.error(
                "message=inventory_error | An error occurred while processing "
                "the Inventory. {}".format(e)
            )
            logger.error(traceback.format_exc())
            raise

    def transform(self, records: Iterator[Dict[str, Any]]) -> Iterator[Dict[str, Any]]:
        """
        Transform events and migrate data to KVStore.

        Args:
            records: Iterator of search result events

        Yields:
            Dict[str, Any]: Original events (passthrough)
        """
        conf_stanzas = self.read_conf_stanzas("inputs")
        try:
            logger.info("message=transform_events | Graphics card data fetching and ingestion started")

            compute_config = multi_api_inventory_config.get("compute", None)
            if compute_config:
                endpoint = "search/SearchItems"
                searchitems_config = compute_config.get(endpoint, None)
                if searchitems_config:
                    searchitems_config["params"]["$filter"] = (
                        "ClassId in (graphics.Card, compute.RackUnitIdentity, fabric.ElementIdentity)"
                    )

                    if self.saved_search_name == (
                        "splunk_ta_cisco_intersight_index_to_kvstore_migration_inventory_compute"
                    ):
                        for stanza_name, stanza_content in conf_stanzas.items():
                            if (
                                'inventory' in stanza_name and stanza_content.get('inventory', None)
                                and 'compute' in stanza_content.get('inventory', None)
                                and stanza_content.get('compute_endpoints', None)
                            ):
                                if (
                                    'All' in stanza_content.get('compute_endpoints', None)
                                    or 'search/SearchItems' in stanza_content.get('compute_endpoints', None)
                                ):
                                    logger.info("message=transform_events | Fetching graphics card events")
                                    try:
                                        self.ingest_graphic_card_events(
                                            stanza_name,
                                            stanza_content,
                                            endpoint,
                                            searchitems_config
                                        )
                                    except Exception as e:
                                        logger.error(
                                            "message=transform_events | Error:{} occurred while "
                                            "ingesting graphics card data for input: {}".format(
                                                e, stanza_name
                                            )
                                        )

        except Exception as ex:
            logger.error(
                "message=transform_events | Error while fetching and ingesting graphics card data %s",
                str(ex)
            )

        try:
            logger.info("message=transform_events | Advisories checkpoint deletion method started")
            for stanza_name, stanza_content in conf_stanzas.items():
                if (
                    'inventory' in stanza_name and stanza_content.get('inventory', None)
                    and 'advisories' in stanza_content.get('inventory', None)
                ):
                    checkpoint_key = (
                        f"Cisco_Intersight_{stanza_name.split('://')[1]}_advisories_inventory_checkpoint"
                    )
                    delete_checkpoint(checkpoint_key=checkpoint_key, session_key=self._metadata.searchinfo.session_key)

        except Exception as ex:
            logger.error(
                "message=transform_events | Error while deleting the advisory instance checkpoint: %s",
                str(ex)
            )

        try:
            logger.info("message=transform_events | EventingCommand transform method started")

            # Process each event as it comes in (EventingCommand pattern)
            for event in records:
                try:
                    raw_data = event.get("_raw")
                    source = event.get("source")

                    if not raw_data:
                        logger.warning("message=transform_events | Missing _raw in event")
                        yield event  # Pass through original event
                        continue

                    try:
                        parsed_event = json.loads(raw_data)
                    except json.JSONDecodeError as json_error:
                        logger.error("message=transform_events | Invalid JSON in _raw: %s", str(json_error))
                        yield event  # Pass through original event
                        continue
                    except Exception as general_error:  # pylint: disable=broad-except
                        logger.error("message=transform_events | Error parsing JSON in _raw: %s", str(general_error))
                        yield event  # Pass through original event
                        continue

                    object_type = (
                        parsed_event.get("ObjectType")
                        or parsed_event.get("ClassId")
                        or parsed_event.get("SourceObjectType")
                        or ("equipment.chassis" if source == "inventoryObjects" else source)
                    )

                    if not object_type:
                        logger.warning("message=transform_events | Missing ObjectType in event")
                        yield event  # Pass through original event
                        continue

                    # Track event for batch migration in finally block
                    self._track_event_for_migration(parsed_event, object_type)
                    self.total_events_processed += 1

                except Exception as event_error:
                    logger.error(
                        "message=transform_events | Error processing "
                        "event: %s", str(event_error))

                # Always yield the original event
                yield event

        except Exception as ex:
            logger.error(
                "message=transform_events | Error in transform method: %s",
                str(ex)
            )
        finally:
            # This is where we do the actual migration after ALL events are processed
            if self._finished:
                logger.info(
                    "message=transform_events | Command finished, "
                    "performing migration and cleanup"
                )
                self._perform_final_migration()

    def _track_event_for_migration(self, parsed_event: Dict[str, Any], object_type: str) -> None:
        """Track events for batch migration in finally block."""
        if not hasattr(self, '_events_by_type'):
            self._events_by_type = {}

        self._events_by_type.setdefault(object_type, []).append(parsed_event)

    def _perform_final_migration(self) -> None:
        """Perform the actual migration in the finally block when command is finished."""
        try:
            session_key = self._metadata.searchinfo.session_key

            if not hasattr(self, '_events_by_type') or not self._events_by_type:
                logger.info(
                    "message=migration | No events found for migration."
                )
                if self.disable_saved_search(session_key, self.saved_search_name):
                    logger.info(
                        "message=migration | No events found, "
                        "Successfully disabled saved search: %s",
                        self.saved_search_name
                    )
                else:
                    logger.warning(
                        "message=migration | Failed to disable saved search: %s",
                        self.saved_search_name
                    )
                return

            total_migrated = 0

            for object_type, events in self._events_by_type.items():
                logger.info(
                    "message=migration | Migrating %d events of type %s",
                    len(events), object_type
                )

                try:
                    upsert_to_kvstore(
                        session_key=session_key,
                        events=events,
                        object_type=object_type
                    )
                    upsert_result = True  # Function doesn't return a value, assume success

                    if upsert_result:
                        total_migrated += len(events)
                        logger.info(
                            "message=migration | Successfully migrated %d %s events",
                            len(events), object_type
                        )
                    else:
                        logger.error(
                            "message=migration | Failed to migrate %s events",
                            object_type
                        )

                except Exception as upsert_error:
                    logger.error(
                        "message=migration | Error migrating %s events: %s",
                        object_type, str(upsert_error)
                    )

            if total_migrated > 0:
                self.migration_successful = True
                self.migration_required = True
                logger.info(
                    "message=migration | Migration completed successfully. "
                    "Total events migrated: %d",
                    total_migrated
                )

                # Now disable the saved search if configured
                if self.saved_search_name:
                    logger.info(
                        "message=migration | Attempting to disable saved search: %s",
                        self.saved_search_name
                    )
                    if self.disable_saved_search(session_key, self.saved_search_name):
                        logger.info(
                            "message=migration | Successfully disabled saved search: %s",
                            self.saved_search_name
                        )
                    else:
                        logger.warning(
                            "message=migration | Failed to disable saved search: %s",
                            self.saved_search_name
                        )

        except Exception as migration_error:
            logger.error(
                "message=migration | Error in final migration: %s",
                str(migration_error)
            )


if __name__ == "__main__":
    dispatch(CiscoIntersightIndexToKVStoreMigration, sys.argv, sys.stdin, sys.stdout, __name__)
