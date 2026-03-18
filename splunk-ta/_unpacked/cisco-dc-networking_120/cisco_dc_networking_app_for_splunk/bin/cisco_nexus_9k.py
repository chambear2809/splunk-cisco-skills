import import_declare_test

from splunklib import modularinput as smi

import json
import sys
import time
import traceback
import concurrent.futures
from datetime import datetime
import requests
import threading

from cisco_dc_input_validators import nexus9k_input_validator
import common.consts as consts
import common.log as log
import common.proxy as proxy
import common.utils as utils
from nexus_9K_helper import validate_input
from nexus_9k_utils import exceptions
from nexus_9k_utils.nxapi_utils import NXAPITransport


class CISCO_NEXUS_9K(smi.Script):
    def __init__(self):
        super(CISCO_NEXUS_9K, self).__init__()

    def get_scheme(self):
        scheme = smi.Scheme("cisco_nexus_9k")
        scheme.description = "Nexus 9K"
        scheme.use_external_validation = True
        scheme.streaming_mode_xml = True
        scheme.use_single_instance = False

        scheme.add_argument(
            smi.Argument(
                "name", title="Name", description="Name", required_on_create=True
            )
        )
        scheme.add_argument(
            smi.Argument(
                "nexus_9k_account",
                required_on_create=True,
            )
        )
        scheme.add_argument(
            smi.Argument(
                "nexus_9k_input_type",
                required_on_create=True,
            )
        )
        scheme.add_argument(
            smi.Argument(
                "nexus_9k_dme_query_type",
                required_on_create=False,
            )
        )
        scheme.add_argument(
            smi.Argument(
                "nexus_9k_cmd",
                required_on_create=False,
            )
        )
        scheme.add_argument(
            smi.Argument(
                "nexus_9k_component",
                required_on_create=False,
            )
        )
        scheme.add_argument(
            smi.Argument(
                "nexus_9k_class_names",
                required_on_create=False,
            )
        )
        scheme.add_argument(
            smi.Argument(
                "nexus_9k_distinguished_names",
                required_on_create=False,
            )
        )
        scheme.add_argument(
            smi.Argument(
                "nexus_9k_additional_parameters",
                required_on_create=False,
            )
        )
        return scheme

    def validate_input(self, definition: smi.ValidationDefinition):
        return validate_input(definition)

    def fetch_n9k_data(self, input_info, acc, session_key, smi, ew, logger):
        logger.info(f"Starting data collection for account {acc}.")
        thread_name = threading.current_thread().name
        logger.debug(
            f"ThreadPoolExecutor thread '{thread_name}' is associated with account: '{acc}'. "
            f"Check logs with thread name '{thread_name}' to debug issues related to '{acc}' account."
        )
        self.event_writer = ew
        nexus_9k_input_type = input_info.get("nexus_9k_input_type")
        account_info = utils.get_credentials(
            session_key=session_key,
            account_type="nexus_9k_account",
            account_name=acc,
        )
        device_ip = account_info.get("nexus_9k_device_ip")
        device_port = account_info.get("nexus_9k_port", 443)
        username = account_info.get("nexus_9k_username")
        password = account_info.get("nexus_9k_password")
        self.index = input_info.get("index")
        proxies = proxy.get_proxies(account_info)
        if proxies:
            logger.info("Proxy is enabled.")
        else:
            logger.info("Proxy is disabled.")

        if nexus_9k_input_type == "nexus_9k_cli":
            nexus_9k_cmd = input_info.get("nexus_9k_cmd")
            nexus_9k_component = input_info.get("nexus_9k_component")

            device_val = f"{device_ip}:{device_port}"

            target_url = f"https://{str(device_ip)}:{str(device_port)}/ins"

            try:
                nxapi_class = NXAPITransport(
                    target_url=target_url,
                    username=username,
                    password=password,
                    timeout=consts.TIMEOUT,
                    verify=utils.get_sslconfig(session_key),
                    proxies=proxies,
                )
            except Exception as e:
                logger.error(
                    f"Nexus Error: Not able to connect to NXAPI: DEVICE IP: {str(target_url)}, Error: {str(e)}"
                )
                logger.error(traceback.format_exc())

            nexus_9k_cmd = input_info.get("nexus_9k_cmd")
            if nexus_9k_cmd == "*":
                commands = consts.COMMAND_TO_COMPONENT_MAPPING.keys()
            else:
                commands = nexus_9k_cmd.split("|")

            for nexus_9k_cmd in commands:
                try:
                    response = self._collect_data(nxapi_class, nexus_9k_cmd, target_url, logger)

                    if response:
                        response_json = json.loads(response)

                    events_collected = 0

                    if response_json is not None:
                        data_keys = list(response_json.keys())
                        row_key_val = []
                        for i in range(len(data_keys)):
                            if "TABLE" not in data_keys[i]:
                                check_type = response_json[data_keys[i]]
                                if type(check_type) is dict:
                                    internal_single_row = response_json[
                                        data_keys[i]
                                    ]  # single_row  has inside raw data in k:v pair
                                    events_collected += (
                                        self._collect_internal_keys_info(
                                            internal_single_row,
                                            device_val,
                                            nexus_9k_component,
                                            logger,
                                        )
                                    )
                                else:
                                    value = response_json[data_keys[i]]
                                    key_value = {data_keys[i]: value}
                                    row_key_val.append(key_value)
                        if row_key_val:
                            events_collected += self._display_data(
                                device_val, nexus_9k_component, row_key_val, logger
                            )
                        table_names = []
                        row_names = []

                        events_collected += self._collect_table_info(
                            data_keys,
                            table_names,
                            row_names,
                            nexus_9k_component,
                            response_json,
                            device_val,
                            logger,
                        )

                    logger.info(
                        f'Collected total={events_collected} events for device {device_val} for command "{nexus_9k_cmd}" and component "{nexus_9k_component}".'  # noqa: E501
                    )
                except Exception as e:
                    logger.error(
                        f'Following error occured while collecting data for command="{nexus_9k_cmd}" | {str(e)}'
                    )
                    logger.error(traceback.format_exc())
        else:
            try:
                nexus_9k_class_names = input_info.get("nexus_9k_class_names")
                nexus_9k_distinguished_names = input_info.get(
                    "nexus_9k_distinguished_names"
                )
                nexus_9k_additional_parameters = input_info.get("nexus_9k_additional_parameters")
                if nexus_9k_additional_parameters and nexus_9k_additional_parameters.strip():
                    nexus_9k_additional_parameters = nexus_9k_additional_parameters.strip(' ?&')
                else:
                    nexus_9k_additional_parameters = None
                nexus_9k_dme_query_type = input_info.get("nexus_9k_dme_query_type")
                device = f"{device_ip}:{device_port}"
                sourcetype = "cisco:dc:nexus9k:dme"
                login_url = f"https://{device_ip}:{device_port}/api/aaaLogin.json"

                logger.debug(f"Login URL: {login_url}")

                payload = json.dumps(
                    {"aaaUser": {"attributes": {"name": username, "pwd": password}}}
                )
                response = requests.post(
                    url=login_url, data=payload, verify=utils.get_sslconfig(session_key)
                )

                if response.ok:
                    logger.info(
                        f"Login Successful: Host: {device_ip}, Username: {username}"
                    )
                else:
                    logger.error(
                        f"Could not login to Nexus 9K: Host: {device_ip}, Username: {username}"
                    )
                    return

                try:
                    final_response = response.json()
                    class_token_data = final_response.get("imdata", [{}])[0].get("aaaLogin", {}).get("attributes", {})
                    class_token = class_token_data.get("token")
                    header = {"Cookie": f"APIC-cookie={class_token}"}
                except Exception as e:
                    logger.error(f"Error while getting token: {str(e)}")
                    logger.error(traceback.format_exc())
                    return

                query_key = (
                    "nexus_9k_class"
                    if nexus_9k_dme_query_type == "nexus_9k_class"
                    else "nexus_9k_distinguished_names"
                )
                message_prefix = (
                    "Class Name"
                    if nexus_9k_dme_query_type == "nexus_9k_class"
                    else "Distinguished Name"
                )
                query_list = (
                    nexus_9k_class_names.split()
                    if query_key == "nexus_9k_class"
                    else nexus_9k_distinguished_names.split()
                )

                for query_item in query_list:
                    query_item = query_item.strip('/')
                    target_url = f"https://{device_ip}:{device_port}/api/{'class' if query_key == 'nexus_9k_class' else 'mo'}/{query_item}.json"

                    if nexus_9k_additional_parameters:
                        logger.debug(f"Target URL: {target_url}?{nexus_9k_additional_parameters}")
                    else:
                        logger.debug(f"Target URL: {target_url}")
                    logger.info(
                        f"Starting to collect data for device: {device} and {message_prefix}: {query_item}"
                    )

                    try:
                        response = requests.get(
                            url=target_url,
                            headers=header,
                            params=nexus_9k_additional_parameters,
                            verify=utils.get_sslconfig(session_key),
                            timeout=consts.TIMEOUT,
                            proxies=proxies,
                        )
                        response.raise_for_status()
                    except Exception as e:
                        logger.error(
                            f"Nexus Error: Not able to connect to DME: Device IP: {device_ip}, {message_prefix}: {query_item}, Error: {str(e)},"
                        )
                        logger.error(traceback.format_exc())
                        continue

                    current_time = datetime.now().strftime(consts.TIMESTAMP_FORMAT)
                    final_response = response.json()
                    events_count = 0
                    for payload_data in final_response.get("imdata", []):
                        for key, value in payload_data.items():
                            final_payload_data = value.get("attributes", {})
                            nexus_9k_final_data_component = key

                        if nexus_9k_final_data_component == "error":
                            logger.error(
                                f"Nexus Error: Class is invalid, Device IP: {device_ip}, {message_prefix}: {query_item}"
                            )
                            continue

                        final_data = {
                            "timestamp": current_time,
                            "component": nexus_9k_final_data_component,
                            "device": device,
                            "Row_info": final_payload_data,
                        }
                        self.write_event(
                            json.dumps(final_data, ensure_ascii=False),
                            logger,
                            sourcetype,
                        )
                        events_count += 1

                    logger.info(
                        f"Collected total={events_count} events for device {device} and {message_prefix}: {query_item}."
                    )

            except requests.exceptions.RequestException as e:
                logger.error(f"Network error occurred: {str(e)}")
            except KeyError as e:
                logger.error(f"Key error occurred: {str(e)}")
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error occurred: {str(e)}")
            except Exception as e:
                logger.error(f"An unexpected error occurred: {str(e)}")

    def stream_events(self, inputs: smi.InputDefinition, ew: smi.EventWriter):
        try:  
            input_items = [{"count": len(inputs.inputs)}]
            meta_configs = self._input_definition.metadata
            session_key = meta_configs["session_key"]
            for input_name, input_item in inputs.inputs.items():
                input_item["stanza_name"] = input_name
            input_item["name"] = input_name.split("://")[1]
            input_item["session_key"] = session_key
            input_items.append(input_item)

            logger = log.get_logger(f"cisco_dc_n9k_{input_item['name']}")
            validation_success = nexus9k_input_validator(input_items[1], logger)
            if not validation_success:
                return

            account_names = input_items[1]["nexus_9k_account"].split(",")
            with concurrent.futures.ThreadPoolExecutor(max_workers=consts.MAX_THREADS_MULTI_ACC) as executor:
                futures = []
                for account_name in account_names:
                    future = executor.submit(self.fetch_n9k_data, input_items[1], account_name, session_key, smi, ew, logger)
                    futures.append(future)
                for future in futures:
                    future.result()
            logger.info("Data collection completed.")
        except Exception as e:
            logger.error(f"An error occured while collecting data. Error: {str(e)}")
 

    def _collect_table_info(
        self,
        data_keys,
        table_names,
        row_names,
        component,
        cmd_json,
        device,
        logger,
    ):
        events_collected = 0
        for table in data_keys:
            if "TABLE" in table:
                table_names.append(table)
                row = table.replace("TABLE", "ROW")
                row_names.append(row)

        for i in range(len(table_names)):
            events_collected += self._split_json(
                device, component, cmd_json, table_names[i], row_names[i], logger
            )

        return events_collected

    def _collect_internal_keys_info(
        self,
        internal_single_row,
        device,
        component,
        logger,
    ):
        events_collected = 0
        internal_data_keys = list(internal_single_row.keys())
        internal_table_names = []
        internal_row_names = []
        for table in internal_data_keys:
            if "TABLE" not in table:
                internal_value = internal_single_row[table]
                if type(internal_value) is dict:
                    current_time = datetime.now().strftime(consts.TIMESTAMP_FORMAT)
                    response = {
                        "timestamp": current_time,
                        "component": component,
                        "device": device,
                        "Row_info": internal_single_row[table],
                    }
                    sourcetype = "cisco:dc:nexus9k"
                    self.write_event(
                        json.dumps(response, ensure_ascii=False), logger, sourcetype
                    )
                    events_collected += 1
                else:
                    current_time = datetime.now().strftime(consts.TIMESTAMP_FORMAT)
                    internal_key_value = {table: internal_value}
                    response = {
                        "timestamp": current_time,
                        "component": component,
                        "device": device,
                        "Row_info": internal_key_value,
                    }
                    sourcetype = "cisco:dc:nexus9k"
                    self.write_event(
                        json.dumps(response, ensure_ascii=False), logger, sourcetype
                    )
                    events_collected += 1

            if "TABLE" in table:
                internal_table_names.append(table)
                row = table.replace("TABLE", "ROW")
                internal_row_names.append(row)

        for i in range(len(internal_table_names)):
            events_collected += self._split_json(
                device,
                component,
                internal_single_row,
                internal_table_names[i],
                internal_row_names[i],
                logger,
            )

        return events_collected

    def _display_data(
        self,
        device,
        component,
        json_element,
        logger,
    ):
        events_collected = 0
        json_row = json.dumps(json_element, ensure_ascii=False)
        row_string = json.loads(json_row)
        if type(row_string) is dict:
            for key, value in list(row_string.items()):
                if (
                    value is not None
                    and type(value) not in [list, tuple, dict]
                    and value.startswith('"')
                    and value.endswith('"')
                ):
                    value = value[1:-1]
                    row_string[key] = value
        current_time = datetime.now().strftime(consts.TIMESTAMP_FORMAT)
        response = {
            "timestamp": current_time,
            "component": component,
            "device": device,
            "Row_info": row_string,
        }
        sourcetype = "cisco:dc:nexus9k"
        self.write_event(json.dumps(response, ensure_ascii=False), logger, sourcetype)
        events_collected += 1
        return events_collected

    def _split_json(
        self,
        device,
        component,
        json_data,
        table_name,
        row_name,
        logger,
    ):
        events_collected = 0
        if table_name in json_data:
            single_row = json_data[table_name][row_name]
            if type(single_row) is list:
                for element in single_row:
                    events_collected += self._display_data(
                        device, component, element, logger
                    )
            elif type(single_row) is dict:
                events_collected += self._display_data(
                    device, component, single_row, logger
                )
        return events_collected

    def _collect_data(
        self,
        nxapiclass,
        command,
        target_url,
        logger,
    ):
        try:
            logger.info(
                f'Starting to collect data for device {target_url} for command "{command}".'
            )
            cmd_out = nxapiclass.clid(command)
        except Exception as e:
            logger.error(
                f"Nexus Error: Not able to Execute command through NXAPI: DEVICE IP: {str(target_url)}, Error: {str(e)}"
            )
            raise exceptions.Nexus9kError(
                f"Nexus Error: Not able to Execute command through NXAPI: DEVICE IP: {str(target_url)}, Error: {str(e)}"
            )

        return cmd_out

    def write_event(
        self,
        event: dict,
        logger,
        sourcetype: str,
    ) -> None:
        event_time = time.time()
        event = smi.Event(
            data=event,
            time=event_time,
            index=self.index,
            sourcetype=sourcetype,
            unbroken=True,
        )
        self.event_writer.write_event(event)


if __name__ == "__main__":
    exit_code = CISCO_NEXUS_9K().run(sys.argv)
    sys.exit(exit_code)
