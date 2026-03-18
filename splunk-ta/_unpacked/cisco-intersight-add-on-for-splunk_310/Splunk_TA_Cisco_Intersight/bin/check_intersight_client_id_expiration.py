"""Check Intersight Client Id Expiration."""

import sys
# This import is required to resolve the absolute paths of supportive modules
# implemented throughout the add-on. The relative imports used in other files
# of the add-on are resolved by importing this module.
import import_declare_test  # noqa: F401  # pylint: disable=unused-import # needed to resolve paths
from splunklib.searchcommands import dispatch, GeneratingCommand, Configuration
from solnlib.utils import is_true
from solnlib.conf_manager import ConfManagerException
from intersight_helpers.conf_helper import get_conf_file
from intersight_helpers.constants import SplunkEndpoints, Rest, ConfFilename
from intersight_helpers.logger_manager import setup_logging
from intersight_helpers.rest_helper import RestHelper
from intersight_helpers.common_helper import CommonHelper
from splunk import rest
import datetime
import time
import traceback
from typing import Dict, Any

logger = setup_logging("ta_intersight_client_id_validation")


def get_expiration_time_diff(client_id_expiry: str) -> int:
    """
    Get Expiration days remaining with respect to the current day.

    Given the Intersight Client ID expiration timestamp, calculate the days
    remaining until expiration.

    :param str client_id_expiry: Intersight Client ID expiration timestamp
    :return int: Days remaining until Client ID expiration
    """
    datetime_format = Rest.INTERSIGHT_DATETIME_FORMAT

    expiry_dt = datetime.datetime.strptime(client_id_expiry, datetime_format).date()
    current_date = datetime.datetime.utcnow().date()

    days_remaining = (expiry_dt - current_date).days
    return days_remaining


@Configuration()
class CheckIntersightClientExpiration(GeneratingCommand):
    """Check Intersight Client Id Expiration.

    This class is responsible for periodically checking the expiration status of the
    Intersight Client ID and sending notifications to the Splunk UI if the Client ID
    is about to expire.
    """

    def get_conf_object(self, session_key: str) -> object:
        """
        Fetch Conf file object.

        :param session_key: The session key of the user.
        :type session_key: str
        :return: A Conf file object
        :rtype: object
        """
        try:
            stanza = get_conf_file(
                file=ConfFilename.ACCOUNT_CONF,
                session_key=session_key,
            )
            return stanza
        except ConfManagerException as e:
            # If the file does not exist, return an empty dictionary
            if f"{ConfFilename.ACCOUNT_CONF} does not exist." in str(e):
                return {}
            else:
                raise
        except Exception as e:
            raise FileNotFoundError(
                "message=client_id_expiration_check | Error occurred while fetching configurations from "
                f"'{ConfFilename.ACCOUNT_CONF}.conf' file. Error: {e}"
            )

    def fetch_account_information(self, session_key: str) -> dict:
        """
        Fetch Account Information.

        Fetch all the configured accounts from the file specified by the parameter
        ConfFilename.ACCOUNT_CONF.

        :param session_key: The session key of the user.
        :type session_key: str
        :return: A dictionary containing account information
        :rtype: dict
        """
        try:
            stanza = self.get_conf_object(session_key)
            # Fetch all the configured accounts
            account_info = stanza.get_all(only_current_app=True)
            return account_info
        except Exception as e:
            raise e

    def update_account_information(
        self,
        session_key: str,
        stanza_name: str,
        updated_stanza_details: dict,
        encrypt_keys: list
    ) -> None:
        """
        Update Account Information.

        :param session_key: The session key of the user.
        :type session_key: str
        :param stanza_name: The stanza name (account name).
        :type stanza_name: str
        :param updated_stanza_details: The dict for the account info.
        :type updated_stanza_details: dict
        :param encrypt_keys: The list of keys to be encrypted.
        :type encrypt_keys: list
        :return: None
        :rtype: None
        """
        try:
            stanza = self.get_conf_object(session_key)
            # Fetch all the configured accounts
            stanza.update(stanza_name=stanza_name, stanza=updated_stanza_details, encrypt_keys=encrypt_keys)
        except Exception as e:
            raise e

    def generate(
        self
    ) -> Dict[str, Any]:
        """Generate Method.

        This method is responsible for periodically checking the expiration status of
        the Intersight Client ID and sending notifications to the Splunk UI if the Client
        ID is about to expire.

        The method fetches all the configured accounts from the file specified by the
        parameter ConfFilename.ACCOUNT_CONF. It then iterates through the account stanzas
        to check for Client Id expiration.

        If the Client Id is about to expire in 14 days, a notification is sent to the
        Splunk UI.

        :return dict: An empty dictionary
        """
        logger.info("message=client_id_expiration_check | Started Verification of Client for Cisco Intersight Account.")
        session_key = self._metadata.searchinfo.session_key
        account_stanza = self.fetch_account_information(session_key)

        # No configured accounts.
        if not account_stanza:
            logger.info("message=client_id_expiration_check | No configured accounts found.")
            return {}

        # Iterate through the account stanzas to check for Client Id expiration.
        for stanza_name, stanza_details in account_stanza.items():
            logger.info(
                "message=client_id_expiration_check | "
                "Verifying Client Id expiration for stanza: '{}'".format(stanza_name)
            )

            error_occured = None

            client_id = stanza_details["client_id"]
            client_secret = stanza_details["client_secret"]
            intersight_hostname = stanza_details["intersight_hostname"]

            # Create a dictionary to store the configuration for the client
            acc_data = {
                "session_key": session_key,
                "client_id": client_id,
                "client_secret": client_secret,
                "intersight_hostname": intersight_hostname
            }

            expiration_delta_days = 0
            try:
                # Create a RestHelper object with the configuration
                rest_helper = RestHelper(acc_data, logger)
            except Exception as e:
                error_occured = str(e)
                logger.error(
                    "message=client_id_expiration_check | Exception occcured while creating rest helper object "
                    "Error: {}".format(e)
                )
                # Check for specific errors
                err_msg = "OAuth2.0 Application is invalid, disabled or expired"
                if err_msg in str(e.args[0]):
                    expiration_delta_days = -1
                    stanza_details["valid_until"] = "Expired"
                else:
                    yield {
                        '_time': time.time(),
                        '_raw': f"Verification failed for intersight account '{stanza_name}'. Error: {error_occured}"
                    }
                    continue

            if expiration_delta_days != -1:
                # Create a CommonHelper object
                common_helper_obj = CommonHelper(logger)

                # Call the fetch_client_id_expire_timestamp method from the CommonHelper object
                # to fetch the Client ID expiration timestamp
                client_expiry_timestamp, client_never_expiring = common_helper_obj.fetch_client_id_expire_timestamp(
                    client_id, rest_helper
                )

                # Check if the Client ID never expires
                client_never_expiring = is_true(client_never_expiring)

                logger.info(
                    "message=client_id_expiration_check | "
                    "Client ID Expiration Timestamp: {}".format(client_expiry_timestamp)
                )
                logger.info(
                    "message=client_id_expiration_check | "
                    "Client ID never expiring: {}".format(client_never_expiring)
                )

                if client_never_expiring:
                    logger.info(
                        "message=client_id_expiration_check | "
                        "Client ID for account: '{}' is never expiring.".format(stanza_name)
                    )
                    stanza_details["valid_until"] = "Never Expires"
                    expiration_delta_days = -2
                else:
                    # Calculate the days remaining until expiration
                    expiration_delta_days = get_expiration_time_diff(client_expiry_timestamp)

                    logger.info(
                        "message=client_id_expiration_check | {} days "
                        "remaining for Client ID Expiration for Cisco Intersight account '{}'."
                        .format(expiration_delta_days, stanza_name)
                    )

                    stanza_details["valid_until"] = client_expiry_timestamp.rstrip('Z').replace("T", " ")

            try:
                self.update_account_information(
                    stanza_name=stanza_name,
                    updated_stanza_details=stanza_details,
                    session_key=session_key,
                    encrypt_keys=['client_secret']
                )
            except Exception as e:
                error_occured = str(e)
                logger.error(
                    "message=client_id_expiration_check | Exception occcured while updating "
                    "the stanza details in the conf file. "
                    "Error: {}".format(e)
                )
                yield {
                    '_time': time.time(),
                    '_raw': f"Verification failed for intersight account '{stanza_name}'. Error: {error_occured}"
                }
                continue

            # Client Id is about to expire in 14 days.
            if int(expiration_delta_days) <= Rest.CLIENT_ID_EXPIRATION_THRESHOLD and expiration_delta_days != -2:
                # Create a notification message
                notification_message = ""
                severity_level = ""
                if int(expiration_delta_days) == -1:
                    # Create a notification message
                    notification_message = (
                        f"The Client ID for the Cisco Intersight account '{stanza_name}' "
                        f"is expired. To ensure uninterrupted operations and prevent potential"
                        " data loss, please update the Client at your earliest convenience."
                    )
                    severity_level = "critical"
                else:
                    # Create a notification message
                    notification_message = (
                        f"The Client ID for the Cisco Intersight account '{stanza_name}' "
                        f"is set to expire in {expiration_delta_days} days. To ensure uninterrupted operations and "
                        "prevent potential data loss, please update the Client at your earliest convenience."
                    )
                    severity_level = "warn"

                try:
                    # Post notification to Splunk UI.
                    rest.simpleRequest(
                        SplunkEndpoints.SPLUNK_NOTIFICATION_ENDPOINT,
                        method='POST',
                        sessionKey=session_key,
                        postargs={
                            "name": f"TA_Intersight-client_id_Expired-acc-{stanza_name}",
                            "value": notification_message,
                            "severity": severity_level
                        },
                        raiseAllErrors=True
                    )
                    logger.info(
                        "message=client_id_expiration_check | Notification message sent on Splunk UI for Client ID "
                        "expiration for account: '{}'.".format(stanza_name))
                except Exception as e:
                    error_occured = e
                    logger.error(
                        "message=client_id_expiration_check | Exception occcured while sending notification on "
                        "Splunk UI for account: {}. Error: {}".format(stanza_name, e)
                    )
                    logger.debug(
                        "message=client_id_expiration_check | Exception occcured while sending notification on UI for "
                        "account: {}. Error trace: {}".format(stanza_name, traceback.format_exc())
                    )
                    yield {
                        '_time': time.time(),
                        '_raw': f"Verification failed for intersight account '{stanza_name}'. Error: {error_occured}"
                    }
                    continue
            else:
                logger.info("message=client_id_expiration_check | The Client ID is valid and not nearing expiration. "
                            "It is safe to use for the data collection.")
            yield {
                '_time': time.time(),
                '_raw': (
                    "Client Id and Client Secret verification successfully "
                    f"completed for intersight account '{stanza_name}'."
                )
            }
        return {}


dispatch(CheckIntersightClientExpiration, sys.argv, sys.stdin, sys.stdout, __name__)
