#!/usr/bin/env python
"""
Cisco Intersight Metrics Checkpoint Reset Command.

This custom Splunk command resets metrics dimension checkpoints for network,
temperature, and domains. It removes the last_fetched_time and sets status to False,
forcing a fresh collection of metrics dimensions on the next run.
"""

# This import is required to resolve the absolute paths of supportive modules
import import_declare_test  # pylint: disable=unused-import

import sys
import time
import json
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
from import_declare_test import ta_name

logger = setup_logging("ta_intersight_metrics_checkpoint_reset")


@Configuration()
class CiscoIntersightMetricsCheckpointReset(GeneratingCommand):
    """
    Custom Splunk generating command to reset metrics dimension checkpoints.

    This command resets the last_fetched_time and status for metrics dimension
    checkpoints (network, temperature, domains) across all configured accounts.
    This forces a fresh collection of dimension data on the next metrics run.
    """

    # Optional parameter to specify the saved search name for auto-disable functionality
    saved_search_name = Option(
        doc='Name of the saved search to disable after successful reset',
        require=False
    )

    # Metrics to reset (these need dimension recollection)
    METRICS_TO_RESET = ["domains", "network", "temperature"]

    # Intervals for checkpoints
    INTERVALS = ["1h"]

    def get_all_accounts(self, session_key: str) -> List[str]:
        """
        Get all configured account names from Splunk.

        Args:
            session_key: The session key for authentication

        Returns:
            list: List of account names
        """
        try:
            # Get all account configurations
            _, content = rest.simpleRequest(
                f"/servicesNS/nobody/{ta_name}/Splunk_TA_Cisco_Intersight_account",
                sessionKey=session_key,
                getargs={"output_mode": "json"},
                raiseAllErrors=True,
            )

            content_dict = json.loads(content)
            account_names = []

            # Extract account names from entries
            for entry in content_dict.get("entry", []):
                account_name = entry.get("name")
                if account_name:
                    account_names.append(account_name)

            logger.info(
                "message=get_all_accounts | Found %d configured accounts: %s",
                len(account_names),
                ", ".join(account_names)
            )
            return account_names

        except Exception as e:
            logger.error(
                "message=get_all_accounts | Error retrieving accounts: %s",
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
        Reset a single checkpoint by removing last_fetched_time and setting status to False.

        Args:
            session_key: Splunk session key
            checkpoint_key: The checkpoint key to reset

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Get current checkpoint value
            current_value = conf_helper.get_checkpoint(
                checkpoint_key, session_key, ta_name
            ) or {}

            # If checkpoint doesn't exist or is already empty, skip it
            if not current_value:
                logger.debug(
                    "message=reset_checkpoint | Checkpoint doesn't exist, skipping: %s",
                    checkpoint_key
                )
                return True

            # Create new checkpoint value with status=False and no last_fetched_time
            new_value = {"status": False}

            # Save the reset checkpoint
            conf_helper.save_checkpoint(
                checkpoint_key, session_key, ta_name, new_value
            )

            logger.info(
                "message=reset_checkpoint | Successfully reset checkpoint: %s",
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
        metrics dimension checkpoints for all configured accounts.

        Yields:
            dict: Status events for the checkpoint reset process
        """
        try:
            session_key = self._metadata.searchinfo.session_key
            logger.info("message=generate | Metrics checkpoint reset started")

            # Get all configured accounts
            account_names = self.get_all_accounts(session_key)

            if not account_names:
                logger.warning("message=generate | No accounts found to process")
                yield {
                    "_time": time.time(),
                    "reset_status": "completed",
                    "checkpoints_reset": 0,
                    "message": "No accounts configured"
                }
                return

            # Track statistics
            total_checkpoints_attempted = 0
            total_checkpoints_reset = 0
            failed_checkpoints = []

            # Process each account
            for account_name in account_names:
                logger.info(
                    "message=generate | Processing account: %s",
                    account_name
                )

                # Process each metric
                for metric in self.METRICS_TO_RESET:
                    # Process each interval
                    for interval in self.INTERVALS:
                        # Build checkpoint key
                        checkpoint_key = (
                            f"Cisco_Intersight_{account_name}_{metric}_"
                            f"dimension_checkpoint_{interval}"
                        )

                        total_checkpoints_attempted += 1

                        # Reset the checkpoint
                        if self.reset_checkpoint(session_key, checkpoint_key):
                            total_checkpoints_reset += 1
                            logger.info(
                                "message=generate | Reset checkpoint: %s",
                                checkpoint_key
                            )
                        else:
                            failed_checkpoints.append(checkpoint_key)
                            logger.error(
                                "message=generate | Failed to reset checkpoint: %s",
                                checkpoint_key
                            )

            # Log final results
            logger.info(
                "message=generate | Metrics checkpoint reset completed. "
                "Total attempted: %d, Successfully reset: %d, Failed: %d",
                total_checkpoints_attempted,
                total_checkpoints_reset,
                len(failed_checkpoints)
            )

            # Yield status event
            yield {
                "_time": time.time(),
                "reset_status": "completed",
                "accounts_processed": len(account_names),
                "checkpoints_attempted": total_checkpoints_attempted,
                "checkpoints_reset": total_checkpoints_reset,
                "checkpoints_failed": len(failed_checkpoints),
                "failed_checkpoint_keys": failed_checkpoints if failed_checkpoints else None
            }

            # Disable the saved search if provided and reset was successful
            if self.saved_search_name and total_checkpoints_reset > 0:
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
                "message=generate | Error in Metrics checkpoint reset: %s",
                str(e)
            )
            logger.error(traceback.format_exc())
            yield {
                "_time": time.time(),
                "reset_status": "failed",
                "error": str(e)
            }


if __name__ == "__main__":
    dispatch(CiscoIntersightMetricsCheckpointReset, sys.argv, sys.stdin, sys.stdout, __name__)
