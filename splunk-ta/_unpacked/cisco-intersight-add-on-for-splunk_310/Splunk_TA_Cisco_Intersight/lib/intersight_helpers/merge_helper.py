"""This module provides helper functions specific for Merging of Metrics Data with Dimensions."""
# This import is required to resolve the absolute paths of supportive modules
# implemented throughout the add-on. The relative imports used in other files
# of the add-on are resolved by importing this module.
import import_declare_test  # noqa: F401  # pylint: disable=unused-import # needed to resolve paths
import time
from intersight_helpers import constants
import copy
import traceback
import logging
from intersight_helpers.kvstore import KVStoreManager


class MergeHelper:
    """Helper functions for Merging Metrics Data with Dimensions."""

    def __init__(self, logger: logging.Logger, kvstore_manager: KVStoreManager) -> None:
        """
        Init function for class MetricHelper.

        Args:
            logger (logging.Logger): Logger object.
            kvstore_manager (KVStoreManager): KVStoreManager object.
        """
        self.logger = logger
        self.kvstore_manager = kvstore_manager

    def get_mapped_value(self, value: str) -> str:
        """
        Map values to specific collection names.

        This function takes an input value and returns a mapped value based on
        the mapping dictionary. The mapping dictionary contains the keys that
        need to be mapped to specific collection names.

        Args:
            value (str): Input value to be mapped.

        Returns:
            str: Mapped value or the original value if no mapping is found.
        """
        # Mapping dictionary with keys that need to be mapped to specific
        # collection names.
        mapping_dict = {
            "network.elements": "networkelements",
            "network.element": "networkelements",
            "equipment.chasses": "chassis",
            "equipment.chassis": "chassis",
            "compute.physicalsummaries": "physicalsummary",
            "compute.physicalsummary": "physicalsummary",
            "compute.blades": "physicalsummary",
            "compute.blade": "physicalsummary",
            "compute.rackunits": "physicalsummary",
            "compute.rackunit": "physicalsummary",
            "memory.units": "memoryunit",
            "memory.unit": "memoryunit",
            "processor.units": "processorunit",
            "processor.unit": "processorunit",
            "compute.boards": "computeboard",
            "compute.board": "computeboard",
            "equipment.transceivers": "transceiver",
            "equipment.transceiver": "transceiver",
            "graphics.cards": "graphicscard",
            "graphics.card": "graphicscard",
            "etherhostports": "etherhostports",
            "etherhostport": "etherhostports",
            "ethernetworkports": "ethernetworkports",
            "ethernetworkport": "ethernetworkports",
            "etherphysicalports": "etherphysicalports",
            "etherphysicalport": "etherphysicalports",
            "etherportchannels": "etherportchannels",
            "etherportchannel": "etherportchannels",
            "adapterhostfcinterfaces": "adapterhostfcinterfaces",
            "adapterhostfcinterface": "adapterhostfcinterfaces",
            "fcphysicalports": "fcphysicalports",
            "fcphysicalport": "fcphysicalports",
            "fcportchannels": "fcportchannels",
            "fcportchannel": "fcportchannels",
            "networkvfcs": "networkvfcs",
            "networkvfc": "networkvfcs",
            "networkvethernets": "networkvethernets",
            "networkvethernet": "networkvethernets",
            "adapterhostethinterfaces": "adapterhostethinterfaces",
            "adapterhostethinterface": "adapterhostethinterfaces",
            "adapterextethinterfaces": "adapterextethinterfaces",
            "adapterextethinterface": "adapterextethinterfaces"
        }

        # Return the mapped value or the original value if no mapping is found.
        return mapping_dict.get(value.lower(), value)

    def get_record_by_key(self, json_data, id: str):
        """
        Get a record by its _key from the given JSON data.

        Args:
            json_data (list[dict]): List of records.
            id (str): ID of the record to be fetched.

        Returns:
            Optional[dict]: The record with the given ID if found, otherwise None.
        """
        try:
            if not json_data:
                return None
            # Iterate over each record in the json_data
            for record in json_data:
                # Check if the record's _key matches the given ID
                if record["_key"] == id:
                    # Return a deep copy of the record
                    return copy.deepcopy(record)
            # If the record is not found return None
            return None
        except Exception as e:
            # Log an error message if an exception occurs
            self.logger.error(
                f"message=get_record_by_key | Error while fetching KVStore record for ID: {id}."
                f"Error: {str(e)}"
            )
            # Return None if an exception occurs
            return None

    def merge_fan_data(
        self, kwargs: dict
    ) -> list:
        """
        Merge fan data with dimensions and parent data.

        Args:
            kwargs (dict): A dictionary containing the following keys:
                - response_data (list): List of response items containing host data.
                - account_name (str): Name of the account.
                - domain_id (str): ID of the domain.
                - domain_data (dict): Dictionary containing domain data.
                - collections (dict): Dictionary of collections.

        Returns:
            list[dict]: Merged objects containing metrics and dimensions.
        """
        # Extract necessary data from kwargs
        response_data = kwargs["response_data"]
        account_name = kwargs["account_name"]
        domain_id = kwargs["domain_id"]
        domain_data = kwargs["domain_data"]
        collections = kwargs["collections"]

        start_time_fan = time.time()
        self.logger.info(
            "message=metric_collection | Fan Data Merging Started, "
            f"Total Fan records for Domain: {domain_id} are {len(response_data)}"
        )

        # Fetch fan and fan module data
        fan_data = self.kvstore_manager.get(
            collection_name=constants.CollectionConstants.FAN,
            query={constants.CollectionConstants.DOMAINID: f"/api/v1/asset/DeviceRegistrations/{domain_id}"}
        )
        fanmodule_data = self.kvstore_manager.get(
            collection_name=constants.CollectionConstants.FAN_MODULE,
            query={constants.CollectionConstants.DOMAINID: f"/api/v1/asset/DeviceRegistrations/{domain_id}"}
        )

        merged_objects = []

        # Iterate through each item in response data
        for item in response_data:
            # Initialize merged object with the item data
            merged_object = item.copy()

            # Extract and validate event_id
            event_id = item.get("event", {}).get("id")
            if not event_id:
                self.logger.warning(f"message=metric_collection | Missing event Id. Skipping item: {item}")
                continue

            # Construct account-specific fan ID and fetch matching fan data
            acc_fan_id = f"{account_name}_{event_id.split('/')[-1]}"
            matched_fan = self.get_record_by_key(fan_data, acc_fan_id)
            if not matched_fan:
                self.logger.warning(
                    f"message=metric_collection | No fan data for Id: {acc_fan_id}. "
                    f"Skipping. {domain_id}"
                )
                continue

            # Remove unnecessary keys from matched fan data
            matched_fan.pop("_key", None)
            matched_fan.pop("account_name", None)

            # Update merged object with fan and domain data
            merged_object["event"].update(matched_fan)
            merged_object["event"].update(domain_data)

            # Extract and validate fan module key
            fanmodule_key = (
                matched_fan.get("FanModuleMoid").split("/")[-1]
                if matched_fan.get("FanModuleMoid")
                else None
            )
            if fanmodule_key is None:
                self.logger.warning(
                    f"message=metric_collection | No FanModuleMoid found for fan Id: {event_id.split('/')[-1]}. "
                    "Skipping."
                )
                continue

            # Construct account-specific fan module key and fetch matching fan module data
            acc_fanmodule_key = f"{account_name}_{fanmodule_key}"
            matched_fanmodule = self.get_record_by_key(fanmodule_data, acc_fanmodule_key)
            if not matched_fanmodule:
                self.logger.warning(
                    "message=metric_collection | No fan module data "
                    f"for key: {fanmodule_key}. Skipping."
                )
                continue

            # Remove unnecessary keys from matched fan module data
            matched_fanmodule.pop("_key", None)
            matched_fanmodule.pop("account_name", None)

            # Update merged object with parent data
            merged_object["event"]["ParentId"] = matched_fanmodule.get("ParentId", None)

            # Extract and validate parent data
            parent_key = matched_fanmodule.get("AncestorsId", None)
            parent_type = matched_fanmodule.pop("AncestorsType", None)
            if not parent_type or not parent_key:
                self.logger.warning(
                    "message=metric_collection | Invalid parent data "
                    f"for module key: {fanmodule_key}. Skipping."
                )
                continue

            self.logger.debug(
                f"message=metric_collection | Fanmodule's Ancestors ID: {parent_key} and Ancestors Type: {parent_type}"
            )

            # Fetch parent collection and match parent data
            parent_collection = collections.get(self.get_mapped_value(parent_type))
            matched_parent = self.get_record_by_key(parent_collection, f"{account_name}_{parent_key}")
            if matched_parent:
                merged_object["event"]["HostName"] = matched_parent.get("HostName", None)
                merged_object["event"]["host.tags"] = matched_parent.get("HostTags", None)
                merged_object["event"]["assetDrMoid"] = matched_parent.get("assetDrMoid", None)

            # Append merged object to the list of merged objects
            merged_objects.append(merged_object)

        self.logger.debug(
            "message=metric_collection | Completed merging Fan data for "
            f"Domain: {domain_id}, Count: {len(merged_objects)}, in {time.time() - start_time_fan:.2f} seconds."
        )
        return merged_objects

    def merge_host_data(
        self,
        kwargs: dict
    ) -> list:
        """
        Merge host data with dimensions data based on provided response and account details.

        Args:
            kwargs: A dictionary containing the following keys:
                - response_data (list): List of response items containing host data.
                - account_name (str): Name of the account.
                - domain_id (str): ID of the domain.
                - domain_data (dict): Dictionary containing domain data.
                - collections (dict): Dictionary of collections.

        Returns:
            list: Merged objects containing metrics and dimensions.
        """
        # Extract necessary data from kwargs
        response_data = kwargs.get("response_data")
        account_name = kwargs.get("account_name")
        domain_id = kwargs.get("domain_id")
        domain_data = kwargs.get("domain_data")
        collections = kwargs.get("collections")

        start_time_host = time.time()
        self.logger.info(
            "message=metric_collection | Host Data Merging Started, "
            f"Total Host records for Domain: {domain_id} are {len(response_data)}"
        )

        merged_objects = []
        for item in response_data:
            try:
                # Extract and validate host_id
                event_host_id = item.get("event", {}).get("host.id", "")
                if not event_host_id or event_host_id.count("/") < 2:
                    self.logger.warning(
                        f"message=metric_collection | Invalid or missing host.id: {event_host_id}. Skipping."
                    )
                    continue

                # Parse host_id and construct keys
                host_id_parts = event_host_id.split("/")
                acc_host_id = f"{account_name}_{host_id_parts[-1]}"
                host_key = f"{host_id_parts[-3]}.{host_id_parts[-2]}"
                host_key_mapped = self.get_mapped_value(host_key)
                host_collection = collections.get(self.get_mapped_value(host_key_mapped))

                if not host_collection:
                    self.logger.warning(
                        f"message=metric_collection | No collection found for host_key: {host_key_mapped}. Skipping."
                    )
                    continue

                # Retrieve host data
                host_data = self.get_record_by_key(host_collection, acc_host_id)
                if not host_data:
                    self.logger.warning(
                        f"message=metric_collection | No data found for host_id={acc_host_id} and "
                        f"key={host_key_mapped}."
                    )
                    continue

                # Remove unnecessary keys from host data
                host_data.pop("_key", None)
                host_data.pop("account_name", None)
                host_data.pop("hwChassisNumber", None)

                # Merge host and domain data into the item
                merged_object = item.copy()
                merged_object["event"].update(host_data)
                merged_object["event"].update(domain_data)
                if 'HostTags' in merged_object['event']:
                    merged_object['event']['host.tags'] = merged_object['event'].pop('HostTags')
                merged_objects.append(merged_object)

            except KeyError as e:
                self.logger.error(
                    f"message=metric_collection | KeyError={str(e)} | item={item}"
                )
            except Exception as e:
                self.logger.error(
                    f"message=metric_collection | UnexpectedError={str(e)} | item={item}"
                )

        self.logger.debug(
            f"message=metric_collection | Completed merging host data for Domain: {domain_id}, "
            f"Count: {len(merged_objects)}, in {time.time() - start_time_host:.2f} seconds."
        )
        return merged_objects

    def merge_memory_data(
        self, kwargs: dict
    ) -> list:
        """
        Merge memory data with dimensions data based on provided response and account details.

        This function fetches memory data for the provided domain and account. It then iterates
        through the response data and extracts the memory Id and account-specific Id. Using the
        account-specific Id, it fetches the memory data and validates that it has a parent Id and
        parent type. It then fetches the parent data and merges the memory data, parent data, and
        domain data together.

        Args:
            kwargs (dict): A dictionary containing the following keys:
                - response_data (list): List of response items containing host data.
                - account_name (str): Name of the account.
                - domain_id (str): ID of the domain.
                - domain_data (dict): Dictionary containing domain data.
                - collections (dict): Dictionary of collections.

        Returns:
            list[dict]: Merged objects containing metrics and dimensions.
        """
        response_data = kwargs.get("response_data")
        account_name = kwargs.get("account_name")
        domain_id = kwargs.get("domain_id")
        domain_data = kwargs.get("domain_data")
        collections = kwargs.get("collections")

        start_time_memory = time.time()
        self.logger.info(
            "message=metric_collection | Memory Data Merging Started, "
            f"Total Memory records for Domain: {domain_id} are {len(response_data)}"
        )
        # Fetch all memory data for the domain
        all_memory_data = self.kvstore_manager.get(
            collection_name=constants.CollectionConstants.MEMORY_UNIT,
            query={constants.CollectionConstants.DOMAINID: f"/api/v1/asset/DeviceRegistrations/{domain_id}"}
        )

        merged_objects = []
        for item in response_data:
            try:
                # Validate and extract event Id
                event_id = item.get("event", {}).get("id", "")
                if not event_id:
                    self.logger.warning(
                        f"message=metric_collection | Missing 'event.id'. Skipping item: {item}"
                    )
                    continue

                # Construct memory Id and account-specific Id
                memory_id = event_id.split("/")[-1]
                acc_memory_id = f"{account_name}_{memory_id}"

                # Fetch memory data
                memory_data = self.get_record_by_key(all_memory_data, acc_memory_id)
                if not memory_data:
                    self.logger.warning(
                        f"message=metric_collection | No data found for memory_id={memory_id} | account={account_name}"
                    )
                    continue

                # Extract and validate parent data
                memory_parent_id = memory_data.pop("ParentId").split("/")[-1]
                memory_parent_type = memory_data.pop("ParentType", None)
                memory_data.pop("ParentId", None)
                if not memory_parent_id or not memory_parent_type:
                    self.logger.error(
                        f"message=metric_collection | Missing parent details for memory_id={memory_id}"
                    )
                    continue

                acc_memory_parent_id = f"{account_name}_{memory_parent_id}"

                # Fetch parent data
                memory_collection = collections.get(self.get_mapped_value(memory_parent_type))
                memory_parent_data = self.get_record_by_key(memory_collection, acc_memory_parent_id)
                if not memory_parent_data:
                    self.logger.warning(
                        f"message=metric_collection | No parent data found for parent_id={memory_parent_id} | "
                        f"parent_type={memory_parent_type}"
                    )
                    continue

                # Remove unnecessary keys
                memory_data.pop("_key", None)
                memory_data.pop("account_name", None)
                memory_parent_data.pop("_key", None)
                memory_parent_data.pop("account_name", None)
                memory_parent_data.pop("account_name", None)
                memory_parent_data.pop("ParentName", None)
                memory_parent_data.pop("hwChassisNumber", None)
                memory_parent_data.pop("Model", None)
                memory_parent_data.pop("Name", None)
                memory_parent_data.pop("serial", None)
                memory_parent_data.pop("HostId", None)

                # Merge memory data, parent data, and domain data
                merged_object = item.copy()
                merged_object["event"].update(memory_data)
                merged_object["event"].update(memory_parent_data)
                merged_object["event"].update(domain_data)
                if 'HostTags' in merged_object['event']:
                    merged_object['event']['host.tags'] = merged_object['event'].pop('HostTags')
                merged_objects.append(merged_object)

            except KeyError as e:
                self.logger.error(
                    f"message=metric_collection | KeyError={str(e)} | item={item}"
                )
            except Exception as e:
                self.logger.error(
                    f"message=metric_collection | UnexpectedError={str(e)} | item={item}"
                )

        # Log completion stats
        self.logger.debug(
            "message=metric_collection | Completed merging Memory data for "
            f"Domain: {domain_id}, Count: {len(merged_objects)}, in {time.time() - start_time_memory:.2f} seconds."
        )

        return merged_objects

    def merge_temperature_data(
        self,
        kwargs: dict
    ) -> list:
        """
        Merge Temperature data with dimensions data based on provided response and account details.

        This function fetches Temperature data for the provided domain and account. It then iterates
        through the response data and extracts the Temperature Id and account-specific Id. Using the
        account-specific Id, it fetches the Temperature data and validates that it has a parent Id and
        parent type. It then fetches the parent data and merges the Temperature data, parent data, and
        domain data together.

        Args:
            kwargs: A dictionary containing the following keys:
                - response_data (list): List of response items containing host data.
                - account_name (str): Name of the account.
                - domain_id (str): ID of the domain.
                - domain_data (dict): Dictionary containing domain data.
                - collections (dict): Dictionary of collections.

        Returns:
            list: Merged objects containing metrics and dimensions.
        """
        response_data = kwargs.get("response_data", [])
        account_name = kwargs.get("account_name", "")
        domain_id = kwargs.get("domain_id", "")
        domain_data = kwargs.get("domain_data", {})
        collections = kwargs.get("collections", {})
        start_time_temp = time.time()
        self.logger.info(
            "message=metric_collection | Temperature Data Merging Started, "
            f"Total Temperature records for Domain: {domain_id} are {len(response_data)}"
        )
        # Update collections with processor, computeboard, transceiver, etherhostports, etherphysicalports, and
        # fcphysicalports data
        collections.update({
            "processorunit": self.kvstore_manager.get(
                collection_name=constants.CollectionConstants.PROCESSOR_UNIT,
                query={constants.CollectionConstants.DOMAINID: f"/api/v1/asset/DeviceRegistrations/{domain_id}"}
            ),
            "computeboard": self.kvstore_manager.get(
                collection_name=constants.CollectionConstants.COMPUTE_BOARD,
                query={constants.CollectionConstants.DOMAINID: f"/api/v1/asset/DeviceRegistrations/{domain_id}"}
            ),
            "transceiver": self.kvstore_manager.get(
                collection_name=constants.CollectionConstants.TRANSCEIVER,
                query={constants.CollectionConstants.DOMAINID: f"/api/v1/asset/DeviceRegistrations/{domain_id}"}
            ),
            "etherhostports": self.kvstore_manager.get(
                collection_name=constants.CollectionConstants.ETHER_HOST_PORTS,
                query={constants.CollectionConstants.DOMAINID: f"/api/v1/asset/DeviceRegistrations/{domain_id}"}
            ),
            "etherphysicalports": self.kvstore_manager.get(
                collection_name=constants.CollectionConstants.ETHER_PHYSICAL_PORTS,
                query={constants.CollectionConstants.DOMAINID: f"/api/v1/asset/DeviceRegistrations/{domain_id}"}
            ),
            "fcphysicalports": self.kvstore_manager.get(
                collection_name=constants.CollectionConstants.FC_PHYSICAL_PORTS,
                query={constants.CollectionConstants.DOMAINID: f"/api/v1/asset/DeviceRegistrations/{domain_id}"}
            ),
            "graphicscard": self.kvstore_manager.get(
                collection_name=constants.CollectionConstants.GRAPHICSCARD,
                query={constants.CollectionConstants.DOMAINID: f"/api/v1/asset/DeviceRegistrations/{domain_id}"}
            )
        })
        merged_objects = []
        for item in response_data:
            try:
                # Validate and extract event Id
                event_id = item.get("event", {}).get("id", "")
                if not event_id:
                    self.logger.warning(
                        f"message=metric_collection | Missing 'id' in event data. Skipping item: {item}"
                    )
                    continue
                # Extract temperature Id and type
                temperature_id = event_id.split("/")[-1]
                temperature_type = f"{event_id.split('/')[-3]}.{event_id.split('/')[-2]}"
                acc_temperature_id = f"{account_name}_{temperature_id}"
                temperature_collection = collections.get(self.get_mapped_value(temperature_type))
                # Process temperature data based on its type
                if self.get_mapped_value(temperature_type) in ["transceiver"]:
                    temperature_data = self.get_record_by_key(temperature_collection, acc_temperature_id)
                    if not temperature_data:
                        self.logger.warning(
                            "message=metric_collection | No data found for "
                            f"temperature_id={temperature_id} in {temperature_type}"
                        )
                        continue
                    # Extract and validate parent data
                    parent_id_parts = temperature_data.get("ParentId").split("/")
                    temperature_parent_id = parent_id_parts[-1]
                    temperature_parent_type = f'{parent_id_parts[-3]}{parent_id_parts[-2]}'
                    if not temperature_parent_id:
                        self.logger.warning(
                            "message=metric_collection | Missing parent details for "
                            f"temperature_id={temperature_id} in {temperature_type}"
                        )
                        continue
                    acc_temperature_parent_id = f"{account_name}_{temperature_parent_id}"
                    temperature_parent_collection = collections.get(self.get_mapped_value(temperature_parent_type))
                    temperature_parent_data = self.get_record_by_key(
                        temperature_parent_collection, acc_temperature_parent_id
                    )
                    temperature_data['ParentName'] = temperature_parent_data.get('Name', None)
                    # Extract and validate host data
                    temperature_host_id = temperature_data.get("HostId").split("/")[-1]
                    if not temperature_host_id:
                        self.logger.warning(
                            "message=metric_collection | Missing host details for "
                            f"temperature_id={temperature_id} in {temperature_type}"
                        )
                        continue
                    acc_temperature_host_id = f"{account_name}_{temperature_host_id}"
                    temperature_host_collection = collections.get("networkelements")
                    temperature_host_data = self.get_record_by_key(temperature_host_collection, acc_temperature_host_id)
                    temperature_data['HostName'] = temperature_host_data.get('Name', None)
                    temperature_data['HostType'] = temperature_host_data.get('HostType', None)
                    temperature_data['host.tags'] = temperature_host_data.get('HostTags', None)
                    temperature_data['assetDrMoid'] = temperature_host_data.get('assetDrMoid', None)
                elif self.get_mapped_value(temperature_type) in ["processorunit", "computeboard"]:
                    temperature_data = self.get_record_by_key(temperature_collection, acc_temperature_id)
                    if not temperature_data:
                        self.logger.warning(
                            "message=metric_collection | No data found for "
                            f"temperature_id={temperature_id} in {temperature_type}"
                        )
                        continue
                    # Extract and validate parent data
                    temperature_parent_id = temperature_data.pop("ParentId").split("/")[-1]
                    temperature_parent_type = temperature_data.pop("ParentType", None)
                    if not temperature_parent_id or not temperature_parent_type:
                        self.logger.warning(
                            "message=metric_collection | Missing parent details for "
                            f"temperature_id={temperature_id} in {temperature_type}"
                        )
                        continue
                    acc_temperature_parent_id = f"{account_name}_{temperature_parent_id}"
                    temperature_collection = collections.get(self.get_mapped_value(temperature_parent_type))
                    temperature_data = self.get_record_by_key(temperature_collection, acc_temperature_parent_id)
                    if not temperature_data:
                        self.logger.warning(
                            f"message=metric_collection | No data found for parent_id={temperature_parent_id} "
                            f"in {temperature_parent_type}"
                        )
                        continue
                else:
                    # Handle non-processor/computeboard temperature data
                    temperature_data = self.get_record_by_key(temperature_collection, acc_temperature_id)
                    if not temperature_data:
                        self.logger.warning(
                            "message=metric_collection | No data found for "
                            f"temperature_id={temperature_id} in {temperature_type}"
                        )
                        continue
                # Clean up temperature data
                temperature_data.pop("_key", None)
                temperature_data.pop("Name", None)
                temperature_data.pop("account_name", None)
                temperature_data.pop("hwChassisNumber", None)
                # Update merged object with data
                merged_object = item.copy()
                merged_object["event"].update(temperature_data)
                merged_object["event"].update(domain_data)
                merged_object["event"].update({"hwTemperatureState": "ok", "hwtype": "temperature"})
                if 'HostTags' in merged_object['event']:
                    merged_object['event']['host.tags'] = merged_object['event'].pop('HostTags')
                merged_objects.append(merged_object)
            except KeyError as e:
                self.logger.error(
                    f"message=metric_collection | KeyError={str(e)} | item={item}"
                )
            except Exception as e:
                self.logger.error(
                    f"message=metric_collection | UnexpectedError={str(e)} | item={item}"
                )
        self.logger.debug(
            "message=metric_collection | Completed merging Temperature data for Domain: "
            f"{domain_id}, Count: {len(merged_objects)}, in {time.time() - start_time_temp:.2f} seconds."
        )
        return merged_objects

    def merge_network_data(
        self,
        kwargs: dict
    ) -> list:
        """
        Merge Network data with dimensions data based on provided response and account details.

        This function takes the response data and account details as input and merges the network data
        with the dimensions data. It fetches the network data from the KV store and verifies the existence
        of the parent data. If the parent data is missing, it is skipped.

        Args:
            kwargs (dict): A dictionary containing the following keys:
                - response_data (list): List of response items containing host data.
                - account_name (str): Name of the account.
                - domain_id (str): ID of the domain.
                - domain_data (dict): Dictionary containing domain data.
                - collections (dict): Dictionary of collections.

        Returns:
            list: Merged objects containing metrics and dimensions.
        """
        response_data = kwargs.get("response_data", [])
        account_name = kwargs.get("account_name", "")
        domain_id = kwargs.get("domain_id", "")
        domain_data = kwargs.get("domain_data", {})
        collections = kwargs.get("collections", {})

        start_time_network = time.time()
        self.logger.info(
            "message=metric_collection | Network Data Merging Started, "
            f"Total Network records for Domain: {domain_id} are {len(response_data)}"
        )

        # Load network-related data
        collection_names = [
            "etherhostports", "ethernetworkports", "etherphysicalports", "etherportchannels",
            "adapterhostfcinterfaces", "fcphysicalports", "networkvfcs", "networkvethernets",
            "fcportchannels", "adapterhostethinterfaces", "adapterextethinterfaces"
        ]
        for collection_name in collection_names:
            collections[collection_name] = self.kvstore_manager.get(
                collection_name=f"Cisco_Intersight_{collection_name}",
                query={constants.CollectionConstants.DOMAINID: f"/api/v1/asset/DeviceRegistrations/{domain_id}"}
            )

        collection_names = {
            "etherhostports": constants.CollectionConstants.ETHER_HOST_PORTS,
            "ethernetworkports": constants.CollectionConstants.ETHER_NETWORK_PORTS,
            "etherphysicalports": constants.CollectionConstants.ETHER_PHYSICAL_PORTS,
            "etherportchannels": constants.CollectionConstants.ETHER_PORT_CHANNELS,
            "adapterhostfcinterfaces": constants.CollectionConstants.ADAPTER_HOST_FC_INTERFACES,
            "fcphysicalports": constants.CollectionConstants.FC_PHYSICAL_PORTS,
            "networkvfcs": constants.CollectionConstants.NETWORK_VFCS,
            "networkvethernets": constants.CollectionConstants.NETWORK_VETHERNETS,
            "fcportchannels": constants.CollectionConstants.FC_PORT_CHANNELS,
            "adapterhostethinterfaces": constants.CollectionConstants.ADAPTER_HOST_ETH_INTERFACES,
            "adapterextethinterfaces": constants.CollectionConstants.ADAPTER_EXT_ETH_INTERFACES
        }

        for key, collection_name in collection_names.items():
            collections[key] = self.kvstore_manager.get(
                collection_name=collection_name,
                query={constants.CollectionConstants.DOMAINID: f"/api/v1/asset/DeviceRegistrations/{domain_id}"}
            )

        merged_objects = []
        for item in response_data:
            try:
                # Extract and validate event Id
                event_id = item.get("event", {}).get("id", "")
                if not event_id:
                    self.logger.warning(
                        f"message=metric_collection | Missing 'event.id'. Skipping item: {item}"
                    )
                    continue

                # Construct identifiers
                network_id = event_id.split("/")[-1]
                network_type = f"{event_id.split('/')[-3]}{event_id.split('/')[-2]}"
                acc_network_id = f"{account_name}_{network_id}"

                self.logger.debug(
                    f"message=metric_collection | Processing network_id={network_id}, type={network_type}"
                )

                # Fetch network data
                network_collection = collections.get(self.get_mapped_value(network_type))
                network_data = self.get_record_by_key(network_collection, acc_network_id)
                if not network_data:
                    self.logger.warning(
                        f"message=metric_collection | No data found for event={event_id}, "
                        f"network_id={network_id}, type={network_type}, "
                        f"acc_network_id: {acc_network_id}, "
                        f"network_data: {network_data}"
                    )
                    continue

                # Extract parent details
                network_parent_id = network_data.pop("AncestorsId", None)
                if network_parent_id and "/" in network_parent_id:
                    network_parent_id = network_parent_id.split("/")[-1]
                network_parent_type = network_data.pop("ParentType", None)

                if not network_parent_id or not network_parent_type:
                    self.logger.warning(
                        f"message=metric_collection | Missing parent details for network_id={network_id}"
                        f", network_type: {network_type}"
                    )
                    continue

                # Fetch parent data
                acc_network_parent_id = f"{account_name}_{network_parent_id}"
                network_parent_collection = collections.get(self.get_mapped_value(network_parent_type))

                network_parent_data = self.get_record_by_key(network_parent_collection, acc_network_parent_id)
                if not network_parent_data:
                    self.logger.warning(
                        f"message=metric_collection | No parent data found for parent_id={network_parent_id}, "
                        f"type={network_parent_type}"
                    )
                    continue
                network_parent_data.pop("Name", None)

                # Clean up network data
                network_data.pop("_key", None)
                network_data.pop("account_name", None)
                network_data.pop("hwNetworkPortRole", None)
                network_parent_data.pop("_key", None)
                network_parent_data.pop("account_name", None)
                if self.get_mapped_value(network_type) not in ["etherphysicalports", "fcphysicalports"]:
                    network_parent_data.pop("Model", None)
                network_parent_data.pop("ParentId", None)
                network_parent_data.pop("HostId", None)
                network_parent_data.pop("serial", None)
                if network_data.get("HostType", False):
                    network_parent_data.pop("HostType", None)

                # Merge data into the item
                merged_object = item.copy()
                merged_object["event"].update(domain_data)
                merged_object["event"].update(network_data)
                merged_object["event"].update(network_parent_data)
                if 'HostTags' in merged_object['event']:
                    merged_object['event']['host.tags'] = merged_object['event'].pop('HostTags')
                if 'HostId' in merged_object['event']:
                    merged_object['event'].pop('HostId')
                merged_objects.append(merged_object)

            except KeyError as e:
                self.logger.error(
                    f"message=metric_collection | KeyError={str(e)} | item={item}"
                )
            except Exception as e:
                self.logger.error(
                    f"message=metric_collection | UnexpectedError={str(e)} | item={item}"
                )
                self.logger.error(f"metric_collection traceback: {traceback.format_exc()}")

        # Log completion stats
        self.logger.debug(
            "message=metric_collection | Completed merging Network data for "
            f"Domain: {domain_id}, Count: {len(merged_objects)}, in {time.time() - start_time_network:.2f} seconds."
        )

        return merged_objects

    def merge_cpu_utilization_data(self, kwargs: dict) -> list:
        """
        Merge CPU Utilization data with dimensions data based on provided response and account details.

        Args:
            kwargs (dict): A dictionary containing the following keys:
                - response_data (list): List of response items containing host data.
                - account_name (str): Name of the account.
                - domain_id (str): ID of the domain.
                - domain_data (dict): Dictionary containing domain data.
                - collections (dict): Dictionary of collections.

        Returns:
            list: Merged objects containing metrics and dimensions.
        """
        response_data = kwargs.get("response_data", [])
        account_name = kwargs.get("account_name", "")
        domain_id = kwargs.get("domain_id", "")
        domain_data = kwargs.get("domain_data", {})
        collections = kwargs.get("collections", {})

        start_time_host = time.time()
        self.logger.info(
            "message=metric_collection | CPU Utilization Data Merging Started, "
            f"Total Host records for Domain: {domain_id} are {len(response_data)}"
        )
        merged_objects = []
        for item in response_data:
            try:
                # Extract and validate host_id
                event_host_id = item.get("event", {}).get("host.id", "")
                if not event_host_id or event_host_id.count("/") < 2:
                    self.logger.warning(
                        f"message=metric_collection | Invalid or missing host.id: {event_host_id}"
                        " for CPU Utilization. Skipping."
                    )
                    continue
                # Parse host_id and construct keys
                host_id_parts = event_host_id.split("/")
                acc_host_id = f"{account_name}_{host_id_parts[-1]}"
                host_key = f"{host_id_parts[-3]}.{host_id_parts[-2]}"
                host_key_mapped = self.get_mapped_value(host_key)
                host_collection = collections.get(self.get_mapped_value(host_key_mapped))
                if not host_collection:
                    self.logger.warning(
                        f"message=metric_collection | No collection found for host_key: {host_key_mapped}"
                        " for CPU Utilization. Skipping."
                    )
                    continue
                # Retrieve host data
                host_data = self.get_record_by_key(host_collection, acc_host_id)
                if not host_data:
                    self.logger.warning(
                        f"message=metric_collection | No data found for host_id={acc_host_id} and "
                        f"key={host_key_mapped} for CPU Utilization."
                    )
                    continue
                # Remove unnecessary keys
                host_data.pop("_key", None)
                host_data.pop("account_name", None)
                host_data.pop("hwChassisNumber", None)
                # Merge host and domain data into the item
                merged_object = item.copy()
                merged_object["event"].update(host_data)
                merged_object["event"].update(domain_data)
                if 'HostTags' in merged_object['event']:
                    merged_object['event']['host.tags'] = merged_object['event'].pop('HostTags')
                merged_objects.append(merged_object)
            except KeyError as e:
                self.logger.error(
                    f"message=metric_collection | KeyError={str(e)} | item={item}"
                )
            except Exception as e:
                self.logger.error(
                    f"message=metric_collection | UnexpectedError={str(e)} | item={item}"
                )
        self.logger.debug(
            f"message=metric_collection | Completed merging CPU Utilization data for Domain: {domain_id}, "
            f"Count: {len(merged_objects)}, in {time.time() - start_time_host:.2f} seconds."
        )
        return merged_objects
