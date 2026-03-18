"""This module provides helper functions specific for inputs."""
# This import is required to resolve the absolute paths of supportive modules
# implemented throughout the add-on. The relative imports used in other files
# of the add-on are resolved by importing this module.
import import_declare_test  # noqa: F401  # pylint: disable=unused-import # needed to resolve paths
from itertools import islice
import math
from intersight_helpers import (
    constants, metric_mapper
)
from copy import deepcopy
from datetime import datetime
import logging


class CommonHelper:
    """Helper functions for Metrics Data collection."""

    def __init__(self, logger: logging.Logger) -> None:
        """
        Initialize the CommonHelper class.

        This class contains common helper functions used by multiple inputs.

        Args:
            logger (logging.Logger): Logger instance used for logging messages.
        """
        # Keep a reference to the logger instance for logging messages
        self.logger = logger

        # Initialize the MetricMapper instance with the logger
        # MetricMapper is used to map the data to the correct format
        # for the metrics endpoint
        self.metric_mapper = metric_mapper.MetricMapper(logger)

    def round_up_to_nearest_time(self, dt: datetime, selected_interval: int) -> datetime:
        """
        Round up time to the nearest exact minute based on the user provided time interval.

        Args:
            dt (datetime.datetime): The datetime object to be rounded up.
            selected_interval (int): The time interval in minutes from the user that is used to round up the time.

        Returns:
            datetime.datetime: The datetime object rounded up to the nearest exact minute.
        """
        # Calculate the exact minute based on the selected interval
        self.logger.info(f"message=metric_collection | Selected Time Interval: {selected_interval} seconds")
        selected_interval = selected_interval // 60

        # Calculate the minute to round up to
        minutes = math.floor(dt.minute / selected_interval) * selected_interval

        # Create a new datetime object with the rounded up minute
        return dt.replace(minute=minutes, second=0, microsecond=0)

    def format_time_to_utc(self, timestamp: datetime) -> str:
        """
        Format a datetime object to a UTC ISO-8601 timestamp with millisecond precision.

        Args:
            timestamp (datetime.datetime): The datetime object to be formatted.

        Returns:
            str: The formatted timestamp in UTC ISO-8601 with millisecond precision.
        """
        # Set the seconds and microseconds to zero
        timestamp = timestamp.replace(second=0, microsecond=0)
        # Format the timestamp to ISO-8601
        return timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    def update_filter(self, params: dict, domain_ids: tuple) -> dict:
        """
        Update the filter parameter based on the key and domain Ids.

        This method appends the domain Ids filter to the existing filter
        parameters. If the "$filter" key is not present in the parameters,
        it creates the filter; otherwise, it appends the domain Ids filter
        to the existing filter.

        Args:
            params (dict): Existing parameters.
            domain_ids (tuple): Domain Ids to include in the filter.
            key (str): API key type.
            owners_filter (list): Keys requiring special handling for owners.

        Returns:
            dict: Updated parameters.
        """
        filter_query = f"Owners IN {domain_ids}"
        if params.get("$filter"):
            params["$filter"] += f" AND {filter_query}"
        else:
            params["$filter"] = filter_query

        self.logger.info(
            f'message=metric_collection | Added Domain filters: {filter_query}'
        )
        return params

    def update_fan_filter(self, params: dict, fanmodule_ids: tuple) -> dict:
        """
        Update the filter parameter based on the key and fanmodule Ids.

        Args:
            params (dict): Existing parameters.
            fanmodule_ids (tuple): fanmodule_ids to include in the filter.
            key (str): API key type.

        Returns:
            dict: Updated parameters.
        """
        # Create a filter query for the fanmodule Ids
        filter_query = f"Parent.Moid IN {fanmodule_ids}"

        # If the filter key is already present in the parameters,
        # append the filter to the existing filter
        if params.get("$filter"):
            params["$filter"] += f" AND {filter_query}"
        else:
            # otherwise, set the filter key to the filter query
            params["$filter"] = filter_query

        # Log the updated filter
        self.logger.info(
            f'message=metric_collection | Updated filter for Fan Dimension Collection: {filter_query}'
        )
        return params

    def add_filter_to_payload(self, domain_id: str, payload: dict) -> dict:
        """
        Add Domain.id filters in metrics payload.

        Args:
            domain_id (str): Domain Id to filter.
            payload (dict): Payload to update.

        Returns:
            dict: Updated payload with Domain.id filters.
        """
        # Add Domain.id filters in the payload
        payload["filter"]["fields"].append({
            # Filter type
            "type": "in",
            # Filter dimension
            "dimension": "intersight.domain.id",
            # Filter values
            "values": [f"/api/v1/asset/DeviceRegistrations/{domain_id}"]
        })

        # Log the updated filter
        self.logger.info(
            'message=metric_collection | Added Domain Id filter in the Payload'
        )
        return payload

    def chunk_list(self, iterable: list, size: int) -> list:
        """
        Yield successive chunks of a list of the specified size.

        This method divides the input list into smaller chunks of the specified
        size and returns each chunk as a generator.

        Args:
            iterable (list): The list to chunk.
            size (int): The chunk size.

        Returns:
            generator: Yields chunks of the original list.
        """
        # Convert the input iterable to an iterator
        iterable = iter(iterable)
        # Get the first chunk of the specified size
        chunk = list(islice(iterable, size))
        while chunk:
            # Yield the current chunk
            yield chunk
            # Get the next chunk
            chunk = list(islice(iterable, size))

    def enrich_payload_with_metrics(self, payload: dict, metrics_list: list) -> dict:
        """
        Update the payload with metrics aggregations and post-aggregations.

        Args:
            payload (dict): The existing payload.
            metrics_list (list): List of metrics to enrich.

        Returns:
            dict: Enriched metric payload.
        """
        for metric in metrics_list:
            if f"{metric}_aggregations" in payload:
                # Extend the existing payload with the metric aggregations
                payload["metric"]["aggregations"].extend(payload[f"{metric}_aggregations"])

            if f"{metric}_postAggregations" in payload:
                # Extend the existing payload with the metric post aggregations
                payload["metric"]["postAggregations"].extend(payload[f"{metric}_postAggregations"])

        # Log a message to indicate the enrichment of payload
        self.logger.info(
            'message=metric_collection | Added Aggregations and PostAggregatios in the Paylaod'
        )
        # Return the enriched payload
        return payload["metric"]

    def collect_inventory(self, kwargs: dict) -> bool:
        """
        Collect inventory for a specified time interval and API attribute.

        Args:
            kwargs (dict): A dictionary containing the following keys:
                - account_name (str): The name of the account.
                - api_items (dict): A dictionary of API items to collect.
                - last_checkpoint (str): The last checkpoint value.
                - kvstore_helper (object): The kvstore helper object.
                - rest_helper (object): The rest helper object.

        Returns:
            bool: A boolean indicating if collection was successful.
        """
        account_name = kwargs["account_name"]
        api_items = kwargs["api_items"]
        last_checkpoint = kwargs["last_checkpoint"]
        kvstore_helper = kwargs["kvstore_helper"]
        rest_helper = kwargs["rest_helper"]

        # Log the API items to be processed
        self.logger.info(
            f"message=metric_collection | Processing API items: {api_items}"
        )
        # Initialize return value to True
        return_value = True
        # Iterate over the API items
        for key, value in api_items.items():
            # Log the start of inventory collection for the key
            self.logger.info(
                f"message=metric_collection | Starting inventory collection for key: {key}"
            )
            # Create a deep copy of the params
            params = deepcopy(value["params"])

            # Add checkpoint filter to params if last_checkpoint exists
            if last_checkpoint:
                # Create a filter string
                checkpoint_filter = f"ModTime gt {last_checkpoint}"
                # Add the filter to the params
                if params.get("$filter", ""):
                    # If params already has a filter, add the checkpoint filter
                    params["$filter"] = (
                        f"{params.get('$filter', '')} AND {checkpoint_filter}".strip()
                    )
                else:
                    # If params does not have a filter, add the checkpoint filter
                    params["$filter"] = f"{checkpoint_filter}".strip()

            # Handle domains
            if key != "domains":
                # Get the list of domains for the account
                domains_list = kvstore_helper.get(
                    constants.CollectionConstants.DOMAINS,
                    [constants.CollectionConstants.KEY],
                    {constants.CollectionConstants.ACCOUNT_NAME: account_name},
                )
                # Log the domains list
                self.logger.info(
                    f"message=metric_collection | Updating Domain IDs in filters: {domains_list}"
                )
                # If no domains are found, log an error and break
                if not domains_list:
                    self.logger.error(
                        f"No Domain IDs found for key: {key}. Skipping."
                    )
                    return_value = False
                    break
                # Get the list of domain IDs
                domain_ids = [item["_key"].split("_")[-1] for item in domains_list]
                # Log the domain IDs
                self.logger.debug(
                    f"message=metric_collection | Domain Ids: {domain_ids}"
                )
            else:
                # If key is domains, set domain_ids to None
                domain_ids = None

            # Initialize local return value to True
            local_return_value = True
            # Process in chunks if key is fan
            if key == "fan":
                # Log a message to indicate the start of fan inventory collection
                self.logger.info(
                    "message=metric_collection | Updating Fan Filter with FanModule."
                )
                # Get the list of fan modules for the account
                fan_modules = kvstore_helper.get(
                    constants.CollectionConstants.FAN_MODULE,
                    [constants.CollectionConstants.KEY],
                    {constants.CollectionConstants.ACCOUNT_NAME: account_name},
                )
                # If no fan modules are found, log an error and skip
                if not fan_modules:
                    self.logger.error(
                        "message=metric_collection | No FanModule IDs found. Skipping fan collection."
                    )
                    continue
                # Get the list of fan module IDs
                fan_module_ids = [
                    item["_key"].split("_")[-1] for item in fan_modules
                ]
                # Log the fan module IDs
                self.logger.debug(
                    f"message=metric_collection | FanModule Ids: {fan_module_ids}"
                )
                # Process fan modules in chunks of 25
                for fanmodule_chunk in self.chunk_list(
                    fan_module_ids, size=25
                ):
                    # Create the chunk kwargs
                    chunk_kwargs = {
                        "key": key,
                        "endpoint": value["endpoint"],
                        "base_params": params,
                        "id_chunk": fanmodule_chunk,
                        "account_name": account_name,
                        "rest_helper": rest_helper,
                        "kvstore_helper": kvstore_helper,
                        "domain_ids": domain_ids,
                    }
                    # Process the chunk
                    local_return_value = self._process_chunk(chunk_kwargs)
            elif key == "domains":
                # Create the chunk kwargs for domains
                chunk_kwargs = {
                    "key": key,
                    "endpoint": value["endpoint"],
                    "base_params": params,
                    "id_chunk": None,
                    "account_name": account_name,
                    "rest_helper": rest_helper,
                    "kvstore_helper": kvstore_helper,
                }
                # Process the chunk
                local_return_value = self._process_chunk(chunk_kwargs)
            else:
                # Process other keys in chunks of 25
                for domain_chunk in self.chunk_list(domain_ids, size=25):
                    # Create the chunk kwargs
                    chunk_kwargs = {
                        "key": key,
                        "endpoint": value["endpoint"],
                        "base_params": params,
                        "id_chunk": domain_chunk,
                        "account_name": account_name,
                        "rest_helper": rest_helper,
                        "kvstore_helper": kvstore_helper,
                    }
                    # Process the chunk
                    local_return_value = self._process_chunk(chunk_kwargs)
            # Update return value
            if return_value:
                return_value = local_return_value

        # Return the final return value
        return return_value

    def _process_chunk(self, kwargs: dict) -> bool:
        """
        Process a single chunk of domain IDs or the entire dataset if no chunk is provided.

        Args:
            kwargs: A dictionary containing the following keys:
                - key (str): The name of the object type.
                - endpoint (str): The endpoint for the API call.
                - base_params (dict): The base parameters for the API call.
                - id_chunk (list): A list of IDs to process.
                - account_name (str): The name of the account.
                - rest_helper (object): The rest helper object.
                - kvstore_helper (object): The kvstore helper object.
                - domain_ids (list): A list of domain IDs.
        Returns:
            bool: True if processing is successful, False if there is an error.
        """
        key = kwargs["key"]
        endpoint = kwargs["endpoint"]
        base_params = kwargs["base_params"]
        id_chunk = kwargs["id_chunk"]
        account_name = kwargs["account_name"]
        rest_helper = kwargs["rest_helper"]
        kvstore_helper = kwargs["kvstore_helper"]
        domain_ids = kwargs.get("domain_ids", None)

        try:
            # Fetch paginated data
            results = rest_helper.paginate_data(endpoint, base_params, key=key, id_chunk=id_chunk)

            # Apply additional filters if key is 'physicalsummary'
            if key == "physicalsummary":
                results = self.license_filter(results)

            # Initialize list to store batch of events
            events_batch = []
            mergeable_data_kwargs = {
                "account_name": account_name,
                "id_chunk": id_chunk,
                "domain_ids": domain_ids,
                "object_type": key
            }

            # Process each event and prepare for upsertion
            for event in results:
                mergeable_data_kwargs["event"] = event
                merged_event = self.metric_mapper.create_mergeable_data(mergeable_data_kwargs)
                if merged_event:
                    events_batch.append(merged_event)

            # Upsert processed events into kvstore
            kvstore_helper.upsert(events_batch, f"Cisco_Intersight_{key}")

            self.logger.info(
                f"message=metric_collection | Upserted {len(events_batch)} records for key: {key}"
            )

            # Log if no events were processed
            if not events_batch:
                self.logger.info(
                    f"message=metric_collection | Inventory dimension updates not found for key: {key}."
                )
                return True

            self.logger.info(
                f"message=metric_collection | Inventory dimension updates found for key: {key}."
            )
            return True
        except Exception as e:
            # Log error and return False if an exception occurs
            self.logger.error(
                f"message=metric_collection | Error processing chunk for key {key}: {e}"
            )
            return False

    def fetch_client_id_expire_timestamp(self, client_id: str, rest_helper: object) -> tuple:
        """
        Fetch Client Id expiration timestamp from the Client Id.

        Args:
            client_id (str): Client Id to fetch the expiration timestamp for.
            rest_helper (obj): Rest Helper object.

        Returns:
            tuple: A tuple containing the expiration timestamp and whether the client id never expires.
        """
        # Fetch the client details including the expiration timestamp
        client_details = rest_helper.get_client_id_details(
            client_id=client_id
        )
        # Extract the expiration timestamp and whether it never expires
        client_expire_timestamp = client_details["ExpiryDateTime"]
        client_never_expiring = client_details["IsNeverExpiring"]
        return client_expire_timestamp, client_never_expiring

    def check_license_tier(self, managed_object: dict) -> bool:
        """
        Check if the managed object has a supported license tier.

        Args:
            managed_object (dict): Managed object to check.

        Returns:
            bool: True if the managed object has a supported license tier, False otherwise.
        """
        # Iterate over the tags of the managed object
        for tag in managed_object.get("Tags", []):
            # Check if the tag is a license tier tag
            # and if its value is in the list of supported license tiers
            if (
                tag["Key"] == "Intersight.LicenseTier"
                and tag["Value"] in constants.Endpoints.SUPPORTED_LICENSE_TIERS
            ):
                # If it is, return True
                return True

        # If no supported license tier is found, return False
        return False

    def license_filter(self, servers_list: list, parent_key_identifier: str = "") -> list:
        """
        Filter servers based on license tier.

        If the parent_key_identifier is provided, it is used to access the parent
        object from the server object. The parent object is then checked for
        supported license tier.

        Args:
            servers_list (list): List of server objects.
            parent_key_identifier (str, optional): Key to access the parent
                object from the server object. Defaults to "".

        Returns:
            list: List of server objects filtered based on license tier.
        """
        filtered_list = []
        for search_api_item in servers_list:
            if parent_key_identifier:
                try:
                    # Access the parent object from the server object
                    parent_obj = search_api_item[parent_key_identifier]
                except KeyError as e:
                    self.logger.error(
                        "message=filter_servers | Error occurred while"
                        " filtering servers based on license Tier. "
                        f"Error: {e}"
                    )
                    raise
            else:
                # Parent object is the server object itself
                parent_obj = search_api_item

            # Check if the parent object has a supported license tier
            if self.check_license_tier(parent_obj):
                filtered_list.append(search_api_item)

        return filtered_list

    def get_filter_condition(self, checkpoint_value: str, filter_flag: bool = True) -> str:
        """
        Create filter condition based on the checkpoint value.

        Args:
            checkpoint_value (str): The checkpoint value.
            filter_flag (bool, optional): A flag to indicate if the filter
                condition should use the "gt" or "ge" operator. Defaults to True.

        Returns:
            str: The filter condition.
        """
        if checkpoint_value:
            if filter_flag:
                # Use "gt" operator if filter_flag is True
                operator = "gt"
            else:
                # Use "ge" operator if filter_flag is False
                operator = "ge"
            return f"ModTime {operator} {checkpoint_value}"
        else:
            # Return empty string if checkpoint_value is empty
            return ""

    def apply_additional_filter(self, base_filter_condition: str, filter: str) -> str:
        """
        Apply additional filter condition.

        Args:
            base_filter_condition (str): The base filter condition.
            filter (str): The additional filter condition.

        Returns:
            str: The combined filter condition.
        """
        condition = ""
        if base_filter_condition:
            condition = base_filter_condition

        if filter:
            # If base_filter_condition is not provided, use the filter as
            # the condition
            if not condition:
                condition = filter
            else:
                # If base_filter_condition is provided, append the filter
                # condition to it
                condition += f" AND {filter}"

        return condition
