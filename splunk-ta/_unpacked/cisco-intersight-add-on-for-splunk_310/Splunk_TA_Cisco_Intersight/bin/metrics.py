"""This module fetches data from Cisco Intersight metrics."""
# This import is required to resolve the absolute paths of supportive modules
# implemented throughout the add-on. The relative imports used in other files
# of the add-on are resolved by importing this module.
import import_declare_test
import sys
import time
import traceback
import threading
from splunklib import modularinput as smi
from intersight_helpers import kvstore
from intersight_helpers.logger_manager import setup_logging
from intersight_helpers.rest_helper import RestHelper
from intersight_helpers.event_ingestor import EventIngestor
from intersight_helpers.conf_helper import get_checkpoint, save_checkpoint
from intersight_helpers.metric_helper import MetricHelper
from intersight_helpers.constants import TA_METRICS
from typing import List, Tuple, Dict, Any


class METRICS(smi.Script):
    """Handle the collection and streaming of metrics data."""

    def get_scheme(self) -> smi.Scheme:
        """Define the scheme for the metrics input.

        This method creates and returns a scheme object that defines the input
        parameters for the metrics collection. Each parameter is described with
        its attributes such as title, description, and whether it's required on creation.

        Returns:
            Scheme: The scheme object that defines the input parameters for the metrics.
        """
        # Create a new scheme for metrics
        scheme = smi.Scheme('metrics')
        scheme.description = 'Metrics'
        scheme.use_external_validation = True
        scheme.streaming_mode_xml = True
        scheme.use_single_instance = False

        # Add 'name' argument to the scheme
        scheme.add_argument(
            smi.Argument(
                'name',
                title='Name',
                description='Name',
                required_on_create=True
            )
        )
        # Add 'global_account' argument to the scheme
        scheme.add_argument(
            smi.Argument(
                'global_account',
                required_on_create=True,
            )
        )
        # Add 'metrics' argument to the scheme
        scheme.add_argument(
            smi.Argument(
                'metrics',
                required_on_create=True,
            )
        )
        # Add 'host_power_energy_metrics' argument to the scheme
        scheme.add_argument(
            smi.Argument(
                'host_power_energy_metrics',
                required_on_create=False,
            )
        )
        # Add 'memory_metrics' argument to the scheme
        scheme.add_argument(
            smi.Argument(
                'memory_metrics',
                required_on_create=False,
            )
        )
        # Add 'network_metrics' argument to the scheme
        scheme.add_argument(
            smi.Argument(
                'network_metrics',
                required_on_create=False,
            )
        )
        return scheme

    def _initialize_input_data(
        self, inputs: smi.InputDefinition
    ) -> Tuple[str, List[Dict[str, Any]], List[str]]:
        """
        Extract and validates input data.

        Extract the session key, input items and selected metrics from the input
        definition. Validate the selected metrics and return the input data.

        Args:
            inputs (smi.InputDefinition): Input parameters definition.

        Returns:
            tuple: A tuple containing the session key (str), input items (list of dicts)
            and selected metrics (list of str).
        """
        meta_configs = self._input_definition.metadata
        session_key = meta_configs['session_key']
        input_items = [{'count': len(inputs.inputs)}]

        for input_name, input_item in inputs.inputs.items():
            input_item.update({
                'stanza_name': input_name,
                'name': input_name.split('://')[1],
                'session_key': session_key,
            })
            input_items.append(input_item)

        metrics_selected = input_items[1].get('metrics', '')
        selected_metrics = list(metrics_selected.split(','))
        return session_key, input_items, selected_metrics

    def stream_events(self, inputs: smi.InputDefinition, ew: smi.EventWriter) -> None:
        """
        Stream events from the metrics data source.

        This function processes the inputs, validates the selected metrics, and
        starts the data collection process. It calls the _process_metrics_and_ingest
        function to process each category of metrics and ingest the data into Splunk.

        The function does the following:
        1. Initializes the input data.
        2. Initializes the KVStoreManager and MetricHelper objects.
        3. Initializes the RestHelper and EventIngestor objects.
        4. Collects inventory data based on checkpoints for 1-hour and 24-hour intervals.
        5. Gets the metrics map and builds the metrics dictionary.
        6. Processes each category of metrics and ingests the data into Splunk.
        7. Saves the new checkpoint values.

        Args:
            inputs (smi.InputDefinition): Input parameters definition.
            ew (smi.EventWriter): Event writer for Splunk.
        """
        logger = setup_logging(TA_METRICS)
        try:
            start_time = time.time()

            # Initialize the input data
            session_key, input_items, selected_metrics = self._initialize_input_data(inputs)
            input_name = input_items[1]['name']
            logger = setup_logging(TA_METRICS, input_name=input_name)

            # Initialize the KVStoreManager and MetricHelper objects
            kvstore_manager = kvstore.KVStoreManager(session_key=session_key)
            metric_helper = MetricHelper(logger, kvstore_manager)
            metric_helper.update_account_info(session_key, input_items[1])

            # Initialize the RestHelper and EventIngestor objects
            rest_helper = RestHelper(input_items[1], logger)
            event_ingestor = EventIngestor(
                input_items[1], ew, logger,
                rest_helper.ckpt_account_name)

            # Collect inventory data based on checkpoints for 1-hour and 24-hour intervals
            status_dict = metric_helper.collect_inventory(
                rest_helper, session_key, input_items, selected_metrics
            )
            status_dict["host"] = True
            status_dict["cpu_utilization"] = True
            logger.info(
                "message=metric_collection | Data collection for Inventory Dimensions completed in %.2f seconds.",
                time.time() - start_time
            )

            # Get the metrics map and build the metrics dictionary
            interval = int(input_items[1]['interval'])
            metrics_checkpoint_key = f"Cisco_Intersight_{input_name}_metric_checkpoint"
            metrics_checkpoint_values = get_checkpoint(
                metrics_checkpoint_key, session_key, import_declare_test.ta_name
            )
            metrics_map = metric_helper.get_metrics_map()
            metrics_dict = metric_helper.build_metrics_dict(
                selected_metrics, metrics_map, input_items[1]
            )

            if not metrics_dict:
                logger.error("message=metric_collection | No valid metrics found in the dictionary.")
                return

            # Process each category of metrics and ingest the data into Splunk
            kwargs = {
                "rest_helper": rest_helper,
                "event_ingestor": event_ingestor,
                "logger": logger,
                "metric_helper": metric_helper,
                "interval": interval,
                "status_dict": status_dict,
                "account_name": input_items[1]['global_account'],
                "metrics_dict": metrics_dict,
                "metrics_checkpoint_values": metrics_checkpoint_values
            }
            new_checkpoint_values = self._process_metrics_and_ingest(kwargs)
            save_checkpoint(
                metrics_checkpoint_key, session_key, import_declare_test.ta_name, new_checkpoint_values
            )
            logger.info(
                "message=metric_collection | Data collection completed in %.2f seconds.",
                time.time() - start_time
            )
            logger.info(
                "message=intersight_api_count | API call statistics: {}".format(
                    rest_helper.api_call_count
                )
            )

        except Exception as e:
            logger.error(
                "message=metric_collection | Exception occurred: %s", e
            )
            logger.error(traceback.format_exc())

    def _process_metrics_and_ingest(
        self,
        kwargs: Dict[str, Any]
    ) -> Dict[str, Dict[str, Any]]:
        """Process metrics categories, fetch data, and ingest into Splunk.

        This function processes each category of metrics, fetches the data
        from the API, and ingests it into Splunk using the provided event
        ingestor. It uses a thread pool to process the categories in parallel.

        Args:
            kwargs (Dict[str, Any]): A dictionary containing the following keys:
                - rest_helper (RestHelper): RestHelper object for making API calls.
                - event_ingestor (EventIngestor): EventIngestor object for ingesting data.
                - logger (logging.Logger): Logger object for logging messages.
                - metric_helper (MetricHelper): MetricHelper object for processing metrics.
                - interval (int): Interval in seconds for data collection.
                - status_dict (Dict[str, bool]): Dictionary containing status values for inventory dimensions.
                - account_name (str): Account name.
                - metrics_dict (Dict[str, List[str]]): Dictionary containing metrics and their categories.
                - metrics_checkpoint_values (Dict[str, Dict[str, int]]): Dictionary containing
                checkpoint values for metrics.

        Returns:
            Dict[str, Dict[str, Any]]: A dictionary containing the results of each thread.
            The keys are the metrics categories and the values are dictionaries containing
            the event count and the last fetched time for the metrics.
        """
        rest_helper = kwargs.get("rest_helper")
        event_ingestor = kwargs.get("event_ingestor")
        logger = kwargs.get("logger")
        metric_helper = kwargs.get("metric_helper")
        interval = kwargs.get("interval")
        status_dict = kwargs.get("status_dict")
        account_name = kwargs.get("account_name")
        metrics_dict = kwargs.get("metrics_dict")
        metrics_checkpoint_values = kwargs.get("metrics_checkpoint_values")

        workers = []
        results = {}
        results_lock = threading.Lock()

        for category, metrics_list in metrics_dict.items():
            logger.info(
                f'message=metric_collection | Start Metrics Processing for: {category} '
                f'with metrics: {metrics_list}'
            )
            metrics_checkpoint_value = (
                metrics_checkpoint_values.get(category, {}).get('last_fetched_time')
                if metrics_checkpoint_values
                else None
            )
            thread_kwargs = {
                'category': category,
                'metrics_list': metrics_list,
                'metrics_checkpoint_value': metrics_checkpoint_value,
                'rest_helper': rest_helper,
                'event_ingestor': event_ingestor,
                'logger': logger,
                'metric_helper': metric_helper,
                'interval': interval,
                'results': results,
                'account_name': account_name,
                'results_lock': results_lock,
                'status_dict': status_dict
            }

            thread = threading.Thread(
                target=self._process_single_category,
                kwargs=thread_kwargs,
            )
            thread.daemon = True
            thread.start()
            workers.append(thread)

        for worker in workers:
            worker.join()

        total_events_ingested = sum(result.get("event_count", 0) for result in results.values())
        logger.info(f"Total events ingested for all metrics: {total_events_ingested}")

        for result in results.values():
            result.pop('event_count', None)

        return results

    def _process_single_category(self, **kwargs: Dict[str, Any]) -> None:
        """Threaded function to process a single metrics category.

        This function is the main entry point for each thread spawned by the
        `stream_events` method. It processes a single metrics category and
        stores the results in a dictionary.

        Args:
            **kwargs: Keyword arguments passed from the `stream_events`
                method. These include the category, metrics list,
                metrics checkpoint value, interval, account name, results
                dictionary, and the event ingestor object.
        """
        try:
            rest_helper = kwargs.get("rest_helper")
            event_ingestor = kwargs.get("event_ingestor")
            logger = kwargs.get("logger")
            metric_helper = kwargs.get("metric_helper")
            interval = kwargs.get("interval")
            results = kwargs.get("results")
            account_name = kwargs.get("account_name")
            results_lock = kwargs.get("results_lock")
            status_dict = kwargs.get("status_dict")
            category = kwargs.get("category")
            metrics_list = kwargs.get("metrics_list")
            metrics_checkpoint_value = kwargs.get("metrics_checkpoint_value")

            # Check if the metrics collection was successful for domains and common
            if status_dict.get("domains") and status_dict.get("common") and status_dict.get(category):
                metrics_kwargs = {
                    "category": category,
                    "metrics_list": metrics_list,
                    "metrics_checkpoint_value": metrics_checkpoint_value,
                    "interval_selected": interval,
                    "account_name": account_name,
                    "event_ingestor": event_ingestor,
                    "rest_helper": rest_helper
                }
                # Fetch metrics data for the given category and metrics list
                result = metric_helper.fetch_metrics_data(
                    metrics_kwargs
                )
                logger.info(
                    "message=metric_collection | Total Events Ingested "
                    f"for {category} along with checkpoint value is {result}"
                )
                with results_lock:
                    # Store the results in the dictionary
                    results[category] = result
            else:
                logger.error(
                    "message=metric_collection | Dimension Collection was failed "
                    f"for {category} metric type, hence terminating Metrics Collection"
                    f"Status of Dimensions: {status_dict}"
                )
                # If the metrics collection was not successful, set the event count to 0
                # and store the last fetched time in the results dictionary
                if not metrics_checkpoint_value:
                    _, _, metrics_checkpoint_value = metric_helper.get_time_interval(
                        metrics_checkpoint_value, interval
                    )
                with results_lock:
                    results[category] = {"event_count": 0, "last_fetched_time": metrics_checkpoint_value}
        except Exception as e:
            logger.error(
                f'message=metric_collection | Error processing category {category}: {e}'
            )
            logger.error(traceback.format_exc())
            # If an exception occurs, set the event count to 0 and store the last
            # fetched time in the results dictionary
            if not metrics_checkpoint_value:
                _, _, metrics_checkpoint_value = metric_helper.get_time_interval(
                    metrics_checkpoint_value, interval
                )
            with results_lock:
                results[category] = {"event_count": 0, "last_fetched_time": metrics_checkpoint_value}


if __name__ == '__main__':
    exit_code = METRICS().run(sys.argv)
    sys.exit(exit_code)
