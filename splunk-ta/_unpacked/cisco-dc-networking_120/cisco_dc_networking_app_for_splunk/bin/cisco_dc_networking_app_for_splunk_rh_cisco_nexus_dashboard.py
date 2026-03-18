import import_declare_test

from splunktaucclib.rest_handler.endpoint import (
    field,
    validator,
    RestModel,
    DataInputModel,
)
from splunktaucclib.rest_handler import admin_external, util
from splunktaucclib.rest_handler.admin_external import AdminExternalHandler
from cisco_nexus_dashboard_validation import IntervalValidator, SliceValidator, GranualarityValidator

import logging

util.remove_http_proxy_env_vars()

fields = [
    field.RestField(
        'nd_account',
        required=True,
        encrypted=False,
        default=None,
        validator=None
    ),
    field.RestField(
        'interval',
        required=True,
        encrypted=False,
        default=300,
        validator=IntervalValidator()
    ),
    field.RestField(
        'index',
        required=True,
        encrypted=False,
        default='default',
        validator=validator.String(
            max_len=80,
            min_len=1,
        )
    ),
    field.RestField(
        'nd_alert_type',
        required=True,
        encrypted=False,
        default='advisories',
        validator=None
    ),
    field.RestField(
        'nd_anomalies_category',
        required=False,
        encrypted=False,
        default='*',
        validator=None
    ),
    field.RestField(
        'nd_advisories_category',
        required=False,
        encrypted=False,
        default='*',
        validator=None
    ),
    field.RestField(
        'nd_severity',
        required=False,
        encrypted=False,
        default='*',
        validator=None
    ),
    field.RestField(
        'nd_time_range',
        required=False,
        encrypted=False,
        default=4,
        validator=None
    ),
    field.RestField(
        'nd_granularity',
        required=False,
        encrypted=False,
        default='5m',
        validator=GranualarityValidator()
    ),
    field.RestField(
        'nd_time_slice',
        required=False,
        encrypted=False,
        default=5,
        validator=SliceValidator()
    ),
    field.RestField(
        'nd_additional_filter',
        required=False,
        encrypted=False,
        validator=None
    ),
    field.RestField(
        'nd_interface_name',
        required=False,
        encrypted=False,
        validator=None
    ),
    field.RestField(
        'nd_node_name',
        required=False,
        encrypted=False,
        validator=None
    ),
    field.RestField(
        'nd_protocol_site_name',
        required=False,
        encrypted=False,
        validator=None
    ),
    field.RestField(
        'nd_start_date',
        required=False,
        encrypted=False,
        default="1h",
        validator=None
    ),
    field.RestField(
        'nd_flow_start_date',
        required=False,
        encrypted=False,
        default="1m",
        validator=None
    ),
    field.RestField(
        'nd_scope',
        required=False,
        encrypted=False,
        validator=None
    ),
    field.RestField(
        'orchestrator_arguments',
        required=False,
        encrypted=False,
        default=None,
        validator=None
    ),
    field.RestField(
        'custom_endpoint',
        required=False,
        encrypted=False,
        default=None,
        validator=None
    ),
    field.RestField(
        'nd_additional_parameters',
        required=False,
        encrypted=False,
        default=None,
        validator=None
    ),
    field.RestField(
        'custom_sourcetype',
        required=False,
        encrypted=False,
        default=None,
        validator=None
    ),
    field.RestField(
        'custom_resp_key',
        required=False,
        encrypted=False,
        default=None,
        validator=None
    ),
    field.RestField(
        'disabled',
        required=False,
        validator=None
    )

]
model = RestModel(fields, name=None)


endpoint = DataInputModel(
    'cisco_nexus_dashboard',
    model,
)


if __name__ == '__main__':
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=AdminExternalHandler,
    )
