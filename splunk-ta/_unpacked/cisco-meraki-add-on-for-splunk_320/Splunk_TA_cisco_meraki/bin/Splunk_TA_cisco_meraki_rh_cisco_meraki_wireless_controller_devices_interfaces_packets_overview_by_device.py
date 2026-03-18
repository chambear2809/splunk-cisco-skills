import import_declare_test  # noqa: F401 # isort: skip

import logging

import cisco_meraki_rh as rh
from splunktaucclib.rest_handler import admin_external, util
from splunktaucclib.rest_handler.endpoint import (
    DataInputModel,
    RestModel,
    field,
    validator,
)

util.remove_http_proxy_env_vars()


fields = [
    field.RestField(
        "organization_name",
        required=True,
        encrypted=False,
        default=None,
        validator=None,
    ),
    field.RestField(
        "interval",
        required=True,
        encrypted=False,
        default=86400,
        validator=validator.Number(
            max_val=86400,
            min_val=360,
        ),
    ),
    field.RestField(
        "index",
        required=True,
        encrypted=False,
        default="main",
        validator=validator.String(
            max_len=80,
            min_len=1,
        ),
    ),
    field.RestField("disabled", required=False, validator=None),
]
model = RestModel(fields, name=None)


endpoint = DataInputModel(
    "cisco_meraki_wireless_controller_devices_interfaces_packets_overview_by_device",
    model,
)


if __name__ == "__main__":
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=rh.CiscoMerakiExternalHandler,
    )
