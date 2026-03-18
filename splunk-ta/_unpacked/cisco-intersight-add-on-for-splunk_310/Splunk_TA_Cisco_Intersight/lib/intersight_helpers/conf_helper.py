"""Conf handler which returns conf information."""
import json
import re
import traceback
from requests.compat import quote_plus
from splunk import ResourceNotFound, admin, rest
from solnlib import conf_manager, utils, modular_input
import splunk.clilib.cli_common
from splunklib import client

# Splunk imports
from intersight_helpers.logger_manager import setup_logging
from intersight_helpers.constants import Endpoints
from intersight_helpers.account_helper import add_missing_account_moid
from import_declare_test import ta_name

logger = setup_logging("ta_intersight_conf_helper")


class GetSessionKey(admin.MConfigHandler):
    """To get Splunk session key."""

    def __init__(self) -> None:
        """Initialize.

        Get session key for Splunk admin endpoint.
        """
        self.session_key = self.getSessionKey()


def get_conf_file(
    file: str,
    app: str = ta_name,
    session_key: str = None,
    stanza: str = None,
    realm: str = "__REST_CREDENTIAL__#{}#configs/conf-{}"  # pylint: disable=unused-variable
) -> object:
    """
    Conf info returns the file information.

    :param session_key: The session key for the Splunk admin endpoint.
    :param file: The name of the conf file.
    :param app: The name of the app.
    :param realm: The realm of the conf file.
    :param stanza: The stanza name in the conf file. If provided, the stanza
        will be returned instead of the whole conf file.
    :return: Conf File Object
    """
    if session_key is None:
        session_key = GetSessionKey().session_key
    cfm = conf_manager.ConfManager(
        session_key, app, realm=realm.format(ta_name, file)
    ).get_conf(file)
    if stanza:
        return cfm.get(stanza)
    return cfm


def create_service() -> object:
    """
    Create Service to communicate with splunk.

    This function creates a client connection to the splunkd management
    port. This is used to communicate with the splunkd REST API.

    :return: Service object
    :rtype: splunklib.client.Service
    """
    mgmt_port = splunk.clilib.cli_common.getMgmtUri().split(":")[-1]
    service = client.connect(
        port=mgmt_port, token=GetSessionKey().session_key, app=ta_name
    )
    return service


def get_proxy_info(session_key: str) -> dict:
    """
    Get proxy information from Splunk REST endpoints.

    The function will return a dictionary containing the proxy details or None.
    The dictionary will have the proxy type, url, port, username and password.
    The username and password will be quoted if they contain special characters.

    :param session_key: Splunk session key
    :return: dictionary containing proxy details or None
    """
    proxy_info_dict = {}

    # Retrieve proxy configurations
    logger.debug(
        "message=get_proxy_info |"
        " Retrieving proxy settings from Splunk rest endpoints"
    )
    try:
        # Get the proxy settings from the Splunk REST endpoint
        _, content = rest.simpleRequest(
            f"{Endpoints.SERVICES_NS}{ta_name}/Splunk_TA_Cisco_Intersight_settings/proxy",
            sessionKey=session_key,
            getargs={"output_mode": "json", "--cred--": "1"},
        )
        # Parse the response
        content = json.loads(content)
        logger.debug(
            "message=get_proxy_info_success |"
            " Successfully retrieved proxy settings from Splunk rest endpoints")
    except Exception:
        logger.exception(
            "message=get_proxy_info_error |"
            " Could not get proxy settings from the rest endpoint")
        raise

    # Loop through the response and extract the first proxy setting
    for item in content["entry"]:
        proxy_info_dict = item["content"]
        break

    # Return None if proxy_enabled is false or proxy hostname or proxy port is not found
    if (
        not utils.is_true(proxy_info_dict.get("proxy_enabled"))
        or not proxy_info_dict.get("proxy_port")
        or not proxy_info_dict.get("proxy_url")
    ):
        return None

    # Quote username and password if available
    user_pass = ""
    if proxy_info_dict.get("proxy_username") and proxy_info_dict.get("proxy_password"):
        username = quote_plus(proxy_info_dict["proxy_username"], safe="")
        password = quote_plus(proxy_info_dict["proxy_password"], safe="")
        user_pass = f"{username}:{password}@"

    # Prepare proxy string
    proxy = (
        f"{proxy_info_dict['proxy_type']}://"
        f"{user_pass}{proxy_info_dict['proxy_url']}:{proxy_info_dict['proxy_port']}"
    )
    proxies = {
        "http": proxy,
        "https": proxy,
    }

    logger.debug("message=get_proxy_info_success | Returning proxy settings...")
    return proxies


def get_credentials(account_name: str, session_key: str) -> dict:
    """
    Get credentials of Query API.

    :param account_name: The name of the account to get credentials for.
    :param session_key: Splunk session key.
    :return: dictionary containing credentials
    """
    logger.debug(
        "message=get_credentials |"
        " Getting account from Splunk rest endpoint.")
    try:
        # Make a request to the Splunk REST endpoint to get the credentials
        _, content = rest.simpleRequest(
            f"{Endpoints.SERVICES_NS}{ta_name}/Splunk_TA_Cisco_Intersight_account/{account_name}",
            sessionKey=session_key,
            getargs={"output_mode": "json", "--cred--": 1},
            raiseAllErrors=True,
        )
    except Exception:
        # Handle any exceptions that occur
        logger.exception(
            "message=get_credentials_error |"
            " Could not read account settings from the rest endpoint"
        )
        raise

    # Successfully got the response from the Splunk REST endpoint
    logger.debug(
        "message=get_credentials_success |"
        " Successfully got response from the Splunk rest endpoint.")
    content = json.loads(content)
    response_dict = content["entry"][0]["content"]

    # Return the credentials dictionary
    logger.debug(
        "message=get_credentials_success |"
        " Returning account settings...")
    return response_dict


def get_credentials_by_account_moid(
    account_moid: str, session_key: str, account_name: str = None
) -> dict:
    """
    Get credentials by matching AccountMoid or AccountName with configuration.

    Matching priority:
    1. Match by AccountMoid (primary)
    2. Match by account_name (fallback if provided)

    :param account_moid: The AccountMoid from Intersight data to match
    :param session_key: Splunk session key
    :param account_name: Optional account name for fallback matching when account_moid is incorrect
    :return: dictionary containing credentials
    """
    logger.debug(
        "message=get_credentials_by_account | Getting account configuration for AccountMoid: %s, AccountName: %s",
        account_moid, account_name)
    try:
        # Get all account configurations
        _, content = rest.simpleRequest(
            f"{Endpoints.SERVICES_NS}{ta_name}/Splunk_TA_Cisco_Intersight_account",
            sessionKey=session_key,
            getargs={"output_mode": "json", "--cred--": 1},
            raiseAllErrors=True,
        )

        content = json.loads(content)

        # Find the account configuration that matches the AccountMoid
        for entry in content.get("entry", []):
            account_config = entry.get("content", {})

            # Check if intersight_account_moid exists in the configuration
            if ("intersight_account_moid" in account_config) and ("intersight_account_name" in account_config):
                # Priority 1: Try to match by AccountMoid
                if account_config.get("intersight_account_moid") == account_moid:
                    logger.debug(
                        "message=get_credentials_by_account_success | "
                        "Found matching account configuration for AccountMoid: %s",
                        account_moid)
                    return account_config

                # Priority 2: Fallback to account_name if AccountMoid doesn't match but account_name is provided
                if account_config.get("intersight_account_name") == account_name:
                    logger.info(
                        "message=get_credentials_by_account_name_fallback | "
                        "Found matching account configuration by account_name: %s "
                        "(AccountMoid in record: %s, AccountMoid in config: %s)",
                        account_name, account_moid, account_config.get("intersight_account_moid")
                    )
                    return account_config
            else:
                # Backward compatibility: intersight_account_moid missing, try to add it
                logger.info(
                    "message=get_credentials_by_account_missing_field | "
                    "Account %s missing intersight_account_moid or intersight_account_name, attempting to add it",
                    entry.get('name'))
                try:
                    # Add the missing intersight_account_moid to this account
                    updated_account_config = add_missing_account_moid(entry, session_key)

                    # Check if this is the account we're looking for by AccountMoid
                    if updated_account_config.get("intersight_account_moid") == account_moid:
                        logger.debug(
                            "message=get_credentials_by_account_moid_success_after_update | "
                            "Found matching account configuration for AccountMoid: %s after update",
                            account_moid)
                        return updated_account_config

                    # Also check by account_name as fallback
                    if account_name and updated_account_config.get("intersight_account_name") == account_name:
                        logger.info(
                            "message=get_credentials_by_account_name_fallback_after_update | "
                            "Found matching account configuration by account_name: %s after update",
                            account_name)
                        return updated_account_config

                except Exception as e:
                    logger.warning(
                        "message=get_credentials_by_account_moid_update_failed | "
                        "Failed to update account %s with intersight_account_moid: %s",
                        entry.get('name'), str(e))
                    # Continue to next account instead of failing completely
                    continue

        # If all attempts failed
        if account_name:
            error_msg = (
                f"No account configuration found with AccountMoid: {account_moid} "
                f"or AccountName: {account_name}"
            )
        else:
            error_msg = f"No account configuration found with AccountMoid: {account_moid}"
        raise ValueError(error_msg)

    except Exception as e:
        # Handle any exceptions that occur
        logger.exception(
            "message=get_credentials_by_account_moid_error | Could not read account settings for AccountMoid %s: %s",
            account_moid, str(e)
        )
        raise


def get_kvstore_info(session_key: str) -> dict:
    """
    Fetch KVStore configuration from the Splunk REST endpoint.

    The function makes a request to the Splunk REST endpoint to get the KVStore
    configuration. The response is then parsed and returned as a dictionary.

    :param session_key: Splunk session key
    :return: dictionary containing KVStore details
    """
    logger.debug(
        "message=get_kvstore_info |"
        " Fetching KVStore configs from rest endpoint."
    )
    try:
        # Make a request to the Splunk REST endpoint to get the KVStore config
        _, content = rest.simpleRequest(
            f"{Endpoints.SERVICES_NS}{ta_name}/Splunk_TA_Cisco_Intersight_settings/splunk_rest_host",
            sessionKey=session_key,
            getargs={"output_mode": "json", "--cred--": "1"},
            raiseAllErrors=True,
        )
    except Exception:
        # Handle any exceptions that occur
        logger.exception(
            "message=get_kvstore_error |"
            " Could not read kvstore settings from the rest endpoint."
        )
        raise

    logger.debug(
        "message=get_kvstore_success |"
        " Successfully got response from the Splunk rest endpoint.")

    # Parse the response
    content = json.loads(content)

    # Loop through the response and extract the KVStore config
    kvstore_config = {}
    for item in content["entry"]:
        kvstore_config = item["content"]
        break

    logger.debug("message=get_kvstore_success | Returning kvstore info...")
    return kvstore_config


def get_mgmt_port(session_key: str) -> str:
    """
    Get Management Port from web.conf file.

    Makes a request to the Splunk REST endpoint to get the management port
    from the web.conf file. The response is then parsed and the management port
    is returned.

    Parameters
    ----------
    session_key : str
        Splunk session key

    Returns
    -------
    str
        Management port
    """
    try:
        # Make a request to the Splunk REST endpoint to get the management port
        _, content = rest.simpleRequest(
            "/services/configs/conf-web/settings",
            method="GET",
            sessionKey=session_key,
            getargs={"output_mode": "json"},
            raiseAllErrors=True,
        )
    except Exception as e:
        # Handle any exceptions that occur
        logger.error(
            "message=get_mgmt_port_error |"
            " Intersight Get Management Port Error: Error while making request to read"
            " web.conf file. Error: {}".format(str(e))
        )
        logger.debug(
            "message=get_mgmt_port_error |"
            " Intersight Get Management Port Error: Error while making request to read"
            " web.conf file. Error: {}".format(traceback.format_exc())
        )
        raise

    # Parse the response
    try:
        # Parse the response to get the management port
        content = json.loads(content)
        content = re.findall(r":(\d+)", content["entry"][0]["content"]["mgmtHostPort"])[0]
        logger.info(
            "message=get_mgmt_port_success |"
            " Intersight Info: Get managemant port from web.conf is {}.".format(content)
        )
    except Exception as e:
        # Handle any exceptions that occur
        logger.error(
            "message=get_mgmt_port_error |"
            " Intersight Error: Error while parsing web.conf file. Error: {}".format(str(e))
        )
        logger.debug(
            "message=get_mgmt_port_error |"
            " Intersight Error: Error while parsing"
            " web.conf file. Error: {}".format(traceback.format_exc())
        )
        raise

    # Return the management port
    return content


def get_checkpoint(checkpoint_key: str, session_key: str, app_name: str) -> str:
    """
    Get checkpoint.

    Retrieves the checkpoint value from the KVStore using the provided
    checkpoint_key and session_key.

    Parameters
    ----------
    checkpoint_key : str
        Key of the checkpoint.
    session_key : str
        Splunk session key.
    app_name : str
        App name.

    Returns
    -------
    str
        Checkpoint value.
    """
    try:
        # Get the checkpoint value from the KVStore
        checkpoint_collection = modular_input.checkpointer.KVStoreCheckpointer(
            checkpoint_key, session_key, app_name
        )
        value = checkpoint_collection.get(checkpoint_key)
        logger.info(
            'message=get_checkpoint | Received checkpoint of value: {} '
            'for key: {}'.format(value, checkpoint_key)
        )
        return value
    except Exception:
        # Handle any exceptions that occur
        logger.error(
            "message=checkpoint_error |"
            " Error occurred while Getting Checkpoint.\n{0}"
            " Make sure your splunk management port is configured correctly in"
            " Configurations > KVStore Lookup Rest".format(traceback.format_exc())
        )
        raise


def save_checkpoint(checkpoint_key: str, session_key: str, app_name: str, value: str) -> None:
    """
    Save checkpoint.

    Saves the checkpoint value in the KVStore using the provided
    checkpoint_key and session_key.

    Parameters
    ----------
    checkpoint_key : str
        Key of the checkpoint.
    session_key : str
        Splunk session key.
    app_name : str
        App name.
    value : str
        Value of the checkpoint to be saved.

    Raises
    ------
    Exception
        If an error occurs while saving the checkpoint.
    """
    try:
        # Get the checkpoint collection
        checkpoint_collection = modular_input.checkpointer.KVStoreCheckpointer(
            checkpoint_key, session_key, app_name
        )
        # Update the checkpoint
        checkpoint_collection.update(checkpoint_key, value)
        logger.info(
            'message=save_checkpoint | Saved checkpoint of value: {} '
            'for key: {}'.format(value, checkpoint_key)
        )
    except Exception:
        # Handle any exceptions that occur
        logger.error(
            "message=checkpoint_error |"
            " Error occurred while Updating Checkpoint.\n{0}"
            " Make sure your splunk management port is configured correctly in"
            " Configurations > KVStore Lookup Rest".format(traceback.format_exc())
        )
        raise


def delete_checkpoint(checkpoint_key: str, session_key: str) -> None:
    """
    Delete the checkpoint from the KVStore.

    This function uses the Splunk REST API to delete the checkpoint
    from the KVStore. It logs an error if the checkpoint is not found.

    Parameters
    ----------
    checkpoint_key : str
        Key of the checkpoint to be deleted.
    session_key : str
        Splunk session key.

    Raises
    ------
    Exception
        If an error occurs while deleting the checkpoint.
    """
    try:
        # Delete the checkpoint from the KVStore
        _, _ = rest.simpleRequest(
            str(Endpoints.SERVICES_NS) + "" + str(ta_name)
            + "/storage/collections/config/" + checkpoint_key,
            sessionKey=session_key, method='DELETE', getargs={"output_mode": "json"}, raiseAllErrors=True
        )
        logger.info(
            'message=delete_checkpoint | Deleted checkpoint for key: {}'.format(checkpoint_key)
        )
    except ResourceNotFound:
        # Log a debug message if the checkpoint is not found
        logger.debug('message=delete_checkpoint | Checkpoint key was not present: {}'.format(checkpoint_key))
    except Exception:
        # Handle any exceptions that occur
        logger.error(
            "message=checkpoint_error |"
            " Error occurred while Deleting Checkpoint.\n{0}"
            " Make sure your splunk management port is configured correctly in"
            " Configurations > KVStore Lookup Rest".format(traceback.format_exc())
        )
        raise
