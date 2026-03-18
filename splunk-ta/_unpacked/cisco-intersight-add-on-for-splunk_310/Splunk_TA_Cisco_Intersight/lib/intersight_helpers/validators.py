"""This file is used for validation."""
from splunktaucclib.rest_handler.endpoint.validator import Validator
from intersight_helpers import logger_manager, conf_helper, constants, common_helper, rest_helper
from splunk import admin
import traceback
from copy import deepcopy
from import_declare_test import ta_name
import datetime
import re
import requests
import splunklib.client as splunkClient
from splunklib.client import KVStoreCollection
from solnlib.credentials import CredentialException
from typing import Any, Dict, Optional, Union

SSL_ERROR = "_ssl.c"


class GetSessionKey(admin.MConfigHandler):
    """Session key."""

    def __init__(self) -> None:
        """Initialize Session Key."""
        self.session_key = self.getSessionKey()


class FetchExpirationTime(Validator):
    """This class validates intersight account service account."""

    # pylint: disable=too-many-positional-arguments  # this is UCCs default function hence can't modify it
    def validate(
        self,
        value: Any,  # pylint: disable=unused-argument
        data: Dict[str, Any],
        acc_name: Optional[str] = None,
        session_key: Optional[str] = None,
        ui: bool = True  # pylint: disable=unused-argument
    ) -> bool:
        """
        Validate intersight account service account.

        :param value: The value of the field to be validated
        :param data: The data of the configuration
        :param acc_name: The name of the account
        :param session_key: The session key
        :param ui: If the validation is running in the UI or not
        :return: True if the validation is successful, False otherwise
        """
        try:
            logger = logger_manager.setup_logging(constants.TA_ACCOUNT_VALIDATION, account_name=acc_name)
            logger.info("message=account_validation | Account validation started.")
            if not session_key:
                session_key = GetSessionKey().session_key
            acc_data = deepcopy(data)
            acc_data.update({"session_key": session_key})
            intersight_rest_helper = rest_helper.RestHelper(acc_data, logger)
            intersight_common_helper = common_helper.CommonHelper(logger)
            logger.info("message=account_validation_success | Account validation successful.")

            # Fetch AccountMoid during validation
            try:
                intersight_rest_helper.get_hostname_source()
                account_moid = getattr(intersight_rest_helper, 'ckpt_account_moid', None)
                account_name = getattr(intersight_rest_helper, 'ckpt_account_name', None)
                if account_moid or account_name:
                    data['intersight_account_moid'] = account_moid
                    data['intersight_account_name'] = account_name
                    logger.info("message=account_moid_fetched | Successfully fetched AccountMoid: %s", account_moid)
                else:
                    logger.warning("message=account_moid_warning | No AccountMoid found during validation")
            except Exception as e:
                logger.warning(
                    "message=account_moid_fetch_warning | Could not fetch AccountMoid during validation: %s",
                    str(e)
                )

            client_expiry_timestamp, client_never_expiring = intersight_common_helper.fetch_client_id_expire_timestamp(
                acc_data["client_id"].strip(), intersight_rest_helper
            )
            if client_never_expiring:
                data['valid_until'] = "Never Expires"
            else:
                data['valid_until'] = client_expiry_timestamp.rstrip('Z').replace("T", " ")
            logger.info("message=client_id_expiration_timestamp | Fetched Client Id Expiration timestamp.")
            logger.info(
                "message=client_id_expiration_timestamp | client_expiry_timestamp: {} and "
                "client_never_expiring: {}".format(
                    client_expiry_timestamp, client_never_expiring
                )
            )
            return True
        except Exception as e:
            logger.error(
                "message=account_validation_error | Error occurred "
                f" while validating account: {traceback.format_exc()}"
            )
            # 404: URL not found.
            # 502: Connection time out.
            if "404" in str(e) or "522" in str(e):
                self.put_msg(
                    "Error occurred while validating account."
                    " Please check if the hostname provided is valid."
                    f"\nError: {e}"
                )
            else:
                self.put_msg(
                    f"{e}"
                )

            return False


class ValidateStartTime(Validator):
    """Validate Start date and Time."""

    # pylint: disable=arguments-renamed # this is UCCs default function hence can't modify it
    def validate(
        self,
        date_input: str,
        acc_name: Optional[str] = None,
        session_key: Optional[str] = None,  # pylint: disable=unused-argument
        ui: bool = True  # pylint: disable=unused-argument
    ) -> bool:
        """
        Validate the provided date_input.

        The function checks if the provided date_input is in the correct format and not in the future.

        :param date_input: The date string to be validated.
        :param acc_name: The name of the account.
        :param session_key: The session key.
        :param ui: Boolean indicating if the validation is running in the UI.
        :return: True if the date is valid, False otherwise.
        """
        # Set up logging for the validation process
        logger = logger_manager.setup_logging(constants.TA_ACCOUNT_VALIDATION, account_name=acc_name)
        logger.info("message=start_time_validation | Start Time validation started.")

        try:
            # Parse the date_input to a datetime object
            parsed_date = datetime.datetime.strptime(date_input, "%Y-%m-%dT%H:%M:%SZ")

            # Check if the parsed date is in the future
            if parsed_date > datetime.datetime.utcnow():
                logger.error("message=future_date_error | The provided date {} is in the future.".format(date_input))
                self.put_msg("Invalid date provided. The date cannot be in the future.")
                return False

            # Return True if the date is valid
            return True

        except ValueError as e:
            # Handle ValueError if the date_input is in wrong format
            logger.error("message=date_validation_error | ValueError: {} for date_input: {}".format(e, date_input))
            self.put_msg("Invalid date provided. Please provide a valid date in the expected format.")
            return False

        except Exception as e:
            # Handle any other unexpected exceptions
            logger.error("message=date_validation_error | Exception: {} for date_input: {}".format(e, date_input))
            self.put_msg(
                "Error occurred while validating the start date. "
                "Please provide a valid date in the expected format."
            )
            return False


class IntervalValidation(Validator):
    """This class validates audit&alarm and inventory interval."""

    # pylint: disable=arguments-renamed # this is UCCs default function hence can't modify it
    def validate(
        self,
        interval: Union[str, int],
        acc_name: Optional[str] = None,
        session_key: Optional[str] = None,  # pylint: disable=unused-argument
        ui: bool = True  # pylint: disable=unused-argument
    ) -> bool:
        """
        Validate intersight poling interval for audit&alarm and inventory data.

        :param interval: The interval provided by the user.
        :param acc_name: The name of the account.
        :param session_key: The session key.
        :param ui: Boolean indicating if the validation is running in the UI.
        :return: True if the interval is valid, False otherwise.
        """
        logger = logger_manager.setup_logging(constants.TA_INTERVAL_VALIDATION, account_name=acc_name)
        logger.info("message=interval_validation | Interval validation started.")
        try:
            # Check if the interval is a positive integer
            if interval.isdigit():
                interval = int(interval)
                if interval < 3600:
                    # If the interval is less than 1 hour, put an error message
                    self.put_msg("Interval must be greater than 1 hour.")
                    logger.error("Interval must be greater than 1 hour.")
                    return False
            else:
                logger.error("Interval must be a positive integer.")
                self.put_msg("Interval must be a positive integer.")
                return False
            # If the interval is not a positive integer, log an error and put an error message
            logger.info("message=interval_validation | Interval validation successful.")
        except Exception as e:
            # Handle any other unexpected exceptions
            logger.error(
                "message=interval_validation | "
                "Error occurred while validating interval: {}, Traceback: {}".format(
                    e, traceback.format_exc()
                )
            )
            self.put_msg("Interval must be a positive integer.")
            return False
        # If all checks pass, return True
        return True


class MetricsIntervalValidation(Validator):
    """This class validates intersight metrics interval."""

    # pylint: disable=arguments-renamed # this is UCCs default function hence can't modify it
    def validate(
        self,
        interval: Union[str, int],
        acc_name: Optional[str] = None,
        session_key: Optional[str] = None,  # pylint: disable=unused-argument
        ui: bool = True  # pylint: disable=unused-argument
    ) -> bool:
        """
        Validate intersight poling interval for metrics data.

        :param interval: The interval provided by the user.
        :param acc_name: The name of the account.
        :param session_key: The session key.
        :param ui: Boolean indicating if the validation is running in the UI.
        :return: True if the interval is valid, False otherwise.
        """
        logger = logger_manager.setup_logging(constants.TA_INTERVAL_VALIDATION, account_name=acc_name)
        logger.info("message=interval_validation | Interval validation started.")
        try:
            # Check if the interval is a positive integer
            pattern = r'^\d+$'
            if re.match(pattern, str(interval)):
                interval = int(interval)
                # Check if the interval is greater than 900 seconds
                if interval < 900:
                    logger.error("Interval must be greater than 900 seconds.")
                    self.put_msg("Interval must be greater than 900 seconds.")
                    return False
            else:
                logger.error("Interval must be a positive integer.")
                self.put_msg("Interval must be a positive integer.")
                return False
            # If the interval is not a positive integer, log an error and put an error message
            logger.info("message=interval_validation | Interval validation successful.")
        except Exception as e:
            # Handle any other unexpected exceptions
            logger.error(
                "message=interval_validation | "
                "Error occurred while validating interval: {}, Traceback: {}".format(
                    e, traceback.format_exc()
                )
            )
            self.put_msg("Interval must be a positive integer.")
            return False
        # If all checks pass, return True
        return True


class SplunkKvStoreRest(Validator):
    """Validate Splunk KV Store REST configurations and connections."""

    COLLECTIONS: Dict[str, Any] = {
        "Cisco_Intersight_cond_alarms": KVStoreCollection,
    }

    def __init__(self) -> None:
        """
        Initialize the SplunkKvStoreRest instance and sets up logging.

        This class is used to validate Splunk KV Store REST configurations and connections.
        """
        self.logger = logger_manager.setup_logging('ta_intersight_kvstore_validation')
        """The logger for this class."""
        self.splunk_service = None
        """The Splunk service object."""
        self.splunk_host = None
        """The host name of the Splunk instance."""
        super().__init__()

    def _connect_splunk_service(
            self,
            kvstore_stanza: Dict[str, Any]) -> None:
        """
        Connect to the Splunk service using the provided KV Store stanza.

        This method uses the provided KV Store stanza to connect to the Splunk service.
        If the host is not localhost or 127.0.0.1, it logs in using the provided username
        and password. Otherwise, it logs in using the provided session key.

        :param kvstore_stanza: The KV Store stanza configuration.
        :return: None
        """
        if (
            kvstore_stanza.get("host") not in ("localhost", "127.0.0.1")
            or kvstore_stanza.get("username")
            or kvstore_stanza.get("password")
        ):
            self.logger.debug(
                "message=kvstore_validation | Logging in to the RemoteSplunk: {}".format(
                    kvstore_stanza.get('host')
                )
            )
            # Log in to the Splunk service using the provided username and password
            self.splunk_service = splunkClient.connect(
                host=kvstore_stanza.get("host"),
                port=kvstore_stanza.get("port"),
                verify=kvstore_stanza.get("verify"),
                username=kvstore_stanza.get("username"),
                password=kvstore_stanza.get("password"),
                owner=kvstore_stanza.get("owner"),
                app=kvstore_stanza.get("app"),
            )
            self.logger.debug(
                "message=kvstore_validation_success | Successfully logged into "
                "RemoteSplunk: {}".format(kvstore_stanza.get('host'))
            )
        else:
            # Log in to the Splunk service using the provided session key
            self.splunk_service = splunkClient.connect(
                host=kvstore_stanza.get("host"),
                port=kvstore_stanza.get("port"),
                verify=kvstore_stanza.get("verify"),
                token=kvstore_stanza.get("session_key"),
                owner=kvstore_stanza.get("owner"),
                app=kvstore_stanza.get("app"),
            )
        # Set the splunk_host attribute to the host name of the Splunk instance
        self.splunk_host = kvstore_stanza.get("host")

    def check_kvstore_collections(self) -> None:
        """
        Verify the existence of the Splunk KV Store collections.

        This function will iterate over the list of collections specified in the
        `COLLECTIONS` class attribute and verify the existence of each collection
        in the Splunk KV Store.
        """
        for intersight_collection in self.COLLECTIONS:
            # Iterate over the collections in the Splunk KV Store
            for each_collection in self.splunk_service.kvstore:
                # Check if the collection name matches the expected name
                if str(each_collection.name) == intersight_collection:
                    # If the collection is found, log a success message
                    self.logger.debug(
                        "message=kvstore_validation | Found the collection {}".format(
                            intersight_collection
                        )
                    )
                    # Store the collection object in the COLLECTIONS class
                    # attribute
                    self.COLLECTIONS[
                        intersight_collection
                    ] = self.splunk_service.kvstore[each_collection.name]
                    # Break out of the loop as the collection is found
                    break
            else:
                # If the collection is not found, raise an exception with a
                # detailed error message
                raise Exception(
                    f"KVStore collection {intersight_collection} not found on "
                    f"{self.splunk_host} Splunk instance."
                )

    def validate_splunk_kvstore_rest_credentials(
            self, data: Dict[str, Any]) -> None:
        """
        Validate Splunk KV Store REST credentials.

        This function checks the configuration for connecting to the Splunk KV Store
        and verifies the existence of the necessary collections.

        :param data: A dictionary containing configuration details for Splunk KV Store.
        :raises Exception: If validation fails due to various reasons such as connection errors,
                           SSL errors, or credential issues.
        """
        try:
            # Prepare the KV Store connection configuration
            kvstore_stanza = {
                "host": data.get("splunk_rest_host_url"),
                "port": data.get("splunk_rest_port"),
                "session_key": GetSessionKey().session_key,
                "owner": "nobody",
                "app": ta_name,
                "username": data.get("splunk_username"),
                "password": data.get("splunk_password"),
                "verify": constants.VERIFY_SSL,
            }

            # Disable SSL verification for local connections
            if kvstore_stanza["host"] in ("127.0.0.1", "localhost"):
                kvstore_stanza["verify"] = False

            # Connect to Splunk service if not already connected
            if not self.splunk_service:
                self._connect_splunk_service(kvstore_stanza)
            else:
                self.splunk_host = "local"

            # Log the start of the validation process
            self.logger.debug("message=kvstore_validation | Checking in the Cisco "
                              "Intersight Collections...")

            # Check for the existence of required KV Store collections
            self.check_kvstore_collections()

        except requests.exceptions.SSLError as e:
            # Handle SSL errors
            error_msg = "Please verify the SSL certificate for the provided configuration."
            self.logger.exception("message=kvstore_validation_error | {} : {}".format(error_msg, e))
            raise Exception(f"Error occurred while validating the provided details: {error_msg}") from None

        except ValueError as e:
            # Handle value errors
            self.logger.exception("message=kvstore_validation_error | {}".format(str(e)))
            self.put_msg(str(e))
            raise Exception(f"Error occurred while validating the provided details: {e}") from None

        except (
            requests.exceptions.ConnectionError,
            ConnectionRefusedError,
            requests.exceptions.RequestException,
        ) as e:
            # Handle connection errors
            error_msg = "Could not connect to the Splunk instance. Please verify Host URL and Port."
            self.logger.exception("message=kvstore_validation_error | {} : {}".format(error_msg, e))
            raise Exception(f"Error occurred while validating the provided details: {error_msg}") from None

        except CredentialException as e:
            # Handle credential errors
            error_msg = "Please verify the credentials provided."
            self.logger.exception("message=kvstore_validation_error | {} : {}".format(error_msg, e))
            self.put_msg(error_msg)
            raise CredentialException(error_msg) from None

        except Exception as e:
            # Handle any other exceptions
            self.logger.exception("message=kvstore_validation_error | {}".format(str(e)))
            raise Exception(f"Error occurred while validating the provided details: {e}") from None

    # this is UCCs default function hence can't modify it
    def validate(
            self,
            value: Any,
            data: Dict[str, Any]) -> bool:  # pylint: disable=unused-argument
        """
        Validate the input data for Splunk KV Store REST configuration.

        This function validates the input data for connecting to the Splunk KV Store
        and verifies the existence of the necessary collections.

        :param value: The value of the current field.
        :param data: A dictionary containing configuration details for Splunk KV Store.
        :return: True if the validation is successful, False otherwise.
        """
        try:
            # If the host URL is not provided, set it to localhost
            if not data.get("splunk_rest_host_url"):
                data["splunk_rest_host_url"] = "localhost"
            # If the port is not provided, set it to the management port
            if not data.get("splunk_rest_port"):
                data["splunk_rest_port"] = int(
                    conf_helper.get_mgmt_port(GetSessionKey().session_key)
                )
            # Validate the Splunk KV Store REST credentials
            self.validate_splunk_kvstore_rest_credentials(data)
            # Log a success message if the validation is successful
            self.logger.info(
                "message=kvstore_validation_success | KVStore Validation: success"
            )
        except Exception as e:
            # Handle SSL errors
            if SSL_ERROR in str(e):
                self.logger.exception(
                    "message=kvstore_validation_error | SSL certificate verification "
                    "failed. Please add a valid SSL certificate."
                )
            # Handle other exceptions
            else:
                self.logger.exception("message=kvstore_validation_error | KVStore "
                                      "Validation: failed. Error : {}".format(e))
            # Store the error message in the message queue
            self.put_msg(e)
            # Return False to indicate that the validation has failed
            return False
        finally:
            # Reset the Splunk service object
            self.splunk_service = None

        # Return True to indicate that the validation has succeeded
        return True
