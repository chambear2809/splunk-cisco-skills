#!/usr/bin/env python3.9
"""
Cisco Intersight Inventory Lifecycle Tracker.

This custom Splunk streaming command tracks the lifecycle of Cisco Intersight inventory items.
It calls the process_lifecycle_tracking function from kvstore_helper.py to perform the actual tracking.
Now supports dynamic collections created by custom inputs.
"""
# This import is required to resolve the absolute paths of supportive modules
import import_declare_test  # pylint: disable=unused-import

import sys
from intersight_helpers.kvstore_helper import process_lifecycle_tracking
from intersight_helpers.logger_manager import setup_logging
from intersight_helpers.custom_input_mapping import get_mapping_manager

from splunklib.searchcommands import (
    StreamingCommand,
    dispatch,
    Configuration
)

logger = setup_logging("ta_intersight_inventory_lifecycle_tracker")


def get_custom_input_configurations(_session_key):
    """
    Get custom input configurations from the dynamic mapping system.

    Args:
        _session_key (str): Splunk session key (unused but kept for consistency)

    Returns:
        dict: Dictionary with custom input mappings {objecttype: {collection: str, api_endpoint: str}}
    """
    try:
        mapping_manager = get_mapping_manager(_session_key)
        custom_mappings = mapping_manager.get_custom_input_collections()

        logger.info("Retrieved %d custom input mappings from dynamic mapping system", len(custom_mappings))

        # Log the mappings for debugging
        for object_type, mapping in custom_mappings.items():
            logger.debug(
                "Custom input mapping: %s -> collection: %s, endpoint: %s, input: %s",
                object_type, mapping["collection"], mapping["api_endpoint"], mapping["input_name"]
            )

        return custom_mappings

    except Exception as e:
        logger.error("Error reading custom input mappings from dynamic system: %s", str(e))
        logger.info("Proceeding with static inventory mappings only (ignoring custom inputs)")
        return {}


@Configuration()
class CiscoIntersightInventoryLifecycleTracker(StreamingCommand):
    """
    Custom Splunk streaming command for tracking Cisco Intersight inventory lifecycle.

    This command calls the process_lifecycle_tracking function to perform comprehensive
    lifecycle tracking of Cisco Intersight inventory objects, including dynamic
    collections created by custom inputs.
    """

    def stream(self, _):
        """Process lifecycle tracking by calling the kvstore_helper function.

        Now includes dynamic custom input collections.

        Yields:
            dict: Results from lifecycle tracking process
        """
        logger.info("Starting Cisco Intersight inventory lifecycle tracking")

        try:
            # Get session key from the search context
            session_key = self._metadata.searchinfo.session_key

            # Get custom input configurations for dynamic collection tracking
            custom_mappings = get_custom_input_configurations(session_key)

            # Execute multi-account lifecycle tracking process
            # The process_lifecycle_tracking function will be enhanced to accept custom mappings
            process_lifecycle_tracking(
                session_key=session_key,
                retention_days=1,  # Default retention period
                track_types=None,  # Track all types
                custom_mappings=custom_mappings  # Pass custom input mappings
            )

        except Exception as e:
            logger.error("Error in lifecycle tracking: %s", str(e))
            raise

        return []


if __name__ == '__main__':
    try:
        dispatch(CiscoIntersightInventoryLifecycleTracker, sys.argv, sys.stdin, sys.stdout, __name__)
    except Exception as e:
        logger.error("Error in main dispatch: %s", str(e))
        sys.exit(1)
