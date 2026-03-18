"""This module handles the collection and ingestion of inventory data from Cisco Intersight."""
# This import is required to resolve the absolute paths of supportive modules
# implemented throughout the add-on. The relative imports used in other files
# of the add-on are resolved by importing this module.
import import_declare_test

import sys
import time
import traceback

from splunklib import modularinput as smi
from intersight_helpers.logger_manager import setup_logging
from intersight_helpers.rest_helper import RestHelper
from intersight_helpers.event_ingestor import EventIngestor
from intersight_helpers.constants import (
    InventoryApis,
)
from intersight_helpers.conf_helper import (
    get_credentials,
    get_checkpoint,
    save_checkpoint,
    get_conf_file,
)
import copy
from typing import Tuple, List, Dict, Any
import logging
from solnlib import utils


# dictionary mapping inventory types to their respective endpoints and ingest functions
inventory_config = getattr(InventoryApis, "inventory_config", {})
multi_api_inventory_config = getattr(InventoryApis, "multi_api_inventory_config", {})
target_wise_inventory = getattr(InventoryApis, "target_wise_inventory", [])


class INVENTORY(smi.Script):
    """A class that represents an inventory script for Splunk Modular Input.

    This class handles the collection and ingestion of inventory data from Intersight.
    """

    def is_checkpoint_reset_enabled(self, session_key: str, logger: logging.Logger) -> bool:
        """Check if the inventory checkpoint reset saved search is enabled.

        Args:
            session_key (str): The session key for authentication.
            logger (logging.Logger): The logger object for logging messages.

        Returns:
            bool: True if the saved search is enabled (disabled=0), False otherwise.
        """
        try:
            saved_search_name = "splunk_ta_cisco_intersight_inventory_checkpoint_reset"

            # Get the saved search stanza from savedsearches.conf
            saved_search = get_conf_file(
                file="savedsearches",
                app=import_declare_test.ta_name,
                session_key=session_key,
                stanza=saved_search_name
            )

            if saved_search:
                # Get the disabled field (0 = enabled, 1 = disabled)
                disabled_value = saved_search.get("disabled", "1")
                is_enabled = utils.is_false(disabled_value)
                logger.info(
                    f"message=checkpoint_reset_check | Saved search '{saved_search_name}' "
                    f"disabled={disabled_value}, is_enabled={is_enabled}"
                )
                return is_enabled
            else:
                logger.debug(
                    f"message=checkpoint_reset_check | Saved search '{saved_search_name}' not found, "
                    "assuming disabled (safe default)"
                )
                return False

        except Exception as e:
            logger.error(
                f"message=checkpoint_reset_check | Error checking saved search status: {str(e)}"
            )
            logger.error(traceback.format_exc())
            # Return False (disabled) as safe default
            return False

    def get_scheme(self) -> smi.Scheme:
        """Define the scheme for the inventory input.

        This method defines the scheme object that specifies the input parameters
        for the inventory script. The scheme object defines the input parameters,
        their descriptions, and whether they are required or not.

        Returns:
            smi.Scheme: The scheme object that defines the input parameters for the inventory.
        """
        scheme = smi.Scheme("inventory")
        scheme.description = "Inventory"
        scheme.use_external_validation = True
        scheme.streaming_mode_xml = True
        scheme.use_single_instance = False

        scheme.add_argument(
            smi.Argument(
                "name",  # Name of the input
                title="Name",
                description="Name",
                required_on_create=True  # Required when creating a new input
            )
        )
        scheme.add_argument(
            smi.Argument(
                "global_account",  # Global Account Name
                required_on_create=True,  # Required when creating a new input
            )
        )
        scheme.add_argument(
            smi.Argument(
                "inventory",  # Inventory
                required_on_create=True,  # Required when creating a new input
            )
        )
        scheme.add_argument(
            smi.Argument(
                "compute_endpoints",  # Compute Endpoints
                required_on_create=False,  # Optional when creating a new input
            )
        )
        scheme.add_argument(
            smi.Argument(
                "fabric_endpoints",  # Fabric Endpoints
                required_on_create=False,  # Optional when creating a new input
            )
        )
        scheme.add_argument(
            smi.Argument(
                "license_endpoints",  # License Endpoints
                required_on_create=False,  # Optional when creating a new input
            )
        )
        scheme.add_argument(
            smi.Argument(
                "ports_endpoints",  # Ports Endpoints
                required_on_create=False,  # Optional when creating a new input
            )
        )
        scheme.add_argument(
            smi.Argument(
                "pools_endpoints",  # Pools Endpoints
                required_on_create=False,  # Optional when creating a new input
            )
        )
        scheme.add_argument(
            smi.Argument(
                "advisories_endpoints",  # Advisory Endpoints
                required_on_create=False,  # Optional when creating a new input
            )
        )
        return scheme

    def stream_events(
        self, inputs: smi.InputDefinition, ew: smi.EventWriter
    ) -> None:
        """Stream events from the inventory data source.

        Args:
            inputs (smi.InputDefinition): The input definition containing the input parameters.
            ew (smi.EventWriter): The event writer object used to write events to Splunk.

        Returns:
            None
        """
        logger = setup_logging("ta_intersight_inventory")
        try:
            start_time = time.time()
            # Prepare the input items based on the input definition
            input_items = self.prepare_input_items(inputs)
            # Set up the logger
            logger = self.setup_logging(input_items)

            # Check if checkpoint reset is running
            session_key = input_items[1].get("session_key")
            if self.is_checkpoint_reset_enabled(session_key, logger):
                logger.info(
                    "message=checkpoint_reset_active | Inventory checkpoint reset saved search is currently enabled. "
                    "Deferring inventory collection to allow checkpoint reset to complete."
                )
                return

            # Get the account information and update the input items
            account_info = self.get_account_info(input_items)
            input_items[1].update(account_info)

            # Create the REST helper and event ingestor objects
            intersight_rest_helper = RestHelper(input_items[1], logger)
            event_ingestor = EventIngestor(
                input_items[1], ew, logger,
                intersight_rest_helper.ckpt_account_name
            )

            # Get the target moids if needed
            target_moids = self.get_target_if_needed(input_items[1], intersight_rest_helper, logger)

            # Process inventory types
            inventory_kwargs = {
                "input_items": input_items,
                "intersight_rest_helper": intersight_rest_helper,
                "event_ingestor": event_ingestor,
                "logger": logger,
                "target_moids": target_moids
            }
            self.process_inventory_types(inventory_kwargs)
            self.process_multi_api_inventory(inventory_kwargs)

            # Log the API call statistics and total time taken
            total_time_taken = time.time() - start_time
            logger.info(
                "message=intersight_api_count | API call statistics: {}".format(
                    intersight_rest_helper.api_call_count
                )
            )
            logger.info(
                "message=data_collection_end_execution | Data collection completed"
                " and total time taken: {}. ".format(total_time_taken)
            )
        except Exception as e:
            # Log any errors that occurred
            logger.error(
                "message=inventory_error | An error occurred while processing the Inventory. {}".format(e)
            )
            logger.error(traceback.format_exc())
            raise

    def get_target_if_needed(
        self, input_items: Dict[str, Any], intersight_rest_helper: RestHelper, logger: logging.Logger
    ) -> List[str]:
        """Get Target Moids.

        Args:
            input_items (dict): The input definition containing the input parameters.
            intersight_rest_helper (RestHelper): The REST helper for making API calls.
            logger (Logger): The logger object for logging messages.

        Returns:
            list: A list of Target Moids.
        """
        collecting_inventory = {}

        # Extract inventory items from the input definition
        inventory_items = input_items['inventory'].split(',')
        for item in inventory_items:
            # Extract endpoints if present in input_items
            if input_items.get(f'{item}_endpoints'):
                collecting_inventory[item] = input_items[f'{item}_endpoints'].split(',')

            # Check inventory_config and update collecting_inventory
            if item in inventory_config:
                collecting_inventory[item] = [inventory_config[item]["endpoint"]]
            elif item in multi_api_inventory_config and "All" in collecting_inventory.get(item, []):
                collecting_inventory[item] = list(multi_api_inventory_config[item].keys())  # Extract child keys

        found = self.is_target_needed(collecting_inventory)

        if found:
            logger.info(
                f"message=fetching_target_list | Target-wise inventory: {target_wise_inventory}. "
                f"One or more items are present in the collection list: {collecting_inventory}, "
                "proceeding with target collection."
            )
            return self.get_target_moids(intersight_rest_helper, logger)
        else:
            logger.info(
                f"message=target_not_required | Target-wise inventory: {target_wise_inventory}. "
                f"No items are present in the collection list: {collecting_inventory}, "
                "no need of target collection."
            )
            return []

    def is_target_needed(self, collecting_inventory: dict) -> bool:
        """Determine if target-wise inventory is required.

        Args:
            collecting_inventory (dict): A dictionary of inventory items and their endpoints.

        Returns:
            bool: True if target-wise inventory is needed, False otherwise.
        """
        # Iterate over each inventory type and its associated endpoints
        for _, value_list in collecting_inventory.items():
            # Check if any endpoint is part of the target-wise inventory list
            for item in value_list:
                if item in target_wise_inventory:
                    return True  # Target-wise inventory is needed
        return False  # Target-wise inventory is not needed

    def prepare_input_items(self, inputs: smi.InputDefinition) -> List[Dict[str, Any]]:
        """Prepare the input items for processing.

        Args:
            inputs (smi.InputDefinition): The input definition containing the input parameters.

        Returns:
            List[Dict[str, Any]]: A list of prepared input items, including metadata and session keys.
        """
        # Initialize the input items list with the count of inputs
        input_items = [{"count": len(inputs.inputs)}]
        # Get the metadata configurations
        meta_configs = self._input_definition.metadata
        # Get the session key from the metadata configurations
        session_key = meta_configs["session_key"]
        # Iterate over the input items
        for input_name, input_item in inputs.inputs.items():
            # Set the stanza name and name for the input item
            input_item["stanza_name"] = input_name
            input_item["name"] = input_name.split("://")[1]
            # Set the session key for the input item
            input_item["session_key"] = session_key
            # Append the input item to the list
            input_items.append(input_item)
        # Return the prepared input items
        return input_items

    def setup_logging(
        self, input_items: List[Dict[str, Any]]
    ) -> logging.Logger:
        """Set up the logger object for the inventory script.

        The logger is configured with the name of the input stanza and is used to
        log messages during the data collection process.

        Args:
            input_items (List[Dict[str, Any]]): A list of dictionaries containing the input items.

        Returns:
            logging.Logger: The configured logger object.

        """
        input_name = input_items[1]["name"]
        logger = setup_logging("ta_intersight_inventory", input_name=input_name)
        logger.info(
            "message=data_collection_start_execution | Data collection started."
        )
        return logger

    def get_account_info(
        self, input_items: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Retrieve account information based on the input items.

        This function retrieves the account credentials using the session key and
        global account name from the input items. The account credentials are then
        returned as a dictionary.

        Args:
            input_items (List[Dict[str, Any]]): A list of dictionaries containing the input items.

        Returns:
            Dict[str, Any]: A dictionary containing the account credentials.
        """
        # Retrieve the session key and global account name from the input items
        account_name = input_items[1]["global_account"]
        session_key = input_items[1]["session_key"]

        # Retrieve the account credentials using the session key and global account name
        account_info = get_credentials(account_name, session_key)

        # Return the account credentials as a dictionary
        return account_info

    def process_inventory_types(
        self,
        kwargs: Dict[str, Any]
    ) -> None:
        """Process the various inventory types based on the provided configuration.

        This function iterates over the available inventory types and processes each
        one according to its configuration. It initializes checkpoints, processes
        inventory data, and saves the latest modification times.

        Args:
            kwargs (dict): A dictionary containing the following keys:
                - input_items (list): The prepared input items.
                - intersight_rest_helper (intersight_rest_helper.RestHelper): The REST helper for making API calls.
                - event_ingestor (event_ingestor.EventIngestor): The event ingestor for ingesting data into Splunk.
                - logger (logging.Logger): The logger object for logging messages.
                - target_moids (list): List of target MOIDs.

        Returns:
            None
        """
        try:
            # Extract necessary components from kwargs
            input_items = kwargs["input_items"]
            intersight_rest_helper = kwargs["intersight_rest_helper"]
            event_ingestor = kwargs["event_ingestor"]
            logger = kwargs["logger"]
            target_moids = kwargs.get("target_moids", [])

            # Get the inventory types specified in the input items
            inventory_types = input_items[1].get("inventory", [])

            # Prepare common arguments for processing inventory data
            inventory_data_kwargs = {
                "intersight_rest_helper": intersight_rest_helper,
                "event_ingestor": event_ingestor,
                "logger": logger,
            }

            # Iterate over each inventory type configuration
            for inv_type, config in inventory_config.items():
                # Skip inventory types not specified in the input
                if inv_type not in inventory_types:
                    continue

                # Initialize checkpoint for the current inventory type
                checkpoint_key, session_key, inventory_checkpoint_dict = (
                    self._initialize_checkpoint(input_items, config, logger)
                )

                # Update arguments with specific data for processing
                inventory_data_kwargs["inventory_checkpoint_dict"] = inventory_checkpoint_dict
                inventory_data_kwargs["config"] = config
                inventory_data_kwargs["target_moids"] = target_moids

                # Process the inventory data and update checkpoint
                inventory_checkpoint_dict = self._process_inventory_data(inventory_data_kwargs)

                # Save the updated checkpoint data
                save_checkpoint(
                    checkpoint_key,
                    session_key,
                    import_declare_test.ta_name,
                    inventory_checkpoint_dict
                )

                # Log the latest modification time for the processed inventory type
                logger.info(
                    "message=latest_modtime | Latest modification time saved in "
                    f"Splunk KVStore for {config.get('log_name', inv_type)}: {inventory_checkpoint_dict}"
                )

        except Exception as e:
            # Log any exceptions that occur during processing
            logger.error(f"message=inventory_processing_error | Error processing inventory: {e}")
            logger.error(traceback.format_exc())

    def _initialize_checkpoint(
        self,
        input_items: List[Dict[str, Any]],
        config: Dict[str, Any],
        logger: logging.Logger
    ) -> Tuple[str, str, Dict[str, Any]]:
        """Initialize checkpoint key and retrieve checkpoint value.

        This function initializes a checkpoint key based on the input items and
        inventory configuration. It then retrieves the checkpoint value from the
        KVStore and returns the checkpoint key, session key, and a dictionary
        containing the checkpoint value.

        Args:
            input_items (List[Dict[str, Any]]): The prepared input items.
            config (Dict[str, Any]): Inventory configuration.
            logger (logging.Logger): Logger object.

        Returns:
            Tuple containing (checkpoint_key, session_key, inventory_checkpoint_dict).
        """
        try:
            # Retrieve input name and session key from the input items
            input_config = input_items[1]
            input_name = input_config.get("name")
            session_key = input_config.get("session_key")

            # Initialize the checkpoint key using the input name and inventory log name
            checkpoint_key = f"Cisco_Intersight_{input_name}_{config.get('log_name').lower()}_inventory_checkpoint"

            # Retrieve the checkpoint value from the KVStore
            inventory_checkpoint_value = get_checkpoint(
                checkpoint_key,
                session_key,
                import_declare_test.ta_name
            )

            # Convert the checkpoint value to a dictionary
            inventory_checkpoint_dict = dict(inventory_checkpoint_value or {})

            # Log the checkpoint initialization
            logger.info(
                f"message=checkpoint_initialized | Inventory checkpoint for {config.get('log_name')}: "
                f"{inventory_checkpoint_dict}"
            )

            # Return the checkpoint key, session key, and checkpoint dictionary
            return checkpoint_key, session_key, inventory_checkpoint_dict

        except Exception as e:
            # Log any exceptions that occur during checkpoint initialization
            logger.error(f"message=checkpoint_init_error | Error initializing checkpoint: {e}")
            logger.error(traceback.format_exc())
            return None, None, {}

    def _process_inventory_data(
        self,
        kwargs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Fetch inventory data from the API and ingest it into Splunk.

        Args:
            kwargs: A dictionary containing the following keys:
                - intersight_rest_helper (intersight_rest_helper.RestHelper): The REST helper for making API calls.
                - event_ingestor (event_ingestor.EventIngestor): The event ingestor for ingesting data into Splunk.
                - logger (logging.Logger): The logger object for logging messages.
                - inventory_checkpoint_dict (dict): The inventory checkpoint dictionary.
                - config (dict): The inventory configuration.
                - target_moids (list): List of target MOIDs.

        Returns:
            dict: Inventory checkpoint dictionary.

        Notes:
            This function fetches inventory data from the API and ingests it into Splunk.
            It uses the provided checkpoint dictionary to track the latest modification time
            for the inventory type. If the inventory type is target-wise, it processes the
            inventory data for each target in the target list. Otherwise, it fetches the
            inventory data for the entire inventory type.
        """
        try:
            intersight_rest_helper = kwargs["intersight_rest_helper"]
            event_ingestor = kwargs["event_ingestor"]
            logger = kwargs["logger"]
            inventory_checkpoint_dict = kwargs["inventory_checkpoint_dict"]
            config = kwargs["config"]
            target_moids = kwargs["target_moids"]

            # Process inventory data for target-wise inventory types
            if config.get("endpoint", "") in target_wise_inventory:
                target_inventory_kwargs = {
                    "intersight_rest_helper": intersight_rest_helper,
                    "event_ingestor": event_ingestor,
                    "logger": logger,
                    "checkpoint_dict": inventory_checkpoint_dict,
                    "config": config,
                    "endpoint": config.get("endpoint", "")
                }
                for target in target_moids:
                    target_inventory_kwargs["target"] = target
                    self.process_target_inventory(target_inventory_kwargs)
            else:
                # Process inventory data for non-target-wise inventory types
                if not inventory_checkpoint_dict:
                    inventory_checkpoint_dict = {"time": None, "status": True}
                logger.info(
                    "message=inventory_checkpoint | Using Checkpoint "
                    f"{inventory_checkpoint_dict} for {config.get('endpoint', '')}"
                )
                fetch_and_ingest_inventory_data_kwargs: Dict[str, Any] = {
                    "inventory_checkpoint_dict": inventory_checkpoint_dict,
                    "inventory": config.get("endpoint", ""),
                    "config": config,
                    "event_ingestor": event_ingestor,
                }
                inventory_checkpoint_dict = intersight_rest_helper.fetch_and_ingest_inventory_data(
                    fetch_and_ingest_inventory_data_kwargs
                )

            return inventory_checkpoint_dict

        except Exception as e:
            logger.error(f"message=fetch_inventory_error | Error fetching inventory data: {e}")
            logger.error(traceback.format_exc())
            return {}

    def process_multi_api_inventory(
        self,
        kwargs: Dict[str, Any]
    ) -> None:
        """Process inventory data from multiple APIs based on the provided configuration.

        Process inventory data from multiple APIs based on the provided configuration.
        This function iterates over the available inventory types and processes each
        one according to its configuration. It initializes checkpoints, processes
        inventory data, and saves the latest modification times.

        Args:
            kwargs (dict): A dictionary containing the following keys:
                - input_items (list): The prepared input items.
                - intersight_rest_helper (intersight_rest_helper.RestHelper): The REST helper for making API calls.
                - event_ingestor (event_ingestor.EventIngestor): The event ingestor for ingesting data into Splunk.
                - logger (logging.Logger): The logger object for logging messages.
                - target_moids (list): List of target MOIDs.

        Returns:
            None
        """
        try:
            # Extract necessary components from kwargs
            input_items = kwargs["input_items"]
            intersight_rest_helper = kwargs["intersight_rest_helper"]
            event_ingestor = kwargs["event_ingestor"]
            logger = kwargs["logger"]
            target_moids = kwargs["target_moids"]

            if target_moids is None:
                target_moids = []
            input_data = input_items[1]
            enabled_inventory = input_data.get("inventory", {})

            # Iterate over each inventory type configuration
            for inv_type, endpoint_dict in multi_api_inventory_config.items():
                # Skip inventory types not specified in the input
                if inv_type not in enabled_inventory:
                    logger.debug(
                        f"message=not_enabled | {inv_type.capitalize()} inventory type "
                        "was not enabled in the input."
                    )
                    continue

                enabled_endpoints = input_data.get(f"{inv_type}_endpoints", "")
                enabled_endpoints = enabled_endpoints.split(",") if enabled_endpoints else []

                # Create a dictionary for standard inventory processing
                standard_inventory_kwargs = {
                    "intersight_rest_helper": intersight_rest_helper,
                    "event_ingestor": event_ingestor,
                    "logger": logger,
                    "target_moids": target_moids
                }

                # Iterate over each endpoint of the inventory type
                for endpoint, config in endpoint_dict.items():
                    # Skip endpoints not enabled in the input
                    if (
                        endpoint not in enabled_endpoints
                        and "All" not in enabled_endpoints
                        and inv_type != "advisories"
                    ):
                        continue

                    # Create a unique checkpoint key for the endpoint
                    checkpoint_key = (
                        f"Cisco_Intersight_{input_data.get('name')}_"
                        f"{config.get('log_name', inv_type).lower()}_inventory_checkpoint"
                    )

                    # Get the session key for the input
                    session_key = input_data.get("session_key", "")

                    # Update the standard inventory processing kwargs
                    standard_inventory_kwargs["config"] = config
                    standard_inventory_kwargs["endpoint"] = endpoint
                    standard_inventory_kwargs["checkpoint_key"] = checkpoint_key
                    standard_inventory_kwargs["session_key"] = session_key

                    # Process the standard inventory
                    self.process_standard_inventory(standard_inventory_kwargs)

        except Exception as e:
            logger.error(f"message=multi_api_inventory_error | Error processing multi-API inventory: {e}")
            logger.error(traceback.format_exc())

    def get_target_moids(
        self, intersight_rest_helper: RestHelper, logger: logging.Logger
    ) -> List[str]:
        """Get the registered devices of targets with ManagementMode = Intersight, Intersight Standalone.

        This function retrieves the target MOIDs from the Cisco Intersight API. It fetches the target data with the
        "RegisteredDevice" and "Name" fields in the response. The fetched data is not ingested into Splunk, but
        is returned as a list of target MOIDs.

        Args:
            intersight_rest_helper (intersight_rest_helper.RestHelper): The REST helper for making API calls.
            logger (logging.Logger): The logger object for logging messages.

        Returns:
            List[str]: Retrieved target MOIDs.
        """
        try:
            # Get the target configuration
            target_config = copy.deepcopy(inventory_config.get("target", {}))
            target_api = target_config.get("endpoint", "")

            # Check if the target API or parameters are missing
            if not target_api or not target_config.get("params", {}):
                logger.warning(
                    "message=get_target_moids_warning | Target API or parameters missing in inventory config."
                )
                return []

            # Update the target configuration
            target_config.get("params", {}).update({"$select": "RegisteredDevice,Name"})
            fetch_and_ingest_inventory_data_kwargs = {
                "inventory_checkpoint_dict": None,
                "inventory": target_api,
                "config": target_config,
                "event_ingestor": None,
                "add_modtime_filter": False
            }
            # Fetch the target data
            target_moids = intersight_rest_helper.fetch_and_ingest_inventory_data(
                fetch_and_ingest_inventory_data_kwargs
            )
            return target_moids

        except Exception as e:
            logger.error(f"message=get_target_moids_error | Error retrieving target MOIDs: {str(e)}")
            logger.error(traceback.format_exc())
            return []

    def process_target_inventory(
        self,
        kwargs: Dict[str, Any]
    ) -> None:
        """Process inventory data for a specific target.

        This function fetches inventory data for a specific target, applies necessary filters,
        and updates the checkpoint data after processing.

        Args:
            kwargs: A dictionary containing the following keys:
                - intersight_rest_helper: The REST helper for making API calls.
                - event_ingestor: The event ingestor for ingesting data into Splunk.
                - logger: The logger object for logging messages.
                - target: The target data.
                - checkpoint_dict: The checkpoint dictionary.
                - config: The inventory configuration.
                - endpoint: The endpoint for the inventory.

        Returns:
            None
        """
        try:
            # Extract necessary components from kwargs
            intersight_rest_helper = kwargs["intersight_rest_helper"]
            target = kwargs["target"]
            config = kwargs["config"]
            event_ingestor = kwargs["event_ingestor"]
            logger = kwargs["logger"]
            checkpoint_dict = kwargs["checkpoint_dict"]
            endpoint = kwargs["endpoint"]

            # Retrieve target MOID
            target_moid = target.get("RegisteredDevice", {}).get("Moid")

            # Check if target MOID is missing
            if not target_moid:
                logger.warning(f"message=missing_target_moid | Target '{target.get('Name')}' has no Moid.")
                return

            logger.info(
                f"message=executing_inventory_object | Fetching inventory objects for target '{target.get('Name')}'."
            )

            # Prepare API parameters with filters
            local_config = copy.deepcopy(config)
            api_params = local_config.get("params", {})
            filter_param = "$filter"
            owners_filter = f"Owners/any(x: x eq '{target_moid}')"
            if api_params.get(filter_param, False):
                api_params[filter_param] += f" AND {owners_filter}"
            else:
                api_params[filter_param] = owners_filter

            local_config["params"] = api_params

            # Initialize checkpoint dictionary for the target if not present
            if not checkpoint_dict.get(target_moid):
                checkpoint_dict[target_moid] = {"time": None, "status": True}

            logger.info(
                "message=inventory_checkpoint | Using Checkpoint "
                f"{checkpoint_dict[target_moid]} for {endpoint}"
            )

            # Prepare arguments for fetching and ingesting inventory data
            fetch_and_ingest_inventory_data_kwargs = {
                "inventory_checkpoint_dict": checkpoint_dict.get(target_moid),
                "inventory": endpoint,
                "config": local_config,
                "event_ingestor": event_ingestor,
            }

            # Fetch and ingest inventory data, updating the checkpoint
            checkpoint_dict[target_moid] = intersight_rest_helper.fetch_and_ingest_inventory_data(
                fetch_and_ingest_inventory_data_kwargs
            )

        except Exception as e:
            logger.error(f"message=process_target_inventory_error | Error processing target inventory: {str(e)}")
            logger.error(traceback.format_exc())

    def process_standard_inventory(
        self,
        kwargs: Dict[str, Any],
        is_save_checkpoint=True
    ) -> None:
        """Process standard inventory endpoints.

        This function processes standard inventory endpoints, which include
        both target-wise and non-target-wise inventory types. It uses the
        provided checkpoint dictionary to track the latest modification time
        for the inventory type. If the inventory type is target-wise, it
        processes the inventory data for each target in the target list.
        Otherwise, it fetches the inventory data for the entire inventory
        type.

        Args:
            kwargs: A dictionary containing the following keys:
                - intersight_rest_helper: The REST helper for making API calls.
                - event_ingestor: The event ingestor for handling events.
                - logger: The logger object for logging messages.
                - session_key: The session key for authentication.
                - checkpoint_key: The key for tracking checkpoint data.
                - config: API configuration settings.
                - endpoint: The API endpoint being processed.
                - target_moids: List of target MOIDs.

        Returns:
            None
        """
        try:
            intersight_rest_helper = kwargs["intersight_rest_helper"]
            event_ingestor = kwargs["event_ingestor"]
            logger = kwargs["logger"]
            session_key = kwargs["session_key"]
            checkpoint_key = kwargs["checkpoint_key"]
            config = kwargs["config"]
            endpoint = kwargs["endpoint"]
            target_moids = kwargs["target_moids"]
            if target_moids is None:
                target_moids = []

            # Get the checkpoint dictionary
            checkpoint_dict = get_checkpoint(
                checkpoint_key, session_key, import_declare_test.ta_name
            ) or {}

            # Process target-wise inventory endpoints
            if endpoint in target_wise_inventory:
                process_target_inventory_kwargs = {
                    "intersight_rest_helper": intersight_rest_helper,
                    "event_ingestor": event_ingestor,
                    "logger": logger,
                    "checkpoint_dict": checkpoint_dict,
                    "config": config,
                    "endpoint": endpoint,
                }
                for target in target_moids:
                    process_target_inventory_kwargs["target"] = target
                    self.process_target_inventory(process_target_inventory_kwargs)

            # Process non-target-wise inventory endpoints
            else:

                if not checkpoint_dict:
                    checkpoint_dict = {"time": None, "status": True}
                logger.info(
                    "message=inventory_checkpoint | Using Checkpoint "
                    f"{checkpoint_dict} for {endpoint}"
                )
                fetch_and_ingest_inventory_data_kwargs = {
                    "inventory_checkpoint_dict": checkpoint_dict,
                    "inventory": endpoint,
                    "config": config,
                    "event_ingestor": event_ingestor,
                }
                checkpoint_dict = intersight_rest_helper.fetch_and_ingest_inventory_data(
                    fetch_and_ingest_inventory_data_kwargs
                )

            # Save the checkpoint dictionary
            if is_save_checkpoint:
                save_checkpoint(checkpoint_key, session_key, import_declare_test.ta_name, checkpoint_dict)

            logger.info(
                "message=latest_modtime | Latest modification time saved "
                f"in Splunk KVStore for {config.get('log_name')}: {checkpoint_dict}"
            )

        except Exception as e:
            logger.error(f"message=process_standard_inventory_error | Error processing inventory: {e}")
            logger.error(traceback.format_exc())


if __name__ == "__main__":
    exit_code = INVENTORY().run(sys.argv)
    sys.exit(exit_code)
