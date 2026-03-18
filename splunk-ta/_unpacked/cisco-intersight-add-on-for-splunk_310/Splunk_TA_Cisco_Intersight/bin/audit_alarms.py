"""This module fetches data from Cisco Intersight Audit logs and Alarms."""
# This import is required to resolve the absolute paths of supportive modules
# implemented throughout the add-on. The relative imports used in other files
# of the add-on are resolved by importing this module.
import import_declare_test

import sys
import time
import traceback

from splunklib import modularinput as smi
from solnlib.utils import is_true
from solnlib.conf_manager import ConfManagerException
from intersight_helpers.logger_manager import setup_logging
from intersight_helpers.rest_helper import RestHelper
from intersight_helpers.event_ingestor import EventIngestor
from intersight_helpers.conf_helper import get_credentials, get_checkpoint, save_checkpoint, get_conf_file
from inventory import INVENTORY
from datetime import datetime, timedelta, timezone
from copy import deepcopy
from typing import List, Tuple, Dict, Any
import logging


class AUDITALARMS(smi.Script):
    """Class to fetch data for Cisco Intersight Audit logs and Alarms."""

    def get_scheme(self) -> smi.Scheme:
        """
        Define the scheme for the audit_alarms input.

        Returns:
            smi.Scheme: The scheme object that defines the input parameters for the
            audit_alarms input.
        """
        scheme = smi.Scheme('audit_alarms')
        scheme.description = 'Audit & Alarms'
        scheme.use_external_validation = True
        scheme.streaming_mode_xml = True
        scheme.use_single_instance = False

        scheme.add_argument(
            smi.Argument(
                'name',  # Name of the input
                title='Name',
                description='Name',
                required_on_create=True  # Required when creating a new input
            )
        )
        scheme.add_argument(
            smi.Argument(
                'global_account',  # Global Account Name
                required_on_create=True,  # Required when creating a new input
            )
        )
        scheme.add_argument(
            smi.Argument(
                'enable_aaa_audit_records',  # Enable AAA Audit Records
                required_on_create=False,  # Optional when creating a new input
            )
        )
        scheme.add_argument(
            smi.Argument(
                'enable_alarms',  # Enable Alarms
                required_on_create=False,  # Optional when creating a new input
            )
        )
        scheme.add_argument(
            smi.Argument(
                'acknowledge',  # Acknowledge
                required_on_create=False,  # Optional when creating a new input
            )
        )
        scheme.add_argument(
            smi.Argument(
                'suppressed',  # Suppressed
                required_on_create=False,  # Optional when creating a new input
            )
        )
        scheme.add_argument(
            smi.Argument(
                'info_alarms',  # Info alarms
                required_on_create=False,  # Optional when creating a new input
            )
        )
        scheme.add_argument(
            smi.Argument(
                "date_input",  # Specific date input
                required_on_create=False,  # Optional when creating a new input
            )
        )
        scheme.add_argument(
            smi.Argument(
                'interval_proxy',  # flag variable for restarting data collection
                required_on_create=False,  # Optional when creating a new input
            )
        )
        return scheme

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
                file='inputs',
                session_key=session_key,
            )
            return stanza
        except ConfManagerException as e:
            # If the file does not exist, return an empty dictionary
            if "inputs does not exist." in str(e):
                return {}
            else:
                raise
        except Exception as e:
            raise FileNotFoundError(
                "message=client_id_expiration_check | Error occurred while fetching configurations from "
                f"'inputs.conf' file. Error: {e}"
            )

    def update_inputs(
        self,
        session_key: str,
        stanza_name: str,
        updated_stanza_details: dict
    ) -> None:
        """
        Update Inputs.

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
            stanza.update(stanza_name=stanza_name, stanza=updated_stanza_details)
        except Exception as e:
            raise e

    def stream_events(self, inputs: smi.InputDefinition, ew: smi.EventWriter) -> None:
        """
        Stream events from the audit_alarms data source.

        Args:
            inputs (smi.InputDefinition): The input definition containing the input parameters.
            ew (smi.EventWriter): The event writer object used to write events to Splunk.

        Returns:
            None
        """
        logger = setup_logging("ta_intersight_audit_alarms")
        try:
            # Initialize inputs and logger
            start_time = time.time()
            input_items, session_key, logger = self._initialize_inputs(inputs)

            if not input_items:
                # If no input items are available, return
                return

            # Initialize REST helper and event ingestor
            intersight_rest_helper, event_ingestor = self._initialize_helpers(
                input_items, ew, logger
            )

            kwargs = {
                "input_items": input_items,
                "session_key": session_key,
                "intersight_rest_helper": intersight_rest_helper,
                "event_ingestor": event_ingestor,
                "logger": logger
            }
            # Process AAA Audit Records
            if is_true(input_items[1].get('enable_aaa_audit_records', False)):
                self._process_audit_records(kwargs)

            # Process Alarms
            if is_true(input_items[1].get('enable_alarms', False)):
                self._process_alarms(kwargs)

            # Log time taken to complete data collection
            total_time_taken = time.time() - start_time
            logger.info(
                "message=data_collection_end_execution | Data collection completed"
                " and total time taken: {}. ".format(total_time_taken)
            )
            # Log API call statistics
            logger.info(
                "message=intersight_api_count | API call statistics: {}".format(
                    intersight_rest_helper.api_call_count
                )
            )

        except Exception as e:
            # Log errors
            logger.error("message=audit_alarm_error | An error occurred while processing the audit alarm. {}".format(e))
            logger.error(traceback.format_exc())

    def _initialize_inputs(self, inputs: smi.InputDefinition) -> tuple:
        """
        Initialize input items and logger.

        This function validates the input parameters and initializes the input items
        and logger. It returns the prepared input items, session key, and logger.

        Args:
            inputs (smi.InputDefinition): The input definition containing the input parameters.

        Returns:
            tuple: A tuple containing the prepared input items (list), session key (str), and logger (logging.Logger).
        """
        input_items = [{'count': len(inputs.inputs)}]
        meta_configs = self._input_definition.metadata
        session_key = meta_configs['session_key']

        for input_name, input_item in inputs.inputs.items():
            input_item['stanza_name'] = input_name
            input_item['name'] = input_name.split('://')[1]
            input_item['session_key'] = session_key
            input_items.append(input_item)

        input_name = input_items[1]['name']
        logger = setup_logging("ta_intersight_audit_alarms", input_name=input_name)
        logger.info("message=data_collection_start_execution | Data collection started.")

        account_info = get_credentials(
            session_key=session_key,
            account_name=input_items[1]['global_account']
        )
        input_items[1].update(account_info)

        # Return the prepared input items, session key, and logger
        return input_items, session_key, logger

    def _initialize_helpers(
        self, input_items: List[dict], ew: smi.EventWriter, logger: logging.Logger
    ) -> Tuple[RestHelper, EventIngestor]:
        """
        Initialize REST helper and event ingestor.

        This function initializes the REST helper and event ingestor objects
        based on the provided input items, event writer, and logger. It returns
        the initialized REST helper and event ingestor objects.

        Args:
            input_items (List[dict]): A list containing the prepared input items.
            ew (smi.EventWriter): The event writer object used to write events to Splunk.
            logger (logging.Logger): The logger object for logging messages.

        Returns:
            Tuple[RestHelper, EventIngestor]: A tuple containing the initialized REST helper and event ingestor objects.
        """
        # Initialize the REST helper
        intersight_rest_helper = RestHelper(input_items[1], logger)

        # Initialize the event ingestor
        event_ingestor = EventIngestor(
            input_items[1], ew, logger, intersight_rest_helper.ckpt_account_name
        )

        # Return the initialized REST helper and event ingestor objects
        return intersight_rest_helper, event_ingestor

    def _process_audit_records(
        self,
        kwargs: Dict[str, Any]
    ) -> None:
        """
        Process AAA Audit Records.

        This function processes the AAA Audit Records by calling the
        get_audit_records function of the REST helper object. It uses the
        checkpoint value to determine the start time for the audit records
        collection.

        Args:
            kwargs (Dict[str, Any]): A dictionary containing the following keys:
                - input_items (List[dict]): A list containing the prepared input items.
                - session_key (str): The session key for authentication.
                - intersight_rest_helper (RestHelper): The REST helper object for
                    making API calls.
                - event_ingestor (EventIngestor): The event ingestor object for
                    ingesting data into Splunk.
                - logger (logging.Logger): The logger object for logging messages.

        Returns:
            None
        """
        input_items = kwargs.get("input_items")
        session_key = kwargs.get("session_key")
        intersight_rest_helper = kwargs.get("intersight_rest_helper")
        event_ingestor = kwargs.get("event_ingestor")
        logger = kwargs.get("logger")
        input_stanzas = self.get_conf_object(session_key)
        input_stanzas = input_stanzas.get_all(only_current_app=True)
        stanza_obj = {}
        logger.info(f"Reading stanza: {input_items[1]['name']}")
        stanza_obj = input_stanzas.get("audit_alarms://{}".format(
            input_items[1]['name']), {})
        interval_proxy = int(stanza_obj.get("interval_proxy", 0))

        # Get the checkpoint key and value
        checkpoint_key = f"Cisco_Intersight_{input_items[1]['name']}_audit_checkpoint"
        audit_checkpoint_dict = dict(get_checkpoint(
            checkpoint_key, session_key, import_declare_test.ta_name
        ) or {})

        # If the checkpoint value is not present, set the start time based on
        # the user's input
        if not audit_checkpoint_dict or interval_proxy == 1:
            date_input = input_items[1].get('date_input')
            date_time = self.get_start_time(date_input, logger)
            if interval_proxy == 1:
                logger.info(
                    "message=start_time | Audit records collection would be restarted based on "
                    f"User's input: {date_time}"
                )
            else:
                logger.info(
                    f"message=start_time | Start time for Audit records collection based on User's input: {date_time}"
                )
            audit_checkpoint_dict = {"time": date_time, "status": True}

        # Log the checkpoint value
        logger.info(
            f"message=audit_checkpoint_value | Checkpoint value for Audit : {audit_checkpoint_dict}"
        )

        # Prepare the keyword arguments for the get_audit_records function
        audit_kwargs = {
            "state": audit_checkpoint_dict.get("time", None),
            "event_ingestor": event_ingestor,
            "checkpoint_key": checkpoint_key,
            "session_key": session_key,
            "logger": logger,
            "filter_flag": audit_checkpoint_dict.get("status", True)
        }

        # Call the get_audit_records function
        intersight_rest_helper.get_audit_records(
            audit_kwargs
        )

        if interval_proxy == 1:
            logger.info(
                f"Changing value of interval_proxy parameter to 0 for input: audit_alarms://{input_items[1]['name']}"
            )
            stanza_obj['interval_proxy'] = 0
            stanza_obj.pop('__app', None)
            stanza_obj.pop('python.version', None)
            stanza_obj.pop('eai:access', None)
            self.update_inputs(
                session_key=session_key,
                stanza_name="audit_alarms://{}".format(input_items[1]['name']),
                updated_stanza_details=stanza_obj
            )

    def get_alarm_filter(self, input_items: list) -> dict:
        """
        Get the filter condition based on the input item configuration.

        This function creates the filter condition based on the user's input
        parameters. It checks the user's input for the acknowledge, suppressed
        and info_alarms parameters and creates the filter condition accordingly.

        Args:
            input_items (list): Input parameters which user has given.

        Returns:
            dict: A dictionary containing the filter condition.
        """
        filter_param = "$filter"
        is_acknowledge = input_items[1].get('acknowledge', False)
        is_suppressed = input_items[1].get('suppressed', False)
        is_info = input_items[1].get('info_alarms', False)

        severity_filter = "('Critical', 'Warning', 'Cleared')"

        if is_true(is_info):
            severity_filter = "('Critical', 'Warning', 'Cleared', 'Info')"

        # If both acknowledge and suppressed are true, create a filter condition
        # that includes all Critical, Warning and Cleared (Info - optional) alarms.
        if is_true(is_acknowledge) and is_true(is_suppressed):
            alarm_filter = {filter_param: f"Severity in {severity_filter}"}
        # If only acknowledge is true, create a filter condition that includes
        # all Critical, Warning ad Cleared (Info - optional) alarms that are not acknowledged.
        elif is_true(is_acknowledge):
            alarm_filter = {filter_param: f"Severity in {severity_filter} and Suppressed eq false"}
        # If only suppressed is true, create a filter condition that includes
        # all Critical, Warning and Cleared (Info - optional) alarms that are not suppressed.
        elif is_true(is_suppressed):
            alarm_filter = {filter_param: f"Severity in {severity_filter} and Acknowledge eq 'None'"}
        # If neither acknowledge nor suppressed are true, create a filter
        # condition that includes all Critical, Warning and Cleared (Info - optional) alarms that are not
        # acknowledged and not suppressed.
        else:
            alarm_filter = {
                filter_param: f"Severity in {severity_filter} and Acknowledge eq 'None' and Suppressed eq false"
            }
        return alarm_filter

    def _process_alarms(
        self,
        kwargs: Dict[str, Any]
    ) -> None:
        """
        Process Alarms data collection.

        This function processes alarms for a specific target by fetching alarms
        from the API and ingesting them into Splunk. It uses the checkpoint
        dictionary to determine the start time for alarms collection.

        Args:
            kwargs (dict): A dictionary containing the following keys:
                - input_items (List[dict]): A list containing the prepared input items.
                - session_key (str): The session key for authentication.
                - intersight_rest_helper (RestHelper): The REST helper object for
                    making API calls.
                - event_ingestor (EventIngestor): The event ingestor object for
                    ingesting data into Splunk.
                - logger (logging.Logger): The logger object for logging messages.

        Returns:
            None
        """
        input_items = kwargs.get("input_items")
        session_key = kwargs.get("session_key")
        intersight_rest_helper = kwargs.get("intersight_rest_helper")
        event_ingestor = kwargs.get("event_ingestor")
        logger = kwargs.get("logger")
        if "intersight_account_moid" in input_items[1]:
            intersight_account_moid = input_items[1]['intersight_account_moid']
        else:
            intersight_account_moid = intersight_rest_helper.ckpt_account_moid

        input_stanzas = self.get_conf_object(session_key)
        input_stanzas = input_stanzas.get_all(only_current_app=True)
        stanza_obj = {}
        logger.info(f"Reading stanza: {input_items[1]['name']}")
        stanza_obj = input_stanzas.get("audit_alarms://{}".format(
            input_items[1]['name']), {})
        interval_proxy = int(stanza_obj.get("interval_proxy", 0))

        checkpoint_key = f"Cisco_Intersight_{input_items[1]['name']}_alarm_checkpoint"
        alarms_checkpoint_value = get_checkpoint(
            checkpoint_key, session_key, import_declare_test.ta_name
        )
        alarm_filter = self.get_alarm_filter(input_items)
        logger.info(f"message=alarm_filter | Alarm filter condition: {alarm_filter}")

        inv_class = INVENTORY()
        target_moids = inv_class.get_target_moids(intersight_rest_helper, logger)
        if not target_moids:
            target_moids = []

        # Added static object to target moids list to fetch the account level alarms
        account_level_alarms_dict = {
            'ClassId': 'asset.Target',
            'Moid': f'{intersight_account_moid}_account_level_alarms',
            'Name': 'account_level_alarms',
            'ObjectType': 'asset.Target',
            'RegisteredDevice': {'Moid': f'{intersight_account_moid}_account_level_alarms'}
        }
        target_moids.append(account_level_alarms_dict)

        main_checkpoint_dict = dict(alarms_checkpoint_value or {})
        alarms_event_count = 0

        date_time = self.get_start_time(input_items[1].get('date_input'), logger)

        kwargs = {
            "main_checkpoint_dict": main_checkpoint_dict,
            "intersight_rest_helper": intersight_rest_helper,
            "event_ingestor": event_ingestor,
            "logger": logger,
            "alarm_filter": alarm_filter,
            "date_time": date_time,
            "interval_proxy": interval_proxy
        }

        for target in target_moids:
            kwargs["target"] = target
            alarm_count, main_checkpoint_dict = self._process_individual_target(kwargs)
            if not alarm_count:
                alarm_count = 0
            alarms_event_count += alarm_count

        save_checkpoint(
            checkpoint_key, session_key, import_declare_test.ta_name, main_checkpoint_dict
        )

        if interval_proxy == 1:
            logger.info(
                f"Changing value of interval_proxy parameter to 0 for input: audit_alarms://{input_items[1]['name']}"
            )
            stanza_obj['interval_proxy'] = 0
            stanza_obj.pop('__app', None)
            stanza_obj.pop('python.version', None)
            stanza_obj.pop('eai:access', None)
            self.update_inputs(
                session_key=session_key,
                stanza_name="audit_alarms://{}".format(input_items[1]['name']),
                updated_stanza_details=stanza_obj
            )

        logger.info(
            "message=events_collected | Total events for Alarms"
            f" ingested in Splunk are {alarms_event_count}."
        )

    def get_start_time(self, days_offset: int, logger) -> datetime:
        """
        Get 12 AM (midnight) UTC time for the given day offset.

        Args:
            days_offset (int): Number of days to go back (0 = today, 1 = yesterday, etc.).

        Returns:
            datetime: The 12 AM UTC time of the corresponding day.
        """
        try:
            # Get the current date in UTC and subtract the required number of days
            target_date = datetime.now(timezone.utc) - timedelta(days=int(days_offset))
        except Exception as e:
            # Log errors
            logger.error(
                "message=audit_alarm_error | No value selected for Start Day for Data Collection field. "
                "Error: {}".format(e)
            )
            raise ValueError("Invalid Start Day for Data Collection offset")

        # Set the time to 12:00 AM
        start_time = target_date.replace(hour=0, minute=0, second=0, microsecond=0)

        return start_time.strftime('%Y-%m-%dT%H:%M:%S.') + f'{start_time.microsecond // 1000:03d}Z'

    def _process_individual_target(
        self,
        kwargs: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """
        Process alarms for a specific target.

        This function processes alarms for a specific target by fetching alarms
        from the API and ingesting them into Splunk. It uses the checkpoint
        dictionary to determine the start time for alarms collection.

        Args:
            kwargs (Dict[str, Any]): A dictionary containing the following keys:
                - main_checkpoint_dict (Dict[str, Dict[str, Any]]): The main checkpoint dictionary.
                - intersight_rest_helper (RestHelper): The REST helper object for making API calls.
                - event_ingestor (EventIngestor): The event ingestor object for ingesting data into Splunk.
                - logger (logging.Logger): The logger object for logging messages.
                - filter_arg (Dict[str, str]): The alarm filter condition.
                - date_time (str): The date and time to start collecting alarms.
                - target (Dict[str, Any]): The target data.

        Returns:
            tuple: A tuple containing the count of alarms ingested and the main checkpoint dictionary.
        """
        main_checkpoint_dict = kwargs["main_checkpoint_dict"]
        intersight_rest_helper = kwargs["intersight_rest_helper"]
        event_ingestor = kwargs["event_ingestor"]
        logger = kwargs["logger"]
        filter_arg = kwargs["alarm_filter"]
        date_time = kwargs["date_time"]
        interval_proxy = int(kwargs["interval_proxy"])
        target = kwargs["target"]

        # Get the target MOID and name
        target_moid = target.get("RegisteredDevice", {}).get("Moid", None)
        target_name = target["Name"]

        # Initialize the target specific checkpoint dictionary
        target_checkpoint = {}

        # If the target MOID is not present in the main checkpoint dictionary,
        # set it with the current date time as the start time
        if target_moid not in main_checkpoint_dict or interval_proxy == 1:
            if interval_proxy == 1:
                logger.info(
                    "message=start_time | Alarms collection would be restarted based on "
                    f"User's input: {date_time} for target: {target_moid}"
                )
            else:
                logger.info(
                    "message=start_time | Start time for Alarms collection based on "
                    f"User's input: {date_time} for target: {target_moid}"
                )
            target_checkpoint = {"time": date_time, "status": True}
        else:
            # If the target MOID is present in the main checkpoint dictionary,
            # get its checkpoint dictionary
            target_checkpoint = main_checkpoint_dict.get(target_moid, {"time": None, "status": True})

        # Log the start time for alarms collection
        logger.debug(f"message=fetch_alarms | Fetching alarms for target: {target_name}")

        # Prepare the alarm filter condition
        alarm_filter = deepcopy(filter_arg)
        if target_name == "account_level_alarms":
            condition = (
                "RegisteredDevice eq null AND NOT "
                "(startswith(AffectedMo.ObjectType, storage) OR "
                "startswith(AffectedMo.ObjectType, hyperflex))"
            )
            alarm_filter['$filter'] += f" AND ({condition})"
        else:
            alarm_filter['$filter'] += f" AND (Owners/any(x: x eq '{target_moid}'))"

        # Fetch and ingest alarms for the target
        alarm_count, alarm_skipped, checkpoint_dict = intersight_rest_helper.fetch_and_ingest_alarms(
            target_checkpoint,
            event_ingestor,
            filter_condition=alarm_filter,
        )

        # Update the main checkpoint dictionary with the new checkpoint
        main_checkpoint_dict[target_moid] = checkpoint_dict

        # Log the count of alarms ingested and skipped
        logger.debug(
            "message=alarms_collected | Total Alarms ingested"
            f" for target: {target_name} are {alarm_count}."
        )
        logger.debug(
            "message=events_skipped | Count of Duplicate Alarms found"
            f" for target: {target_name}: {alarm_skipped}."
        )

        # Return the count of alarms ingested and the main checkpoint dictionary
        return alarm_count, main_checkpoint_dict


if __name__ == '__main__':
    exit_code = AUDITALARMS().run(sys.argv)
    sys.exit(exit_code)
