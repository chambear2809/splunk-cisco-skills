"""
Account helper functions for Cisco Intersight Splunk Add-on.

This module contains utility functions for handling Intersight account operations,
including account configuration and authentication.
"""

from requests.compat import quote_plus
from splunk import rest
from intersight_helpers.logger_manager import setup_logging
from intersight_helpers.constants import Endpoints
from import_declare_test import ta_name

# Module-level logger for consistent logging
logger = setup_logging("ta_intersight_account_helper")


def add_missing_account_moid(account_entry: dict, session_key: str) -> dict:
    """
    Add intersight_account_moid to account configuration for backward compatibility.

    This function fetches the account Moid from Intersight API and updates the configuration.

    :param account_entry: The account entry from configuration
    :param session_key: Splunk session key
    :return: Updated account configuration with intersight_account_moid
    """
    try:
        account_config = account_entry.get("content", {})
        account_name = account_entry.get("name")

        logger.info(
            "message=add_missing_account_moid | Adding missing intersight_account_moid for account: %s",
            account_name
        )

        # Prepare intersight_config for RestHelper
        intersight_config = {
            "session_key": session_key,
            "intersight_hostname": account_config.get("intersight_hostname"),
            "client_id": account_config.get("client_id"),
            "client_secret": account_config.get("client_secret")
        }

        # Import at function level with pylint disable to avoid cyclic imports
        # pylint: disable=import-outside-toplevel,cyclic-import
        from intersight_helpers.rest_helper import RestHelper

        # Create RestHelper instance to fetch account Moid
        rest_helper = RestHelper(
            intersight_config=intersight_config,
            logger=logger
        )

        # Fetch account information
        rest_helper.get_hostname_source()
        account_moid = rest_helper.ckpt_account_moid
        global_account_name = rest_helper.ckpt_account_name

        if not account_moid:
            raise ValueError(f"Could not fetch AccountMoid for account: {account_name}")

        logger.info(
            "message=add_missing_account_moid_success | Fetched AccountMoid %s and AccountName %s for account: %s",
            account_moid, account_name, global_account_name
        )

        # Update the configuration by adding intersight_account_moid and intersight_account_name
        update_data = {
            "intersight_account_moid": account_moid,
            "intersight_account_name": global_account_name
        }

        # Update the account configuration
        rest.simpleRequest(
            f"{Endpoints.SERVICES_NS}{ta_name}/Splunk_TA_Cisco_Intersight_account/{quote_plus(account_name)}",
            sessionKey=session_key,
            postargs=update_data,
            method="POST",
            raiseAllErrors=True,
        )

        # Add the new fields to the returned account config
        account_config["intersight_account_moid"] = account_moid
        account_config["intersight_account_name"] = global_account_name

        logger.info(
            "message=add_missing_account_moid_complete | "
            "Successfully updated account %s with AccountMoid: %s and AccountName: %s",
            account_name, account_moid, global_account_name
        )

        return account_config

    except Exception as e:
        logger.exception(
            "message=add_missing_account_moid_error | Failed to add intersight_account_moid for account %s: %s",
            account_name, str(e)
        )
        raise
