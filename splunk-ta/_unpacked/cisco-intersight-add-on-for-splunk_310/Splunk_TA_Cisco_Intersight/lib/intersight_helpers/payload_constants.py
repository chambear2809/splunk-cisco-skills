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


class Payloads:
    """Payload of Metrics Query."""

    fan = {
        "metric": {
            "queryType": "groupBy",
            "dataSource": "PhysicalEntities",
            "granularity": {
                "type": "period",
                "period": "PT15M"
            },
            "intervals": [
                "2024-11-12T10:00:00.000Z/2024-11-12T10:15:00.000Z"
                # this will be replaced with actual date time in the fetch_metrics_data function of MetricHelper class
            ],
            "dimensions": [
                "id",
                "hw.fan.airflow_direction",
                "model_generation",
                "model_family",
                "model",
                "serial_number"
            ],
            "filter": {
                "type": "and",
                "fields": [
                    {
                        "type": "selector",
                        "dimension": "instrument.name",
                        "value": "hw.fan"
                    },
                    {
                        "type": "in",
                        "dimension": "intersight.license.license_info.license_type",
                        "values": constants.Endpoints.SUPPORTED_LICENSE_TIERS
                    }
                ]
            },
            "aggregations": [
            ],
            "postAggregations": [
            ]
        },
        "hw.fan.speed_aggregations": [
            {
                "type": "longSum",
                "name": "fsc",
                "fieldName": "hw.fan.speed_count"
            },
            {
                "type": "longSum",
                "name": "fss",
                "fieldName": "hw.fan.speed"
            },
            {
                "type": "longMax",
                "name": "fsmx",
                "fieldName": "hw.fan.speed_max"
            },
            {
                "type": "longMin",
                "name": "fsmn",
                "fieldName": "hw.fan.speed_min"
            }
        ],
        "hw.fan.speed_postAggregations": [
            {
                "type": "expression",
                "name": "fsa",
                "expression": "(\"fss\" / \"fsc\")"
            }
        ]
    }

    host = {
        "metric": {
            "queryType": "groupBy",
            "dataSource": "PhysicalEntities",
            "granularity": {
                "type": "period",
                "period": "PT15M"
            },
            "intervals": [
                "2024-11-12T10:00:00.000Z/2024-11-12T10:15:00.000Z"
                # this will be replaced with actual date time in the fetch_metrics_data function of MetricHelper class
            ],
            "dimensions": [
                "host.id",
                "model_generation",
                "model_family"
            ],
            "filter": {
                "type": "and",
                "fields": [
                    {
                        "type": "selector",
                        "dimension": "instrument.name",
                        "value": "hw.host"
                    },
                    {
                        "type": "in",
                        "dimension": "intersight.license.license_info.license_type",
                        "values": constants.Endpoints.SUPPORTED_LICENSE_TIERS
                    }
                ]
            },
            "aggregations": [
            ],
            "postAggregations": [
            ]
        },
        "hw.host.power_aggregations": [
            {
                "type": "longSum",
                "name": "hpc",
                "fieldName": "hw.host.power_count"
            },
            {
                "type": "doubleSum",
                "name": "hps",
                "fieldName": "hw.host.power"
            },
            {
                "type": "doubleMax",
                "name": "hpmx",
                "fieldName": "hw.host.power_max"
            },
            {
                "type": "doubleMin",
                "name": "hpmn",
                "fieldName": "hw.host.power_min"
            }
        ],
        "hw.host.power_postAggregations": [
            {
                "type": "expression",
                "name": "hpa",
                "expression": "(\"hps\" / \"hpc\")"
            }
        ],
        "hw.host.energy_aggregations": [
            {
                "type": "doubleSum",
                "name": "hes",
                "fieldName": "hw.host.energy"
            },
            {
                "type": "longSum",
                "name": "hec",
                "fieldName": "hw.host.energy"
            },
            {
                "type": "doubleMax",
                "name": "hemx",
                "fieldName": "hw.host.energy"
            },
            {
                "type": "doubleMin",
                "name": "hemn",
                "fieldName": "hw.host.energy"
            }
        ],
        "hw.host.energy_postAggregations": [
            {
                "type": "expression",
                "name": "hea",
                "expression": "(\"hes\" / \"hec\")"
            }
        ]
    }

    network = {
        "metric": {
            "queryType": "groupBy",
            "dataSource": "NetworkInterfaces",
            "granularity": {
                "type": "period",
                "period": "PT15M"
            },
            "intervals": [
                "2024-11-12T10:00:00.000Z/2024-11-12T10:15:00.000Z"
                # this will be replaced with actual date time in the fetch_metrics_data function of MetricHelper class
            ],
            "dimensions": [
                "id",
                "model_generation",
                "model_family",
                "host.id",
                "serial_number",
                "hw.network.port.role",
                "host.name"
            ],
            "filter": {
                "type": "and",
                "fields": [
                    {
                        "type": "selector",
                        "dimension": "instrument.name",
                        "value": "hw.network"
                    },
                    {
                        "type": "in",
                        "dimension": "intersight.license.license_info.license_type",
                        "values": constants.Endpoints.SUPPORTED_LICENSE_TIERS
                    }
                ]
            },
            "aggregations": [
            ],
            "postAggregations": [
            ]
        },
        "hw.network.bandwidth.utilization_receive_aggregations": [
            {
                "type": "longSum",
                "name": "nurc",
                "fieldName": "hw.network.bandwidth.utilization_receive_count"
            },
            {
                "type": "doubleSum",
                "name": "nurs",
                "fieldName": "hw.network.bandwidth.utilization_receive"
            },
            {
                "type": "doubleMin",
                "name": "nurmn",
                "fieldName": "hw.network.bandwidth.utilization_receive_min"
            },
            {
                "type": "doubleMax",
                "name": "nurmx",
                "fieldName": "hw.network.bandwidth.utilization_receive_max"
            }
        ],
        "hw.network.bandwidth.utilization_receive_postAggregations": [
            {
                "type": "expression",
                "name": "nura",
                "expression": "(\"nurs\" / \"nurc\")"
            }
        ],
        "hw.network.bandwidth.utilization_transmit_aggregations": [
            {
                "type": "longSum",
                "name": "nutc",
                "fieldName": "hw.network.bandwidth.utilization_transmit_count"
            },
            {
                "type": "doubleSum",
                "name": "nuts",
                "fieldName": "hw.network.bandwidth.utilization_transmit"
            },
            {
                "type": "doubleMin",
                "name": "nutmn",
                "fieldName": "hw.network.bandwidth.utilization_transmit_min"
            },
            {
                "type": "doubleMax",
                "name": "nutmx",
                "fieldName": "hw.network.bandwidth.utilization_transmit_max"
            }
        ],
        "hw.network.bandwidth.utilization_transmit_postAggregations": [
            {
                "type": "expression",
                "name": "nuta",
                "expression": "(\"nuts\" / \"nutc\")"
            }
        ],
        "hw.network.io_receive_aggregations": [
            {
                "type": "doubleSum",
                "name": "nirds",
                "fieldName": "hw.network.io_receive_duration"
            },
            {
                "type": "longSum",
                "name": "nirs",
                "fieldName": "hw.network.io_receive"
            },
            {
                "type": "doubleSum",
                "name": "nirsag",
                "fieldName": "hw.network.io_receive"
            },
            {
                "type": "doubleMax",
                "name": "nirmx",
                "fieldName": "hw.network.io_receive_max"
            },
            {
                "type": "doubleMin",
                "name": "nirmn",
                "fieldName": "hw.network.io_receive_min"
            }
        ],
        "hw.network.io_receive_postAggregations": [
            {
                "type": "expression",
                "name": "nirr",
                "expression": "(\"nirs\" / \"nirds\")"
            },
            {
                "type": "expression",
                "name": "nirspa",
                "expression": "(round((\"nirsag\" * 600) / \"nirds\"), 0))"
            }
        ],
        "hw.network.io_transmit_aggregations": [
            {
                "type": "doubleSum",
                "name": "nitds",
                "fieldName": "hw.network.io_transmit_duration"
            },
            {
                "type": "longSum",
                "name": "nits",
                "fieldName": "hw.network.io_transmit"
            },
            {
                "type": "doubleSum",
                "name": "nitsag",
                "fieldName": "hw.network.io_transmit"
            },
            {
                "type": "doubleMax",
                "name": "nitmx",
                "fieldName": "hw.network.io_transmit_max"
            },
            {
                "type": "doubleMin",
                "name": "nitmn",
                "fieldName": "hw.network.io_transmit_min"
            }
        ],
        "hw.network.io_transmit_postAggregations": [
            {
                "type": "expression",
                "name": "nitr",
                "expression": "(\"nits\" / \"nitds\")"
            },
            {
                "type": "expression",
                "name": "nitspa",
                "expression": "(round((\"nitsag\" * 600) / \"nitds\"), 0))"
            }
        ],
        "hw.errors_network_receive_crc_aggregations": [
            {
                "type": "doubleSum",
                "name": "ncrcc",
                "fieldName": "hw.errors_network_receive_crc_duration"
            },
            {
                "type": "longSum",
                "name": "ncrccs",
                "fieldName": "hw.errors_network_receive_crc"
            }
        ],
        "hw.errors_network_receive_crc_postAggregations": [
            {
                "type": "expression",
                "name": "ncrccr",
                "expression": "(\"ncrccs\" / \"ncrcc\")"
            }
        ],
        "hw.errors_network_receive_all_aggregations": [
            {
                "type": "doubleSum",
                "name": "nrac",
                "fieldName": "hw.errors_network_receive_all_duration"
            }
        ],
        "hw.errors_network_transmit_all_aggregations": [
            {
                "type": "doubleSum",
                "name": "ntac",
                "fieldName": "hw.errors_network_transmit_all_duration"
            }
        ],
        "hw.errors_network_receive_pause_aggregations": [
            {
                "type": "doubleSum",
                "name": "nrpds",
                "fieldName": "hw.errors_network_receive_pause_duration"
            },
            {
                "type": "longSum",
                "name": "nrps",
                "fieldName": "hw.errors_network_receive_pause"
            },
            {
                "type": "doubleMin",
                "name": "nrpmn",
                "fieldName": "hw.errors_network_receive_pause_min"
            },
            {
                "type": "doubleMax",
                "name": "nrpmx",
                "fieldName": "hw.errors_network_receive_pause_max"
            }
        ],
        "hw.errors_network_receive_pause_postAggregations": [
            {
                "type": "expression",
                "name": "nrpr",
                "expression": "(\"nrps\" / \"nrpds\")"
            }
        ],
        "hw.errors_network_transmit_pause_aggregations": [
            {
                "type": "doubleSum",
                "name": "ntpds",
                "fieldName": "hw.errors_network_transmit_pause_duration"
            },
            {
                "type": "longSum",
                "name": "ntps",
                "fieldName": "hw.errors_network_transmit_pause"
            },
            {
                "type": "doubleMin",
                "name": "ntpmn",
                "fieldName": "hw.errors_network_transmit_pause_min"
            },
            {
                "type": "doubleMax",
                "name": "ntpmx",
                "fieldName": "hw.errors_network_transmit_pause_max"
            }
        ],
        "hw.errors_network_transmit_pause_postAggregations": [
            {
                "type": "expression",
                "name": "ntpr",
                "expression": "(\"ntps\" / \"ntpds\")"
            }
        ],
        "hw.network.packets_receive_ppp_aggregations": [
            {
                "type": "doubleSum",
                "name": "nprpppds",
                "fieldName": "hw.network.packets_receive_ppp_duration"
            },
            {
                "type": "longSum",
                "name": "nprppps",
                "fieldName": "hw.network.packets_receive_ppp"
            },
            {
                "type": "doubleMin",
                "name": "nprpppmn",
                "fieldName": "hw.network.packets_receive_ppp_min"
            },
            {
                "type": "doubleMax",
                "name": "nprpppmx",
                "fieldName": "hw.network.packets_receive_ppp_max"
            },
            {
                "type": "doubleSum",
                "name": "nprpppsag",
                "fieldName": "hw.network.packets_receive_ppp"
            }
        ],
        "hw.network.packets_receive_ppp_postAggregations": [
            {
                "type": "expression",
                "name": "nprpppr",
                "expression": "(\"nprppps\" / \"nprpppds\")"
            },
            {
                "type": "expression",
                "name": "nprpppsum",
                "expression": "(round((\"nprpppsag\" * 600) / \"nprpppds\"), 0)"
            }
        ],
        "hw.network.packets_transmit_ppp_aggregations": [
            {
                "type": "doubleSum",
                "name": "nptpppds",
                "fieldName": "hw.network.packets_transmit_ppp_duration"
            },
            {
                "type": "longSum",
                "name": "nptppps",
                "fieldName": "hw.network.packets_transmit_ppp"
            },
            {
                "type": "doubleMin",
                "name": "nptpppmn",
                "fieldName": "hw.network.packets_transmit_ppp_min"
            },
            {
                "type": "doubleMax",
                "name": "nptpppmx",
                "fieldName": "hw.network.packets_transmit_ppp_max"
            },
            {
                "type": "doubleSum",
                "name": "nptpppsag",
                "fieldName": "hw.network.packets_transmit_ppp"
            }
        ],
        "hw.network.packets_transmit_ppp_postAggregations": [
            {
                "type": "expression",
                "name": "nptpppr",
                "expression": "(\"nptppps\" / \"nptpppds\")"
            },
            {
                "type": "expression",
                "name": "nptpppsum",
                "expression": "(round((\"nptpppsag\" * 600) / \"nptpppds\"), 0))"
            }
        ],
        "hw.errors_network_receive_runt_aggregations": [
            {
                "type": "doubleSum",
                "name": "nrrds",
                "fieldName": "hw.errors_network_receive_runt_duration"
            },
            {
                "type": "longSum",
                "name": "nrrs",
                "fieldName": "hw.errors_network_receive_runt"
            },
            {
                "type": "doubleMin",
                "name": "nrrmn",
                "fieldName": "hw.errors_network_receive_runt_min"
            },
            {
                "type": "doubleMax",
                "name": "nrrmx",
                "fieldName": "hw.errors_network_receive_runt_max"
            }
        ],
        "hw.errors_network_receive_runt_postAggregations": [
            {
                "type": "expression",
                "name": "nrrr",
                "expression": "(\"nrrs\" / \"nrrds\")"
            }
        ],
        "hw.errors_network_receive_too_long_aggregations": [
            {
                "type": "doubleSum",
                "name": "enrtld",
                "fieldName": "hw.errors_network_receive_too_long_duration"
            },
            {
                "type": "longSum",
                "name": "enrtls",
                "fieldName": "hw.errors_network_receive_too_long"
            },
            {
                "type": "doubleMin",
                "name": "enrtlmn",
                "fieldName": "hw.errors_network_receive_too_long_min"
            },
            {
                "type": "doubleMax",
                "name": "enrtlmx",
                "fieldName": "hw.errors_network_receive_too_long_max"
            }
        ],
        "hw.errors_network_receive_too_long_postAggregations": [
            {
                "type": "expression",
                "name": "enrtlr",
                "expression": "(\"enrtls\" / \"enrtld\")"
            }
        ],
        "hw.errors_network_receive_no_buffer_aggregations": [
            {
                "type": "doubleSum",
                "name": "enrnbds",
                "fieldName": "hw.errors_network_receive_no_buffer_duration"
            },
            {
                "type": "longSum",
                "name": "enrnbs",
                "fieldName": "hw.errors_network_receive_no_buffer"
            },
            {
                "type": "doubleMin",
                "name": "enrnbmn",
                "fieldName": "hw.errors_network_receive_no_buffer_min"
            },
            {
                "type": "doubleMax",
                "name": "enrnbmx",
                "fieldName": "hw.errors_network_receive_no_buffer_max"
            }
        ],
        "hw.errors_network_receive_no_buffer_postAggregations": [
            {
                "type": "expression",
                "name": "enrnbr",
                "expression": "(\"enrnbs\" / \"enrnbds\")"
            }
        ],
        "hw.errors_network_receive_too_short_aggregations": [
            {
                "type": "doubleSum",
                "name": "enrtsds",
                "fieldName": "hw.errors_network_receive_too_short_duration"
            },
            {
                "type": "longSum",
                "name": "enrtss",
                "fieldName": "hw.errors_network_receive_too_short"
            },
            {
                "type": "doubleMin",
                "name": "enrtsmn",
                "fieldName": "hw.errors_network_receive_too_short_min"
            },
            {
                "type": "doubleMax",
                "name": "enrtsmx",
                "fieldName": "hw.errors_network_receive_too_short_max"
            }
        ],
        "hw.errors_network_receive_too_short_postAggregations": [
            {
                "type": "expression",
                "name": "enrtsr",
                "expression": "(\"enrtss\" / \"enrtsds\")"
            }
        ],
        "hw.errors_network_receive_discard_aggregations": [
            {
                "type": "doubleSum",
                "name": "enrdds",
                "fieldName": "hw.errors_network_receive_discard_duration"
            },
            {
                "type": "longSum",
                "name": "enrds",
                "fieldName": "hw.errors_network_receive_discard"
            },
            {
                "type": "doubleMin",
                "name": "enrdmn",
                "fieldName": "hw.errors_network_receive_discard_min"
            },
            {
                "type": "doubleMax",
                "name": "enrdmx",
                "fieldName": "hw.errors_network_receive_discard_max"
            }
        ],
        "hw.errors_network_receive_discard_postAggregations": [
            {
                "type": "expression",
                "name": "enrdr",
                "expression": "(\"enrds\" / \"enrdds\")"
            }
        ],
        "hw.errors_network_transmit_discard_aggregations": [
            {
                "type": "doubleSum",
                "name": "entdds",
                "fieldName": "hw.errors_network_transmit_discard_duration"
            },
            {
                "type": "longSum",
                "name": "entds",
                "fieldName": "hw.errors_network_transmit_discard"
            },
            {
                "type": "doubleMin",
                "name": "entdmn",
                "fieldName": "hw.errors_network_transmit_discard_min"
            },
            {
                "type": "doubleMax",
                "name": "entdmx",
                "fieldName": "hw.errors_network_transmit_discard_max"
            }
        ],
        "hw.errors_network_transmit_discard_postAggregations": [
            {
                "type": "expression",
                "name": "entdr",
                "expression": "(\"entds\" / \"entdds\")"
            }
        ],
        "hw.errors_network_transmit_deferred_aggregations": [
            {
                "type": "doubleSum",
                "name": "entdfds",
                "fieldName": "hw.errors_network_transmit_deferred_duration"
            },
            {
                "type": "longSum",
                "name": "entdfs",
                "fieldName": "hw.errors_network_transmit_deferred"
            },
            {
                "type": "doubleMin",
                "name": "entdfmn",
                "fieldName": "hw.errors_network_transmit_deferred_min"
            },
            {
                "type": "doubleMax",
                "name": "entdfmx",
                "fieldName": "hw.errors_network_transmit_deferred_max"
            }
        ],
        "hw.errors_network_transmit_deferred_postAggregations": [
            {
                "type": "expression",
                "name": "entdfr",
                "expression": "(\"entdfs\" / \"entdfds\")"
            }
        ],
        "hw.errors_network_late_collisions_aggregations": [
            {
                "type": "doubleSum",
                "name": "enlcds",
                "fieldName": "hw.errors_network_late_collisions_duration"
            },
            {
                "type": "longSum",
                "name": "enlcs",
                "fieldName": "hw.errors_network_late_collisions"
            },
            {
                "type": "doubleMin",
                "name": "enlcmn",
                "fieldName": "hw.errors_network_late_collisions_min"
            },
            {
                "type": "doubleMax",
                "name": "enlcmx",
                "fieldName": "hw.errors_network_late_collisions_max"
            }
        ],
        "hw.errors_network_late_collisions_postAggregations": [
            {
                "type": "expression",
                "name": "enlcr",
                "expression": "(\"enlcs\" / \"enlcds\")"
            }
        ],
        "hw.errors_network_carrier_sense_aggregations": [
            {
                "type": "doubleSum",
                "name": "encsds",
                "fieldName": "hw.errors_network_carrier_sense_duration"
            },
            {
                "type": "longSum",
                "name": "encss",
                "fieldName": "hw.errors_network_carrier_sense"
            },
            {
                "type": "doubleMin",
                "name": "encsmn",
                "fieldName": "hw.errors_network_carrier_sense_min"
            },
            {
                "type": "doubleMax",
                "name": "encsmx",
                "fieldName": "hw.errors_network_carrier_sense_max"
            }
        ],
        "hw.errors_network_carrier_sense_postAggregations": [
            {
                "type": "expression",
                "name": "encsr",
                "expression": "(\"encss\" / \"encsds\")"
            }
        ],
        "hw.errors_network_transmit_jabber_aggregations": [
            {
                "type": "doubleSum",
                "name": "entjds",
                "fieldName": "hw.errors_network_transmit_jabber_duration"
            },
            {
                "type": "longSum",
                "name": "entjs",
                "fieldName": "hw.errors_network_transmit_jabber"
            },
            {
                "type": "doubleMin",
                "name": "entjmn",
                "fieldName": "hw.errors_network_transmit_jabber_min"
            },
            {
                "type": "doubleMax",
                "name": "entjmx",
                "fieldName": "hw.errors_network_transmit_jabber_max"
            }
        ],
        "hw.errors_network_transmit_jabber_postAggregations": [
            {
                "type": "expression",
                "name": "entjr",
                "expression": "(\"entjs\" / \"entjds\")"
            }
        ]
    }

    temperature = {
        "metric": {
            "queryType": "groupBy",
            "dataSource": "PhysicalEntities",
            "granularity": {
                "type": "period",
                "period": "PT15M"
            },
            "intervals": [
                "2024-11-12T10:00:00.000Z/2024-11-12T10:15:00.000Z"
                # this will be replaced with actual date time in the fetch_metrics_data function of MetricHelper class
            ],
            "dimensions": [
                "hw.temperature.sensor.airflow_direction",
                "model_generation",
                "id",
                "name",
                "model_family",
                "sensor_location",
                "hw.temperature.sensor.name"
            ],
            "filter": {
                "type": "and",
                "fields": [
                    {
                        "type": "selector",
                        "dimension": "instrument.name",
                        "value": "hw.temperature"
                    },
                    {
                        "type": "in",
                        "dimension": "intersight.license.license_info.license_type",
                        "values": constants.Endpoints.SUPPORTED_LICENSE_TIERS
                    }
                ]
            },
            "aggregations": [
            ],
            "postAggregations": [
            ]
        },
        "hw.temperature_aggregations": [
            {
                "type": "longSum",
                "name": "tc",
                "fieldName": "hw.temperature_count"
            },
            {
                "type": "doubleSum",
                "name": "ts",
                "fieldName": "hw.temperature"
            },
            {
                "type": "doubleMax",
                "name": "tmx",
                "fieldName": "hw.temperature_max"
            },
            {
                "type": "doubleMin",
                "name": "tmn",
                "fieldName": "hw.temperature_min"
            }
        ],
        "hw.temperature_postAggregations": [
            {
                "type": "expression",
                "name": "ta",
                "expression": "(\"ts\" / \"tc\")"
            }
        ]
    }

    memory = {
        "metric": {
            "queryType": "groupBy",
            "dataSource": "PhysicalEntities",
            "granularity": {
                "type": "period",
                "period": "PT15M"
            },
            "intervals": [
                "2024-11-12T10:00:00.000Z/2024-11-12T10:15:00.000Z"
                # this will be replaced with actual date time in the fetch_metrics_data function of MetricHelper class
            ],
            "dimensions": [
                "id",
                "model_generation",
                "model_family",
                "model",
                "serial_number"
            ],
            "filter": {
                "type": "and",
                "fields": [
                    {
                        "type": "selector",
                        "dimension": "instrument.name",
                        "value": "hw.memory"
                    },
                    {
                        "type": "in",
                        "dimension": "intersight.license.license_info.license_type",
                        "values": constants.Endpoints.SUPPORTED_LICENSE_TIERS
                    }
                ]
            },
            "aggregations": [
            ],
            "postAggregations": [
            ]
        },
        "hw.errors_correctable_ecc_errors_aggregations": [
            {
                "type": "doubleSum",
                "name": "mceds",
                "fieldName": "hw.errors_correctable_ecc_errors_duration"
            },
            {
                "type": "longSum",
                "name": "mces",
                "fieldName": "hw.errors_correctable_ecc_errors"
            },
            {
                "type": "doubleMax",
                "name": "mcemx",
                "fieldName": "hw.errors_correctable_ecc_errors_max"
            },
            {
                "type": "doubleMin",
                "name": "mcemn",
                "fieldName": "hw.errors_correctable_ecc_errors_min"
            }
        ],
        "hw.errors_correctable_ecc_errors_postAggregations": [
            {
                "type": "expression",
                "name": "mcer",
                "expression": "(\"mces\" / \"mceds\")"
            }
        ],
        "hw.errors_uncorrectable_ecc_errors_aggregations": [
            {
                "type": "doubleSum",
                "name": "mueds",
                "fieldName": "hw.errors_uncorrectable_ecc_errors_duration"
            },
            {
                "type": "longSum",
                "name": "mues",
                "fieldName": "hw.errors_uncorrectable_ecc_errors"
            },
            {
                "type": "doubleMin",
                "name": "muemn",
                "fieldName": "hw.errors_uncorrectable_ecc_errors_min"
            },
            {
                "type": "doubleMax",
                "name": "muemx",
                "fieldName": "hw.errors_uncorrectable_ecc_errors_max"
            }
        ],
        "hw.errors_uncorrectable_ecc_errors_postAggregations": [
            {
                "type": "expression",
                "name": "muer",
                "expression": "(\"mues\" / \"mueds\")"
            }
        ]
    }

    cpu_utilization = {
        "metric": {
            "queryType": "groupBy",
            "dataSource": "PhysicalEntities",
            "granularity": {
                "type": "period",
                "period": "PT15M"
            },
            "intervals": [
                "2024-11-12T10:00:00.000Z/2024-11-12T10:15:00.000Z"
                # this will be replaced with actual date time in the fetch_metrics_data function of MetricHelper class
            ],
            "dimensions": [
                "host.id"
            ],
            "filter": {
                "type": "and",
                "fields": [
                    {
                        "type": "selector",
                        "dimension": "instrument.name",
                        "value": "hw.cpu"
                    }
                ]
            },
            "aggregations": [
            ],
            "postAggregations": [
            ]
        },
        "hw.cpu.utilization_c0_aggregations": [
            {
                "type": "longSum",
                "name": "cc",
                "fieldName": "hw.cpu.utilization_c0_count"
            },
            {
                "type": "doubleSum",
                "name": "cs",
                "fieldName": "hw.cpu.utilization_c0"
            },
            {
                "type": "doubleMin",
                "name": "cmn",
                "fieldName": "hw.cpu.utilization_c0_min"
            },
            {
                "type": "doubleMax",
                "name": "cmx",
                "fieldName": "hw.cpu.utilization_c0_max"
            }
        ],
        "hw.cpu.utilization_c0_postAggregations": [
            {
                "type": "expression",
                "name": "ca",
                "expression": "(\"cs\" / \"cc\")"
            }
        ]
    }
