# encoding = utf-8
import json
import re
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone

import common.proxy as proxy
import import_declare_test  # noqa: F401
import requests
from common.consts import (
    API_RETRY_COUNT,
    APP_NAME,
    ND_CHKPT_COLLECTION,
    NUM_NDI_THREAD,
    ND_startTs,
)
from solnlib.modular_input import checkpointer
from splunklib import modularinput as smi


class NexusDashboardParameters(object):
    """Class responsible for all communication with the Nexus Dashboard."""

    def __init__(
        self,
        nd_api_call_count,
        ew,
        nd_account,
        nd_host,
        timeout,
        verify_ssl,
        ORIGINAL_HOSTS,
        TRIED_HOSTS,
        input_info,
        ac_creds,
        index,
        input_name,
        session_key,
        logger,
        acc_name,
    ):
        """
        Initialize the NexusDashboardParameters class.

        Parameters:
        nd_api_call_count (int): count of events per api call
        ew (EventWriter): event writer object
        nd_account (str): Nexus Dashboard account name
        nd_host (str): Nexus Dashboard host name/IP address
        timeout (int): connection timeout in seconds
        verify_ssl (bool): whether to verify SSL cert or not
        ORIGINAL_HOSTS (list): list of original hosts
        TRIED_HOSTS (list): list of tried hosts
        input_info (dict): info about the input
        ac_creds (dict): credentials for the account
        index (str): index name
        input_name (str): input name
        session_key (str): session key
        """
        self.nd_api_call_count = nd_api_call_count
        self.nd_account = nd_account
        self.nd_host = nd_host
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.ew = ew
        self.token = None
        self.data_count = 0
        self.data_count_API = 0
        self.ORIGINAL_HOSTS = ORIGINAL_HOSTS
        self.TRIED_HOSTS = TRIED_HOSTS
        self.input_info = input_info
        self.ac_creds = ac_creds
        self.index = index
        self.input_name = input_name
        self.session_key = session_key
        self.logger = logger
        self.acc_name = acc_name

    def get_url(self, endpoint=None, recomd_type=None):
        """Return the entire URL for the required endpoint."""
        ENDPOINT_URLS = {
            "insightsGroup": "sedgeapi/v1/cisco-nir/api/api/telemetry/v2/config/insightsGroup",
            "anomalies": "sedgeapi/v1/cisco-nir/api/api/telemetry/anomalies/details.json",
            "advisories": "sedgeapi/v1/cisco-nir/api/api/telemetry/advisories/details.json",
            "flows": "sedgeapi/v1/cisco-nir/api/api/v1/flows",
            "endpoints": "sedgeapi/v1/cisco-nir/api/api/v1/endpoints",
            "protocols": "sedgeapi/v1/cisco-nir/api/api/v1/protocols/details",
            "congestion": "sedgeapi/v1/cisco-nir/api/api/v1/congestion/trends",
            "recommendations": {
                "advisories": "advisories/recommendations.json",
                "anomalies": "anomalies/recommendations.json",
            },
            "switches": "api/v1/manage/inventory/switches",
            "fabrics": "api/v1/manage/fabricsSummary",
        }

        if endpoint in ENDPOINT_URLS:
            if (
                isinstance(ENDPOINT_URLS[endpoint], dict)
                and recomd_type in ENDPOINT_URLS[endpoint]
            ):
                return (
                    "sedgeapi/v1/cisco-nir/api/api/telemetry/"
                    + ENDPOINT_URLS[endpoint][recomd_type]
                )
            return ENDPOINT_URLS[endpoint]

        return None

    def convert_nd_input_to_list(self, field_value):
        """Split a field value into a list of unique values."""
        split_list = field_value.split("~")
        final_list = list(set(split_list))
        return final_list

    def get_checkpoint(self, checkpoint_key, session_key, app_name):
        """Get checkpoint."""
        value = {}
        try:
            checkpoint_collection = checkpointer.KVStoreCheckpointer(
                ND_CHKPT_COLLECTION, session_key, app_name
            )
            value = checkpoint_collection.get(checkpoint_key)
            self.logger.debug(
                f"message=get_checkpoint | Received checkpoint of value: {value} "
                f"for key: {checkpoint_key}"
            )
            return value
        except Exception:
            self.logger.error(
                f"message=checkpoint_error | Error occured while Getting Checkpoint.\n{traceback.format_exc()}"
            )
            return None

    def save_checkpoint(self, checkpoint_key, session_key, app_name, value):
        """Get checkpoint."""
        try:
            checkpoint_collection = checkpointer.KVStoreCheckpointer(
                ND_CHKPT_COLLECTION, session_key, app_name
            )
            checkpoint_collection.update(checkpoint_key, value)
            self.logger.debug(
                f"message=save_checkpoint | Saved checkpoint of value: {value} "
                f"for key: {checkpoint_key}"
            )
        except Exception:
            self.logger.error(
                f"message=checkpoint_error |"
                f" Error occured while Updating Checkpoint.\n{traceback.format_exc()}"
            )
            return

    def nd_get_interface_all(self, current_time):
        """
        Retrieve and process interface data for all switches in a specified site.

        This function queries the Cisco NIR API to get a list of switches for a given site (`nd_site_name`),
        then iterates over each switch and fetches its interface data using the `nd_get_interface()` method.

        :param nd_site_name: The name of the site to retrieve switch and interface data from.
        :type nd_site_name: str
        :param current_time: The current time used for logging and interface data processing.
        :type current_time: datetime

        :returns: None
        """
        try:
            nd_site_name = self.input_info.get("nd_protocol_site_name", None)

            start_date = self.input_info.get("nd_start_date")
            if start_date is None:
                start_date = "1h"
            start_date = "now-" + start_date
            nd_filter = self.input_info.get("nd_additional_filter")

            self.nd_get_interface(
                siteName=nd_site_name,
                start_date=start_date,
                end_date="now",
                filter=nd_filter,
                current_time=current_time,
            )
        except Exception as e:
            self.logger.error(
                f"Nexus Dashboard Error: An Error Occured while fetching data for protocols data."
                f" Host: {self.nd_host}. Error: {str(e)}"
            )

    def process_flows_entries_event(
        self,
        entries_events,
        alert_type,
        siteName,
        index,
        source_type,
        key,
        current_time,
    ):
        """Process each event in entries_events and write to event writer."""
        for events in entries_events:
            payload = events
            payload["nd_host"] = self.nd_host
            payload["fabricName"] = siteName

            event = smi.Event(
                data=json.dumps(payload, ensure_ascii=False),
                index=index,
                sourcetype=source_type,
                source=alert_type,
            )
            self.ew.write_event(event)

        self.data_count += len(entries_events)

    def process_protocols_entries_event(
        self,
        entries_events,
        alert_type,
        siteName,
        index,
        source_type,
        key,
        current_time,
    ):
        """Process each event in entries_events and write to event writer."""
        for events in entries_events:
            events["nd_host"] = self.nd_host
            entries_dict = events.get("entries")[0] if events.get("entries") else {}
            for field, value in entries_dict.items():
                events[field] = value

            event = smi.Event(
                data=json.dumps(events, ensure_ascii=False),
                index=index,
                sourcetype=source_type,
                source=alert_type,
            )
            self.ew.write_event(event)

        endTs = current_time
        self.save_checkpoint(key, self.session_key, APP_NAME, endTs)
        self.logger.debug(f"chkpt_save_time {key}: {endTs}")
        self.logger.info(
            f"Nexus Dashboard Info: Value saved in checkpoint: {endTs} for "
            f"{alert_type} endpoint for Fabric: {siteName} and Host: {self.nd_host}."
        )

        self.data_count += len(entries_events)

    def process_endpoints_entries_event(
        self,
        entries_events,
        alert_type,
        siteName,
        index,
        source_type,
        key,
        current_time,
    ):
        """Process each event in entries_events and write to event writer."""
        for events in entries_events:
            events["nd_host"] = self.nd_host

            event = smi.Event(
                data=json.dumps(events, ensure_ascii=False),
                index=index,
                sourcetype=source_type,
                source=alert_type,
            )
            self.ew.write_event(event)

        endTs = current_time
        self.save_checkpoint(key, self.session_key, APP_NAME, endTs)
        self.logger.debug(f"chkpt_save_time {key}: {endTs}")
        self.logger.info(
            f"Nexus Dashboard Info: Value saved in checkpoint: {endTs} for "
            f" {alert_type} endpoint for "
            f"fabric: {siteName} and Host: {self.nd_host}."
        )
        self.data_count += len(entries_events)

    def pagination(
        self,
        params,
        endpoint_url,
        index,
        source_type,
        alert_type,
        key,
        siteName,
        current_time,
    ):
        """
        Handle paginated API responses and process data based on the alert type.

        This function queries an API endpoint using pagination, retrieves data, and
        delegates the processing to specific functions based on `alert_type`. The process
        continues until all data is fetched.

        :param params: Parameters for the API request, including pagination details.
        :type params: dict
        :param endpoint_url: The URL of the API endpoint to fetch data from.
        :type endpoint_url: str
        :param index: The index to store event data.
        :type index: str
        :param source_type: The source type of the event data.
        :type source_type: str
        :param alert_type: Specifies the type of data being processed
                        (e.g., "protocols", "endpoints", "flows").
        :type alert_type: str
        :param key: The checkpoint key used for saving progress.
        :type key: str
        :param siteName: The name of the site/fabric being processed.
        :type siteName: str
        :param current_time: The current timestamp used for logging and checkpoints.
        :type current_time: str

        :raises Exception: Logs any errors encountered during data retrieval and processing.

        :return: None
        """
        try:
            offset = 0
            total_Items_Count = 0
            while True:
                params["offset"] = offset
                response = self.get(endpoint_url, params=params)
                if response:
                    entries_events = response.get("entries", [])
                    if len(entries_events) > 0:
                        total_Items_Count = response.get("totalResultsCount", 0)
                        if alert_type == "protocols":
                            self.process_protocols_entries_event(
                                entries_events,
                                alert_type,
                                siteName,
                                index,
                                source_type,
                                key,
                                current_time,
                            )
                        elif alert_type == "endpoints":
                            self.process_endpoints_entries_event(
                                entries_events,
                                alert_type,
                                siteName,
                                index,
                                source_type,
                                key,
                                current_time,
                            )
                        elif alert_type == "flows":
                            self.process_flows_entries_event(
                                entries_events,
                                alert_type,
                                siteName,
                                index,
                                source_type,
                                key,
                                current_time,
                            )
                    if len(entries_events) < params["count"]:
                        break
                    offset += params["count"]
                else:
                    break
            if total_Items_Count:
                self.data_count_API += total_Items_Count
        except Exception as e:
            if total_Items_Count:
                self.data_count_API += total_Items_Count
            self.logger.error(
                f"Nexus Dashboard Error: An Error Occured while fetching data for {alert_type} data."
                f" URL: {endpoint_url} and Host: {self.nd_host}. Error: {str(e)}"
            )

    def nd_get_interface(self, siteName, start_date, end_date, filter, current_time):
        """
        Retrieve and process interface statistics data for a specified node within a site.

        This function queries the Cisco NIR API to retrieve interface-level statistics
        for a given `nodeName` in a specific `siteName` over a defined time period.

        :param siteName: Name of the site where the node resides.
        :type siteName: str
        :param nodeName: Name of the node to retrieve interface data for.
        :type nodeName: str
        :param start_date: Start date or time range for data collection.
        :type start_date: str
        :param end_date: End date for data collection.
        :type end_date: str
        :param filter: Optional filter to apply to interface data.
        :type filter: str or None
        :param current_time: Current time used for logging and checkpointing.
        :type current_time: datetime

        :returns: None
        """
        alert_type = self.input_info.get("nd_alert_type")

        endpoint_url = self.get_url(alert_type)
        current_time = current_time.isoformat() + "Z"
        index = self.index
        source_type = "cisco:dc:nd:" + alert_type
        start_date = self.convertTimestamp(start_date)
        end_date = current_time

        key = f"{self.acc_name}_{self.input_name}_{siteName}_{alert_type}"
        chkpt_start_time = self.get_checkpoint(key, self.session_key, APP_NAME)
        self.logger.debug(f"chkpt_start_time {key}: {chkpt_start_time}")

        if chkpt_start_time:
            startTs = datetime.strptime(
                chkpt_start_time, "%Y-%m-%dT%H:%M:%S.%fZ"
            ) + timedelta(seconds=0.001)
            startTs = startTs.isoformat() + "Z"
            self.logger.info(
                f"Nexus Dashboard Info: Found an existing checkpoint with value: {startTs} for "
                f" {alert_type} endpoint for fabric: {siteName} and "
                f"Host: {self.nd_host}."
            )
        else:
            startTs = start_date
            self.logger.info(
                f"Nexus Dashboard Info: No existing checkpoint found, starting data collection"
                f" with value: {start_date} for "
                f" {alert_type} endpoint for fabric: {siteName} and Host: {self.nd_host}"
            )
        self.logger.info(
            f"Nexus Dashboard Info: Value of startTs: {startTs} endTs: {end_date} for {alert_type}"
            f" endpoint for fabric: {siteName} and Host: {self.nd_host}."
        )

        params = {
            "statName": "interface",
            "startDate": startTs,
            "endDate": end_date,
            "count": 1000,
            "siteName": siteName,
        }

        if filter:
            params["filter"] = filter

        self.pagination(
            params=params,
            endpoint_url=endpoint_url,
            index=index,
            source_type=source_type,
            alert_type=alert_type,
            key=key,
            siteName=siteName,
            current_time=current_time,
        )

    def get(self, endpoint_url, params=None):
        """
        Hit particular endpoint and fetch data.

        :param endpoint_url: Endpoint URL for which we want to fetch data.
        :type endpoint_url: string
        :param params: The parameter to be set for http/https request.
        :type params: dict
        """
        remaining_hosts = list(set(self.ORIGINAL_HOSTS) - set(self.TRIED_HOSTS))

        if not endpoint_url:
            self.logger.error("Nexus Dashboard Error: Endpoint URL is None.")

        url = f"https://{self.nd_host}/{endpoint_url}"
        self.logger.debug(f"URL:{url} params: {params}")

        proxy_settings = proxy.get_proxies(self.ac_creds)

        response = requests.request(
            url=url,
            method="GET",
            headers=self.form_headers(),
            params=params,
            verify=self.verify_ssl,
            timeout=self.timeout,
            proxies=proxy_settings,
        )

        if response.status_code in {200, 201}:
            try:
                return response.json()
            except Exception:
                self.logger.error(f"Nexus Dashboard Error: err: {response.text}")
                return
        elif response.status_code == 401:
            self.logger.debug(
                "Nexus Dashboard Error: Performing Nexus Dashboard relogin."
            )
            try:
                self.login()
                return self.get(endpoint_url, params)
            except Exception as err:
                self.logger.error(
                    f"Nexus Dashboard Error: Could not re-login to Nexus Dashboard. Error: {str(err)}"
                )
                return

        elif response.status_code == 429 or 500 <= response.status_code < 600:
            self.logger.warning(
                f"Nexus Dashboard Warning: Received error for URL: {url} params: {params}. "
                f"Response Code: {response.status_code}. Response: {response.text}"
            )
            retries = API_RETRY_COUNT
            while retries > 0:
                if response.status_code == 429:
                    time.sleep(15)

                self.logger.debug(f"Retrying: URL:{url} params: {params}")
                response = requests.request(
                    url=url,
                    method="GET",
                    headers=self.form_headers(),
                    params=params,
                    verify=self.verify_ssl,
                    timeout=self.timeout,
                    proxies=proxy_settings,
                )

                if response.status_code in {200, 201}:
                    return response.json()
                elif response.status_code == 401:
                    self.logger.debug(
                        "Nexus Dashboard Error: Performing Nexus Dashboard relogin."
                    )
                    try:
                        self.login()
                    except Exception as err:
                        self.logger.error(
                            f"Nexus Dashboard Error: Could not re-login to Nexus Dashboard. Error: {str(err)}"
                        )
                        return
                self.logger.debug(
                    f"Retrying was not successful for URL:{url} params: {params}"
                )
                retries -= 1
            if retries == 0:
                if len(remaining_hosts) == 0:
                    self.logger.error(
                        f"Nexus Dashboard Error: URL:{url} params: {params} Response Code: {response.status_code}. "
                        f"Response: {response.text}"
                    )
                    if len(self.ORIGINAL_HOSTS) > 1:
                        self.logger.error(
                            f"Nexus Dashboard Insights Error: None of the cluster host is reachable: "
                            f"{', '.join(self.ORIGINAL_HOSTS)}."
                        )
                    response.raise_for_status()
                else:
                    self.logger.error(
                        f"Nexus Dashboard Error: URL:{url} params: {params} Response Code: {response.status_code}. "
                        f"Response: {response.text}"
                    )
                    self.nd_host = remaining_hosts[0]
                    self.logger.warning(
                        f"Nexus Dashboard Warning: Performing login in Host: {self.nd_host} to fetch further data."
                    )
                    self.login()
                    return self.get(endpoint_url, params)
        else:
            if len(remaining_hosts) == 0:
                self.logger.error(
                    f"Nexus Dashboard Error: URL:{url} params: {params} Response Code: {response.status_code}. "
                    f"Response Reason: {response.reason}"
                )
                if len(self.ORIGINAL_HOSTS) > 1:
                    self.logger.error(
                        "Nexus Dashboard Error: None of the cluster host is reachable: "
                        f"{', '.join(self.ORIGINAL_HOSTS)}."
                    )
                response.raise_for_status()
            else:
                self.logger.error(
                    f"Nexus Dashboard Error: URL:{url} params: {params} Response Code: {response.status_code}. "
                    f"Response Reason: {response.reason}"
                )
                self.nd_host = remaining_hosts[0]
                self.logger.warning(
                    f"Nexus Dashboard Warning: Performing login in Host: {self.nd_host} to fetch further data."
                )
                self.login()
                return self.get(endpoint_url, params)

    def login(self):
        """Perform login Nexus Dashboard instance and set token."""
        self.TRIED_HOSTS.append(self.nd_host)

        self.logger.info(
            f"Nexus Dashboard Info: Hit login endpoint for Host: {self.nd_host}"
        )

        msg = f"Nexus Dashboard Error: An Error Occured while logging in Host: {self.nd_host}"
        login_domain = (
            "local"
            if self.ac_creds.get("nd_authentication_type")
            == "local_user_authentication"
            else self.ac_creds.get("nd_login_domain")
        )

        credentials = {
            "userName": self.ac_creds.get("nd_username"),
            "userPasswd": self.ac_creds.get("nd_password"),
            "domain": login_domain,
        }
        credentials = json.dumps(credentials)
        url = f"https://{self.nd_host}/login"
        try:
            response = requests.post(
                url=url,
                data=credentials,
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            if response.status_code in {200, 201}:
                self.logger.debug(
                    f"Login Successful for Nexus Dashboard Host: {self.nd_host}"
                )
                self.token = response.json()["token"]
                return self.token

            elif response.status_code == 429 or 500 <= response.status_code < 600:
                self.logger.warning(
                    f"Nexus Dashboard Warning: Received error for Host: {self.nd_host}."
                    f" Response Code: {response.status_code}. Response: {response.text}"
                )
                retries = API_RETRY_COUNT
                while retries > 0:
                    if response.status_code == 429:
                        time.sleep(15)

                    self.logger.debug("Retrying login")
                    response = requests.post(
                        url=url,
                        data=credentials,
                        verify=self.verify_ssl,
                        timeout=self.timeout,
                    )
                    if response.status_code in {200, 201}:
                        self.logger.debug("Login retry was successful.")
                        self.token = response.json()["token"]
                        return self.token
                    retries -= 1
                if retries == 0:
                    self.logger.error(
                        f"{msg}. Response Code: {response.status_code}. Response: {response.text}"
                    )
                    response.raise_for_status()
            else:
                self.logger.error(
                    f"{msg}. Response Code: {response.status_code}. Response: {response.text}"
                )
                response.raise_for_status()
        except requests.exceptions.SSLError:
            self.logger.error(
                f"Nexus Dashboard Error: Please provide valid SSL certificate or "
                f"disable SSL Certificate validation for host: {self.nd_host}."
            )
            return False
        except Exception as e:
            self.logger.error(f"{msg}. Error: {str(e)}")
            return False

    def convertTimestamp(self, input):
        """
        Convert an input string into a properly formatted ISO 8601 timestamp.

        :param input: Input string representing a timestamp, current time, or relative time.
        :type input: str

        :returns: Formatted timestamp in ISO 8601 format or raises an exception if the input is invalid.
        """
        formatted_time = ""
        if re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", input):
            formatted_time = input
        elif input == "now":
            current_time = datetime.now(timezone.utc)
            formatted_time = current_time.isoformat(timespec="milliseconds").replace(
                "+00:00", "Z"
            )
        elif re.match(r"^now-\d+[smhd]$", input):
            current_time = datetime.now(timezone.utc)
            digit = int(input[4:-1])
            unit = input[-1:]
            if unit == "d" or unit == "D":
                modified_time = current_time - timedelta(days=digit)
            elif unit == "h" or unit == "H":
                modified_time = current_time - timedelta(hours=digit)
            elif unit == "m" or unit == "M":
                modified_time = current_time - timedelta(minutes=digit)
            else:
                modified_time = current_time - timedelta(seconds=digit)
            formatted_time = modified_time.isoformat(timespec="milliseconds").replace(
                "+00:00", "Z"
            )
        else:
            raise Exception("INVALID_TIMESTAMP_FORMAT")
        return formatted_time

    def convert2epoch(self, input):
        """
        Convert an ISO 8601 formatted timestamp into epoch time (Unix timestamp) in the "Asia/Seoul" timezone.

        This function takes a timestamp in the format `YYYY-MM-DDTHH:MM:SS.sssZ`, converts it to UTC time,
        and then adjusts it to the "Asia/Seoul" timezone before converting it to epoch time.

        :param input: A string representing the date and time in ISO 8601 format.
        :type input: str

        :returns: The equivalent epoch time (Unix timestamp) in seconds for the given input.
        """
        utc_time = datetime.strptime(input, "%Y-%m-%dT%H:%M:%S.%fZ")
        utc_time = utc_time.replace(tzinfo=timezone.utc)
        local_time = utc_time.astimezone()  # Get local system timezone
        epoch = local_time.timestamp()
        return epoch

    def form_headers(self):
        """Form token for URL endpoint."""
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        return headers

    def get_fabric_details(self):
        """Fetch the fabric endpoint data and form the list of fabrics in given NI."""
        endpoint_url = self.get_url("insightsGroup")
        insights_group_fabrics_dict = {}
        try:
            insights_group_response = self.get(endpoint_url)
            if insights_group_response:
                insights_group = insights_group_response.get("value", {}).get(
                    "data", []
                )
                for data in insights_group:
                    group_name = data.get("name")
                    if group_name:
                        assurance_entities = data.get("assuranceEntities", [])
                        insights_group_fabrics_dict[group_name] = [
                            entity["name"] for entity in assurance_entities
                        ]
        except Exception as e:
            self.logger.error(
                f"Nexus Dashboard Error: An error occurred while fetching Insights Group data. "
                f"Endpoint URL: {endpoint_url} and Host: {self.nd_host}. Error: {str(e)}"
            )
            return None
        return insights_group_fabrics_dict

    def ingest_data_in_splunk(self, current_time):
        """
        Fetch and ingest endpoints data for a specific fabric name in Splunk.

        This function collects data from a specified fabric name and writes relevant events
        into Splunk by using the defined alert type and endpoint. It checks for previously
        stored checkpoints and resumes data collection from the last checkpoint if available.

        :param current_time: The current time for marking the end of data collection.
        :type current_time: datetime

        :returns: None
        """
        alert_type = self.input_info.get("nd_alert_type")
        endpoint_url = self.get_url(alert_type)

        current_time = current_time.isoformat() + "Z"
        index = self.index
        source_type = "cisco:dc:nd:" + alert_type

        nd_protocol_site_name = self.input_info.get("nd_protocol_site_name")
        nd_start_date = self.input_info.get("nd_start_date")
        if nd_start_date is None:
            nd_start_date = "1h"
        nd_start_date = "now-" + nd_start_date
        nd_filter = self.input_info.get("nd_additional_filter")

        start_time = self.convertTimestamp(nd_start_date)
        end_time = current_time

        params = {}

        key = f"{self.acc_name}_{self.input_name}_{nd_protocol_site_name}_{alert_type}"
        chkpt_start_time = self.get_checkpoint(key, self.session_key, APP_NAME)
        self.logger.debug(f"chkpt_start_time {key}: {chkpt_start_time}")

        if chkpt_start_time:
            startTs = datetime.strptime(
                chkpt_start_time, "%Y-%m-%dT%H:%M:%S.%fZ"
            ) + timedelta(seconds=0.001)
            startTs = startTs.isoformat() + "Z"
            self.logger.info(
                f"Nexus Dashboard Info: Found an existing checkpoint with value: {startTs} for "
                f" {alert_type} endpoint for fabric: {nd_protocol_site_name} and "
                f"Host: {self.nd_host}."
            )
        else:
            startTs = start_time
            self.logger.info(
                f"Nexus Dashboard Info: No existing checkpoint found, starting data collection"
                f" with value: {start_time} for "
                f" {alert_type} endpoint for fabric: {nd_protocol_site_name} and Host: {self.nd_host}"
            )
        self.logger.info(
            f"Nexus Dashboard Info: Value of startTs: {startTs} endTs: {current_time} for {alert_type}"
            f" endpoint for fabric: {nd_protocol_site_name} and Host: {self.nd_host}."
        )

        params = {
            "siteName": nd_protocol_site_name,
            "sort": "-anomalyScore",
            "endDate": end_time,
            "startDate": startTs,
            "count": 10000,
        }
        if nd_filter:
            params["filter"] = nd_filter

        self.pagination(
            params=params,
            endpoint_url=endpoint_url,
            index=index,
            source_type=source_type,
            alert_type=alert_type,
            key=key,
            siteName=nd_protocol_site_name,
            current_time=current_time,
        )

    def ingest_one_event_in_splunk(
        self,
        node_name,
        interface_name,
        scope,
        nd_site_name,
        start_time,
        end_time,
        nd_filter,
        current_time,
        granularity,
    ):
        """
        Ingests data for a single event from a specific node and interface into Splunk.

        This method fetches event data for a specified node and interface, converts the data into
        a format suitable for Splunk, and writes it to the configured Splunk index. It uses the
        provided time range and optional filters to refine the data.

        :param node_name: Name of the node for which data is collected.
        :type node_name: str
        :param interface_name: Name of the interface associated with the event.
        :type interface_name: str
        :param scope: Scope of data collection to define data boundaries.
        :type scope: str
        :param nd_site_name: Name of the site associated with the data.
        :type nd_site_name: str
        :param start_time: Start timestamp for data collection (ISO format).
        :type start_time: str
        :param end_time: End timestamp for data collection (ISO format).
        :type end_time: str
        :param nd_filter: Optional filter to refine data (default: None).
        :type nd_filter: str or None
        :param current_time: The current time to record when the event is ingested.
        :type current_time: datetime

        :returns: None
        """
        try:
            alert_type = self.input_info.get("nd_alert_type")
            endpoint_url = self.get_url(alert_type)
            current_time = current_time.isoformat() + "Z"
            index = self.index
            source_type = "cisco:dc:nd:" + alert_type
            key = f"{self.acc_name}_{self.input_name}_{nd_site_name}_{alert_type}"
            params = {
                "siteName": nd_site_name,
                "nodeName": node_name,
                "interfaceName": interface_name,
                "endDate": end_time,
                "startDate": start_time,
                "granularity": granularity,
            }

            if nd_filter:
                params["filter"] = nd_filter
            if scope:
                params["scope"] = scope

            response = self.get(endpoint_url, params=params)

            if response:
                entries_events = response.get("entries", [])
                if len(entries_events) > 0:
                    total_Items_Count = response.get("totalResultsCount", 0)
                    for events in entries_events:
                        for item in events.get("entries"):
                            for stat in item.get("stats"):
                                payload = {
                                    "_time": self.convert2epoch(stat["ts"]),
                                    "nd_host": self.nd_host,
                                    "fabricName": nd_site_name,
                                    "switchName": node_name,
                                    "interfaceName": interface_name,
                                    "counterName": item["counterName"],
                                    "counterNameLabel": item["counterNameLabel"],
                                    "ts": stat["ts"],
                                    "event_value": str(stat["value"]),
                                }
                                if scope != "queue":
                                    payload["operStatus"] = events["operStatus"]

                                event = smi.Event(
                                    data=json.dumps(payload, ensure_ascii=False),
                                    index=index,
                                    sourcetype=source_type,
                                    source=alert_type,
                                )
                                self.ew.write_event(event)
                                self.data_count += 1
                    endTs = current_time
                    self.save_checkpoint(key, self.session_key, APP_NAME, endTs)
                    self.logger.debug(f"chkpt_save_time {key}: {endTs}")
                    self.logger.info(
                        f"Nexus Dashboard Info: Value saved in checkpoint: {endTs} for "
                        f" {alert_type} endpoint for "
                        f"fabric: {nd_site_name} and Host: {self.nd_host}."
                    )
                else:
                    self.logger.info(
                        "Nexus Dashboard Info: Value saved in checkpoint: "
                        f"{self.get_checkpoint(key, self.session_key, APP_NAME)} for "
                        f" {alert_type} endpoint for "
                        f"fabric: {nd_site_name} and Host: {self.nd_host}."
                    )
                if total_Items_Count:
                    self.data_count_API += total_Items_Count
        except Exception as e:
            if total_Items_Count:
                self.data_count_API += total_Items_Count
            self.logger.error(
                f"Nexus Dashboard Error: An Error Occured while fetching data for {alert_type} data."
                f" URL: {endpoint_url} and Host: {self.nd_host}. Error: {str(e)}"
            )

    def call_get_flows(
        self,
        site_name,
        current_startts,
        current_endts,
        nd_filter,
        current_time,
        key,
        failed_key=None,
    ):
        """
        Fetch and process flow data for a given site and alert type over a specified time range.

        This function retrieves flow data for the specified `site_name`
        using a defined time range (`current_startTs` to `current_endTs`),
        applies optional filters, and processes the retrieved data.
        It handles both cases where an existing checkpoint is available and
        where no checkpoint is found, ensuring data collection continues appropriately.

        :param site_name: The name of the site from which to collect flow data.
        :type site_name: str
        :param current_startTs: The start timestamp for data collection in ISO format.
        :type current_startTs: str
        :param current_endTs: The end timestamp for data collection in ISO format.
        :type current_endTs: str
        :param nd_filter: Optional filter criteria applied to the data.
        :type nd_filter: str or None
        :param current_time: The current time used to log and format collected data.
        :type current_time: datetime

        :returns: None
        """
        try:
            alert_type = self.input_info.get("nd_alert_type")

            endpoint_url = self.get_url(alert_type)
            current_time = current_time.isoformat() + "Z"
            index = self.index
            source_type = "cisco:dc:nd:" + alert_type

            params = {
                "siteName": site_name,
                "sort": "-ts",
                "count": 1000,
                "endDate": current_endts,
                "startDate": current_startts,
            }

            if nd_filter:
                params["filter"] = nd_filter

            self.pagination(
                params=params,
                endpoint_url=endpoint_url,
                index=index,
                source_type=source_type,
                alert_type=alert_type,
                key=key,
                siteName=site_name,
                current_time=current_time,
            )
        except Exception:
            if failed_key:
                existing_failed_checkpoint = self.get_checkpoint(
                    failed_key, self.session_key, APP_NAME
                )
                if existing_failed_checkpoint:
                    existing_failed_timestamps = existing_failed_checkpoint.get(
                        "failed_timestamps", []
                    )
                    new_failed_timestamps = {
                        "s": current_startts,
                        "e": current_endts,
                    }
                    existing_failed_timestamps.append(new_failed_timestamps)
                    failed_checkpoint_value = {
                        "failed_timestamps": existing_failed_timestamps,
                    }
                else:
                    failed_checkpoint_value = {
                        "failed_timestamps": [
                            {
                                "s": current_startts,
                                "e": current_endts,
                            },
                        ],
                    }
                self.save_checkpoint(
                    failed_key, self.session_key, APP_NAME, failed_checkpoint_value
                )
            self.logger.error(
                f"Nexus Dashboard Error: An Error Occured while fetching data for {alert_type} data."
                f" URL: {endpoint_url} and Host: {self.nd_host}."
            )

    def get_flows(self, current_time):
        """
        Fetch flow data for a specified site and alert type in parallel using threading.

        This function divides the time range from the specified start date to the current time
        into smaller slices and fetches flow data for each slice in parallel to optimize performance.
        It uses multiple threads to make concurrent requests and collect the data efficiently.

        :param site_name: The name of the site from which to collect the flow data.
        :type site_name: str
        :param current_time: The current time used as the end timestamp for flow collection.
        :type current_time: datetime

        :returns: None
        """
        try:
            alert_type = self.input_info.get("nd_alert_type")
            site_name = self.input_info.get("nd_protocol_site_name", None)
            endpoint_url = self.get_url(alert_type)
            nd_start_date = self.input_info.get("nd_flow_start_date")
            if nd_start_date is None:
                nd_start_date = "1h"
            nd_start_date = "now-" + nd_start_date
            nd_filter = self.input_info.get("nd_additional_filter")
            nd_time_slice = self.input_info.get("nd_time_slice")

            ts_stt = datetime.strptime(
                self.convertTimestamp(nd_start_date), "%Y-%m-%dT%H:%M:%S.%fZ"
            )
            current_endtime = self.convertTimestamp("now")
            ts_end = datetime.strptime(current_endtime, "%Y-%m-%dT%H:%M:%S.%fZ")

            if nd_time_slice:
                nd_time_slice = int(nd_time_slice)
                delta = timedelta(seconds=float(nd_time_slice))

            key = f"{self.acc_name}_{self.input_name}_{site_name}_{alert_type}_success"
            failed_key = (
                f"{self.acc_name}_{self.input_name}_{site_name}_{alert_type}_failed"
            )
            chkpt_start_time = self.get_checkpoint(key, self.session_key, APP_NAME)
            failed_checkpoint_list = self.get_checkpoint(
                failed_key, self.session_key, APP_NAME
            )
            self.logger.debug(f"chkpt_start_time {key}: {chkpt_start_time}")

            if chkpt_start_time:
                startTs = datetime.strptime(
                    chkpt_start_time, "%Y-%m-%dT%H:%M:%S.%fZ"
                ) + timedelta(seconds=0.001)
                log_startTs = startTs.isoformat() + "Z"
                self.logger.info(
                    f"Nexus Dashboard Info: Found an existing checkpoint with value: {log_startTs} for "
                    f" {alert_type} endpoint for fabric: {site_name} and "
                    f"Host: {self.nd_host}."
                )
            else:
                startTs = ts_stt
                current_startts = startTs.isoformat() + "Z"
                self.logger.info(
                    f"Nexus Dashboard Info: No existing checkpoint found, starting data collection"
                    f" with value: {current_startts} for "
                    f" {alert_type} endpoint for fabric: {site_name} and Host: {self.nd_host}"
                )
            log_start_ts = startTs.isoformat() + "Z"
            log_end_ts = ts_end.isoformat() + "Z"
            self.logger.info(
                f"Nexus Dashboard Info: Value of startTs: {log_start_ts} endTs: {log_end_ts} for {alert_type}"
                f" endpoint for fabric: {site_name} and Host: {self.nd_host}."
            )

            delta = timedelta(seconds=float(nd_time_slice))
            segmnt = []
            ts_cur = startTs
            while ts_cur < ts_end:
                if ts_cur + delta < ts_end:
                    ts_nxt = ts_cur + delta
                else:
                    ts_nxt = ts_end
                segmnt.append({"s": ts_cur, "e": ts_nxt})
                ts_cur = ts_nxt

            thr = []
            for _time in segmnt:
                start_time_str = _time["s"].strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                end_time_str = _time["e"].strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                thr.append(
                    threading.Thread(
                        target=self.call_get_flows,
                        args=(
                            site_name,
                            start_time_str,
                            end_time_str,
                            nd_filter,
                            ts_end,
                            key,
                            failed_key,
                        ),
                    )
                )

            if failed_checkpoint_list is not None and len(failed_checkpoint_list) > 0:
                failed_timestamps_list = failed_checkpoint_list.get(
                    "failed_timestamps", []
                )
                for failed_timestamps in failed_timestamps_list:
                    thr.append(
                        threading.Thread(
                            target=self.call_get_flows,
                            args=(
                                site_name,
                                failed_timestamps["s"],
                                failed_timestamps["e"],
                                nd_filter,
                                key,
                                failed_key,
                            ),
                        )
                    )

            cnt = 0
            que = []
            que_size = 180
            for _t in thr:
                _t.start()
                que.append(_t)
                cnt += 1
                if cnt % que_size == 0 or cnt >= len(thr):
                    for t_que in que:
                        t_que.join()
                    que = []

            for t in que:
                t.join()

            if self.data_count:
                self.save_checkpoint(key, self.session_key, APP_NAME, current_endtime)
                self.logger.debug(f"chkpt_save_time {key}: {current_endtime}")
                self.logger.info(
                    f"Nexus Dashboard Info: Value saved in checkpoint: {current_endtime} for "
                    f" {alert_type} endpoint for "
                    f"fabric: {site_name} and Host: {self.nd_host}."
                )

        except Exception as e:
            self.logger.error(
                f"API error during flows data collection. "
                f"The selected timeSlice ({self.input_info.get('nd_time_slice')} seconds)  may be too large. "
                f"Please adjust the timeSlice value from the input page to proceed.",
            )
            self.logger.error(
                f"Nexus Dashboard Error: An Error Occured while fetching data for {alert_type} data."
                f" URL: {endpoint_url} and Host: {self.nd_host}. Error: {str(e)}"
            )

    def ingest_data_in_splunk_threading(
        self, node_names_list, current_time, interface_names_list, scope
    ):
        """
        Fetch and ingest congestion data for a specific fabric and print events in Splunk.

        This method checks for a checkpoint value for the specified alert type and site name.
        - If a checkpoint is found, data collection starts from the checkpoint time.
        - If no checkpoint is found, it uses the provided `nd_congestion_start_date` to start data collection.
        - If `nd_congestion_start_date` is not provided, data collection starts from the beginning of time.

        It logs the start and end times for data collection, and sends collected data to Splunk.

        :param node_names_list: List of node names to be considered for data collection.
        :type node_names_list: list
        :param current_time: Current timestamp indicating the end time for data collection.
        :type current_time: str
        :param interface_names_list: List of interface names to filter data.
        :type interface_names_list: list
        :param scope: Scope of data collection to define data boundaries.
        :type scope: str

        :returns: None
        """
        alert_type = self.input_info.get("nd_alert_type")
        endpoint_url = self.get_url(alert_type)
        nd_granularity = self.input_info.get("nd_granularity")
        if nd_granularity is None:
            nd_granularity = "5m"
        nd_granularity_time = "now-" + nd_granularity
        nd_filter = self.input_info.get("nd_additional_filter")

        nd_site_name = self.input_info.get("nd_protocol_site_name")

        total_Items_Count = None
        key = f"{self.acc_name}_{self.input_name}_{nd_site_name}_{alert_type}"
        chkpt_start_time = self.get_checkpoint(key, self.session_key, APP_NAME)
        self.logger.debug(f"chkpt_start_time {key}: {chkpt_start_time}")

        start_time = self.convertTimestamp(nd_granularity_time)
        endTs = current_time.isoformat() + "Z"

        if chkpt_start_time:
            startTs = datetime.strptime(
                chkpt_start_time, "%Y-%m-%dT%H:%M:%S.%fZ"
            ) + timedelta(seconds=-1)
            startTs = startTs.isoformat() + "Z"
            self.logger.info(
                f"Nexus Dashboard Info: Found an existing checkpoint with value: {startTs} for "
                f" {alert_type} endpoint for fabric: {nd_site_name} and "
                f"Host: {self.nd_host}."
            )
        else:
            startTs = start_time
            self.logger.info(
                f"Nexus Dashboard Info: No existing checkpoint found, starting data collection"
                f" with value: {startTs} for "
                f" {alert_type} endpoint for fabric: {nd_site_name} and Host: {self.nd_host}"
            )
        self.logger.info(
            f"Nexus Dashboard Info: Value of startTs: {startTs} endTs: {endTs} for {alert_type}"
            f" endpoint for fabric: {nd_site_name} and Host: {self.nd_host}."
        )

        try:
            threads = []
            for nodeName in node_names_list:
                for interfaceName in interface_names_list:
                    thread = threading.Thread(
                        target=self.ingest_one_event_in_splunk,
                        args=(
                            nodeName,
                            interfaceName,
                            scope,
                            nd_site_name,
                            startTs,
                            endTs,
                            nd_filter,
                            current_time,
                            nd_granularity,
                        ),
                    )
                    threads.append(thread)

            cnt = 0
            in_progress = []
            for t in threads:
                t.start()
                in_progress.append(t)
                cnt += 1
                if cnt % NUM_NDI_THREAD == 0:
                    for t_in_prog in in_progress:
                        t_in_prog.join()
                    in_progress = []

            for t in in_progress:
                t.join()

        except Exception as e:
            if total_Items_Count:
                self.data_count_API += total_Items_Count
            self.logger.error(
                f"Nexus Dashboard Error: An Error Occured while fetching data for {alert_type} data."
                f" URL: {endpoint_url} and Host: {self.nd_host}. Error: {str(e)}"
            )

    def get_endpoint_details(
        self, fabric_list, group, startTs_from_hrs_configured, current_time
    ):
        """
        Fetch the anomalies/advisories data for particular fabric and print events in Splunk.

        :param fabric_list: List of all fabrics in NI.
        :type fabric_list: list
        """
        alert_type = self.input_info.get("nd_alert_type")
        endpoint_url = self.get_url(alert_type)
        index = self.index
        source_type = "cisco:dc:nd:" + alert_type

        params = self.get_request_params(alert_type, current_time)
        current_time = current_time.isoformat() + "Z"

        hrs_configured = int(self.input_info.get("nd_time_range"))

        for fabric_name in fabric_list:
            total_Items_Count = None
            key = (
                f"{self.acc_name}_{self.input_name}_{group}_{fabric_name}_{alert_type}"
            )
            chkpt_start_time = self.get_checkpoint(key, self.session_key, APP_NAME)
            if not chkpt_start_time:
                old_chkpt_key = f"{self.input_name}_{group}_{fabric_name}_{alert_type}"
                chkpt_start_time = self.get_checkpoint(
                    old_chkpt_key, self.session_key, APP_NAME
                )
            self.logger.debug(f"chkpt_start_time {key}: {chkpt_start_time}")

            if chkpt_start_time:
                startTs = datetime.strptime(
                    chkpt_start_time, "%Y-%m-%dT%H:%M:%S.%fZ"
                ) + timedelta(seconds=0.001)
                startTs = startTs.isoformat() + "Z"
                self.logger.info(
                    f"Nexus Dashboard Info: Found an existing checkpoint with value: {startTs} for "
                    f" {alert_type} endpoint Insights Group: {group} for fabric: {fabric_name} and "
                    f"Host: {self.nd_host}."
                )
            elif hrs_configured == 0:
                startTs = ND_startTs
                self.logger.info(
                    f"Nexus Dashboard Info: No existing checkpoint found, starting data collection"
                    f" to collect all events with value: {startTs} for "
                    f" {alert_type} endpoint Insights Group: {group} for fabric: {fabric_name} and Host: {self.nd_host}"
                )
            else:
                startTs = startTs_from_hrs_configured.isoformat() + "Z"
                self.logger.info(
                    f"Nexus Dashboard Info: No existing checkpoint found, starting data collection"
                    f" with value: {startTs} for "
                    f" {alert_type} endpoint Insights Group: {group} for fabric: {fabric_name} and Host: {self.nd_host}"
                )
            self.logger.info(
                f"Nexus Dashboard Info: Value of startTs: {startTs} endTs: {current_time} for {alert_type}"
                f" endpoint for Insights Group: {group} for fabric: {fabric_name} and Host: {self.nd_host}."
            )

            offset = 0
            params["fabricName"] = fabric_name
            params["startTs"] = startTs
            params["endTs"] = current_time

            try:
                while True:
                    params["offset"] = offset
                    response = self.get(endpoint_url, params=params)
                    if response:
                        entries_events = response.get("entries", [])
                        if len(entries_events) > 0:
                            total_Items_Count = response.get("totalResultsCount", 0)
                            for events in entries_events:
                                events["nd_host"] = self.nd_host
                                events["insights_group"] = group
                                event = smi.Event(
                                    data=json.dumps(events, ensure_ascii=False),
                                    index=index,
                                    sourcetype=source_type,
                                    source=alert_type,
                                )
                                self.ew.write_event(event)
                                endTs = events["endTs"]
                            self.save_checkpoint(key, self.session_key, APP_NAME, endTs)
                            self.logger.debug(f"chkpt_save_time {key}: {endTs}")
                            self.logger.info(
                                f"Nexus Dashboard Info: Value saved in checkpoint: {endTs} for "
                                f" {alert_type} endpoint Insights Group: {group} for "
                                f"fabric: {fabric_name} and Host: {self.nd_host}."
                            )
                            self.data_count += len(entries_events)
                        else:
                            self.logger.info(
                                "Nexus Dashboard Info: Value saved in checkpoint: "
                                f"{self.get_checkpoint(key,self.session_key,APP_NAME)} for "
                                f" {alert_type} endpoint Insights Group: {group} for "
                                f"fabric: {fabric_name} and Host: {self.nd_host}."
                            )
                            break
                    offset += self.nd_api_call_count
                if total_Items_Count:
                    self.data_count_API += total_Items_Count
            except Exception as e:
                if total_Items_Count:
                    self.data_count_API += total_Items_Count
                self.logger.error(
                    f"Nexus Dashboard Error: An Error Occured while fetching data for {alert_type} data."
                    f" URL: {endpoint_url} and Host: {self.nd_host}. Error: {str(e)}"
                )

    def get_endpoint_details_without_fabric(
        self, startTs_from_hrs_configured, current_time
    ):
        """
        Fetch the anomalies/advisories data for particular fabric and print events in Splunk.

        :param fabric_list: List of all fabrics in NI.
        :type fabric_list: list
        """
        alert_type = self.input_info.get("nd_alert_type")
        endpoint_url = self.get_url(alert_type)
        index = self.index
        source_type = "cisco:dc:nd:" + alert_type

        params = self.get_request_params(alert_type, current_time)
        current_time = current_time.isoformat() + "Z"

        hrs_configured = int(self.input_info.get("nd_time_range"))

        total_Items_Count = None
        key = f"{self.acc_name}_{self.input_name}_{alert_type}"
        chkpt_start_time = self.get_checkpoint(key, self.session_key, APP_NAME)
        self.logger.debug(f"chkpt_start_time {key}: {chkpt_start_time}")

        if chkpt_start_time:
            startTs = datetime.strptime(
                chkpt_start_time, "%Y-%m-%dT%H:%M:%S.%fZ"
            ) + timedelta(seconds=0.001)
            startTs = startTs.isoformat() + "Z"
            self.logger.info(
                f"Nexus Dashboard Info: Found an existing checkpoint with value: {startTs} for "
                f" {alert_type} endpoint "
                f"Host: {self.nd_host}."
            )
        elif hrs_configured == 0:
            startTs = ND_startTs
            self.logger.info(
                f"Nexus Dashboard Info: No existing checkpoint found, starting data collection"
                f" to collect all events with value: {startTs} for "
                f" {alert_type} endpoint Host: {self.nd_host}"
            )
        else:
            startTs = startTs_from_hrs_configured.isoformat() + "Z"
            self.logger.info(
                f"Nexus Dashboard Info: No existing checkpoint found, starting data collection"
                f" with value: {startTs} for "
                f" {alert_type} endpoint Host: {self.nd_host}"
            )
        self.logger.info(
            f"Nexus Dashboard Info: Value of startTs: {startTs} endTs: {current_time} for {alert_type}"
            f" endpoint for Host: {self.nd_host}."
        )

        offset = 0
        params["startTs"] = startTs
        params["endTs"] = current_time

        try:
            while True:
                params["offset"] = offset
                response = self.get(endpoint_url, params=params)
                if response:
                    entries_events = response.get("entries", [])
                    if len(entries_events) > 0:
                        total_Items_Count = response.get("totalResultsCount", 0)
                        for events in entries_events:
                            events["nd_host"] = self.nd_host
                            event = smi.Event(
                                data=json.dumps(events, ensure_ascii=False),
                                index=index,
                                sourcetype=source_type,
                                source=alert_type,
                            )
                            self.ew.write_event(event)
                            endTs = events["endTs"]
                        self.save_checkpoint(key, self.session_key, APP_NAME, endTs)
                        self.logger.debug(f"chkpt_save_time {key}: {endTs}")
                        self.logger.info(
                            f"Nexus Dashboard Info: Value saved in checkpoint: {endTs} for "
                            f" {alert_type} endpoint"
                            f" Host: {self.nd_host}."
                        )
                        self.data_count += len(entries_events)
                    else:
                        self.logger.info(
                            "Nexus Dashboard Info: Value saved in checkpoint: "
                            f"{self.get_checkpoint(key,self.session_key,APP_NAME)} for "
                            f" {alert_type} endpoint"
                            f" Host: {self.nd_host}."
                        )
                        break
                offset += self.nd_api_call_count
            if total_Items_Count:
                self.data_count_API += total_Items_Count
        except Exception as e:
            if total_Items_Count:
                self.data_count_API += total_Items_Count
            self.logger.error(
                f"Nexus Dashboard Error: An Error Occured while fetching data for {alert_type} data."
                f" URL: {endpoint_url} and Host: {self.nd_host}. Error: {str(e)}"
            )

    def get_request_params(self, alert_type, current_time):
        """
        Get the request parameters for the API call.

        :param alert_type: The type of alert (e.g. "advisories" or "anomalies")
        :param current_time: The current time
        :return: A dictionary of request parameters
        """
        params = {"count": self.nd_api_call_count, "orderBy": "endTs,asc"}

        nd_severity = self.input_info.get("nd_severity")
        if alert_type == "advisories":
            nd_category = self.input_info.get("nd_advisories_category")
        else:
            nd_category = self.input_info.get("nd_anomalies_category")

        severity_list = self.convert_nd_input_to_list(nd_severity)
        category_list = self.convert_nd_input_to_list(nd_category)

        if "*" in severity_list and "*" in category_list:
            filter_str = ""
        elif "*" in severity_list:
            filter_str = " OR ".join(category_list)
        elif "*" in category_list:
            filter_str = " OR ".join(severity_list)
        else:
            filter_str = ""
            for category in category_list:
                for severity in severity_list:
                    filter_str += "(" + severity + " AND " + category + ") OR "
            filter_str = filter_str[:-4]

        if filter_str != "":
            params["filter"] = filter_str

        return params
