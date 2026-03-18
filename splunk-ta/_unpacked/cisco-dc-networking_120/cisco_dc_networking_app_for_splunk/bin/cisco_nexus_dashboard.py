import import_declare_test
import sys
import time
import threading
from datetime import datetime, timedelta, timezone
import traceback
import concurrent.futures
import cisco_dc_mso_session as mso_session
import common.cisco_dc_mso_urls as mso_urls
import common.log as log
import common.proxy as proxy
import import_declare_test
from cisco_dc_input_validators import nd_input_validator
from cisco_dc_nd_collector import *
from cisco_nd_helper import stream_events, validate_input
from common import consts
from common.consts import ND_CHKPT_COLLECTION
from common.utils import get_credentials, get_sslconfig
from solnlib.modular_input import checkpointer
from splunklib import modularinput as smi


class IngestResponseInSplunk(object):
    """This class consists of all methods that will parse the API response and print on Splunk side."""

    def __init__(self, index):
        """Initialize response."""
        self.response = []
        self.index = index

    def dict_parse(self, data_to_be_parsed, keyset=None):
        """
        Covert the response in key=value format.

        :param data_to_be_parsed: The API data which will be parsed depending on datatype.
        :type keyset: dict
        :param keyset: Holds good, whenever we want to combine keys of nested response.
        :type keyset: string
        """
        if isinstance(data_to_be_parsed, dict):
            for key, val in list(data_to_be_parsed.items()):

                if isinstance(val, dict):
                    for key2, val2 in list(val.items()):
                        if keyset:
                            self.dict_parse(
                                val2, f"{str(keyset)}_{str(key)}_{str(key2)}"
                            )
                        else:
                            self.dict_parse(val2, f"{str(key)}_{str(key2)}")
                elif isinstance(val, list) and len(val) > 0:
                    if keyset:
                        self.list_parse(val, f"{str(keyset)}_{str(key)}")
                    else:
                        self.list_parse(val, str(key))
                elif isinstance(val, list) is False and isinstance(val, dict) is False:
                    if isinstance(val, str):
                        val = val.replace('\n', '').replace('\r', '')
                    if keyset:
                        self.response.append(f"{str(keyset)}_{str(key)}={val}")
                    else:
                        self.response.append(f"{str(key)}={str(val)}")

        elif isinstance(data_to_be_parsed, list) and len(data_to_be_parsed) > 0:
            self.list_parse(data_to_be_parsed, keyset)

        elif isinstance(data_to_be_parsed, list) is False and isinstance(data_to_be_parsed, dict) is False:
            if keyset:
                if isinstance(data_to_be_parsed, str):
                    data_to_be_parsed = data_to_be_parsed.replace('\n', '').replace('\r', '')
                self.response.append(f"{str(keyset)}={str(data_to_be_parsed)}")

    def list_parse(self, data_to_be_parsed, keys, only_list_resp=False):
        """
        Iterate list elements and calls dict_parse method for further parsing.

        :param data_to_be_parsed: The API data which will be parsed depending on datatype.
        :type data_to_be_parsed: list
        :param keys: Holds good, whenever we want to combine keys of nested response.
        :type keys: string
        :param only_list_resp: Holds good, whenever json response is only array and not objects.
        :type only_list_resp: bool
        """
        if only_list_resp:
            for data in data_to_be_parsed:
                if isinstance(data, str):
                    data = data.replace('\n', '').replace('\r', '')
                self.response.append(f"{str(keys)}={str(data)}")
        else:
            for data in data_to_be_parsed:
                self.dict_parse(data, keys)

    def ingest_data(self, data, splunk_field, host, response_key=None, api_name=None, endpt_id=None, ew=None):
        """
        Parse the response in key=value format and print on Splunk side.

        :param data: The data to be printed in Splunk.
        :type data: JSON
        :param response_key: Holds good whenever json response is only array and not objects,
                             since it is the only key in response.
        :type response_key: string
        :param splunk_field: The value for mso_api_endpoint field to be ingested in Splunk.
                             i.e. mso_api_endpoint=splunk_field, so user can know what response of which API is.
        :type splunk_field: string
        :param host: The value of mso_host field to be ingested in Splunk i.e. mso_host=host,
                     so user can know collected data belongs to which MSO host.
        :type host: string
        :param api_name: Holds good whenever API calls fetch specific endpoints details and not entire details.
                         Eg: api/v1/policies/usage/{policy_id}: to get policy usage details for various policy id.
                         Thus api_name=policy
        :type api_name: string
        :param endpt_id: The value of mso_api_name_id field to be ingested in Splunk i.e. mso_api_name_id=endpt_id,
                         so user can know collected data belongs to which id of MSO API.
                         Eg: api/v1/policies/usage/{policy_id}: To get policy usage details for various policy ids.
                         Thus mso_policy_id= policy_id
        :type endpt_id: string
        """
        events_ingested_count = 0
        for mso_data in data:

            self.response = []

            current_time = datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z")

            if splunk_field == "msoAuditRecords":
                timestamp_field = mso_data.get("timestamp")
                if timestamp_field:  # bcz timestamp field is coming in UTC timezone
                    self.response.append("current_time=" + str(timestamp_field) + "Z")
                else:
                    self.response.append("current_time=" + str(current_time))
            else:
                self.response.append("current_time=" + str(current_time))

            self.response.append("mso_host=" + host)
            self.response.append("mso_api_endpoint=" + splunk_field)

            # Because the response of APIs for specific id, does not have id in it
            if api_name and endpt_id:
                if api_name == "fabric":
                    self.response.append("mso_site_id=" + str(endpt_id))
                else:
                    self.response.append("mso_" + api_name + "_id=" + str(endpt_id))

            if not isinstance(mso_data, list) and not isinstance(mso_data, dict):
                if isinstance(data, list) and len(data) > 0:
                    self.list_parse(data, response_key, True)
                    event = "\t".join(self.response)
                    event = smi.Event(data=event, index=self.index, sourcetype="cisco:dc:nd:mso", unbroken=True)
                    ew.write_event(event)
                    events_ingested_count += 1
                    break

                if isinstance(data, dict):
                    self.dict_parse(data)
                    event = "\t".join(self.response)
                    event = smi.Event(data=event, index=self.index, sourcetype="cisco:dc:nd:mso", unbroken=True)
                    ew.write_event(event)
                    events_ingested_count += 1
                    break

            else:
                for keys in mso_data:
                    if str(mso_data[keys]):
                        if isinstance(mso_data[keys], dict):
                            self.dict_parse(mso_data[keys], keys)
                        elif isinstance(mso_data[keys], list) and len(mso_data[keys]) > 0:
                            self.list_parse(mso_data[keys], keys)
                        else:
                            value = mso_data[keys]
                            if isinstance(value, str):
                                value = value.replace('\n', '').replace('\r', '')
                            self.response.append(keys + "=" + str(value))
                event = "\t".join(self.response)
                event = smi.Event(data=event, index=self.index, sourcetype="cisco:dc:nd:mso", unbroken=True)
                ew.write_event(event)
                events_ingested_count += 1

        return events_ingested_count


class GetAPIResponse(object):
    """This class consists of all functions, that will hit various APIs of required endpoints."""

    def __init__(self, session, mso_host, ew, index, logger):
        """
        Initialize object with given parameters.

        :param session: MSO session
        :type session: session object
        :param mso_host: Hostname/IP address of MSO
        :type mso_host: string
        """
        self.session = session
        self.index = index
        self.print_response_object = IngestResponseInSplunk(self.index)
        self.ew = ew
        self.logger = logger
        host_split_by_port = mso_host[::-1].split(":", 1)
        # host variable consists of only mso_host and not port number
        self.host = host_split_by_port[1][::-1] if len(host_split_by_port) == 2 else host_split_by_port[0][::-1]

    @staticmethod
    def fetch_ids(data):
        """Iterate over data to get value of id field returned in API response."""
        ids = []
        for elements in data:
            if elements.get("id"):
                ids.append(elements.get("id"))
        return ids

    def get_response_for_specific_id(self, mso_api_endpoint, ids, api_name, ew):
        """
        Fetch the data for all APIs that require specific id to fetch data.

        Example: The API call will need specific policy id /api/v1/policies/usage/{id}.
        :param mso_api_endpoint: The MSO API endpoint from data is to be fetched.
        :type mso_api_endpoint: string
        :param ids: Fetch endpoint data only for given IDs.
                Eg: api/v1/policies/usage/{policy_id}: Here we want policy usage details for various policy ids.
                So we will hit this endpoint for values in ids list.
        :type ids: list
        :param api_name: Name of MSO API
        :type api_name: string
        """
        for splunk_field, endpt in list(mso_api_endpoint.items()):
            for endpt_id in ids:
                events_ingested_count = 0
                try:
                    endpoint = endpt.format(id=endpt_id)

                    if splunk_field == "siteHealth":
                        params = {"include": "health,faults,cluster-status"}

                    elif splunk_field == "fabricDetails":
                        params = {"include": "health,faults"}

                    else:
                        params = None

                    response = self.session.get(api_endpoint=endpoint, params=params)

                    self.logger.debug(f"Endpoint: {endpoint}. Response returned successfully.")

                    if response:
                        keys = list(response.keys())
                        for key in keys:
                            if len(keys) == 1 and isinstance(response[key], list):
                                events_ingested_count += self.print_response_object.ingest_data(
                                    data=response[key],
                                    splunk_field=splunk_field,
                                    host=self.host,
                                    response_key=key,
                                    api_name=api_name,
                                    endpt_id=endpt_id,
                                    ew=self.ew
                                )
                                self.logger.info(
                                    f"Collected {events_ingested_count} events for {endpt_id} id"
                                    f" for {splunk_field} field."
                                )
                            else:
                                events_ingested_count += self.print_response_object.ingest_data(
                                    data=response,
                                    splunk_field=splunk_field,
                                    host=self.host,
                                    api_name=api_name,
                                    endpt_id=endpt_id,
                                    ew=self.ew
                                )
                                self.logger.info(
                                    f"Collected {events_ingested_count} events for {endpt_id} id "
                                    f"for {splunk_field} field."
                                )
                                break
                    else:
                        self.logger.info(f"Received empty response for Endpoint: {endpoint}.")

                except Exception as err:
                    self.logger.error(
                        f"MSO Error: Error while collecting data for host: {self.host}, api: {api_name}, "
                        f"endpoint: {endpoint}. Error: {str(err)}"
                    )
                    self.logger.error("Skipping this endpoint.")
                    continue

    def get_site_id_for_endpoints(self, api_name, splunk_field_url, ew):
        """
        Fetch set of site IDs.

        :param api_name: Name of MSO API
        :type api_name: string
        :param splunk_field_url: dict holding URLs of MSO API endpoint, from where data is to be fetched.
            dict key: Name of field to be appended alongwith response
            dict value: Endpoint URL
        :type splunk_field_url: dict
        """
        site_id = []
        endpoint = mso_urls.API_RETURNING_SITE_ID

        try:
            response = self.session.get(api_endpoint=endpoint)
            self.logger.debug(f"Endpoint: {endpoint}. Response returned successfully.")

            if response:
                for key in list(response.keys()):
                    data = response[key]
                    site_id = self.fetch_ids(data)
            else:
                self.logger.info(f"Received empty response for Endpoint: {endpoint}.")

        except Exception as err:
            self.logger.error(
                f"MSO Error: Could not fetch the Site Ids for host: {self.host}. Hence data cannot be collected "
                f"for endpoint/s: {list(splunk_field_url.values())}. Error: {str(err)}"
            )
        if site_id:
            self.get_response_for_specific_id(splunk_field_url, site_id, api_name, ew)
        else:
            self.logger.debug(
                f"MSO Error: Failed fetching Site ids for host: {self.host}. Hence data cannot be collected for "
                f"endpoint/s: {list(splunk_field_url.values())}."
            )

    def get_audit_data(self, session_key, inp_name, acc_name):
        """Fetch MSO Audit Logs and create/update checkpoint file."""
        endpoint_details = mso_urls.AUDIT_RECORDS
        endpoint = endpoint_details["api"]
        offset = 0
        check_point_name = acc_name + "_" + inp_name + "_audit"
        checkpoint_collection = checkpointer.KVStoreCheckpointer(
            ND_CHKPT_COLLECTION, session_key, 'cisco_dc_networking_app_for_splunk'
        )
        last_saved_value = checkpoint_collection.get(check_point_name)
        params = {"sort": "timestamp", "limit": 250}
        current_time = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S%z")
        if not last_saved_value:
            old_chkpt_key = inp_name + "_" + self.host.replace('.', '_') + "_LastTransactionTime"
            last_saved_value = checkpoint_collection.get(old_chkpt_key)

        if last_saved_value:
            params["start"] = last_saved_value
            params["end"] = current_time
            self.logger.info(f"Fetched the checkpoint successfully. Value: {last_saved_value}")

        events_ingested_count = 0
        try:
            while True:
                params["offset"] = offset
                response = self.session.get(api_endpoint=endpoint, params=params)
                self.logger.debug(f"Endpoint: {endpoint}. Response returned successfully.")

                offset += 250
                data = response["auditRecords"]

                if not data:
                    break

                events_ingested_count += self.print_response_object.ingest_data(
                    data=data,
                    splunk_field=endpoint_details["splunk_field"],
                    host=self.host,
                    response_key="auditRecords",
                    ew=self.ew
                )

                if data:
                    latest_time = data[-1].get("timestamp", current_time)
                    checkpoint_collection = checkpointer.KVStoreCheckpointer(
                        ND_CHKPT_COLLECTION, session_key, 'cisco_dc_networking_app_for_splunk'
                    )
                    self.logger.info(f"Saving LastTransactionTime as: {latest_time}")
                    checkpoint_collection.update(check_point_name, latest_time)
                    self.logger.info("Successfully saved.")
        except Exception as err:
            self.logger.error(
                f"MSO Error: Error while collecting Audit Logs for host: {self.host} .Error: {str(err)}")

        self.logger.info(f"Collected {events_ingested_count} events for auditrecords.")

    def get_nd_user_response(self, endpoint_details, api_name):
        """Fetch User Response for ND Auth."""
        api_endpoints = endpoint_details["url"]

        events_ingested_count = 0
        for splunk_field, endpoint in list(api_endpoints.items()):
            try:
                response = self.session.get(api_endpoint=endpoint)
                self.logger.debug(
                    f"Host: {self.host} Endpoint: {endpoint}. Response returned successfully."
                )

                if response:
                    keys = response if splunk_field == "userDetails" else list(response.keys())
                    for key in keys:
                        if len(keys) == 1 and isinstance(response[key], list):
                            events_ingested_count += self.print_response_object.ingest_data(
                                data=response[key], splunk_field=splunk_field, host=self.host, response_key=key, ew=self.ew
                            )
                        else:
                            events_ingested_count += self.print_response_object.ingest_data(
                                data=response, splunk_field=splunk_field, host=self.host, ew=self.ew
                            )
                            break
                else:
                    self.logger.info(f"Received empty response for Endpoint: {endpoint}.")

            except Exception as err:
                self.logger.error(
                    f"MSO Error: Could not fetch the data for host: {self.host} and endpoint: {api_name}. "
                    f"Error: {str(err)}"
                )
                self.logger.error(f"Skipping this endpoint: {endpoint}")
                continue

        self.logger.info(f"Collected {events_ingested_count} events for NDO User Response.")

    def get_api_response(self, endpoint_details, api_name, ew):
        """
        Fetch the data for MSO APIs that do not require specific id to fetch data.

        Example: The API call api/v1/users, will give information of all MSO users, not of any specific user.
        :param endpoint_details: dict holding details of MSO API endpoint, from where data is to be fetched.
            - endpoint_details['url']: dict consisting of endpoint URL.
                Eg: endpoint_details['url']= {
                                                'userDetails':'api/v1/users',
                                                'userAllowedRoles':'api/v1/users/allowed-roles'
                                             }
            - endpoint_details['url_consisting_ids']: dict consisting of endpoint URLs which require ids for api_name.
                Eg: endpoint_details['url_consisting_ids'] = {
                                                                'userPermissions':'api/v1/users/{id}/permissions'
                                                             }
            - endpoint_details['splunk_field_consisting_id']: string i.e. key of endpoint_details['url'] dictionary
              which will give list of ids for given api_name.
                Eg: endpoint_details['splunk_field_consisting_id'] = 'userDetails'
        :type endpoint_details: dict
        :param api_name: Name of MSO API
            Example: Here value is user because the above api calls are for MSO users.
        :type api_name: string
        """
        api_endpoints = endpoint_details["url"]

        ids = []
        events_ingested_count = 0
        for splunk_field, endpoint in list(api_endpoints.items()):
            try:
                response = self.session.get(api_endpoint=endpoint)
                self.logger.debug(f"Endpoint: {endpoint}. Response returned successfully.")

                if response:
                    keys = list(response.keys())
                    for key in keys:
                        if len(keys) == 1 and isinstance(response[key], list):
                            events_ingested_count += self.print_response_object.ingest_data(
                                data=response[key], splunk_field=splunk_field, host=self.host, response_key=key, ew=self.ew
                            )
                            if splunk_field == endpoint_details["splunk_field_consisting_id"]:
                                ids = self.fetch_ids(response[key])
                        else:
                            events_ingested_count += self.print_response_object.ingest_data(
                                data=response, splunk_field=splunk_field, host=self.host, ew=self.ew
                            )
                            break
                else:
                    self.logger.info(f"Received empty response for Endpoint: {endpoint}.")

            except Exception as err:
                if (
                    splunk_field == endpoint_details["splunk_field_consisting_id"]
                    and len(endpoint_details["url_consisting_ids"]) > 0
                ):
                    self.logger.error(
                        f"MSO Error: Could not fetch the data for host: {self.host} and endpoint: {api_name}. "
                        f"Hence data cannot be collected for "
                        f"endpoint/s: {list(endpoint_details['url_consisting_ids'].values())}. Error: {str(err)}"
                    )
                else:
                    self.logger.error(
                        f"MSO Error: Could not fetch the data for host: {self.host} and endpoint: {api_name}. "
                        f"Error: {str(err)}"
                    )
                self.logger.error(f"Skipping this endpoint: {endpoint}")
                continue

        self.logger.info(f"Collected {events_ingested_count} events for {api_name} api.")

        if len(endpoint_details["url_consisting_ids"]) > 0 and ids:
            self.get_response_for_specific_id(endpoint_details["url_consisting_ids"], ids, api_name, ew)
        else:
            self.logger.debug(
                f"MSO Error: Failed fetching {api_name} ids for host: {self.host}, hence data cannot be collected "
                f"for endpoints: {endpoint_details['url_consisting_ids']}."
            )


class CISCO_ND(smi.Script):
    def __init__(self):
        super(CISCO_ND, self).__init__()

    def get_scheme(self):
        scheme = smi.Scheme("cisco_nexus_dashboard")
        scheme.description = "ND"
        scheme.use_external_validation = True
        scheme.streaming_mode_xml = True
        scheme.use_single_instance = False

        scheme.add_argument(
            smi.Argument(
                "name", title="Name", description="Name", required_on_create=True
            )
        )
        scheme.add_argument(
            smi.Argument("nd_account", required_on_create=True)
        )
        scheme.add_argument(
            smi.Argument("nd_alert_type", required_on_create=True)
        )
        scheme.add_argument(
            smi.Argument("nd_anomalies_category", required_on_create=False)
        )
        scheme.add_argument(
            smi.Argument("nd_advisories_category", required_on_create=False)
        )
        scheme.add_argument(
            smi.Argument("nd_severity", required_on_create=False)
        )
        scheme.add_argument(
            smi.Argument("nd_time_range", required_on_create=False)
        )
        scheme.add_argument(
            smi.Argument("orchestrator_arguments", required_on_create=False)
        )
        scheme.add_argument(
            smi.Argument("nd_scope", required_on_create=False)
        )
        scheme.add_argument(
            smi.Argument("nd_protocol_site_name", required_on_create=False)
        )
        scheme.add_argument(
            smi.Argument("nd_node_name", required_on_create=False)
        )
        scheme.add_argument(
            smi.Argument("nd_interface_name", required_on_create=False)
        )
        scheme.add_argument(
            smi.Argument("nd_additional_filter", required_on_create=False)
        )
        scheme.add_argument(
            smi.Argument("nd_time_slice", required_on_create=False)
        )
        scheme.add_argument(
            smi.Argument("nd_start_date", required_on_create=False)
        )
        scheme.add_argument(
            smi.Argument("nd_flow_start_date", required_on_create=False)
        )
        scheme.add_argument(
            smi.Argument("nd_granularity", required_on_create=False)
        )
        scheme.add_argument(
            smi.Argument('custom_endpoint', required_on_create=False)
        )
        scheme.add_argument(
            smi.Argument('nd_additional_parameters', required_on_create=False)
        )
        scheme.add_argument(
            smi.Argument('custom_sourcetype', required_on_create=False)
        )
        scheme.add_argument(
            smi.Argument('custom_resp_key', required_on_create=False)
        )

        return scheme

    def validate_input(self, definition: smi.ValidationDefinition):
        return validate_input(definition)

    def collect_mso_data(self, class_names, session, host, auth_type, session_key, ew, index, logger, inp_name, acc_name):
        """
        Call methods of GetAPIResponse based on value of MSO API call arguments.

        :param class_names: scripted inputs arguments
        :type class_names: string
        :param session: MSO session
        :type session: session object
        :param host: MSO hostname
        :type host: string
        """
        get_API_response_object = GetAPIResponse(session=session, mso_host=host, ew=ew, index=index, logger=logger)
        mso_apis = class_names
        mso_apis = mso_apis.strip()
        mso_apis = mso_apis.split(" ")
        endpoint_details = {}
        for api in mso_apis:
            api = api.strip()
            if api == "audit":
                get_API_response_object.get_audit_data(session_key, inp_name, acc_name)
            elif api == "fabric":
                get_API_response_object.get_site_id_for_endpoints(api, mso_urls.FABRIC_API, ew)
            elif api == "policy":
                endpoint_details["url"] = mso_urls.POLICY_APIS
                endpoint_details["url_consisting_ids"] = mso_urls.SPECIFIC_POLICY_APIS
                endpoint_details["splunk_field_consisting_id"] = "policyDetails"
                get_API_response_object.get_api_response(endpoint_details, api, ew)
            elif api == "schema":
                endpoint_details["url"] = mso_urls.SCHEMA_APIS
                endpoint_details["url_consisting_ids"] = mso_urls.SPECIFIC_SCHEMA_APIS
                endpoint_details["splunk_field_consisting_id"] = "schemaDetails"
                get_API_response_object.get_api_response(endpoint_details, api, ew)
            elif api == "site":
                get_API_response_object.get_site_id_for_endpoints(api, mso_urls.SPECIFIC_SITE_APIS, ew)
            elif api == "tenant":
                endpoint_details["url"] = mso_urls.TENANT_APIS
                endpoint_details["url_consisting_ids"] = mso_urls.SPECIFIC_TENANT_APIS
                endpoint_details["splunk_field_consisting_id"] = "tenantDetails"
                get_API_response_object.get_api_response(endpoint_details, api, ew)
            elif api == "user":
                endpoint_details["url"] = mso_urls.USER_APIS
                get_API_response_object.get_nd_user_response(endpoint_details, api)
            else:
                logger.error(
                    "MSO Error: Please choose one of the following APIs: audit, fabricConnectivity, "
                    "schemas, sites, tenant, policy and user."
                )
        session.close()

    def try_other_hosts(self, class_names, host, username, password, domain_name, auth_type, verify_ssl, session_key, ew, index, logger, inp_name, acc_name):
        """
        Fetch the data for MSO APIs that do not require specific id.

        :param host: MSO hostname
        :type host: string
        :param username: MSO Username
        :type username: string
        :param password: MSO Password
        :type password: string
        :param verify_ssl: To perform SSL connections with the MSO.
        :type verify_ssl: string
        """
        try:
            for each in host:
                # Login from 2nd MSO
                if domain_name and domain_name!="local":
                    logger.info(f"Collecting data using Remote Based Authentication for the host: {host}")
                else:
                    logger.info(f"Collecting data using Password Based Authentication for the host: {host}")
                try:
                    each = each.strip()
                    msoUrl = f"https://{str(each)}"
                    session = mso_session.Session(
                        msoUrl, username, password, domain_name, consts.TIMEOUT, auth_type, verify_ssl, logger=logger
                    )
                    response = session.login()
                    if response.ok:
                        self.collect_mso_data(class_names, session, each, auth_type, session_key, ew, index, logger, inp_name, acc_name)
                        break
                except Exception as err:
                    logger.error(f"MSO Error: Unable to connect {each} Error: {str(err)}")
                    if str(each) == str(host[-1]):
                        logger.error(
                            f"Could not find other MSOs to login: {host}, Username: {username}"
                        )
                    continue
        except Exception:
            logger.error(f"Could not find other MSOs to login: {host}, Username: {username}")

    def fetch_nd_data(self, input_info, acc, session_key, smi, ew, logger, input_name_for_log):
        logger.info(f"Starting data collection for account {acc}.")
        thread_name = threading.current_thread().name
        logger.debug(
            f"ThreadPoolExecutor thread '{thread_name}' is associated with account: '{acc}'. "
            f"Check logs with thread name '{thread_name}' to debug issues related to '{acc}' account."
        )
        nd_alert_type = input_info["nd_alert_type"]
        ac_creds = get_credentials(acc, "nd_account", session_key)
        logger.info("Credentials retrieved successfully")
        logger.info(f"Started data collection for the {acc} account and {input_name_for_log} input.")
        global ORIGINAL_HOSTS
        proxy_data = proxy.get_proxies(ac_creds)
        if proxy_data:
            logger.info("Proxy is enabled.")
        else:
            logger.info("Proxy is disabled.")

        if nd_alert_type == "Orchestrator":
            try:
                # Connect to the MSO REST interface and authenticate using the specified credentials
                index = input_info['index']
                host_list = ac_creds.get('nd_hostname')
                host_list = host_list.split(",")
                host = host_list[0].strip()
                class_names = input_info['orchestrator_arguments']
                username = ac_creds.get('nd_username')
                password = ac_creds.get('nd_password')
                verify_ssl = get_sslconfig(session_key)
                auth_type = ac_creds.get('nd_authentication_type')
                domain_name = None
                if auth_type == "local_user_authentication":
                    domain_name = "local"
                elif auth_type == "remote_user_authentication":
                    domain_name = ac_creds.get('nd_login_domain')
                else:
                    domain_name = "DefaultAuth"
                msoUrl = f"https://{str(host)}"
                session = mso_session.Session(
                    msoUrl, 
                    username, 
                    password, 
                    domain_name, 
                    consts.TIMEOUT, 
                    auth_type, 
                    verify_ssl=verify_ssl, 
                    logger=logger, 
                    proxies=proxy.get_proxies(ac_creds),
                )
                response = session.login()
                if response.ok:
                    self.collect_mso_data(class_names, session, host, auth_type, session_key,
                                            ew, index, logger, input_name_for_log, acc)
                else:
                    logger.error(
                        f"MSO Error: Could not login to MSO: {host}, Username: {username}"
                    )
                    if len(host_list) > 1:
                        self.try_other_hosts(
                            class_names,
                            host_list[1:],
                            username,
                            password,
                            domain_name,
                            auth_type,
                            verify_ssl,
                            session_key,
                            ew,
                            index,
                            logger,
                            input_name_for_log,
                            acc
                        )
            except Exception as err:
                logger.error(f"MSO Error: Not able to connect to {host} Error: {str(err)}")
                if len(host_list) > 1:
                    self.try_other_hosts(
                        class_names,
                        host_list[1:],
                        username,
                        password,
                        domain_name,
                        auth_type,
                        verify_ssl,
                        session_key,
                        ew,
                        index,
                        logger,
                        input_name_for_log,
                        acc
                    )
         
        elif nd_alert_type == "endpoints":
            index = input_info.get("index", "main")
            global ORIGINAL_HOSTS
            nd_hosts = ac_creds.get("nd_hostname").split(",")

            for i in range(len(nd_hosts)):
                nd_hosts[i] = nd_hosts[i].strip()

            ORIGINAL_HOSTS = nd_hosts
            login_flag = True

            try:
                nd_api_call_count = consts.ND_API_CALL_COUNT
                if not isinstance(nd_api_call_count, int) or nd_api_call_count <= 0:
                    logger.error(
                        "Nexus Dashboard Error: ND API CALL COUNT should be an integer greater than zero. "
                        "Please change the value first and then enable the input. "
                    )
                    return
            except Exception as e:
                logger.error(
                    f"Nexus Dashboard Error: Error occurred while fetching value of ND API CALL COUNT from consts.py. Exception: {str(e)}."
                )

            try:
                timeout = consts.TIMEOUT
                if timeout <= 0:
                    logger.error(
                        "Nexus Dashboard Error: Timeout should be greater than zero. "
                        "Please change the value first and then enable the input. "
                    )
                    return
            except Exception as e:
                logger.error(
                    f"Nexus Dashboard Error: Error occurred while fetching timeout from consts.py. Exception: {str(e)}."
                )

            current_time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
            current_time = datetime.strptime(current_time_str, "%Y-%m-%d %H:%M:%S.%f")

            for nd_host in nd_hosts:
                logger.info(f"Initializing NexusDashboardParameters for host: {nd_host}")
                nexus_dashboard_object = NexusDashboardParameters(
                    nd_api_call_count,
                    ew,
                    acc,
                    nd_host,
                    timeout,
                    get_sslconfig(session_key),
                    ORIGINAL_HOSTS,
                    [],
                    input_info,
                    ac_creds,
                    index,
                    input_info["name"],
                    session_key,
                    logger,
                    acc
                )
                token = nexus_dashboard_object.login()
                if token:
                    logger.info(f"Login successful for host: {nd_host}")
                    login_flag = False
                    try:
                        nexus_dashboard_object.ingest_data_in_splunk(current_time)
                    except Exception as e:
                        logger.error(
                            f"Nexus Dashboard Error: An Error Occured while fetching {input_info['nd_alert_type']} details for "
                            f"Host: {nd_host}. Error: {e}"
                        )
                        logger.error(traceback.format_exc())
                    break

            if len(nd_hosts) > 1 and login_flag and nd_hosts[-1] == nd_host:
                logger.error(f"Nexus Dashboard Error: Not able to login in any of the cluster instance: {nd_hosts}")

            logger.info(f"Total no. of events in API Response: {nexus_dashboard_object.data_count_API}")
            logger.info(f"Total no. of collected events is: {nexus_dashboard_object.data_count}")

        elif nd_alert_type == "congestion":
            index = input_info.get("index", "main")
            nd_hosts = ac_creds.get("nd_hostname").split(",")

            for i in range(len(nd_hosts)):
                nd_hosts[i] = nd_hosts[i].strip()

            ORIGINAL_HOSTS = nd_hosts
            login_flag = True

            try:
                nd_api_call_count = consts.ND_API_CALL_COUNT
                if not isinstance(nd_api_call_count, int) or nd_api_call_count <= 0:
                    logger.error(
                        "Nexus Dashboard Error: ND API CALL COUNT should be an integer greater than zero. "
                        "Please change the value first and then enable the input. "
                    )
                    return
            except Exception as e:
                logger.error(
                    f"Nexus Dashboard Error: Error occurred while fetching value of ND API CALL COUNT from consts.py. Exception: {str(e)}."
                )

            try:
                timeout = consts.TIMEOUT
                if timeout <= 0:
                    logger.error(
                        "Nexus Dashboard Error: Timeout should be greater than zero. "
                        "Please change the value first and then enable the input. "
                    )
                    return
            except Exception as e:
                logger.error(
                    f"Nexus Dashboard Error: Error occurred while fetching timeout from consts.py. Exception: {str(e)}."
                )

            current_time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
            current_time = datetime.strptime(current_time_str, "%Y-%m-%d %H:%M:%S.%f")

            for nd_host in nd_hosts:
                logger.info(f"Initializing NexusDashboardParameters for host: {nd_host}")
                nexus_dashboard_object = NexusDashboardParameters(
                    nd_api_call_count,
                    ew,
                    acc,
                    nd_host,
                    timeout,
                    get_sslconfig(session_key),
                    ORIGINAL_HOSTS,
                    [],
                    input_info,
                    ac_creds,
                    index,
                    input_info["name"],
                    session_key,
                    logger,
                    acc
                )
                token = nexus_dashboard_object.login()
                if token:
                    logger.info(f"Login successful for host: {nd_host}")
                    login_flag = False
                    try:
                        node_names = input_info["nd_node_name"]
                        node_names_list = node_names.split(",")

                        interface_names = input_info["nd_interface_name"]
                        interface_names_list = interface_names.split(",")
                        scope = input_info.get("nd_scope", None)

                        nexus_dashboard_object.ingest_data_in_splunk_threading(
                            node_names_list,
                            current_time,
                            interface_names_list,
                            scope,
                        )
                    except Exception as e:
                        logger.error(
                            f"Nexus Dashboard Error: An Error Occured while fetching {input_info['nd_alert_type']} details for "
                            f"Host: {nd_host}. Error: {e}"
                        )
                    break

            if len(nd_hosts) > 1 and login_flag and nd_hosts[-1] == nd_host:
                logger.error(f"Nexus Dashboard Error: Not able to login in any of the cluster instance: {nd_hosts}")

            logger.info(f"Total no. of events in API Response: {nexus_dashboard_object.data_count_API}")
            logger.info(f"Total no. of collected events is: {nexus_dashboard_object.data_count}")

        elif nd_alert_type == "protocols":
            index = input_info.get("index", "main")
            nd_hosts = ac_creds.get("nd_hostname").split(",")

            for i in range(len(nd_hosts)):
                nd_hosts[i] = nd_hosts[i].strip()

            ORIGINAL_HOSTS = nd_hosts
            login_flag = True

            try:
                nd_api_call_count = consts.ND_API_CALL_COUNT
                if not isinstance(nd_api_call_count, int) or nd_api_call_count <= 0:
                    logger.error(
                        "Nexus Dashboard Error: ND API CALL COUNT should be an integer greater than zero. "
                        "Please change the value first and then enable the input. "
                    )
                    return
            except Exception as e:
                logger.error(
                    f"Nexus Dashboard Error: Error occurred while fetching value of ND API CALL COUNT from consts.py. Exception: {str(e)}."
                )

            try:
                timeout = consts.TIMEOUT
                if timeout <= 0:
                    logger.error(
                        "Nexus Dashboard Error: Timeout should be greater than zero. "
                        "Please change the value first and then enable the input. "
                    )
                    return
            except Exception as e:
                logger.error(
                    f"Nexus Dashboard Error: Error occurred while fetching timeout from consts.py. Exception: {str(e)}."
                )

            current_time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
            current_time = datetime.strptime(current_time_str, "%Y-%m-%d %H:%M:%S.%f")

            for nd_host in nd_hosts:
                logger.info(f"Initializing NexusDashboardParameters for host: {nd_host}")
                nexus_dashboard_object = NexusDashboardParameters(
                    nd_api_call_count,
                    ew,
                    acc,
                    nd_host,
                    timeout,
                    get_sslconfig(session_key),
                    ORIGINAL_HOSTS,
                    [],
                    input_info,
                    ac_creds,
                    index,
                    input_info["name"],
                    session_key,
                    logger,
                    acc
                )
                token = nexus_dashboard_object.login()
                if token:
                    logger.info(f"Login successful for host: {nd_host}")
                    login_flag = False
                    try:
                        nexus_dashboard_object.nd_get_interface_all(current_time)
                    except Exception as e:
                        logger.error(
                            f"Nexus Dashboard Error: An Error Occured while fetching {input_info['nd_alert_type']} details for "
                            f"Host: {nd_host}. Error: {e}"
                        )
                    break

            if len(nd_hosts) > 1 and login_flag and nd_hosts[-1] == nd_host:
                logger.error(f"Nexus Dashboard Error: Not able to login in any of the cluster instance: {nd_hosts}")

            logger.info(f"Total no. of events in API Response: {nexus_dashboard_object.data_count_API}")
            logger.info(f"Total no. of collected events is: {nexus_dashboard_object.data_count}")

        elif nd_alert_type == "flows":
            index = input_info.get("index", "main")
            nd_hosts = ac_creds.get("nd_hostname").split(",")

            for i in range(len(nd_hosts)):
                nd_hosts[i] = nd_hosts[i].strip()

            ORIGINAL_HOSTS = nd_hosts
            login_flag = True

            try:
                nd_api_call_count = consts.ND_API_CALL_COUNT
                if not isinstance(nd_api_call_count, int) or nd_api_call_count <= 0:
                    logger.error(
                        "Nexus Dashboard Error: ND API CALL COUNT should be an integer greater than zero. "
                        "Please change the value first and then enable the input. "
                    )
                    return
            except Exception as e:
                logger.error(
                    f"Nexus Dashboard Error: Error occurred while fetching value of ND API CALL COUNT from consts.py. Exception: {str(e)}."
                )

            try:
                timeout = consts.TIMEOUT
                if timeout <= 0:
                    logger.error(
                        "Nexus Dashboard Error: Timeout should be greater than zero. "
                        "Please change the value first and then enable the input. "
                    )
                    return
            except Exception as e:
                logger.error(
                    f"Nexus Dashboard Error: Error occurred while fetching timeout from consts.py. Exception: {str(e)}."
                )

            current_time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
            current_time = datetime.strptime(current_time_str, "%Y-%m-%d %H:%M:%S.%f")

            for nd_host in nd_hosts:
                logger.info(f"Initializing NexusDashboardParameters for host: {nd_host}")
                nexus_dashboard_object = NexusDashboardParameters(
                    nd_api_call_count,
                    ew,
                    acc,
                    nd_host,
                    timeout,
                    get_sslconfig(session_key),
                    ORIGINAL_HOSTS,
                    [],
                    input_info,
                    ac_creds,
                    index,
                    input_info["name"],
                    session_key,
                    logger,
                    acc
                )
                token = nexus_dashboard_object.login()
                if token:
                    logger.info(f"Login successful for host: {nd_host}")
                    login_flag = False
                    try:
                        nexus_dashboard_object.get_flows(current_time)
                    except Exception as e:
                        logger.error(
                            f"Nexus Dashboard Error: An Error Occured while fetching {input_info['nd_alert_type']} details for "
                            f"Host: {nd_host}. Error: {e}"
                        )
                    break

            if len(nd_hosts) > 1 and login_flag and nd_hosts[-1] == nd_host:
                logger.error(f"Nexus Dashboard Error: Not able to login in any of the cluster instance: {nd_hosts}")

            logger.info(f"Total no. of events in API Response: {nexus_dashboard_object.data_count_API}")
            logger.info(f"Total no. of collected events is: {nexus_dashboard_object.data_count}")

        elif nd_alert_type == "fabrics" or nd_alert_type == "switches":
            # sourcetype_custom = input_info.get("custom_sourcetype")
            # sourcetype_custom = sourcetype_custom.strip()

            source_type = "cisco:dc:nd:" + nd_alert_type
            ingestion_key = nd_alert_type
            index = input_info.get("index", "main")

            nd_hosts = ac_creds.get("nd_hostname").split(",")

            for _host in range(len(nd_hosts)):
                nd_hosts[_host] = nd_hosts[_host].strip()

            ORIGINAL_HOSTS = nd_hosts
            nd_api_call_count = consts.ND_API_CALL_COUNT
            login_flag = True

            for nd_host in nd_hosts:
                logger.info(
                    f"Initializing NexusDashboardParameters (fabrics/switches) for host: {nd_host}"
                )
                nexus_dashboard_object = NexusDashboardParameters(
                    nd_api_call_count,
                    ew,
                    acc,
                    nd_host,
                    consts.TIMEOUT,
                    get_sslconfig(session_key),
                    ORIGINAL_HOSTS,
                    [],
                    input_info,
                    ac_creds,
                    index,
                    input_info["name"],
                    session_key,
                    logger,
                    acc
                )
                token = nexus_dashboard_object.login()
                if token:
                    logger.info(f"Login successful for host: {nd_host}")
                    login_flag = False
                    count_of_entries = 0
                    try:
                        target_url = nexus_dashboard_object.get_url(nd_alert_type)
                        logger.debug(f"Target URL: {target_url}")
                        rsp = nexus_dashboard_object.get(target_url)
                        if ingestion_key and ingestion_key.strip():
                            custom_nd_data = rsp.get(ingestion_key)
                        else:
                            custom_nd_data = rsp.get('entries')
                        if custom_nd_data:
                            for data in custom_nd_data:
                                data["nd_host"] = nexus_dashboard_object.nd_host
                                event = smi.Event(data=json.dumps(data), index=index, sourcetype=source_type, unbroken=True)
                                ew.write_event(event)
                                count_of_entries = count_of_entries + 1
                    except Exception as e:
                        logger.error(
                            f"Nexus Dashboard Error: An Error Occured while fetching {nd_alert_type} details for "
                            f"Host: {nd_host}. Error: {e}"
                        )
                    logger.info("No. of events ingested: {}".format(count_of_entries))
                    break

            if len(nd_hosts) > 1 and login_flag and nd_hosts[-1] == nd_host:
                logger.error(
                    f"Nexus Dashboard Error: Not able to login in any of the cluster instance: {nd_hosts}"
                )

        elif nd_alert_type == "custom":
            custom_endpoint = input_info.get("custom_endpoint")
            additional_filters = input_info.get("nd_additional_parameters")
            sourcetype_custom = input_info.get("custom_sourcetype")
            sourcetype_custom = sourcetype_custom.strip()
            ingestion_key = input_info.get("custom_resp_key")
            index = input_info.get("index", "main")

            if custom_endpoint and custom_endpoint.strip():
                custom_endpoint = custom_endpoint.strip()
                custom_endpoint = custom_endpoint.strip('/')

            nd_hosts = ac_creds.get("nd_hostname").split(",")

            for _host in range(len(nd_hosts)):
                nd_hosts[_host] = nd_hosts[_host].strip()

            ORIGINAL_HOSTS = nd_hosts
            nd_api_call_count = consts.ND_API_CALL_COUNT
            login_flag = True

            for nd_host in nd_hosts:
                logger.info(
                    f"Initializing NexusDashboardParameters for host: {nd_host}"
                )
                nexus_dashboard_object = NexusDashboardParameters(
                    nd_api_call_count,
                    ew,
                    acc,
                    nd_host,
                    consts.TIMEOUT,
                    get_sslconfig(session_key),
                    ORIGINAL_HOSTS,
                    [],
                    input_info,
                    ac_creds,
                    index,
                    input_info["name"],
                    session_key,
                    logger,
                    acc
                )
                token = nexus_dashboard_object.login()
                if token:
                    logger.info(f"Login successful for host: {nd_host}")
                    login_flag = False
                    count_of_entries = 0
                    try:
                        if additional_filters and additional_filters.strip():
                            additional_filters = additional_filters.strip(" ?&")
                            custom_endpoint = custom_endpoint + "?{}".format(additional_filters)
                        logger.debug(f"Target URL: {custom_endpoint}")
                        rsp = nexus_dashboard_object.get(custom_endpoint)
                        if ingestion_key and ingestion_key.strip():
                            custom_nd_data = rsp.get(ingestion_key)
                        else:
                            custom_nd_data = rsp.get('entries')
                        if custom_nd_data:
                            for data in custom_nd_data:
                                event = smi.Event(data=json.dumps(data), index=index, sourcetype=sourcetype_custom, unbroken=True)
                                ew.write_event(event)
                                count_of_entries = count_of_entries + 1
                    except Exception as e:
                        logger.error(
                            f"Nexus Dashboard Error: An Error Occured while fetching {input_info['nd_alert_type']} details for "
                            f"Host: {nd_host}. Error: {e}"
                        )
                    logger.info("No. of events ingested: {}".format(count_of_entries))
                    break

            if len(nd_hosts) > 1 and login_flag and nd_hosts[-1] == nd_host:
                logger.error(
                    f"Nexus Dashboard Error: Not able to login in any of the cluster instance: {nd_hosts}"
                )

        else:
            index = input_info.get("index", "main")
            nd_hosts = ac_creds.get("nd_hostname").split(",")

            for _host in range(len(nd_hosts)):
                nd_hosts[_host] = nd_hosts[_host].strip()

            ORIGINAL_HOSTS = nd_hosts
            login_flag = True

            try:
                nd_api_call_count = consts.ND_API_CALL_COUNT
                if not isinstance(nd_api_call_count, int) or nd_api_call_count <= 0:
                    logger.error(
                        "Nexus Dashboard Error: ND API CALL COUNT should be an integer greater than zero. "
                        "Please change the value first and then enable the script. "
                    )
                    return
            except Exception as e:
                logger.error(
                    f"Nexus Dashboard Error: Error occurred while fetching value of ND API CALL COUNT from consts.py. Exception: {str(e)}."
                )

            try:
                timeout = consts.TIMEOUT
                if timeout <= 0:
                    logger.error(
                        "Nexus Dashboard Error: Timeout should be greater than zero. "
                        "Please change the value first and then enable the script. "
                    )
                    return
            except Exception as e:
                logger.error(
                    f"Nexus Dashboard Error: Error occurred while fetching timeout from consts.py Exception: {str(e)}."
                )

            hrs_configured = int(input_info.get("nd_time_range"))
            current_time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
            current_time = datetime.strptime(current_time_str, "%Y-%m-%d %H:%M:%S.%f")
            startTs_from_hrs_configured = current_time - timedelta(hours=hrs_configured)
            for nd_host in nd_hosts:
                logger.info(
                    f"Initializing NexusDashboardParameters for host: {nd_host}"
                )
                nexus_dashboard_object = NexusDashboardParameters(
                    nd_api_call_count,
                    ew,
                    acc,
                    nd_host,
                    timeout,
                    get_sslconfig(session_key),
                    ORIGINAL_HOSTS,
                    [],
                    input_info,
                    ac_creds,
                    index,
                    input_info["name"],
                    session_key,
                    logger,
                    acc
                )
                token = nexus_dashboard_object.login()
                if token:
                    logger.info(f"Login successful for host: {nd_host}")
                    insights_group_fabrics_dict = (
                        nexus_dashboard_object.get_fabric_details()
                    )
                    login_flag = False
                    try:
                        if insights_group_fabrics_dict:
                            for group in insights_group_fabrics_dict:
                                fabric_list = insights_group_fabrics_dict[group]
                                if not fabric_list:
                                    logger.info(
                                        f"Nexus Dashboard Info: Host: {nd_host}."
                                    )
                                    logger.warning(f"Nexus Dashboard Warning: No Fabric Name found for Host: {nd_host}.")
                                    nexus_dashboard_object.get_endpoint_details_without_fabric(
                                        startTs_from_hrs_configured,
                                        current_time,
                                    )
                                else:
                                    logger.info(
                                        f"Nexus Dashboard Info: Insights Group: {group} Number of Fabric/s: {len(fabric_list)} "
                                        f"List of Fabric/s: {fabric_list} for Host: {nd_host}."
                                    )
                                    nexus_dashboard_object.get_endpoint_details(
                                        fabric_list,
                                        group,
                                        startTs_from_hrs_configured,
                                        current_time,
                                    )
                        else:
                            logger.warning(f"Nexus Dashboard Warning: No Insights Group found for Host: {nd_host}.")
                            nexus_dashboard_object.get_endpoint_details_without_fabric(
                                startTs_from_hrs_configured,
                                current_time,
                            )
                    except Exception as e:
                        logger.error(
                            f"Nexus Dashboard Error: An Error Occured while fetching {input_info['nd_alert_type']} details for "
                            f"Host: {nd_host}. Error: {str(e)}"
                        )
                    break

            if len(nd_hosts) > 1 and login_flag and nd_hosts[-1] == nd_host:
                logger.error(
                    f"Nexus Dashboard Error: Not able to login in any of the cluster instance: {nd_hosts}"
                )

            logger.info(
                f"Total no. of events in API Response: {nexus_dashboard_object.data_count_API}"
            )
            logger.info(
                f"Total no. of collected events is: {nexus_dashboard_object.data_count}"
            )
        logger.info(f"Completed data collection for the {acc} account and {input_name_for_log} input.")


    def stream_events(self, inputs: smi.InputDefinition, ew: smi.EventWriter):
        input_items = [{"count": len(inputs.inputs)}]
        for input_name, input_item in inputs.inputs.items():
            input_item["name"] = input_name
            input_items.append(input_item)

        input_name = input_items[1]["name"]
        meta_configs = self._input_definition.metadata
        session_key = meta_configs.get("session_key")
        input_name_for_log = input_name.split("//")[1]
        logger = log.get_logger(f"cisco_dc_nd_{input_name_for_log}")

        try:
            script_start_time = time.time()
            validation_success = nd_input_validator(input_items[1], logger)
            if not validation_success:
                return
            logger.info(f"Starting data collection for input: {input_name}.")
            nd_accounts = input_items[1]["nd_account"].split(",")
            with concurrent.futures.ThreadPoolExecutor(max_workers=consts.MAX_THREADS_MULTI_ACC) as executor:
                futures = []
                for account_name in nd_accounts:
                    future = executor.submit(self.fetch_nd_data, input_items[1], account_name, session_key, smi, ew, logger, input_name_for_log)
                    futures.append(future)
                for future in futures:
                    future.result()
            logger.info(
                f"Execution of the script is finished for input: {input_name}. Time taken: {(time.time() - script_start_time) / 60} minutes."
            )
        except Exception as err:
            logger.error("Error occured while starting data collection. Error: {}".format(str(err)))


if __name__ == "__main__":
    exit_code = CISCO_ND().run(sys.argv)
    sys.exit(exit_code)
