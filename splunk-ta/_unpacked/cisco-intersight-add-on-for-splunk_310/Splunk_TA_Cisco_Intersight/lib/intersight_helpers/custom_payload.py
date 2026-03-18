# pylint: disable=C0302
# this file contains payload for metrics telemetry/timeseries api. This
# exception is added as dividing this constants file into multiple files
# does not make sense as the payloads should be easily accessible in single
# file for better readability.
"""
Payload constants for Intersight API.

This module contains the payload constants used for querying the Intersight API.
"""
from intersight_helpers import constants


class CustomPayloads:
    """Payload builder for Metrics Query."""

    @staticmethod
    def build_aggregations(metrics_name, metrics_types, field_names=None):
        """
        Build aggregations array based on metrics name and selected types.

        Args:
            metrics_name (str): The base metrics name (e.g., "hw.fan.speed")
            metrics_types (list): List of metric types (e.g., ["sum", "min", "max"])
            field_names (dict): Optional dict of user-provided field names per type
                                e.g., {"sum": "hw.fan.speed", "min": "hw.fan.speed_min"}

        Returns:
            list: List of aggregation definitions
        """
        aggregations = []
        field_names = field_names or {}
        for metric_type in metrics_types:
            if metric_type == "sum":
                # Get field name from user input or generate default
                field_name = field_names.get("sum", metrics_name)
                # Sum aggregation (also used for count and average calculation)
                aggregations.extend([
                    {
                        "type": "longSum",
                        "name": f"{metrics_name}-Sum",  # sum
                        "fieldName": field_name
                    }
                ])
            elif metric_type == "min":
                # Get field name from user input or generate default
                field_name = field_names.get("min", f"{metrics_name}_min")
                aggregations.append({
                    "type": "longMin",
                    "name": f"{metrics_name}-Min",  # min
                    "fieldName": field_name
                })
            elif metric_type == "max":
                # Get field name from user input or generate default
                field_name = field_names.get("max", f"{metrics_name}_max")
                aggregations.append({
                    "type": "longMax",
                    "name": f"{metrics_name}-Max",  # max
                    "fieldName": field_name
                })
            elif metric_type == "avg":
                # Get field names from user input or generate defaults
                # avg needs two fields: sum and count
                avg_field_value = field_names.get("avg")
                if avg_field_value and "/" in avg_field_value:
                    avg_fields = avg_field_value.split("/")
                    sum_field = avg_fields[0].strip() if len(avg_fields) > 0 else metrics_name
                    count_field = avg_fields[1].strip() if len(avg_fields) > 1 else f"{metrics_name}_count"
                else:
                    sum_field = metrics_name
                    count_field = f"{metrics_name}_count"

                aggregations.append({
                    "type": "doubleSum",
                    "name": f"{metrics_name}_Sum",
                    "fieldName": sum_field
                })
                aggregations.append({
                    "type": "longSum",
                    "name": f"{metrics_name}-Count",
                    "fieldName": count_field
                })
            elif metric_type == "latest":
                # Get field name from user input or generate default
                field_name = field_names.get("latest", metrics_name)
                aggregations.append({
                    "type": "longLast",
                    "name": f"{metrics_name}-Last",
                    "fieldName": field_name
                })

        return aggregations

    @staticmethod
    def build_post_aggregations(metrics_name, metrics_types):
        """Build postAggregations array for calculated metrics like average."""
        post_aggregations = []

        # Add average calculation if avg is selected
        if "avg" in metrics_types:
            post_aggregations.append({
                "type": "expression",
                "name": f"{metrics_name}-Avg",  # average
                "expression": f'("{metrics_name}_Sum" / "{metrics_name}-Count")'
            })

        return post_aggregations

    @staticmethod
    def build_custom_payload(metrics_name, metrics_types, groupby_fields=None, granularity="900", field_names=None):
        """
        Build complete custom payload based on user inputs.

        Args:
            metrics_name (str): The metrics name (e.g., "hw.fan.speed")
            metrics_types (list): List of metric types (e.g., ["sum", "min", "max", "avg", "latest])
            groupby_fields (list): List of group by dimensions (default: ["id"])
            granularity (str): Time granularity ("900", "1800", "3600")
            field_names (dict): Optional dict of user-provided field names per type

        Returns:
            dict: Complete payload for the metrics query
        """
        if groupby_fields is None:
            groupby_fields = ["id"]

        # Convert granularity to ISO 8601 period format
        granularity_map = {
            "900": "PT15M",
            "1800": "PT30M",
            "3600": "PT1H"
        }
        period = granularity_map.get(granularity, "PT15M")

        # Build aggregations and post-aggregations
        aggregations = CustomPayloads.build_aggregations(metrics_name, metrics_types, field_names)
        post_aggregations = CustomPayloads.build_post_aggregations(metrics_name, metrics_types)
        metrics_name_only = None
        if '.' in metrics_name:
            # Split by dots and remove the last part (which is usually the metric type)
            parts = metrics_name.split('.')
            if len(parts) >= 2:
                metrics_name_only = '.'.join(parts[:2])
            else:
                metrics_name_only = metrics_name
        not_null_metrics_name = next(
            (field_names.get(metric) for metric in [
                "sum", "min", "max", "latest"] if
                field_names.get(metric)), metrics_name
        )
        payload = {
            "queryType": "groupBy",
            "dataSource": "PhysicalEntities",
            "granularity": {
                "type": "period",
                "period": period
            },
            "intervals": [
                "2024-11-12T10:00:00.000Z/2024-11-12T10:15:00.000Z"  # Will be replaced with actual intervals
            ],
            "dimensions": groupby_fields,
            "filter": {
                "type": "and",
                "fields": [
                    {
                        "type": "selector",
                        "dimension": "instrument.name",
                        "value": metrics_name_only
                    },
                    {
                        "type": "not",
                        "field": {
                            "type": "null",
                            "column": not_null_metrics_name
                        }
                    },
                    {
                        "type": "in",
                        "dimension": "intersight.license.license_info.license_type",
                        "values": constants.Endpoints.SUPPORTED_LICENSE_TIERS
                    }
                ]
            },
            "aggregations": aggregations,
            "postAggregations": post_aggregations
        }

        return payload

    # Example static payload for reference
    custom_template = {
        "queryType": "groupBy",
        "dataSource": "PhysicalEntities",
        "granularity": {
            "type": "period",
            "period": "PT15M"
        },
        "intervals": [
            "2024-11-12T10:00:00.000Z/2024-11-12T10:15:00.000Z"
        ],
        "dimensions": ["id"],
        "filter": {
            "type": "and",
            "fields": [
                {
                    "type": "selector",
                    "dimension": "instrument.name",
                    "value": "hw.fan.speed"
                },
                {
                    "type": "in",
                    "dimension": "intersight.license.license_info.license_type",
                    "values": constants.Endpoints.SUPPORTED_LICENSE_TIERS
                }
            ]
        },
        "aggregations": [],
        "postAggregations": []
    }
