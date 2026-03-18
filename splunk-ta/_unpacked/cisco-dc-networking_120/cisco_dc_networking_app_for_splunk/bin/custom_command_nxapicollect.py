import json
import sys
import time
import traceback
from datetime import datetime
from common.utils import get_sslconfig

import common.log as log
from common.utils import read_conf_file
import common.proxy as proxy
from splunklib.searchcommands import dispatch, GeneratingCommand, Configuration, Option
from nexus_9k_utils.nxapi_utils import NXAPITransport

logger = log.get_logger("cisco_dc_n9k_nxapicollect")


@Configuration(local=True, retainsevents=True)
class nxapiCommand(GeneratingCommand):
    """
    A Splunk custom search command for executing NXAPI commands on Cisco Nexus devices.

    This class extends Splunk's GeneratingCommand to provide functionality for
    executing NXAPI commands, processing the results, and generating events
    for Splunk indexing.
    """

    account = Option(require=True)
    command = Option(require=True)

    def generate(self):
        """
        Generate events for Splunk indexing.

        This method is the entry point for the custom search command. It
        collects the session key and account details, executes the NXAPI
        command, and generates events for Splunk indexing.
        """
        session_key = self.service.token

        try:
            # Get account details, if fails log and exit
            self.account_info = read_conf_file(
                session_key, "cisco_dc_networking_app_for_splunk_nexus_9k_account", stanza=self.account
            )
        except Exception as e:
            logger.error(f"Following error occured while reading account details. Error={str(e)}")
            self.write_error(
                f"The account {self.account} is not configured in the app. Please provide a configured account."
            )

        try:
            self.events = []
            # Get session key
            logger.info("Splunk session key collected")

            self.execute_command(session_key)
            for event in self.events:
                yield {"_time": time.time(), "_raw": event}
        except Exception as e:
            logger.error(f"Following error occured while running custom command. Error={str(e)}")

    def execute_command(self, session_key):
        """
        Execute the given NXAPI command on the device.

        This method takes the given NXAPI command and executes it on the device.
        It also handles any exceptions that may occur.
        """
        device_ip = self.account_info.get("nexus_9k_device_ip")
        device_port = self.account_info.get("nexus_9k_port", 443)
        username = self.account_info.get("nexus_9k_username")
        password = self.account_info.get("nexus_9k_password")
        self.proxies = proxy.get_proxies(self.account_info)
        target_url = f"https://{str(device_ip)}:{str(device_port)}/ins"

        try:
            nxapi_class = NXAPITransport(
                target_url=target_url,
                username=username,
                password=password,
                timeout=600,
                proxies=self.proxies,
                verify=get_sslconfig(session_key),
            )
        except Exception as e:
            logger.error(f"Nexus Error: Not able to connect to NXAPI: {str(e)} DEVICE IP: {device_ip}:{device_port}")

        try:
            device_name = f"{device_ip}:{device_port}"
            self._execute_command(nxapi_class, command=self.command, device=f"{device_name}")
            logger.info(f"Successfully executed {self.command} cli on switch {device_name}")
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(str(e))
            self.write_error(str(e))

    def _execute_command(self, nxapi_class, command, device, component="N/A"):
        """
        Execute the given NXAPI command on the device.

        This method takes the given NXAPI command and executes it on the device.
        It also handles any exceptions that may occur.
        """
        try:
            cmd_out = nxapi_class.clid(command)
        except Exception as e:
            raise Exception(f"Nexus Error: Unable to execute command through NXAPI: {str(e)} : DEVICE IP: {device}")

        try:
            cmd_json = json.loads(cmd_out)
        except json.JSONDecodeError as e:
            raise Exception(f"Failed to decode JSON output: Error: {str(e)}")

        if cmd_json is not None:
            self._process_keys(device, component, cmd_json)

    def _process_keys(self, device, component, cmd_json):
        """
        Process the keys in the given JSON output.

        This method takes the given JSON output and processes the keys in it.
        It looks for keys that are not tables and processes them. It also looks
        for tables and processes them.
        """
        data_keys = list(cmd_json.keys())
        row_key_values = []

        for key in data_keys:
            if "TABLE" not in key:
                value = cmd_json[key]
                if isinstance(value, dict):
                    self._process_row_data(device, component, value)
                else:
                    row_key_values.append({key: value})

        if row_key_values:
            self._display_data(device, component, row_key_values)

        self._process_tables(device, component, cmd_json, data_keys)

    def _process_row_data(self, device, component, row_data):
        """
        Process the row data in the given JSON output.

        This method takes the given JSON output and processes the row data in it.
        It looks for keys that are not tables and processes them.
        It looks for tables and processes them.
        """
        for key, value in row_data.items():
            if "TABLE" not in key:
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S%z")
                response = {
                    "timestamp": current_time,
                    "component": component,
                    "device": device,
                    "Row_info": {key: value} if not isinstance(value, dict) else value,
                }
                self.events.append(response)
            else:
                internal_table = key
                internal_row = key.replace("TABLE", "ROW")
                self._split_json(device, component, row_data, internal_table, internal_row)

    def _process_tables(self, device, component, cmd_json, data_keys):
        """
        Process the tables in the given JSON output.

        This method takes the given JSON output and processes the tables in it.
        It looks for keys that are tables and processes them.
        """
        table_names = [key for key in data_keys if "TABLE" in key]
        row_names = [name.replace("TABLE", "ROW") for name in table_names]

        for table_name, row_name in zip(table_names, row_names):
            self._split_json(device, component, cmd_json, table_name, row_name)

    def _display_data(self, device, component, jsonElement):
        """
        Process the row data in the given JSON output.

        This method takes the given JSON output and processes the row data in it.
        It looks for keys that are not tables and processes them.
        It looks for tables and processes them.
        """
        json_row = json.dumps(jsonElement, ensure_ascii=False)
        row_string = json.loads(json_row)
        if type(row_string) is dict:
            for key, value in list(row_string.items()):
                if value != None and type(value) not in [list, tuple, dict]:  # noqa: E711
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                        row_string[key] = value
        currentTime = datetime.now().strftime("%Y-%m-%d %H:%M:%S%z")
        response = {"timestamp": currentTime, "component": component, "device": device, "Row_info": row_string}
        self.events.append(response)
        return 1

    def _split_json(self, device, component, jsonData, tableName, rowName):
        """
        Split the given JSON output into individual rows.

        This method takes the given JSON output and processes the tables in it.
        It looks for keys that are tables and processes them.
        """
        if tableName in jsonData:
            single_row = jsonData[tableName][rowName]
            if type(single_row) is list:
                for element in single_row:
                    self._display_data(device, component, element)
            elif type(single_row) is dict:
                self._display_data(device, component, single_row)
        return 1


dispatch(nxapiCommand, sys.argv, sys.stdin, sys.stdout, __name__)
