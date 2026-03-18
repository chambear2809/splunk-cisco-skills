# pylint: disable=too-many-lines

"""
This module provides helper functions and classes for interacting with the Intersight REST API.

It includes utilities for authentication, request handling, and data processing.
"""
import requests
from requests.adapters import HTTPAdapter, Retry
from import_declare_test import ta_name
from intersight_helpers import (
    intersight_authorize, metric_helper, metric_mapper,
    conf_helper, constants, common_helper, kvstore
)
from solnlib.utils import is_true
import traceback
import time
from typing import Optional, List, Tuple, Dict, Any, Union, TYPE_CHECKING
import logging
from datetime import datetime
from copy import deepcopy

if TYPE_CHECKING:
    from intersight_helpers.event_ingestor import EventIngestor


class RestHelper:
    """
    Rest Helper Class.

    This class provides methods for interacting with the Intersight API.
    """

    def __init__(self, intersight_config: dict, logger: logging.Logger) -> None:
        """
        Rest Helper Class Constructor.

        :param intersight_config: Intersight configuration.
        :type intersight_config: dict
        :param logger: Logger object.
        :type logger: logging.Logger
        :return: None
        :rtype: None
        """
        self.intersight_config = intersight_config
        self.logger = logger
        self.session_key = intersight_config.get("session_key")

        # Intersight API details
        self.intersight_hostname = intersight_config.get(
            "intersight_hostname", ""
        ).strip()
        self.client_id = intersight_config.get("client_id", "").strip()
        self.client_secret = intersight_config.get("client_secret", "").strip()

        # API call count
        self.api_call_count = {}

        # Proxy settings
        self.proxy = conf_helper.get_proxy_info(session_key=self.session_key)
        self.ssl = conf_helper.get_conf_file(
            file="splunk_ta_cisco_intersight_settings",
            stanza="verify_ssl",
            session_key=self.session_key,
        )
        self.ssl_value = self.ssl.get('ssl_validation')
        self.verify = is_true(self.ssl_value)

        # app version
        app_conf = conf_helper.get_conf_file(
            file="app", session_key=self.session_key, stanza="launcher"
        )
        self.version = app_conf.get("version")

        # Session object
        self.session = self.__get_session()

        # Get Intersight hostname source
        self.get_hostname_source(retry=False)

        # KVStore manager
        self.kvstore_manager = kvstore.KVStoreManager(session_key=self.session_key)

        # Metric Helper
        self.metric_helper = metric_helper.MetricHelper(self.logger, self.kvstore_manager)

        # Common Helper
        self.common_helper = common_helper.CommonHelper(self.logger)

        # Metric Mapper
        self.metric_mapper = metric_mapper.MetricMapper(self.logger)

    def get(
        self,
        endpoint: str,
        timeout: int = constants.Rest.REQUEST_TIMEOUT,
        retry: bool = True,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Get API call to Intersight.

        :param endpoint: Intersight API endpoint.
        :param timeout: Timeout in seconds for the request.
        :param retry: Whether to retry the request.
        :param params: Parameters for the request.
        :param retries: Number of retry attempts (default: 3).
        :return: Response JSON.
        """
        try:
            self.api_call_count.update({
                endpoint: self.api_call_count.get(endpoint, 0) + 1
            })
            full_url = (
                f"{constants.PROTOCOL}{self.intersight_hostname}"
                f"{constants.Endpoints.INTERSIGHT_SERVER_ADDRESS}{endpoint}"
            )
            session = self.session if retry else self.__get_session(retries=0)

            if endpoint == constants.Endpoints.METRICS:
                session.headers["User-Agent"] = f"{ta_name}-{self.version}_metrics"
            else:
                session.headers["User-Agent"] = f"{ta_name}-{self.version}_inventory"

            self.logger.debug(
                f"message=HttpRequest | type=Get, endpoint={endpoint}, timeout={timeout}, retry={retry}, "
                f"verify={self.verify}, proxy={bool(self.proxy)}, params={params}, initiating..."
            )

            self.logger.info(
                f"message=HttpRequest | API Call Execution: URL: {full_url}, Params: {params}"
            )
            response = session.get(full_url, timeout=timeout, params=params)

            self.logger.debug(
                f"message=HttpRequest | type=Get, url={endpoint}, status={response.status_code}"
            )

            response.raise_for_status()
            return response.json()

        except requests.exceptions.ProxyError as e:
            # Handle proxy errors
            error_msg = "Please verify the configured proxy."
            self.logger.exception(f"message=HttpRequest_error | {error_msg} {e}")
            raise type(e)(error_msg) from None

        except requests.exceptions.SSLError as e:
            # Handle SSL errors
            error_msg = (
                "Please verify the SSL certificate for the provided configuration."
            )
            self.logger.exception(f"message=HttpRequest_error | {error_msg}: {e}")
            raise type(e)(error_msg) from None

        except requests.exceptions.ConnectionError as e:
            # Handle connection errors
            error_msg = (
                "Could not connect to the server. "
                "Please verify the provided credentials or proxy configurations."
            )
            self.logger.exception(f"message=HttpRequest_error | {error_msg}: {e}")
            raise type(e)(error_msg) from None

        except requests.exceptions.HTTPError as e:
            # Handle HTTP errors
            try:
                status_code = e.response.status_code
            except Exception:
                status_code = None

            try:
                resp_error_msg = e.response.json().get("error_description")
            except Exception:
                resp_error_msg = str(e)

            # For server errors (5xx) and 529, re-raise without modification
            # This allows paginate_data to catch and trigger fallback logic
            if status_code in [500, 502, 503, 504, 529]:
                self.logger.warning(
                    f"message=HttpRequest_error | Server error {status_code} occurred for endpoint {endpoint}. "
                    f"Re-raising for fallback handling. Error: {resp_error_msg}"
                )
                raise  # Re-raise original exception for fallback logic

            if status_code == 401:
                # Unauthorized. Rebuild session and retry once.
                try:
                    self.logger.info(
                        "message=HttpRequest_401 | Token may be expired. Rebuilding session and retrying GET once."
                    )
                    # Rebuild session to get a fresh token
                    new_session = self.__get_session()
                    if endpoint == constants.Endpoints.METRICS:
                        new_session.headers["User-Agent"] = f"{ta_name}-{self.version}_metrics"
                    else:
                        new_session.headers["User-Agent"] = f"{ta_name}-{self.version}_inventory"
                    response = new_session.get(full_url, timeout=timeout, params=params)
                    response.raise_for_status()
                    # Update self.session with the new session for future requests
                    self.session = new_session
                    return response.json()
                except Exception as retry_err:
                    self.logger.debug(
                        f"message=HttpRequest_401_retry_failed | Retry after rebuilding session failed: {retry_err}"
                    )
                error_msg = (
                    f"Please verify the provided credentials."
                    f"Error: {resp_error_msg}"
                )
                self.logger.exception(f"message=HttpRequest_error | {error_msg}: {e}")
                raise type(e)(error_msg) from None

            if status_code == 403:
                # Handle forbidden errors
                error_msg = (
                    "Request failed: Insufficient permissions or invalid API endpoint detected."
                    "Verify the endpoint and casing, as API endpoints are case-sensitive."
                    f"Error: {resp_error_msg}"
                )
                self.logger.exception(f"message=HttpRequest_error | {error_msg}: {e}")
                raise type(e)(error_msg) from None

            if status_code == 429:
                # Handle rate limit exceeded errors
                error_msg = (
                    "Intersight API Limit Exceeded."
                    f"Error: {resp_error_msg}"
                )
                self.logger.exception(f"message=HttpRequest_error | {error_msg}: {e}")
                raise type(e)(error_msg) from None

            self.logger.exception(
                f"message=HttpRequest_error | HttpRequest Failed: {e}, Traceback - {traceback.format_exc()}"
            )
            raise
        except Exception as e:
            # Handle other exceptions
            self.logger.exception(
                f"message=HttpRequest_error | HttpRequest Failed: {e}"
            )
            raise

    def post(
        self,
        endpoint: str,
        kwargs: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Post API call to Intersight.

        :param endpoint: API endpoint to call
        :param kwargs: Additional keyword arguments passed to the session.post method
        :return: JSON response from the API call
        """
        timeout = kwargs.get("timeout", constants.Rest.REQUEST_TIMEOUT)
        retry = kwargs.get("retry", True)
        params = kwargs.get("params", None)
        payload = kwargs.get("payload", None)

        try:
            self.api_call_count.update({
                endpoint: self.api_call_count.get(endpoint, 0) + 1
            })
            full_url = (
                f"{constants.PROTOCOL}{self.intersight_hostname}"
                f"{constants.Endpoints.INTERSIGHT_SERVER_ADDRESS}{endpoint}"
            )
            session = self.session if retry else self.__get_session(retries=0)

            if endpoint == constants.Endpoints.METRICS:
                session.headers["User-Agent"] = f"{ta_name}-{self.version}_metrics"
            else:
                session.headers["User-Agent"] = f"{ta_name}-{self.version}_inventory"

            self.logger.debug(
                f"message=HttpRequest | type=Post, endpoint={endpoint}, timeout={timeout}, retry={retry}, "
                f"verify={self.verify}, proxy={bool(self.proxy)}, params={params}, payload={payload} initiating..."
            )

            response = session.post(
                full_url, timeout=timeout, json=payload, params=params
            )

            self.logger.debug(
                f"message=HttpRequest | type=Post, url={endpoint}, status={response.status_code}"
            )

            response.raise_for_status()
            return response.json()

        except requests.exceptions.ProxyError as e:
            error_msg = "Please verify the configured proxy."
            self.logger.exception(f"message=HttpRequest_error | {error_msg} {e}")
            raise type(e)(error_msg) from None

        except requests.exceptions.SSLError as e:
            error_msg = (
                "Please verify the SSL certificate for the provided configuration."
            )
            self.logger.exception(f"message=HttpRequest_error | {error_msg}: {e}")
            raise type(e)(error_msg) from None

        except requests.exceptions.ConnectionError as e:
            error_msg = (
                "Could not connect to the server. "
                "Please verify the provided credentials or proxy configurations."
            )
            self.logger.exception(f"message=HttpRequest_error | {error_msg}: {e}")
            raise type(e)(error_msg) from None

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code

            # Check for specific errors
            if status_code == 400:
                error_sub_string = "response exceeds maximum response size"
                error_message = e.response.json().get('message', '')
                if error_sub_string in error_message:
                    self.logger.error(
                        "message=HttpRequest_error | Falling back to host.id-level metrics collection. "
                        "Reason: {}".format(error_message)
                    )
                    return [{"FALLBACK": True}]
                else:
                    error_msg = "Unexpected 400 Error Occurred."
                    self.logger.exception(f"message=HttpRequest_error | {error_msg}: {e}")
                    raise type(e)(error_msg) from None

            if status_code == 401:
                # Unauthorized. Rebuild session and retry once.
                try:
                    self.logger.info(
                        "message=HttpRequest_401 | Token may be expired. Rebuilding session and retrying POST once."
                    )
                    # Rebuild session to get a fresh token
                    new_session = self.__get_session()
                    if endpoint == constants.Endpoints.METRICS:
                        new_session.headers["User-Agent"] = f"{ta_name}-{self.version}_metrics"
                    else:
                        new_session.headers["User-Agent"] = f"{ta_name}-{self.version}_inventory"
                    response = new_session.post(
                        full_url, timeout=timeout, json=payload, params=params
                    )
                    response.raise_for_status()
                    # Update self.session with the new session for future requests
                    self.session = new_session
                    return response.json()
                except Exception as retry_err:
                    self.logger.debug(
                        f"message=HttpRequest_401_retry_failed | Retry after rebuilding session failed: {retry_err}"
                    )
                error_msg = "Please verify the provided credentials."
                self.logger.exception(f"message=HttpRequest_error | {error_msg}: {e}")
                raise type(e)(error_msg) from None

            if status_code == 403:
                error_msg = (
                    "Request failed: Insufficient permissions or invalid API endpoint detected."
                    "Verify the endpoint and casing, as API endpoints are case-sensitive."
                    f"Error: {e}"
                )
                self.logger.exception(f"message=HttpRequest_error | {error_msg}: {e}")
                raise type(e)(error_msg) from None

            if status_code == 429:
                error_msg = "Intersight API Limit Exceeded."
                self.logger.exception(f"message=HttpRequest_error | {error_msg}: {e}")
                raise type(e)(error_msg) from None

            self.logger.exception(
                f"message=HttpRequest_error | HttpRequest Failed: {e}"
            )
            raise
        except Exception as e:
            self.logger.exception(
                f"message=HttpRequest_error | HttpRequest Failed: {e}"
            )
            raise

    def __get_session(
        self,
        retries: int = 3,
        backoff_factor: float = 60,
        status_forcelist: Tuple[int, ...] = constants.Rest.STATUS_FORCELIST,
        method_whitelist: Optional[List[str]] = None,
    ) -> requests.Session:
        """
        Create and return a session object with retry mechanism.

        :param retries: Maximum number of retries to attempt.
        :param backoff_factor: Backoff factor used to calculate time between retries.
            e.g. For 10 - 5, 10, 20, 40,...
        :param status_forcelist: A tuple containing the response status codes that should trigger a retry.
        :param method_whiltelist: HTTP methods on which retry will be performed.

        :return: Session Object
        """
        if method_whitelist is None:
            method_whitelist = ["GET", "POST", "HEAD"]

        session = requests.Session()

        session.verify = self.verify
        session.proxies = self.proxy

        session.headers["User-Agent"] = f"{ta_name}-{self.version}_token"
        self.logger.debug(f"message=HttpRequest | User-Agent: {session.headers['User-Agent']}")
        session.headers["Content-Type"] = "application/json; charset=utf8"
        # session.headers.update({"X-API-KEY": self.api_key})
        intersight_auth_kwargs = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "verify": self.verify,
            "proxy": self.proxy,
            "user-agent": session.headers["User-Agent"],
            "logger": self.logger,
            "instance_url": f"https://{self.intersight_hostname}/iam/token",
        }
        session.auth = intersight_authorize.IntersightAuth(
            intersight_auth_kwargs
        )

        if retries == 0:
            return session

        retry = Retry(
            total=retries,
            read=retries,
            connect=retries,
            backoff_factor=backoff_factor,
            status_forcelist=status_forcelist,
            allowed_methods=method_whitelist,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def get_hostname_source(
        self, retry: bool = True
    ) -> None:
        """
        Get Hostname and source.

        :param retry: Whether to retry the request if it fails.
        :type retry: bool
        :raises Exception: If there is an error connecting to Intersight.
        """
        try:
            self.logger.info("message=fetch_account | Getting Hostname and source.")
            if bool(constants.SAAS.match(self.intersight_hostname)):
                try:
                    response = self.get(
                        endpoint=constants.Endpoints.SAAS_ACCOUNT_ENDPOINT,
                        retry=retry
                    )
                    self.ckpt_account_name = response["Results"][0]["Name"]
                    self.ckpt_account_moid = response["Results"][0]["Moid"]
                    self.logger.info(
                        "message=fetch_account_success | Connected to Intersight SaaS "
                        f"account named {self.ckpt_account_name}"
                    )
                except Exception as e:
                    self.logger.error(
                        f"message=fetch_data_error | "
                        f"Error connecting intersight SaaS: {self.intersight_hostname} as: {e} "
                        f"Traceback - {traceback.format_exc()}"
                    )
                    raise
            else:
                if bool(constants.FQDN.match(self.intersight_hostname)):
                    try:
                        self.ckpt_account_name = self.intersight_hostname
                        response = self.get(
                            endpoint=constants.Endpoints.FQDN_ACCOUNT_ENDPOINT,
                            retry=retry
                        )
                        self.ckpt_account_moid = response["Results"][0]["AccountMoid"]
                        self.logger.info(
                            "message=fetch_account_success | Connected to Intersight On Prem "
                            f"server named {self.ckpt_account_name}"
                        )
                    except Exception as e:
                        self.logger.error(
                            f"message=fetch_data_error | Failed to connect to Intersight {e}"
                            f"On Prem server named: {self.intersight_hostname}"
                            f" Traceback - {traceback.format_exc()}"
                        )
                        raise
                else:
                    self.logger.error(
                        f"message=invalid_host_name | INVALID HOSTNAME: configured value "
                        f"is {self.intersight_hostname}"
                    )
                    raise ValueError(
                        f"message=invalid_host_name | INVALID HOSTNAME: configured value "
                        f"is {self.intersight_hostname}"
                    )

        except Exception:
            self.logger.error(
                f"message=fetch_data_error | Error occurred while getting hostname: {traceback.format_exc()}"
            )
            raise

    def log_intersight_error(
        self,
        error: Union[requests.exceptions.ConnectionError, requests.exceptions.Timeout, ValueError],
        method: str
    ) -> None:
        """
        Log intersight errors.

        :param error: The error to log.
        :type error: Union[requests.exceptions.ConnectionError, requests.exceptions.Timeout, ValueError]
        :param method: The intersight method that caused the error.
        :type method: str
        :return: None
        """
        if isinstance(error, (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout)):
            self.logger.error(
                f"Connection error occurred while checking intersight endpoint {method}: {error}"
            )
        elif isinstance(error, ValueError):
            self.logger.error(
                f"Value error occurred while checking intersight endpoint {method}: {error}"
            )

    def get_audit_records(
        self,
        audit_kwargs: Dict[str, Any]
    ) -> None:
        """
        Get Audit Records.

        :param audit_kwargs: Dictionary containing arguments for getting audit records.
            - state (str): Modification time in ISO8601 format.
            - event_ingestor (EventIngestor): Object responsible for ingesting audit records.
            - checkpoint_key (str): Key for saving audit records checkpoint in KVStore.
            - session_key (str): Session key for authentication.
            - logger (logging.Logger): Logger object for logging messages.
            - filter_flag (bool): Flag indicating whether to filter records based on checkpoint time.
        :return: None
        """
        state = audit_kwargs["state"]
        event_ingestor = audit_kwargs["event_ingestor"]
        checkpoint_key = audit_kwargs["checkpoint_key"]
        session_key = audit_kwargs["session_key"]
        logger = audit_kwargs["logger"]
        filter_flag = audit_kwargs["filter_flag"]
        try:
            modtime = state
            audit_event_count = 0
            self.logger.info("message=fetch_audit_records | Getting Audit Records.")
            # Get filter condition to filter records based on checkpoint time.
            filter_condition = self.common_helper.get_filter_condition(state, filter_flag=filter_flag)

            self.logger.info(
                f"message=audit_time | Fetching audit records from time: {modtime}"
                " to current time."
            )
            has_more_data = True
            skip = 0
            while has_more_data:
                start_time = time.time()
                params = {
                    "$inlinecount": "allpages",
                    "$orderby": "ModTime asc",
                    "$filter": filter_condition,
                    "$top": constants.PAGE_LIMIT,
                    "$skip": skip,
                }
                # Get audit records from API.
                response = self.get(endpoint=constants.Endpoints.AUDIT_RECORDS, params=params)
                response_len = len(response.get("Results", []))
                # If API returns no new data to ingest.
                if response_len == 0:
                    has_more_data = False
                    self.logger.info(
                        "message=audit_count | No new data to ingest."
                    )
                    break
                # If API returns less than PAGE_LIMIT data to ingest,
                # it means this is the last page, so need to make another
                # API call.
                elif response_len < constants.PAGE_LIMIT:
                    has_more_data = False

                self.logger.info(
                    f"message=records_collected | Collected {response_len} "
                    f"audit records. More data available: {has_more_data}"
                )

                # Ingest audit records using the event ingestor.
                event_count, modtime, status = event_ingestor.ingest_audit_records(
                    response.get("Results", [])
                )
                # Save the latest modification time and status in the
                # checkpoint dictionary.
                checkpoint_value_dict = {"time": modtime, "status": status}
                conf_helper.save_checkpoint(
                    checkpoint_key,
                    session_key,
                    ta_name,
                    checkpoint_value_dict
                )
                self.logger.info(
                    f"message=latest_modtime | Latest modification time saved along with status in "
                    f"Splunk KVStore for audit records: {checkpoint_value_dict}"
                )
                if not event_count:
                    event_count = 0
                audit_event_count += event_count

                elapsed_time = time.time() - start_time
                self.logger.debug(
                    f"message=batch_time | Time taken for batch starting at "
                    f"index {skip}: {elapsed_time:.2f} seconds"
                )
                skip += constants.PAGE_LIMIT

            logger.info(
                "message=events_collected | Total events for Audit Records"
                f" ingested in Splunk are {audit_event_count}."
            )
            return
        except Exception:
            self.logger.error(
                f"message=fetch_data_error | Error occurred while getting audit records: {traceback.format_exc()}"
            )
            # Save the latest modification time and status as False in the
            # checkpoint dictionary in case of an exception.
            checkpoint_value_dict = {"time": modtime, "status": False}
            conf_helper.save_checkpoint(
                checkpoint_key, session_key, ta_name, checkpoint_value_dict
            )
            return

    def fetch_and_ingest_alarms(
        self,
        target_checkpoint: Dict[str, Any],
        event_ingestor: "EventIngestor",
        filter_condition: str = ""
    ) -> Tuple[int, int, Dict[str, Any]]:
        """
        Fetch and ingest alarms.

        :param target_checkpoint: Dictionary containing checkpoint time and status for alarms.
        :param event_ingestor: Object responsible for ingesting alarms.
        :param filter_condition: Additional filter condition for fetching alarms.
        :return: Tuple containing total alarms processed, alarms skipped, and updated checkpoint.
        """
        total_alarm_count, total_alarm_skipped = 0, 0
        checkpoint_dict = target_checkpoint
        try:
            # Extract checkpoint time and status for filtering.
            alarm_checkpoint_value = target_checkpoint.get("time", None)
            filter_flag = target_checkpoint.get("status", None)
            self.logger.info(f"message=fetch_alarms | Getting Alarms with Checkpoint: {target_checkpoint}")
            # Generate filter condition based on checkpoint time and additional filters.
            time_filter_condition = self.common_helper.get_filter_condition(
                alarm_checkpoint_value, filter_flag=filter_flag
            )
            filter = filter_condition.get("$filter", "")
            filter_condition = self.common_helper.apply_additional_filter(
                time_filter_condition, filter
            )
            self.logger.info(
                f"message=alarm_time | Fetching alarm records from time: {alarm_checkpoint_value} to current time."
            )
            has_more_data = True
            skip = 0
            while has_more_data:
                start_time = time.time()
                # Set query parameters for fetching alarm records.
                params = {
                    "$inlinecount": "allpages",
                    "$orderby": "ModTime asc",
                    "$filter": filter_condition,
                    "$top": constants.PAGE_LIMIT,
                    "$skip": skip,
                }
                # Fetch alarm records from the API.
                response = self.get(endpoint=constants.Endpoints.ALARM_RECORDS, params=params)
                response_len = len(response.get("Results", []))
                self.logger.info(f"message=records_collected | Collected {response_len} alarm records.")
                # Determine if there are more records to fetch.
                if response_len == 0:
                    has_more_data = False
                    self.logger.info("message=alarms_count | No new data to ingest.")
                    break
                elif response_len < constants.PAGE_LIMIT:
                    has_more_data = False
                # Process and ingest the fetched alarm data.
                alarm_count, alarm_skipped, checkpoint_dict = self._process_alarms_data(
                    [True, response.get("Results", [])], target_checkpoint, event_ingestor
                )
                total_alarm_count += alarm_count
                total_alarm_skipped += alarm_skipped
                # Log the time taken for the current batch.
                elapsed_time = time.time() - start_time
                self.logger.info(
                    f"message=batch_time | Time taken for batch starting at index {skip}: {elapsed_time:.2f} seconds"
                )
                skip += constants.PAGE_LIMIT
            return total_alarm_count, total_alarm_skipped, checkpoint_dict
        except Exception:
            # Log any exceptions that occur during fetching or ingestion.
            self.logger.error(
                f"message=fetch_data_error | Error occurred while getting alarms: {traceback.format_exc()}"
            )
            return total_alarm_count, total_alarm_skipped, checkpoint_dict

    def _process_alarms_data(
        self, alarms_data: List[Union[bool, List[Dict[str, Any]]]],
        target_checkpoint: Dict[str, Any],
        event_ingestor: "EventIngestor"
    ) -> Tuple[int, int, Dict[str, Any]]:
        """Process fetched alarms and update checkpoint.

        Args:
            alarms_data (List[Union[bool, List[Dict[str, Any]]]]): A list
            containing a boolean indicating the ingestion status and a list of alarm records.
            target_checkpoint (Dict[str, Any]): The target specific checkpoint dictionary.
            event_ingestor (EventIngestor): The event ingestor object for ingesting data into Splunk.

        Returns:
            Tuple[int, int, Dict[str, Any]]: A tuple containing the count of alarms ingested,
            alarms skipped, and the updated checkpoint dictionary.
        """
        checkpoint_dict = target_checkpoint
        alarm_count, alarm_skipped = 0, 0

        if alarms_data and alarms_data[0]:
            if len(alarms_data[1]) > 0:
                alarm_count, alarm_skipped, modtime, status = event_ingestor.ingest_alarms(alarms_data[1])
                if status:
                    checkpoint_dict = {"time": modtime, "status": status}
                else:
                    checkpoint_dict["status"] = status
            else:
                self.logger.warning(
                    "message=modtime | No records found in the current batch."
                )
                return alarm_count, alarm_skipped, checkpoint_dict
        else:
            checkpoint_dict["status"] = alarms_data[0]

        return alarm_count, alarm_skipped, checkpoint_dict

    def fetch_and_ingest_inventory_data(
        self,
        kwargs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Fetch and ingest inventory data.

        :param kwargs: A dictionary containing the following keys:
            - inventory_checkpoint_dict (dict): The inventory checkpoint dictionary.
            - inventory (str): The inventory type.
            - config (dict): The inventory configuration.
            - event_ingestor (EventIngestor): The event ingestor object for ingesting data into Splunk.
            - add_modtime_filter (bool): Flag indicating whether to apply the modification time filter or not.
        :return: The updated inventory checkpoint dictionary.
        """
        inventory_checkpoint = kwargs["inventory_checkpoint_dict"]
        inventory = kwargs["inventory"]
        config = kwargs["config"]
        event_ingestor = kwargs["event_ingestor"]
        add_modtime_filter = kwargs.get("add_modtime_filter", True)
        try:
            self.logger.info(
                f"message=fetch_inventory | Getting Inventory data for {inventory}."
            )
            params = config.get("params", {})
            filter = params.get("$filter")
            if add_modtime_filter is False:
                filter_condition = filter
            else:
                base_filter_condition = self.common_helper.get_filter_condition(
                    inventory_checkpoint.get("time", None), filter_flag=inventory_checkpoint.get("status", None)
                )
                filter_condition = self.common_helper.apply_additional_filter(
                    base_filter_condition, filter
                )

            self.logger.info(
                f"message=inventory_time | Fetching {inventory} records with filter: {filter_condition}"
            )
            has_more_data = True
            skip = 0
            merged_response = []
            while has_more_data:
                start_time = time.time()
                params.update({
                    "$inlinecount": "allpages",
                    "$orderby": "ModTime asc",
                    "$filter": filter_condition,
                    "$top": constants.PAGE_LIMIT,
                    "$skip": skip,
                })

                try:
                    response = self.get(endpoint=inventory, params=params)
                    response_results = response.get("Results", [])
                    response_len = len(response_results)
                    self.logger.info(
                        f"message=records_collected | Collected {response_len} inventory records from {inventory}."
                    )
                    # If API returns no new data to ingest.
                    if response_len == 0:
                        has_more_data = False
                        self.logger.info(f"message=no_records_found | No records found for {inventory}.")
                        return merged_response

                    # If API returns less than PAGE_LIMIT data to ingest,
                    # it means this is the last page, so need to make another
                    # API call.
                    if response_len < constants.PAGE_LIMIT:
                        has_more_data = False  # Last page detected

                    if add_modtime_filter:
                        response_results, filter_status = self._filter_inventory_data(inventory, response_results)

                        if not response_results:
                            self.logger.warning(f"message=no_records_found | No records found for {inventory}.")
                            inventory_checkpoint["status"] = filter_status
                        else:
                            modtime, status = self.ingest_data(event_ingestor, response_results, config)

                            if status:
                                inventory_checkpoint = {"time": modtime, "status": status}
                            else:
                                inventory_checkpoint["status"] = status

                    else:
                        merged_response.extend(response_results)
                        if not has_more_data:
                            return merged_response

                    elapsed_time = time.time() - start_time
                    self.logger.info(
                        f"message=batch_time | Time taken for batch at index {skip}: {elapsed_time:.2f} seconds"
                    )

                    skip += constants.PAGE_LIMIT

                except Exception as e:
                    self.logger.error(f"message=fetch_data_error | Error occurred while fetching inventory: {str(e)}")
                    self.logger.error(traceback.format_exc())
                    break

        except Exception as e:
            self.logger.error(f"message=fetch_data_error | Critical error in fetch_and_ingest_inventory_data: {str(e)}")
            self.logger.error(traceback.format_exc())

        return inventory_checkpoint

    def _filter_inventory_data(
        self, inventory: str,
        response_results: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], bool]:
        """Filter inventory data based on endpoint-specific conditions.

        Args:
            inventory (str): The API endpoint being processed.
            response_results (List[Dict[str, Any]]): The retrieved inventory data.

        Returns:
            Tuple[List[Dict[str, Any]], bool]: Filtered inventory data and a boolean indicating whether the filtering
            was successful.
        """
        try:
            data = response_results
            if inventory == constants.Endpoints.ADVISORIES:
                self.logger.info(
                    "message=advisory_instances | Filtering advisory instances based on PlatformType, "
                    "ManagementMode, and License Tier."
                )
                filtered_advisory_instances = [
                    advisory for advisory in response_results if self._is_valid_advisory(advisory)
                ]
                self.logger.info(
                    f"message=advisory_instances | Found {len(response_results)} relevant advisory instances."
                )
                data = filtered_advisory_instances
            elif inventory == constants.Endpoints.SEARCH_ITEMS:
                data = []
                for mo in response_results:
                    if mo["ClassId"] == "compute.PhysicalSummary" and \
                            not self.common_helper.check_license_tier(mo):
                        continue
                    data.append(mo)
            elif inventory == constants.Endpoints.HCL_STATUSES:
                data = self.common_helper.license_filter(
                    response_results,
                    parent_key_identifier="ManagedObject"
                )
            return data, True

        except Exception as e:
            self.logger.error(f"message=filter_inventory_error | Error while filtering inventory data: {str(e)}")
            self.logger.debug(traceback.format_exc())
            return [], False

    def ingest_data(
        self, event_ingestor: "EventIngestor", data: List[Dict[str, Any]], config: Dict[str, Any]
    ) -> Tuple[Optional[datetime], bool]:
        """Ingest the collected data into Splunk using the specified ingestion function.

        Args:
            event_ingestor: The event ingestor for ingesting data.
            data: The data to be ingested.
            config: The configuration for the ingestion process.

        Returns:
            Tuple[datetime, bool]: modtime and status
        """
        try:
            ingest_method = getattr(event_ingestor, config["ingest_func"])
            self.logger.debug(f"message=inventory_data_ingestion | Ingesting data for {config['log_name']}")

            event_count, modtime = ingest_method(data)
            if modtime is None:
                self.logger.warning("message=modtime | No records found in the current batch.")
                return None, True

            self.logger.info(
                f"message=events_collected | Total events for {config['log_name']} ingested in Splunk: {event_count}"
            )
            return modtime, True

        except Exception as e:
            self.logger.error(
                f"message=ingestion_error | Error in ingesting data for {config['log_name']}. Error: {str(e)}"
            )
            self.logger.error(traceback.format_exc())
            return None, False

    def _is_valid_advisory(self, advisory: Dict[str, Any]) -> bool:
        """Check if advisory is for supported PlatformType and ManagementMode.

        Args:
            advisory (Dict[str, Any]): Advisory to check.

        Returns:
            bool: True if advisory is supported, False otherwise.
        """
        affected_object = advisory.get("AffectedObject", {})

        if affected_object is None:
            return False

        management_mode = affected_object.get("ManagementMode")
        object_type = affected_object.get("ObjectType")

        # If any managed object is not in the list of supported types, return False.
        if management_mode not in constants.Endpoints.SUPPORTED_MODES:
            return False

        if (
            object_type in constants.Endpoints.SUPPORTED_SERVER_OBJECT_TYPES
            and not self.common_helper.check_license_tier(affected_object)
        ):
            return False

        return True

    def get_client_id_details(self, client_id: str) -> Dict[str, Any]:
        """Get Client Id details.

        Args:
            client_id: Client Id to fetch details for.

        Returns:
            Dict[str, Any]: Client Id details.
        """
        try:
            # Fetch Client Id metadata.
            client_id_details = self.get(
                endpoint=constants.Endpoints.CLIENT_ID_METADATA_ENDPOINT,
                params={"$filter": f"ClientId eq '{client_id}'"},
                retry=True,
            )
            if not client_id_details.get("Results", []):
                self.logger.error(
                    f"message=client_id_expiration_timestamp | Client Id {client_id} not found."
                )
                raise Exception(f"Metadata of Client Id {client_id} not found.")
            return client_id_details["Results"][0]
        except Exception:
            self.logger.error(
                "message=client_id_expiration_timestamp | Error occurred while fetch Client Id expiration "
                f"timestamp: {traceback.format_exc()}"
            )
            raise

    def paginate_data(
        self, endpoint: str, base_params: dict, key: str = None,
        id_chunk: list = None
    ) -> list:
        """
        Paginate through data fetched from an API with fallback logic.

        If collecting data for a chunk of IDs fails with server errors (502, 503, 504),
        the method will automatically fallback to processing IDs one at a time.

        Args:
            endpoint (str): API endpoint.
            base_params (dict): Base request parameters.
            key (str): The key/type of data being collected (e.g., 'domains', 'fan', etc.).
            id_chunk (list): List of IDs to filter by.

        Returns:
            list: Consolidated list of fetched results.
        """
        # If no id_chunk provided or only 1 ID, process normally
        if not id_chunk or len(id_chunk) == 1:
            return self._paginate_with_params(endpoint, base_params, key, id_chunk)

        # Try processing with the full chunk first
        self.logger.info(
            "message=metric_collection | Attempting to collect data "
            f"for {len(id_chunk)} IDs in a single chunk for endpoint: {endpoint}"
        )

        try:
            all_data = self._paginate_with_params(endpoint, base_params, key, id_chunk)
            self.logger.info(
                f"message=metric_collection | Successfully collected {len(all_data)} records for {len(id_chunk)} IDs"
            )
            return all_data

        except requests.exceptions.HTTPError as e:
            status_code = getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None

            # Check if error is server-side (500, 502, 503, 504, 529) - fallback applicable
            if status_code in [500, 502, 503, 504, 529]:
                self.logger.warning(
                    f"message=metric_collection | Server error {status_code} "
                    f"encountered when collecting {len(id_chunk)} IDs. "
                    f"Initiating fallback to process IDs one at a time. Error: {str(e)}"
                )
                return self._fallback_to_single_id_processing(endpoint, base_params, key, id_chunk)
            else:
                # For other HTTP errors (400, 401, 403, 429, etc.), log and re-raise
                self.logger.error(
                    f"message=metric_collection | HTTP error {status_code} "
                    f"occurred during data collection for endpoint {endpoint}. "
                    f"Fallback not applicable. Error: {str(e)}"
                )
                raise

        except requests.exceptions.RequestException as e:
            # Catch MaxRetryError and other request exceptions (e.g., "too many 504 error responses")
            error_str = str(e).lower()

            # Check if it's related to server errors (504, 502, 503, 500, 529)
            if any(code in error_str for code in ['504', '502', '503', '500', '529']):
                self.logger.warning(
                    "message=metric_collection | Max retries exceeded with "
                    f"server errors when collecting {len(id_chunk)} IDs. "
                    f"Initiating fallback to process IDs one at a time. Error: {str(e)}"
                )
                return self._fallback_to_single_id_processing(endpoint, base_params, key, id_chunk)
            else:
                # For other request exceptions, log and re-raise
                self.logger.error(
                    "message=metric_collection | Request exception occurred "
                    f"during data collection for endpoint {endpoint}. "
                    f"Fallback not applicable. Error: {str(e)}"
                )
                raise

        except Exception as e:
            # For non-HTTP exceptions, log and re-raise
            self.logger.error(
                "message=metric_collection | Unexpected error occurred "
                f"during data collection for endpoint {endpoint}. "
                f"Error: {str(e)}\nTraceback: {traceback.format_exc()}"
            )
            raise

    def _paginate_with_params(
        self, endpoint: str, base_params: dict, key: str, id_chunk: list
    ) -> list:
        """
        Paginate data with given parameters.

        Args:
            endpoint (str): API endpoint.
            base_params (dict): Base request parameters.
            key (str): The key/type of data being collected.
            id_chunk (list): List of IDs to filter by.
            batch_size (int): Number of records to fetch per request.

        Returns:
            list: Consolidated list of fetched results.
        """
        all_data = []
        skip = 0
        batch_size = constants.PAGE_LIMIT

        # Create a deep copy of base parameters to avoid modifying the original
        params = deepcopy(base_params)

        # Initialize id_chunk_string for filtering
        id_chunk_string = ""
        if id_chunk:
            # Concatenate IDs into a formatted string
            for moid in id_chunk:
                id_chunk_string += f"'{moid}', "
            id_chunk_string = f"({id_chunk_string.strip(', ')})"

            # Update parameters based on key and ID chunk
            if key != "fan" and id_chunk:
                params = self.common_helper.update_filter(params, id_chunk_string)
            elif key == "fan" and id_chunk:
                params = self.common_helper.update_fan_filter(params, id_chunk_string)

        self.logger.info(
            f"message=metric_collection | Processing chunk for endpoint: {endpoint}, key: {key}, "
            f"id_count: {len(id_chunk) if id_chunk else 0}"
        )

        # Paginate through all results using common get() method with reduced retries
        while True:
            params["$skip"] = skip
            self.logger.debug(
                f"message=metric_collection | Paginating: {endpoint}, skip: {skip}, batch_size: {batch_size}"
            )

            # Call common get() method with retries=1 for faster fallback
            response = self.get(endpoint=endpoint, params=params, retry=False)

            if not response or response.get("Count", 0) == 0:
                break
            all_data.extend(response.get("Results", []))
            if len(all_data) >= response.get("Count", 0):
                break
            self.logger.debug(
                f"message=metric_collection | Collected {len(all_data)} records so far"
            )
            skip += batch_size

        return all_data

    def _fallback_to_single_id_processing(
        self, endpoint: str, base_params: dict, key: str, id_chunk: list
    ) -> list:
        """
        Fallback method to process IDs one at a time when bulk processing fails.

        Args:
            endpoint (str): API endpoint.
            base_params (dict): Base request parameters.
            key (str): The key/type of data being collected.
            id_chunk (list): List of IDs to process individually.
            batch_size (int): Number of records to fetch per request.

        Returns:
            list: Consolidated list of fetched results from all successful individual ID processing.
        """
        self.logger.info(
            "message=metric_collection | Starting fallback: "
            f"Processing {len(id_chunk)} IDs individually for endpoint: {endpoint}"
        )

        all_data = []
        successful_ids = 0
        failed_ids = 0
        failed_id_list = []

        for idx, single_id in enumerate(id_chunk, 1):
            try:
                self.logger.info(
                    "message=metric_collection | Processing individual ID "
                    f"{idx}/{len(id_chunk)}: {single_id}"
                )

                # Process single ID
                single_id_data = self._paginate_with_params(
                    endpoint, base_params, key, [single_id]
                )

                all_data.extend(single_id_data)
                successful_ids += 1

                self.logger.info(
                    "message=metric_collection | Successfully collected "
                    f"{len(single_id_data)} records for ID: {single_id}"
                )

            except requests.exceptions.HTTPError as e:
                status_code = getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None
                failed_ids += 1
                failed_id_list.append(single_id)

                self.logger.error(
                    f"message=metric_collection | Failed to collect data for ID: {single_id}. "
                    f"HTTP Status: {status_code}, Error: {str(e)}. "
                    f"Continuing with next ID..."
                )

            except Exception as e:
                failed_ids += 1
                failed_id_list.append(single_id)

                self.logger.error(
                    f"message=metric_collection | Unexpected error while processing ID: {single_id}. "
                    f"Error: {str(e)}. Continuing with next ID..."
                )

        # Log final summary of fallback processing
        self.logger.info(
            f"message=metric_collection | Fallback processing completed for endpoint: {endpoint}. "
            f"Total IDs: {len(id_chunk)}, Successful: {successful_ids}, Failed: {failed_ids}, "
            f"Total records collected: {len(all_data)}"
        )

        if failed_ids > 0:
            self.logger.warning(
                f"message=metric_collection | Failed IDs ({failed_ids}): {failed_id_list}"
            )

        return all_data
