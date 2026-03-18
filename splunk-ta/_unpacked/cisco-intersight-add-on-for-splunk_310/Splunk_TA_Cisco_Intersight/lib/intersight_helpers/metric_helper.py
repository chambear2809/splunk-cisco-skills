"""This module provides helper functions specific for metric input."""
# This import is required to resolve the absolute paths of supportive modules
# implemented throughout the add-on. The relative imports used in other files
# of the add-on are resolved by importing this module.
import import_declare_test
from datetime import datetime, timedelta
import pytz
from intersight_helpers import constants, common_helper, merge_helper, payload_constants, conf_helper
import copy
import logging
import time
from typing import Optional, List, Tuple, Dict, Any, Union


class MetricHelper:
    """
    Class MetricHelper provides helper functions specific for metric input.

    Attributes:
        logger: Logger object.
        kvstore_manager: KVStoreManager object.
        common_helper: CommonHelper object.
        merge_helper: MergeHelper object.
    """

    def __init__(self, logger: logging.Logger, kvstore_manager: merge_helper.KVStoreManager) -> None:
        """
        Init function for class MetricHelper.

        Args:
            logger (logging.Logger): Logger object.
            kvstore_manager (merge_helper.KVStoreManager): KVStoreManager object.
        """
        self.logger = logger
        self.kvstore_manager = kvstore_manager
        self.common_helper = common_helper.CommonHelper(self.logger)
        self.merge_helper = merge_helper.MergeHelper(self.logger, self.kvstore_manager)

    def collect_inventory(
        self,
        rest_helper,
        session_key: str,
        input_items: List[Dict[str, Any]],
        selected_metrics: List[str]
    ) -> Dict[str, bool]:
        """
        Collect inventory data based on checkpoints for 1-hour and 24-hour intervals.

        The function collects the inventory data for the given metrics and intervals.
        It first checks if the data was collected within the given time interval (1h or 24h).

        If the data is within the given interval, it skips the collection and returns the
        last collected data. If the data is older than the given interval, it collects the
        new data and updates the checkpoint.

        Args:
            rest_helper: RestHelper object.
            session_key (str): The session key to use for saving the checkpoint.
            input_items (list): A list of input items.
            selected_metrics (list): A list of selected metrics.

        Returns:
            dict: A dictionary with the metric as the key and the status as the value.
        """
        account_name = input_items[1]['global_account']
        new_checkpoint_value = constants.RequiredTime.formatted_current_time
        modified_selected_metrics = copy.deepcopy(selected_metrics)
        modified_selected_metrics.insert(0, 'domains')
        if 'host' in modified_selected_metrics:
            modified_selected_metrics.remove('host')
        if 'cpu_utilization' in modified_selected_metrics:
            modified_selected_metrics.remove('cpu_utilization')
        modified_selected_metrics.insert(1, 'common')
        # Add Common Inventory APIs needed for Network and Temperature
        if 'temperature' in modified_selected_metrics or 'network' in modified_selected_metrics:
            modified_selected_metrics.append('network_temprature')
        status_dict = {}
        for metric in modified_selected_metrics:
            for interval, hours in [("1h", 1), ("24h", 24)]:
                all_api_items = getattr(
                    constants.MetricsDimensions, f"inventory_checkpoint_key_{interval}_apis", {}
                ).items()
                api_items = self.filter_apis_by_metric(metric, all_api_items, interval)
                if not api_items:
                    continue
                checkpoint_key = f"Cisco_Intersight_{account_name}_{metric}_dimension_checkpoint_{interval}"
                last_checkpoint_value = dict(
                    conf_helper.get_checkpoint(
                        checkpoint_key, session_key, import_declare_test.ta_name
                    ) or {}
                )

                if self.is_within_interval(
                    last_checkpoint_value.get("last_fetched_time"), new_checkpoint_value, hours
                ):
                    self.logger.info(
                        f"message=metric_collection | Skipping {interval} inventory collection "
                        f"as interval is less than {hours} hour(s)."
                    )
                    status_dict[metric] = last_checkpoint_value.get("status")
                    continue

                self.logger.info(f"message=metric_collection | Starting {interval} inventory collection.")

                collect_inventory_kwargs = {
                    "account_name": account_name,
                    "last_checkpoint": last_checkpoint_value.get("last_fetched_time"),
                    "api_items": api_items,
                    "kvstore_helper": self.kvstore_manager,
                    "rest_helper": rest_helper
                }
                update_checkpoint = self.common_helper.collect_inventory(collect_inventory_kwargs)

                if update_checkpoint:
                    self.logger.info("message=metric_collection | Inventory Dimensions found updating checkpoint.")
                    conf_helper.save_checkpoint(
                        checkpoint_key, session_key, import_declare_test.ta_name,
                        {"last_fetched_time": new_checkpoint_value, "status": update_checkpoint}
                    )
                else:
                    last_checkpoint_value["status"] = update_checkpoint
                    conf_helper.save_checkpoint(
                        checkpoint_key, session_key, import_declare_test.ta_name,
                        last_checkpoint_value
                    )
                status_dict[metric] = update_checkpoint
        return status_dict

    def filter_apis_by_metric(
        self,
        metric_name: str,
        all_api_items: List[Tuple[str, str]],
        interval: str
    ) -> Dict[str, str]:
        """
        Filter the API items by the specified metric name.

        Args:
            metric_name (str): The name of the metric.
            all_api_items (List[Tuple[str, str]]): The list of all API items for the specified interval.
            interval (str): The interval for which the API items are applicable.

        Returns:
            Dict[str, str]: The filtered dictionary containing the API items for the specified metric.
        """
        metrics = getattr(constants.MetricsDimensions, "metrics_checkpoints", {})

        # Get the list of keys for the specified metric_name
        metric_keys = metrics.get(metric_name, [])
        dict_all_api_items = dict(all_api_items)

        filtered_dict = {}
        for key in metric_keys:
            if key in dict_all_api_items:
                filtered_dict[key] = dict_all_api_items[key]
            else:
                self.logger.info(
                    f"message=metric_collection | Key '{key}' not part of '{interval}' inventory update cycle."
                )

        return filtered_dict

    def is_within_interval(
        self,
        last_checkpoint_value: Optional[str],
        current_time_value: str,
        interval_hours: int
    ) -> bool:
        """
        Check if the last checkpoint is within the specified interval.

        Args:
            last_checkpoint_value (str): The last checkpoint time value.
            current_time_value (str): The current time value.
            interval_hours (int): The interval in hours.

        Returns:
            bool: If the last checkpoint is within the specified interval.
        """
        # Check if last_checkpoint_value is not None
        if last_checkpoint_value is not None:
            # Convert the last checkpoint and current time to datetime objects
            last_checkpoint = datetime.strptime(last_checkpoint_value, "%Y-%m-%dT%H:%M:%S.%fZ")
            current_time = datetime.strptime(current_time_value, "%Y-%m-%dT%H:%M:%S.%fZ")
            # Calculate the difference between the current time and the last checkpoint
            time_diff = (current_time - last_checkpoint).total_seconds()
            # Check if the difference is within the specified interval
            return time_diff < interval_hours * 3600
        return False

    def get_metrics_map(self) -> Dict[str, Dict[str, Union[List[str], str]]]:
        """
        Return the predefined metrics map.

        This dictionary maps the metric category to its corresponding key in the input item and default metrics.

        Args:
            None

        Returns:
            A dictionary with the metric categories as keys and dictionaries with 'key' and 'default' as values.
            The 'key' is used to retrieve the metric values from the input item and the 'default' is a
            list of default metrics for each category.
        """
        return {
            'network': {
                'key': 'network_metrics',
                'default': [
                    # Network metrics
                    "hw.network.bandwidth.utilization_receive",
                    "hw.network.bandwidth.utilization_transmit",
                    "hw.network.io_receive",
                    "hw.network.io_transmit",
                    # Network errors
                    "hw.errors_network_receive_crc",
                    "hw.errors_network_receive_all",
                    "hw.errors_network_transmit_all",
                    "hw.errors_network_receive_pause",
                    "hw.errors_network_transmit_pause",
                    "hw.network.packets_receive_ppp",
                    "hw.network.packets_transmit_ppp",
                    "hw.errors_network_receive_runt",
                    "hw.errors_network_receive_too_long",
                    "hw.errors_network_receive_no_buffer",
                    "hw.errors_network_receive_too_short",
                    "hw.errors_network_receive_discard",
                    "hw.errors_network_transmit_discard",
                    "hw.errors_network_transmit_deferred",
                    "hw.errors_network_late_collisions",
                    "hw.errors_network_carrier_sense",
                    "hw.errors_network_transmit_jabber"
                ],
            },
            'memory': {
                'key': 'memory_metrics',
                'default': [
                    # Memory metrics
                    "hw.errors_correctable_ecc_errors",
                    "hw.errors_uncorrectable_ecc_errors"
                ],
            },
            'host': {
                'key': 'host_power_energy_metrics',
                'default': [
                    # Host power and energy metrics
                    "hw.host.power",
                    "hw.host.energy"
                ],
            },
            'fan': {
                'default': [
                    # Fan metrics
                    'hw.fan.speed'
                ]
            },
            'temperature': {
                'default': [
                    # Temperature metrics
                    'hw.temperature'
                ]
            },
            'cpu_utilization': {
                'default': [
                    # cpu metrics
                    'hw.cpu.utilization_c0'
                ]
            }
        }

    def build_metrics_dict(
        self,
        selected_metrics: List[str],
        metrics_map: Dict[str, Dict[str, Union[List[str], str]]],
        input_item: Dict[str, Any]
    ) -> Dict[str, List[str]]:
        """
        Build and return a dictionary of metrics based on selected metrics and the predefined metrics map.

        Args:
            selected_metrics (List[str]): List of selected metrics.
            metrics_map (Dict[str, Dict[str, Union[List[str], str]]]): Predefined metrics map.
            input_item (Dict[str, Any]): Input item containing the metrics values.

        Returns:
            Dict[str, List[str]]: Dictionary of metrics.
        """
        metrics_dict = {}
        for metric in selected_metrics:
            # Check if the metric is in the predefined metrics map
            if metric in metrics_map:
                # Get the metric information from the metrics map
                metric_info = metrics_map[metric]
                # Get the metrics value from the input item
                metrics_value = input_item.get(metric_info.get('key', ''), '')

                # If the metric value is not 'All', split the value by comma
                if metrics_value != 'All':
                    metrics_dict[metric] = metrics_value.split(',')
                # Otherwise, use the default metrics for the category
                else:
                    metrics_dict[metric] = metric_info['default']

                # If the metric is fan or temperature, use the default metrics
                if metric in ['fan', 'temperature', 'cpu_utilization']:
                    metrics_dict[metric] = metric_info['default']

        return metrics_dict

    def update_account_info(
        self,
        session_key: str,
        input_item: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Fetch and update account credentials into the input item.

        Args:
            session_key (str): Session key to access the account credentials.
            input_item (dict): Input item containing the account name.

        Returns:
            dict: Updated input item with account credentials.
        """
        # Get the account info based on the session key and account name
        account_info = conf_helper.get_credentials(session_key=session_key, account_name=input_item['global_account'])
        # Update the input item with the account info
        input_item.update(account_info)

    def merge_responses_with_dimensions(
        self,
        response_data: List[Dict[str, Any]],
        category: str,
        account_name: str,
        domain_id: str
    ) -> List[Dict[str, Any]]:
        """
        Merge response data with dimensions based on the category.

        Args:
            response_data (List[Dict[str, Any]]): Response data from API.
            category (str): Category of metrics.
            account_name (str): Account name.
        Returns:
            List[Dict[str, Any]]: Merged response data.
        """
        # Mapping of category to merge function
        merge_functions = {
            # Fan metrics
            "fan": self.merge_helper.merge_fan_data,
            # Host metrics
            "host": self.merge_helper.merge_host_data,
            # Memory metrics
            "memory": self.merge_helper.merge_memory_data,
            # Network metrics
            "network": self.merge_helper.merge_network_data,
            # Temperature metrics
            "temperature": self.merge_helper.merge_temperature_data,
            # CPU Utilization metrics
            "cpu_utilization": self.merge_helper.merge_cpu_utilization_data
        }
        # Get the merge function based on the category
        merge_function = merge_functions.get(category)
        if not merge_function:
            self.logger.warning(f"Invalid category: {category}. No merge function available.")
            return []

        # Get the domain data
        domain_data = self.kvstore_manager.get(
            constants.CollectionConstants.DOMAINS,
            query={constants.CollectionConstants.KEY: f"{account_name}_{domain_id}"}
        )[0]

        if not domain_data:
            self.logger.warning(f"Domain Id {domain_id} missing. Skipping this domain.")
            return []
        # Remove unnecessary keys
        domain_data.pop("account_name", None)
        domain_data.pop("_key", None)

        # Pre-fetch required collections
        collections = {
            # Chassis collection
            "chassis": self.kvstore_manager.get(
                collection_name=constants.CollectionConstants.CHASSIS,
                query={constants.CollectionConstants.DOMAINID: f"/api/v1/asset/DeviceRegistrations/{domain_id}"}
            ),
            # Network elements collection
            "networkelements": self.kvstore_manager.get(
                collection_name=constants.CollectionConstants.NETWORK_ELEMENTS,
                query={constants.CollectionConstants.DOMAINID: f"/api/v1/asset/DeviceRegistrations/{domain_id}"}
            ),
            # Physical summary collection
            "physicalsummary": self.kvstore_manager.get(
                collection_name=constants.CollectionConstants.PHYSICAL_SUMMARY,
                query={constants.CollectionConstants.DOMAINID: f"/api/v1/asset/DeviceRegistrations/{domain_id}"}
            )
        }

        # Merge the response data with the domain data and collections
        merge_function_kwargs = {
            "response_data": response_data,
            "account_name": account_name,
            "domain_id": domain_id,
            "domain_data": domain_data,
            "collections": collections,
        }
        return merge_function(merge_function_kwargs)

    def get_time_interval(
        self,
        metrics_checkpoint_value: Optional[datetime],
        selected_interval: int,
        metrics_calc: int = 300,
    ) -> Tuple[List[str], str, str]:
        """
        Generate a time interval string, rounded to the nearest 15-minute floor interval.

        Args:
            metrics_checkpoint_value (datetime or str): The last checkpoint timestamp (datetime object or string).
            selected_interval (int): Interval in seconds (must be a multiple of 900 for 15-minute intervals).
            metrics_calc (int): Calculation buffer time in seconds. Default is 300.

        Returns:
            list[str]: Time intervals for the selected period.
            str: Updated checkpoint timestamp in ISO-8601 format.
            str: Start time of the first interval in ISO-8601 format.
        """
        self.logger.info("message=metric_collection | Generating time interval.")

        # Get current time with timezone information
        current_time = datetime.now(pytz.UTC)

        # Determine start time
        if metrics_checkpoint_value is None:
            # If no checkpoint, start from the current time minus the buffer interval
            start_time = self.common_helper.round_up_to_nearest_time(
                current_time - timedelta(seconds=selected_interval + metrics_calc), selected_interval
            )
        else:
            # Parse the checkpoint value from string to datetime object
            if isinstance(metrics_checkpoint_value, str):
                # Handle timezone conversion and format normalization
                checkpoint_str = metrics_checkpoint_value.replace("Z", "+00:00")

                # Fix single-digit hour format (e.g., 'T9:' -> 'T09:')
                if 'T' in checkpoint_str:
                    time_part = checkpoint_str.split('T')[1]
                    if ':' in time_part and len(time_part.split(':')[0]) == 1:
                        # Single digit hour, pad with zero
                        hour_part = time_part.split(":")[0]
                        checkpoint_str = checkpoint_str.replace(
                            f'T{hour_part}:', f'T0{hour_part}:'
                        )

                try:
                    metrics_checkpoint_value = datetime.fromisoformat(checkpoint_str)
                except ValueError as e:
                    self.logger.warning(
                        f"message=metric_collection | Failed to parse checkpoint datetime "
                        f"'{checkpoint_str}': {e}. Using current time."
                    )
                    # Fallback to current time minus interval if parsing fails
                    metrics_checkpoint_value = current_time - timedelta(seconds=selected_interval + metrics_calc)

            # Round up the checkpoint time to the nearest 15-minute interval
            start_time = self.common_helper.round_up_to_nearest_time(metrics_checkpoint_value, selected_interval)

        # Generate time intervals
        time_intervals = []
        new_time = start_time
        while new_time < current_time - timedelta(seconds=metrics_calc):
            # Calculate the end time of the current interval
            interval_end_time = new_time + timedelta(seconds=selected_interval)
            # If the next interval exceeds the current time, stop
            if interval_end_time > current_time - timedelta(seconds=metrics_calc):
                break
            # Format the start and end times to UTC ISO-8601 strings
            start_time_str = self.common_helper.format_time_to_utc(new_time)
            end_time_str = self.common_helper.format_time_to_utc(interval_end_time)
            # Add the time interval to the list
            time_intervals.append(f"{start_time_str}/{end_time_str}")
            # Move to the next interval
            new_time = interval_end_time

        # Log and return results
        self.logger.info(f"message=metric_collection | Time Intervals: {time_intervals}")
        return (
            time_intervals,
            self.common_helper.format_time_to_utc(new_time),
            self.common_helper.format_time_to_utc(start_time),
        )

    def fetch_metrics_data(
        self,
        kwargs: Dict[str, Any]
    ) -> Tuple[Dict[str, int], int]:
        """
        Fetch metrics data for the given category and metrics list.

        Args:
            category (str): The category of metrics.
            metrics_list (list): List of metrics to fetch.
            metrics_checkpoint_value (int): Checkpoint for metrics.
            interval_selected (int): Interval in seconds for data aggregation.
            account_name (str): Account name.
        Returns:
            tuple: Merged response data and updated checkpoint value.
        """
        category = kwargs["category"]
        metrics_list = kwargs["metrics_list"]
        metrics_checkpoint_value = kwargs["metrics_checkpoint_value"]
        interval_selected = kwargs["interval_selected"]
        account_name = kwargs["account_name"]
        event_ingestor = kwargs["event_ingestor"]
        rest_helper = kwargs["rest_helper"]
        start_time_category = time.time()
        self.logger.debug(
            f"message=metric_collection | {category} Metrics Started at {start_time_category}"
        )
        # Fetch the time intervals
        time_intervals, new_checkpoint, _ = self.get_time_interval(
            metrics_checkpoint_value, interval_selected
        )
        if not time_intervals:
            self.logger.info(
                "message=metric_collection | metrics data till the time already collected."
            )
            return {"event_count": 0, "last_fetched_time": metrics_checkpoint_value}

        self.logger.info(
            f"message=metric_collection | Collecting metrics for the time interval : {time_intervals}"
        )
        # Fetch domain IDs
        domains_list = self.kvstore_manager.get(
            constants.CollectionConstants.DOMAINS,
            [constants.CollectionConstants.KEY],
            {constants.CollectionConstants.ACCOUNT_NAME: account_name},
        )
        if not domains_list:
            self.logger.error(
                "No domains found for the account. Skipping the interval."
            )
            raise ValueError("Domains not found")

        domain_ids = tuple(item["_key"].split("_")[-1] for item in domains_list)
        if not domain_ids:
            raise ValueError("Empty domain IDs list")

        # Prepare the payload for the category
        payload_template = getattr(payload_constants.Payloads, category, None)  # get payload based on metrics type
        if not payload_template:
            self.logger.error(f"Payload template for category '{category}' not found.")
            return [], metrics_checkpoint_value

        total_event_count = 0
        enriched_payload = self.common_helper.enrich_payload_with_metrics(
            payload_template, metrics_list
        )  # add aggregations and post_aggregations based on what user has selected in input
        for time_interval in time_intervals:
            enriched_payload["intervals"] = time_interval  # add time interval to payload
            if interval_selected == 1800:  # add granularity based on user's selection, default PT15M
                enriched_payload["granularity"]["period"] = "PT30M"
            elif interval_selected == 3600:
                enriched_payload["granularity"]["period"] = "PT60M"

            # Process metrics data using batch handling logic
            fetch_enriched_stats_args = {
                "domain_ids": domain_ids,
                "enriched_payload": enriched_payload,
                "category": category,
                "account_name": account_name,
                "rest_helper": rest_helper
            }
            merged_data = self.fetch_enriched_stats(
                fetch_enriched_stats_args
            )  # collect data using prepared payload from timeseries api
            if not merged_data:
                self.logger.info(f"No events found for category {category}.")
                total_event_count += 0
            else:
                event_count = event_ingestor.ingest_metrics_data(merged_data, category)  # ingest data into splunk index
                total_event_count += event_count  # update total event count for logging

            self.logger.debug(
                f"message=metric_collection | {category} metrics completed in "
                f"{time.time() - start_time_category:.2f} seconds."
            )

        return {"event_count": total_event_count, "last_fetched_time": new_checkpoint}  # return count and checkpoint

    def fetch_enriched_stats(
        self, fetch_enriched_stats_args: dict
    ) -> list:
        """
        Handle processing of metrics collection for each domain ID.

        Args:
            domain_ids (tuple): Domain IDs to process.
            enriched_payload (dict): Payload enriched with metrics details.
            category (str): Category of metrics.
            account_name (str): Account name.

        Returns:
            list: Response data.
        """
        domain_ids = fetch_enriched_stats_args["domain_ids"]
        enriched_payload = fetch_enriched_stats_args["enriched_payload"]
        category = fetch_enriched_stats_args["category"]
        account_name = fetch_enriched_stats_args["account_name"]
        rest_helper = fetch_enriched_stats_args["rest_helper"]
        if domain_ids is None:
            domain_ids = []
        merged_data = []
        for domain_id in domain_ids:
            start_time_category_local = time.time()
            self.logger.debug(
                f"message=metric_collection | {category} Metrics Started at {start_time_category_local}"
            )
            try:
                self.logger.info(
                    f"message=metric_collection | Processing Data Collection for Domain ID : {domain_id} "
                    f"for category: {category}"
                )
                domain_id = domain_id.split("_")[-1]
                payload = self.common_helper.add_filter_to_payload(
                    domain_id, copy.deepcopy(enriched_payload)
                )
                self.logger.info(
                    f"message=metric_collection | Calling API with Payload : {payload}"
                    f" for category {category}"
                )

                post_kwargs = {
                    "payload": payload
                }
                response = rest_helper.post(constants.Endpoints.METRICS, post_kwargs)
                if response and response[0].get("FALLBACK", False):
                    self.logger.info(
                        f"message=metric_collection | FALLBACK case encountered for Domain: {domain_id}"
                        "Attempting to fetch data at host.id level."
                    )
                    iterate_and_collect_over_hostid_args = {
                        "domain_id": domain_id,
                        "payload": payload,
                        "rest_helper": rest_helper
                    }
                    response = self.iterate_and_collect_over_hostid(
                        iterate_and_collect_over_hostid_args
                    )

                merged_data.extend(
                    self.merge_responses_with_dimensions(
                        response, category, account_name, domain_id
                    )
                )
                self.logger.debug(
                    f"message=metric_collection | {category} metric got one Domain data Merge completed in "
                    f"{time.time() - start_time_category_local:.2f} seconds. "
                    f"with the total count {len(response)} now total merged_data is {len(merged_data)}"
                )
            except Exception as e:
                self.logger.error(f"message=metric_collection | Error: {e}")
                raise e
        return merged_data

    def iterate_and_collect_over_hostid(
        self, iterate_and_collect_over_hostid_args: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Iterate over the servers in a domain and collect metrics for each server.

        Args:
            iterate_and_collect_over_hostid_args (Dict[str, Any]): A dictionary containing the following keys:
                - domain_id (str): Domain ID to process.
                - payload (dict): Payload to update.
                - rest_helper (object): RestHelper object.

        Returns:
            List[Dict[str, Any]]: A list of responses from the API.
        """
        domain_id = f'/api/v1/asset/DeviceRegistrations/{iterate_and_collect_over_hostid_args["domain_id"]}'
        payload = iterate_and_collect_over_hostid_args["payload"]
        rest_helper = iterate_and_collect_over_hostid_args["rest_helper"]

        # Fetch the list of Host ID under the Domains
        self.logger.info(f"message=metric_collection | Fetching the list of host.id for Domain ID: {domain_id}")
        payload_for_host = copy.deepcopy(payload)

        payload_for_host["aggregations"] = []
        payload_for_host["postAggregations"] = []
        payload_for_host["dimensions"] = ['host.id']

        host_id_post_kwargs = {
            "payload": payload_for_host
        }
        response = rest_helper.post(constants.Endpoints.METRICS, host_id_post_kwargs)

        host_ids = [entry["event"]["host.id"] for entry in response]
        self.logger.info(
            f"message=metric_collection | Fetched the list of host.id for Domain ID: {domain_id}, host.id: {host_ids}"
        )

        # Initialize an empty list to store the responses
        response_list = []

        # Iterate over the servers and collect the metrics
        for host_id in host_ids:
            # Add the server ID filter to the payload
            server_payload = self.add_server_filter_to_payload(
                host_id, copy.deepcopy(payload)
            )

            # Post the request to the API
            self.logger.info(
                f"message=metric_collection | Posting the request to the timeseries API for host.id: {host_id}"
            )
            post_kwargs = {
                "payload": server_payload
            }
            response = rest_helper.post(constants.Endpoints.METRICS, post_kwargs)
            self.logger.info(
                'message=metric_collection | Collected {} metrics for host.id: {}.'.format(len(response), host_id)
            )
            # Append the response to the list
            response_list.extend(response)

        # Return the list of responses
        self.logger.info(
            f"message=metric_collection | Collected metrics for all servers in Domain ID: {domain_id}"
        )
        return response_list

    def add_server_filter_to_payload(self, host_id: str, payload: dict) -> dict:
        """
        Add host.id filters in metrics payload.

        Args:
            host_id (str): Server Ids to filter.
            payload (dict): Payload to update.

        Returns:
            dict: Updated payload with Domain.id filters.
        """
        # Add Domain.id filters in the payload
        payload["filter"]["fields"].append({
            # Filter type
            "type": "in",
            # Filter dimension
            "dimension": "host.id",
            # Filter values
            "values": [host_id]
        })

        # Log the updated filter
        self.logger.info(
            'message=metric_collection | Added Host Id filter in the Payload for host.id: {}'.format(host_id)
        )
        self.logger.info(
            'message=metric_collection | host.id level metrics payload: {}'.format(payload)
        )
        return payload
