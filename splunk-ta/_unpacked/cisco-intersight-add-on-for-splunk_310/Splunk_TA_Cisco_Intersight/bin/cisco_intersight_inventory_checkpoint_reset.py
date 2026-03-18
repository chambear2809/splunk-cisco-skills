#!/usr/bin/env python
"""
Cisco Intersight Inventory Checkpoint Reset Command.

This custom Splunk command resets inventory checkpoints for equipment/Chasses
and network endpoints. It completely removes the checkpoints, forcing a fresh
collection of inventory data on the next run.
"""

# This import is required to resolve the absolute paths of supportive modules
import import_declare_test  # pylint: disable=unused-import

import sys
import time
import traceback
from splunklib.searchcommands import (
    dispatch,
    GeneratingCommand,
    Configuration,
    Option
)
from typing import Iterator, Dict, Any, List
from intersight_helpers.logger_manager import setup_logging
from intersight_helpers import conf_helper
from splunk import rest
from splunk.clilib import cli_common
from import_declare_test import ta_name

logger = setup_logging("ta_intersight_inventory_checkpoint_reset")


@Configuration()
class CiscoIntersightInventoryCheckpointReset(GeneratingCommand):
    """
    Custom Splunk generating command to reset inventory checkpoints.

    This command completely removes inventory checkpoints (equipment/Chasses
    and network) across all configured inventory inputs. This forces a fresh
    collection of inventory data on the next run.
    """

    # Optional parameter to specify the saved search name for auto-disable functionality
    saved_search_name = Option(
        doc='Name of the saved search to disable after successful reset',
        require=False
    )

    # Checkpoint configurations to reset
    # Format: (log_name from constants, description)
    CHECKPOINTS_TO_RESET = [
        ("equipmentchasses", "Equipment Chasses"),
        ("network", "Network"),
        ("target", "Asset Targets")
    ]

    def get_all_inventory_inputs(self) -> List[Dict[str, str]]:
        """
        Get all configured inventory input stanzas from inputs.conf.

        Returns:
            list: List of dictionaries containing input_name and stanza info
        """
        try:
            # Read all stanzas from inputs.conf
            conf_stanzas = cli_common.getConfStanzas("inputs")

            inventory_inputs = []

            # Filter for inventory input stanzas
            for stanza_name, stanza_content in conf_stanzas.items():
                # Check if this is an inventory input stanza
                if 'inventory://' in stanza_name:
                    # Extract the input name (part after "inventory://")
                    input_name = stanza_name.split('inventory://')[1]

                    inventory_inputs.append({
                        "stanza_name": stanza_name,
                        "input_name": input_name,
                        "inventory_types": stanza_content.get('inventory', ''),
                        "disabled": stanza_content.get('disabled', '0')
                    })

            logger.info(
                "message=get_all_inventory_inputs | Found %d inventory inputs: %s",
                len(inventory_inputs),
                ", ".join([inp["input_name"] for inp in inventory_inputs])
            )
            return inventory_inputs

        except Exception as e:
            logger.error(
                "message=get_all_inventory_inputs | Error retrieving inventory inputs: %s",
                str(e)
            )
            logger.error(traceback.format_exc())
            return []

    def reset_checkpoint(
        self,
        session_key: str,
        checkpoint_key: str
    ) -> bool:
        """
        Reset a single checkpoint by completely removing it.

        Args:
            session_key: Splunk session key
            checkpoint_key: The checkpoint key to reset

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Get current checkpoint value to check if it exists
            current_value = conf_helper.get_checkpoint(
                checkpoint_key, session_key, ta_name
            ) or {}

            # If checkpoint doesn't exist or is already empty, skip it
            if not current_value:
                logger.debug(
                    "message=reset_checkpoint | Checkpoint doesn't exist or is empty, skipping: %s",
                    checkpoint_key
                )
                return True

            # Completely remove the checkpoint by setting it to empty dict
            conf_helper.save_checkpoint(
                checkpoint_key, session_key, ta_name, {}
            )

            logger.info(
                "message=reset_checkpoint | Successfully removed checkpoint: %s",
                checkpoint_key
            )
            return True

        except Exception as e:
            logger.error(
                "message=reset_checkpoint | Error resetting checkpoint %s: %s",
                checkpoint_key,
                str(e)
            )
            logger.error(traceback.format_exc())
            return False

    def disable_saved_search(self, session_key: str, saved_search_name: str) -> bool:
        """
        Disable a saved search after successful checkpoint reset.

        Args:
            session_key: The session key for authentication
            saved_search_name: Name of the saved search to disable

        Returns:
            bool: True if successfully disabled, False otherwise
        """
        try:
            endpoint = f"/servicesNS/nobody/{ta_name}/saved/searches/{saved_search_name}"

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

    def generate(self) -> Iterator[Dict[str, Any]]:
        """
        Generate checkpoint reset results.

        This method is called by Splunk to execute the command. It resets
        inventory checkpoints for all configured inventory inputs.

        Yields:
            dict: Status events for the checkpoint reset process
        """
        try:
            session_key = self._metadata.searchinfo.session_key
            logger.info("message=generate | Inventory checkpoint reset started")

            # Get all configured inventory inputs
            inventory_inputs = self.get_all_inventory_inputs()

            if not inventory_inputs:
                logger.warning("message=generate | No inventory inputs found to process")
                yield {
                    "_time": time.time(),
                    "reset_status": "completed",
                    "checkpoints_reset": 0,
                    "message": "No inventory inputs configured"
                }
                return

            # Track statistics
            total_checkpoints_attempted = 0
            total_checkpoints_reset = 0
            failed_checkpoints = []

            # Process each inventory input
            for input_info in inventory_inputs:
                input_name = input_info["input_name"]

                logger.info(
                    "message=generate | Processing inventory input: %s (disabled=%s)",
                    input_name,
                    input_info["disabled"]
                )

                # Process each checkpoint type
                for checkpoint_log_name, checkpoint_desc in self.CHECKPOINTS_TO_RESET:
                    # Build checkpoint key
                    # Format: Cisco_Intersight_{input_name}_{log_name}_inventory_checkpoint
                    checkpoint_key = (
                        f"Cisco_Intersight_{input_name}_{checkpoint_log_name}_inventory_checkpoint"
                    )

                    total_checkpoints_attempted += 1

                    # Reset the checkpoint
                    if self.reset_checkpoint(session_key, checkpoint_key):
                        total_checkpoints_reset += 1
                        logger.info(
                            "message=generate | Reset checkpoint: %s (%s)",
                            checkpoint_key,
                            checkpoint_desc
                        )
                    else:
                        failed_checkpoints.append({
                            "checkpoint_key": checkpoint_key,
                            "input_name": input_name,
                            "description": checkpoint_desc
                        })
                        logger.error(
                            "message=generate | Failed to reset checkpoint: %s (%s)",
                            checkpoint_key,
                            checkpoint_desc
                        )

            # Log final results
            logger.info(
                "message=generate | Inventory checkpoint reset completed. "
                "Total attempted: %d, Successfully reset: %d, Failed: %d",
                total_checkpoints_attempted,
                total_checkpoints_reset,
                len(failed_checkpoints)
            )

            # Yield status event
            yield {
                "_time": time.time(),
                "reset_status": "completed",
                "inputs_processed": len(inventory_inputs),
                "checkpoints_attempted": total_checkpoints_attempted,
                "checkpoints_reset": total_checkpoints_reset,
                "checkpoints_failed": len(failed_checkpoints),
                "failed_checkpoints": failed_checkpoints if failed_checkpoints else None
            }

            # Disable the saved search if provided and reset was successful
            if total_checkpoints_reset - total_checkpoints_attempted == 0:
                logger.info(
                    "message=generate | Checkpoint reset successful, disabling saved search: %s",
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

        except Exception as e:
            logger.error(
                "message=generate | Error in Inventory checkpoint reset: %s",
                str(e)
            )
            logger.error(traceback.format_exc())
            yield {
                "_time": time.time(),
                "reset_status": "failed",
                "error": str(e)
            }


if __name__ == "__main__":
    dispatch(CiscoIntersightInventoryCheckpointReset, sys.argv, sys.stdin, sys.stdout, __name__)
