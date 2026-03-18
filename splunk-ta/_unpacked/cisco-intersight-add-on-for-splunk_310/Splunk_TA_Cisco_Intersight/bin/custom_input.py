"""This module handles the collection and ingestion of custom API data from Cisco Intersight.

It defines a Splunk Modular Input class (CUSTOMINPUT) to collect either normal inventory
or telemetry data with flexible endpoint and filtering options.
"""

import import_declare_test  # Splunk UCC relative import resolver

import sys
import time
import json
from typing import List, Dict, Tuple, Any

from splunklib import modularinput as smi
from intersight_helpers.logger_manager import setup_logging
from intersight_helpers.rest_helper import RestHelper
from intersight_helpers.event_ingestor import EventIngestor
from intersight_helpers.conf_helper import get_checkpoint, save_checkpoint
from intersight_helpers import constants
from intersight_helpers.custom_payload import CustomPayloads
from intersight_helpers.custom_input_mapping import get_mapping_manager
from intersight_helpers.metric_helper import MetricHelper
from intersight_helpers import kvstore
from inventory import INVENTORY


class CUSTOMINPUT(smi.Script):
    """Custom Splunk Modular Input for Cisco Intersight APIs."""

    def get_scheme(self) -> smi.Scheme:
        """Define the input scheme for Splunk modular input."""
        scheme = smi.Scheme("custom_input")
        scheme.description = "Custom Input for Cisco Intersight add-on for Splunk"
        scheme.use_external_validation = True
        scheme.streaming_mode_xml = True
        scheme.use_single_instance = False

        # Standard arguments
        scheme.add_argument(smi.Argument("name", title="Name", description="Input name", required_on_create=True))
        scheme.add_argument(smi.Argument(
            "global_account", title="Account", description="Intersight Account",
            required_on_create=True
        ))

        scheme.add_argument(smi.Argument(
            "api_type", title="API Type",
            description="Inventory / Configuration APIs or Telemetry / Metrics APIs",
            required_on_create=True
        ))
        scheme.add_argument(smi.Argument(
            "api_endpoint", title="API Endpoint",
            description="Relative endpoint (e.g. /compute/Blades)",
            required_on_create=True
        ))

        # Other Data Query parameters (for normal_inventory)
        scheme.add_argument(smi.Argument(
            "filter", title="Filter",
            description="OData $filter parameter", required_on_create=False
        ))
        scheme.add_argument(smi.Argument(
            "expand", title="Expand",
            description="OData $expand parameter", required_on_create=False
        ))
        scheme.add_argument(smi.Argument(
            "select", title="Select",
            description="OData $select parameter", required_on_create=False
        ))

        # Telemetry/Metrics specific parameters
        scheme.add_argument(smi.Argument(
            "groupby", title="Group By",
            description="Group By fields for telemetry", required_on_create=False
        ))
        scheme.add_argument(smi.Argument(
            "metrics_name", title="Metrics Name",
            description="Specific metrics name (e.g. hw.fan.speed)", required_on_create=False
        ))
        scheme.add_argument(smi.Argument(
            "metrics_type", title="Metrics Type",
            description="Aggregation types (sum, min, max, avg, duration)",
            required_on_create=False
        ))

        return scheme

    def prepare_input_items(self, inputs: smi.InputDefinition) -> List[Dict[str, Any]]:
        """Prepare Splunk input items with metadata and session keys."""
        input_items = [{"count": len(inputs.inputs)}]
        meta_configs = inputs.metadata  # Correct way to get metadata
        session_key = meta_configs["session_key"]

        for input_name, input_item in inputs.inputs.items():
            input_item["stanza_name"] = input_name
            input_item["name"] = input_name.split("://")[1]
            input_item["session_key"] = session_key
            input_items.append(input_item)

        return input_items

    def _initialize_checkpoint(self, input_name, session_key, logger) -> Tuple[str, Dict[str, Any]]:
        """Initialize checkpoint key and fetch checkpoint dict."""
        try:
            ckpt_key = f"Cisco_Intersight_{input_name}_custom_input_checkpoint"
            ckpt_val = get_checkpoint(ckpt_key, session_key, import_declare_test.ta_name)
            ckpt_dict = dict(ckpt_val or {})
            logger.info(f"message=custom_input_checkpoint | Checkpoint initialized for {input_name}: {ckpt_dict}")
            return ckpt_key, ckpt_dict
        except Exception as e:
            logger.error(f"message=custom_input_checkpoint_error | Checkpoint init error: {e}", exc_info=True)
            return None, {}

    def _normalize_api_endpoint(self, api_endpoint: str) -> str:
        if not api_endpoint:
            return ""

        # Remove leading/trailing slashes
        endpoint = api_endpoint.strip("/")

        # Split by '/' and find 'search' or last 2 parts
        parts = endpoint.split("/")

        # Ensure we only take the last two segments
        if len(parts) >= 2:
            normalized = "/".join(parts[-2:])
        else:
            normalized = parts[-1]

        return normalized

    def _safe_strip(self, value):
        return (value or "").strip()

    def stream_events(self, inputs: smi.InputDefinition, ew: smi.EventWriter) -> None:
        """Stream events from Cisco Intersight APIs to Splunk."""
        logger = setup_logging("ta_intersight_custom_input")
        try:
            for input_name, input_item in inputs.inputs.items():
                logger = setup_logging("ta_intersight_custom_input", input_name=input_name.split("://")[1])
            logger.info("message=custom_input | Starting custom input data collection")

            inv_class = INVENTORY()
            input_items = self.prepare_input_items(inputs)

            logger.info(
                "message=custom_input | Prepared %d input configurations",
                len(input_items) - 1
            )

            # Account info
            account_info = inv_class.get_account_info(input_items)
            input_items[1].update(account_info)

            # REST + Ingestor
            rest_helper = RestHelper(input_items[1], logger)
            event_ingestor = EventIngestor(input_items[1], ew, logger, rest_helper.ckpt_account_name)

            # Process each input stanza
            for input_name, input_item in inputs.inputs.items():
                api_type = input_item.get("api_type")
                api_endpoint = input_item.get("api_endpoint")
                api_endpoint = self._normalize_api_endpoint(api_endpoint)
                # Log user configuration parameters
                user_params = {
                    'input_name': input_name.split("://")[1],
                    'api_type': api_type,
                    'api_endpoint': self._safe_strip(api_endpoint),
                    'filter': self._safe_strip(input_item.get('filter')),
                    'select': self._safe_strip(input_item.get('select')),
                    'expand': self._safe_strip(input_item.get('expand')),
                    'groupby': self._safe_strip(input_item.get('groupby')),
                    'metrics_name': self._safe_strip(input_item.get('metrics_name')),
                    'metrics_type': self._safe_strip(input_item.get('metrics_type'))
                }
                logger.info(
                    "message=custom_input_config | Processing input configuration: %s",
                    user_params
                )

                # Sourcetype and source are now created dynamically
                logger.info("message=custom_input_defaults | Using dynamic sourcetype and source creation")

                if api_type == "normal_inventory":
                    self._stream_normal_inventory({
                        'input_name': input_name.split("://")[1],
                        'input_item': input_item,
                        'api_endpoint': api_endpoint,
                        'rest_helper': rest_helper,
                        'event_ingestor': event_ingestor,
                        'logger': logger,
                        'inv_class': inv_class
                    })
                elif api_type == "telemetry":
                    # Log telemetry-specific configuration
                    telemetry_params = {
                        'groupby': input_item.get('groupby'),
                        'metrics_name': input_item.get('metrics_name'),
                        'metrics_type': input_item.get('metrics_type')
                    }
                    logger.info(
                        "message=custom_input_telemetry_config | Telemetry parameters: %s",
                        telemetry_params
                    )

                    # Generate custom payload for telemetry
                    self._stream_telemetry({
                        'input_name': input_name.split("://")[1],
                        'input_item': input_item,
                        'api_endpoint': api_endpoint,
                        'rest_helper': rest_helper,
                        'event_ingestor': event_ingestor,
                        'logger': logger
                    })

            logger.info(
                "message=intersight_api_count | API call statistics: {}".format(
                    rest_helper.api_call_count
                )
            )

            logger.info("message=custom_input_complete | Custom input data collection completed successfully")
        except Exception as e:
            logger.error("message=custom_input_error | Stream events error: %s", e, exc_info=True)

    def _stream_normal_inventory(self, args):
        """Stream normal inventory data with dictionary arguments."""
        input_name = args['input_name']
        input_item = args['input_item']
        api_endpoint = args['api_endpoint']
        rest_helper = args['rest_helper']
        event_ingestor = args['event_ingestor']
        logger = args['logger']
        inv_class = args['inv_class']
        session_key = input_item["session_key"]
        ckpt_key, ckpt_dict = self._initialize_checkpoint(input_name, session_key, logger)

        # Determine if API is target-based
        is_target_based = self._is_target_based_api(api_endpoint, rest_helper, logger)
        logger.info(f"message=custom_input_api_detection | API {api_endpoint} target-based: {is_target_based}")

        if is_target_based:
            # Targets
            target_moids = inv_class.get_target_moids(rest_helper, logger) or []
            logger.info(
                "message=custom_input_targets | Found %d registered device targets",
                len(target_moids)
            )
            # Target-based API: loop over targets
            logger.info(
                f"message=custom_input_target_processing | Processing target-based API for "
                f"{len(target_moids)} targets"
            )

            for target in target_moids:
                target_moid = target.get("RegisteredDevice", {}).get("Moid")
                if not target_moid:
                    logger.warning(f"message=custom_input_target_skip | Skipping target with missing Moid: {target}")
                    continue

                api_params = self._build_api_params(
                    input_item,
                    ckpt_dict.get(target_moid, {"time": None, "status": True}),
                    target_moid
                )
                logger.info(
                    f"message=custom_input_filter_applied | Applied user filters for Target based API: {api_params}"
                )

                ckpt_dict[target_moid] = self._fetch_paginated_data({
                    'api_endpoint': api_endpoint,
                    'api_params': api_params,
                    'rest_helper': rest_helper,
                    'event_ingestor': event_ingestor,
                    'ckpt': ckpt_dict.get(target_moid, {"time": None, "status": True}),
                    'logger': logger,
                    'input_name': input_name,
                    'session_key': session_key,
                    'account_name': input_item.get('global_account')
                })
        else:
            # Non-target-based API: fetch data without Owners filter
            logger.info(
                f"message=custom_input_non_target | Fetching data for non-target-based API: "
                f"{api_endpoint}"
            )

            # Build params with filter/select/expand for non-target-based API
            api_params = {}

            # Apply user-provided filter

            filters = []
            if ckpt_dict.get("time"):
                op = "gt" if ckpt_dict.get("status", True) else "ge"
                filters.append(f"ModTime {op} {ckpt_dict['time']}")

            if api_endpoint.lower() == constants.TARGET_BASED_APIS[0]:
                filters.append(constants.Endpoints.TARGET_FILTER)
                logger.info(
                    "message=custom_input_filter_applied | Applied target_type filter for "
                    f"{constants.TARGET_BASED_APIS[0]}."
                )
            elif api_endpoint.lower() == constants.TARGET_BASED_APIS[1]:
                filters.append(constants.Endpoints.PLATFORM_FILTER)
                logger.info(
                    "message=custom_input_filter_applied | Applied platform_type filter for "
                    f"{constants.TARGET_BASED_APIS[1]}."
                )

            if input_item.get("filter"):
                filters.append(input_item["filter"])

            if filters:
                api_params["$filter"] = " AND ".join(filters)

            if input_item.get("select"):
                api_params["$select"] = f'{input_item["select"]},ModTime,AccountMoid'

            if input_item.get("expand"):
                api_params["$expand"] = input_item["expand"]

            logger.info(f"message=custom_input_filter_applied | Applied user filters: {api_params}")

            # Fetch all data paginated
            ckpt_dict = self._fetch_paginated_data({
                'api_endpoint': api_endpoint,
                'api_params': api_params,
                'rest_helper': rest_helper,
                'event_ingestor': event_ingestor,
                'ckpt': ckpt_dict,
                'logger': logger,
                'input_name': input_name,
                'session_key': session_key,
                'account_name': input_item.get('global_account')
            })

        # Save minimal checkpoint
        try:
            save_checkpoint(ckpt_key, session_key, import_declare_test.ta_name, ckpt_dict)
            logger.info(
                f"message=custom_input_checkpoint_save | Checkpoint saved for input "
                f"{input_name}: {ckpt_dict}"
            )
        except Exception as e:
            logger.error(
                f"message=custom_input_checkpoint_save_error | Error saving checkpoint for "
                f"{input_name}: {e}", exc_info=True
            )

    def _stream_telemetry(self, args):
        """Stream telemetry data using custom payload generation and metrics collection pattern."""
        input_name = args['input_name']
        input_item = args['input_item']
        api_endpoint = args['api_endpoint']
        rest_helper = args['rest_helper']
        event_ingestor = args['event_ingestor']
        logger = args['logger']
        try:
            start_time = time.time()
            session_key = input_item["session_key"]

            # Parse telemetry parameters
            metrics_name = input_item.get('metrics_name', '').strip()
            metrics_type_str = input_item.get('metrics_type', '').strip()
            groupby_str = input_item.get('groupby', 'intersight.domain.id').strip()
            interval_seconds = int(input_item.get('interval', 900).strip())
            account_name = input_item.get('global_account')

            # Validate required parameters
            if not metrics_name:
                logger.error("message=custom_input_telemetry_error | metrics_name is required for telemetry")
                return

            if not metrics_type_str:
                logger.error("message=custom_input_telemetry_error | metrics_type is required for telemetry")
                return

            # Parse comma-separated values
            metrics_types = [mt.strip() for mt in metrics_type_str.split(',') if mt.strip()]
            groupby_fields = [gb.strip() for gb in groupby_str.split(',') if gb.strip()]

            # Extract user-provided field names for each metric type
            field_names = {}
            for metric_type in metrics_types:
                field_key = f'metrics_{metric_type}'
                field_value = input_item.get(field_key, '').strip()
                if field_value:
                    # For avg, split slash-separated values (sum/count)
                    if metric_type == 'avg' and '/' in field_value:
                        field_names[metric_type] = [f.strip() for f in field_value.split('/')]
                    else:
                        field_names[metric_type] = field_value

            logger.info(
                f"message=custom_input_telemetry_parsed | Parsed parameters - "
                f"metrics_name: {metrics_name}, metrics_types: {metrics_types}, "
                f"groupby_fields: {groupby_fields}, granularity: {interval_seconds}, "
                f"field_names: {field_names}"
            )

            # Initialize KVStoreManager and MetricHelper (following metrics.py pattern)
            kvstore_manager = kvstore.KVStoreManager(session_key=session_key)
            metric_helper = MetricHelper(logger, kvstore_manager)
            metric_helper.update_account_info(session_key, input_item)

            # Initialize checkpoint management
            ckpt_key, ckpt_dict = self._initialize_checkpoint(input_name, session_key, logger)
            metrics_checkpoint_value = ckpt_dict.get('last_fetched_time')

            logger.info(f"message=custom_input_telemetry_checkpoint | Using checkpoint: {metrics_checkpoint_value}")

            # Generate time intervals based on checkpoint (following metrics.py pattern)
            time_intervals, new_checkpoint, _ = metric_helper.get_time_interval(
                metrics_checkpoint_value, interval_seconds
            )

            if not time_intervals:
                logger.info(
                    "message=custom_input_telemetry_complete | Telemetry data up to "
                    "current time already collected"
                )
                return

            logger.info(
                f"message=custom_input_telemetry_intervals | Collecting telemetry for "
                f"time intervals: {time_intervals}"
            )

            # Fetch domain IDs from KVStore (following metrics.py pattern)
            domains_list = kvstore_manager.get(
                constants.CollectionConstants.DOMAINS,
                [constants.CollectionConstants.KEY],
                {constants.CollectionConstants.ACCOUNT_NAME: account_name},
            )

            # If no domains found, collect domains data using metric_helper
            if not domains_list:
                logger.info(
                    "message=custom_input_telemetry_domains_missing | No domains found in "
                    "KVStore. Collecting domains data..."
                )
                try:
                    # Collect only domains data (not other inventory)
                    domains_only_metrics = ['domains']  # Only collect domains

                    # Prepare input_items in the format expected by collect_inventory
                    input_items_for_domains = [
                        {'count': 1},
                        input_item  # The actual input item configuration
                    ]

                    status_dict = metric_helper.collect_inventory(
                        rest_helper, session_key, input_items_for_domains, domains_only_metrics
                    )

                    if status_dict.get('domains'):
                        logger.info(
                            "message=custom_input_telemetry_domains_collected | "
                            "Successfully collected domains data"
                        )

                        # Retry fetching domains from KVStore after collection
                        domains_list = kvstore_manager.get(
                            constants.CollectionConstants.DOMAINS,
                            [constants.CollectionConstants.KEY],
                            {constants.CollectionConstants.ACCOUNT_NAME: account_name},
                        )

                        if not domains_list:
                            logger.error(
                                "message=custom_input_telemetry_error | No domains found even "
                                "after collection. Cannot proceed."
                            )
                            return
                    else:
                        logger.error(
                            "message=custom_input_telemetry_error | Failed to collect domains "
                            "data. Cannot proceed."
                        )
                        return

                except Exception as domain_error:
                    logger.error(
                        f"message=custom_input_telemetry_domain_collection_error | "
                        f"Error collecting domains: {domain_error}", exc_info=True
                    )
                    return

            domain_ids = tuple(item["_key"].split("_")[-1] for item in domains_list)
            logger.info(f"message=custom_input_telemetry_domains | Found {len(domain_ids)} domain IDs: {domain_ids}")

            # Generate base payload using custom payload builder
            base_payload = CustomPayloads.build_custom_payload(
                metrics_name=metrics_name,
                metrics_types=metrics_types,
                groupby_fields=groupby_fields,
                granularity=interval_seconds,
                field_names=field_names  # Pass user-provided field names
            )

            logger.info(
                f"message=custom_input_telemetry_payload | Generated payload: "
                f"{len(base_payload.get('aggregations', []))} aggregations, "
                f"{len(base_payload.get('postAggregations', []))} post-aggregations"
            )

            total_event_count = 0

            # Process each time interval (following metrics.py pattern)
            for time_interval in time_intervals:
                payload = json.loads(json.dumps(base_payload))  # Deep copy
                payload["intervals"] = [time_interval]

                logger.info(
                    f"message=custom_input_telemetry_interval_start | Processing interval: "
                    f"{time_interval}"
                )

                # Collect data for each domain (following fetch_enriched_stats pattern)
                interval_events = self._collect_telemetry_for_domains({
                    'domain_ids': domain_ids,
                    'payload': payload,
                    'metrics_name': metrics_name,
                    'account_name': account_name,
                    'rest_helper': rest_helper,
                    'event_ingestor': event_ingestor,
                    'logger': logger,
                    'api_endpoint': api_endpoint
                })

                total_event_count += interval_events
                logger.info(
                    f"message=custom_input_telemetry_interval_complete | Interval "
                    f"{time_interval}: {interval_events} events"
                )

            # Update checkpoint with new value
            ckpt_dict['last_fetched_time'] = new_checkpoint
            save_checkpoint(ckpt_key, session_key, import_declare_test.ta_name, ckpt_dict)

            logger.info(
                f"message=custom_input_telemetry_complete | Telemetry collection completed: "
                f"{total_event_count} total events in {time.time() - start_time:.2f} seconds"
            )

        except Exception as e:
            logger.error(
                f"message=custom_input_telemetry_error | Error in telemetry streaming: {e}",
                exc_info=True
            )

    def _collect_telemetry_for_domains(self, args) -> int:
        """Collect telemetry data for all domains (following fetch_enriched_stats pattern)."""
        domain_ids = args['domain_ids']
        payload = args['payload']
        metrics_name = args['metrics_name']
        account_name = args['account_name']
        rest_helper = args['rest_helper']
        event_ingestor = args['event_ingestor']
        logger = args['logger']
        api_endpoint = args['api_endpoint']
        total_events = 0

        for domain_id in domain_ids:
            try:
                logger.info(
                    f"message=custom_input_telemetry_domain_start | Processing domain: "
                    f"{domain_id}"
                )

                # Add domain filter to payload (following metrics.py pattern)
                domain_payload = self._add_domain_filter_to_payload(
                    domain_id, json.loads(json.dumps(payload))
                )

                logger.debug(
                    f"message=custom_input_telemetry_api_call | Calling telemetry API "
                    f"with payload for domain {domain_id}"
                )

                # Make POST request to user-provided telemetry endpoint
                post_kwargs = {"payload": domain_payload}

                # Log the JSON-formatted payload being sent (for debugging)
                logger.info(
                    f"message=custom_input_telemetry_payload_json | Using endpoint: "
                    f"{api_endpoint} | JSON Payload: {domain_payload}"
                )

                response = rest_helper.post(api_endpoint, post_kwargs)
                logger.info(f"message=custom_input_telemetry_response | Response Length: {len(response)}")

                if not response:
                    logger.warning(f"message=custom_input_telemetry_no_response | No response for domain {domain_id}")
                    continue

                # Check for FALLBACK case (following metrics.py pattern)
                if response and response[0].get("FALLBACK", False):
                    logger.info(
                        f"message=custom_input_telemetry_fallback | FALLBACK encountered for "
                        f"domain {domain_id}, attempting host-level collection"
                    )
                    continue

                # Process response and ingest (simplified version of merge_responses_with_dimensions)
                if response:
                    event_count = self._ingest_telemetry_response({
                        'response_data': response,
                        'metrics_name': metrics_name,
                        'account_name': account_name,
                        'domain_id': domain_id,
                        'event_ingestor': event_ingestor,
                        'logger': logger
                    })
                    total_events += event_count
                    logger.info(
                        f"message=custom_input_telemetry_domain_complete | Domain {domain_id}: "
                        f"{event_count} events"
                    )

            except Exception as e:
                logger.error(
                    f"message=custom_input_telemetry_domain_error | Error processing domain "
                    f"{domain_id}: {e}", exc_info=True
                )

        return total_events

    def _add_domain_filter_to_payload(self, domain_id: str, payload: dict) -> dict:
        """Add domain filter to payload (simplified version of common_helper.add_filter_to_payload)."""
        try:
            # Clean domain_id if it has prefix
            clean_domain_id = domain_id.split("_")[-1] if "_" in str(domain_id) else domain_id
            clean_domain_id = f"/api/v1/asset/DeviceRegistrations/{clean_domain_id}"

            # Add domain filter to existing filters
            if "filter" in payload and "fields" in payload["filter"]:
                # Add domain filter to existing filter fields
                domain_filter = {
                    "type": "selector",
                    "dimension": "intersight.domain.id",
                    "value": clean_domain_id
                }
                payload["filter"]["fields"].append(domain_filter)
            else:
                # Create new filter structure if it doesn't exist
                payload["filter"] = {
                    "type": "and",
                    "fields": [
                        {
                            "type": "selector",
                            "dimension": "intersight.domain.id",
                            "value": clean_domain_id
                        }
                    ]
                }

            return payload

        except Exception:
            return payload

    def _ingest_telemetry_response(self, args) -> int:
        """Ingest telemetry response data (simplified version of metrics data ingestion)."""
        response_data = args['response_data']
        metrics_name = args['metrics_name']
        account_name = args['account_name']
        domain_id = args['domain_id']
        event_ingestor = args['event_ingestor']
        logger = args['logger']
        try:
            if not response_data:
                return 0

            # Process response data for ingestion
            processed_events = []
            for item in response_data:
                if isinstance(item, dict):
                    # Add metadata for tracking
                    event = item.copy()
                    event['custom_input_metrics'] = metrics_name
                    event['account_name'] = account_name
                    event['domain_id'] = domain_id
                    event['collection_type'] = 'telemetry'
                    processed_events.append(event)

            if processed_events:
                # Use the existing ingest_metrics_data function which is designed for telemetry
                event_count = event_ingestor.ingest_metrics_data(processed_events, metrics_name, is_custom_input=True)
                logger.info(
                    f"message=custom_input_telemetry_ingest | Ingested {event_count} "
                    f"telemetry events for {metrics_name}"
                )
                return event_count
            else:
                logger.info(
                    f"message=custom_input_telemetry_ingest | No valid events to ingest for "
                    f"{metrics_name}"
                )
                return 0

        except Exception as e:
            logger.error(
                f"message=custom_input_telemetry_ingest_error | Error ingesting telemetry data: {e}",
                exc_info=True
            )
            return 0

    def _is_target_based_api(self, api_endpoint, rest_helper, logger) -> bool:
        """Determine if API is target-based by inspecting first result for 'RegisteredDevice'."""
        try:
            if api_endpoint.lower() in constants.TARGET_BASED_APIS:
                return False
            params = {"$top": 1}  # Only fetch 1 record to check
            resp = rest_helper.get(endpoint=api_endpoint, params=params)
            results = resp.get("Results", [])
            if results and "RegisteredDevice" in results[0]:
                return True
        except Exception as e:
            logger.error(
                f"message=custom_input_api_detection_error | Error checking target-based API for "
                f"{api_endpoint}: {e}", exc_info=True
            )
        return False

    def _build_api_params(self, input_item, ckpt, target_moid):
        """Build OData params with filter/select/expand."""
        params, filters = {}, []

        if ckpt.get("time"):
            op = "gt" if ckpt.get("status", True) else "ge"
            filters.append(f"ModTime {op} {ckpt['time']}")

        filters.append(f"Owners/any(x: x eq '{target_moid}')")
        if input_item.get("filter"):
            filters.append(input_item["filter"])

        if filters:
            params["$filter"] = " AND ".join(filters)

        if input_item.get("select"):
            params["$select"] = f'{input_item["select"]},ModTime,AccountMoid'
        if input_item.get("expand"):
            params["$expand"] = input_item["expand"]

        return params

    def _fetch_paginated_data(self, args):
        """Fetch paginated data with dictionary arguments."""
        api_endpoint = args['api_endpoint']
        api_params = args['api_params']
        rest_helper = args['rest_helper']
        event_ingestor = args['event_ingestor']
        ckpt = args['ckpt']
        logger = args.get('logger')
        input_name = args.get('input_name')
        session_key = args.get('session_key')
        account_name = args.get('account_name')

        skip, has_more = 0, True
        collected_object_types = set()  # Track unique ObjectTypes collected

        while has_more:
            batch_params = {
                **api_params,
                "$inlinecount": "allpages",
                "$orderby": "ModTime asc",
                "$top": constants.PAGE_LIMIT,
                "$skip": skip,
            }

            modtime = ckpt.get("time")
            try:
                resp = rest_helper.get(endpoint=api_endpoint, params=batch_params)
                results = resp.get("Results", [])
                if not results:
                    break

                # Track ObjectTypes in this batch
                obj_type = '.'.join(resp.get('ObjectType', '').split('.')[:2])
                for result in results:
                    if 'ObjectType' not in result:
                        result['ObjectType'] = obj_type
                    else:
                        obj_type = result.get('ObjectType', obj_type)
                    if obj_type:
                        collected_object_types.add(obj_type)

                _, modtime = event_ingestor.ingest_custom_input_data(
                    results, obj_type
                )

                # Update checkpoint
                ckpt["time"] = modtime
                ckpt["status"] = True

                if len(results) < constants.PAGE_LIMIT:
                    has_more = False
                else:
                    skip += constants.PAGE_LIMIT

            except Exception as e:
                logger.error(f"Fetch error at {api_endpoint}: {e}", exc_info=True)
                # Update checkpoint
                ckpt["time"] = modtime
                ckpt["status"] = False
                break

        # Update ObjectType mapping after successful collection
        if collected_object_types and input_name and session_key:
            try:
                mapping_manager = get_mapping_manager(session_key, account_name)
                mapping_manager.update_endpoint_mapping(
                    input_name=input_name,
                    api_endpoint=api_endpoint,
                    collected_object_types=list(collected_object_types)
                )
                logger.info(
                    f"message=custom_input_mapping | Updated mapping for {api_endpoint}: "
                    f"{len(collected_object_types)} ObjectTypes"
                )
            except Exception as e:
                logger.error(
                    f"message=custom_input_mapping_error | Error updating mapping: {e}",
                    exc_info=True
                )
                # Continue execution even if mapping update fails

        return ckpt


if __name__ == "__main__":
    exit_code = CUSTOMINPUT().run(sys.argv)
    sys.exit(exit_code)
