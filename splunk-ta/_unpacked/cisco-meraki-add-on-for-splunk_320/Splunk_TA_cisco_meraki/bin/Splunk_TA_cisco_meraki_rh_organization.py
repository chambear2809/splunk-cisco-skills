#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#

import import_declare_test  # noqa: F401 # isort: skip
from cisco_meraki_utils import read_conf_file
import logging

from splunk_ta_cisco_meraki_organization_validation import organization_validation
from splunktaucclib.rest_handler import admin_external, util
from splunktaucclib.rest_handler.admin_external import AdminExternalHandler
from splunk import rest
from urllib.parse import quote_plus
from splunktaucclib.rest_handler.error import RestError
from solnlib import conf_manager
import cisco_meraki_const as const
from solnlib.utils import is_true
from splunktaucclib.rest_handler.endpoint import (
    RestModel,
    SingleModel,
    field,
    validator,
)

util.remove_http_proxy_env_vars()


fields = [
    field.RestField(
        "region",
        required=True,
        encrypted=False,
        default=None,
        validator=validator.Enum(
            values={"global", "india", "canada", "china", "fedramp", "other"},
        ),
    ),
    field.RestField(
        "base_url",
        required=True,
        encrypted=False,
        default=None,
        validator=validator.AllOf(
            validator.String(
                max_len=120,
                min_len=1,
            ),
            validator.Pattern(
                regex= r"^https:\/\/"
            )
        )
    ),
    field.RestField(
        "organization_id",
        required=True,
        encrypted=False,
        default=None,
        validator=validator.AllOf(
            validator.String(
                max_len=50,
                min_len=1,
            ),
            validator.Pattern(
                regex=r"""^\d+$""",
            ),
        ),
    ),
    field.RestField(
        "organization_api_key",
        required=False,
        encrypted=True,
        default=None,
        validator=validator.AllOf(
            validator.String(
                max_len=50,
                min_len=1,
            ),
            validator.Pattern(
                regex=r"""^[a-z0-9]+$""",
            ),
        ),
    ),
    field.RestField(
        "max_api_calls_per_second",
        required=False,
        default="5",
        validator=validator.Number(
            max_val=10,
            min_val=1,
        ),
    ),
    field.RestField(
        "automatic_input_creation", required=False, default="false", validator=None
    ),
    field.RestField(
        "automatic_input_creation_index",
        required=False,
        encrypted=False,
        default="main",
        validator=None
    ),
    field.RestField(
        'domain',
        required=False,
        encrypted=False,
        default=None,
        validator=None
    ), 
    field.RestField(
        'client_id',
        required=False,
        encrypted=False,
        default=None,
        validator=None
    ), 
    field.RestField(
        'client_secret',
        required=False,
        encrypted=True,
        default=None,
        validator=None
    ), 
    field.RestField(
        'redirect_url',
        required=False,
        encrypted=False,
        default=None,
        validator=None
    ), 
    field.RestField(
        'endpoint',
        required=False,
        encrypted=False,
        default='as.meraki.com',
        validator=None
    ), 
    field.RestField(
        'scope',
        required=False,
        encrypted=False,
        default='dashboard:general:config:read dashboard:general:telemetry:read wireless:config:read switch:telemetry:read sdwan:telemetry:read dashboard:licensing:config:read camera:config:read sensor:config:read sensor:telemetry:read camera:telemetry:read switch:config:read wireless:telemetry:read dashboard:general:telemetry:write',
        validator=None
    ), 
    field.RestField(
        'access_token',
        required=False,
        encrypted=True,
        default=None,
        validator=None
    ), 
    field.RestField(
        'refresh_token',
        required=False,
        encrypted=True,
        default=None,
        validator=None
    ), 
    field.RestField(
        'instance_url',
        required=False,
        encrypted=False,
        default=None,
        validator=None
    ), 
    field.RestField(
        'auth_type',
        required=False,
        encrypted=False,
        default=None,
        validator=None
    )
]
model = RestModel(fields, name=None)


endpoint = SingleModel(
    "splunk_ta_cisco_meraki_organization", model, config_name="organization"
)


class CiscoMerakiOrganizationExternalHandler(AdminExternalHandler):
    def __init__(self, *args, **kwargs):
        AdminExternalHandler.__init__(self, *args, **kwargs)

    def handleList(self, confInfo):
        AdminExternalHandler.handleList(self, confInfo)

    def handleEdit(self, confInfo):
        auth_type = self.payload.get("auth_type", "basic")
        key = (
            self.payload.get("organization_api_key") if auth_type == "basic" 
            else self.payload.get("access_token")
        )
        organization_validation(
            self.payload.get("region"),
            self.payload.get("base_url"),
            self.payload.get("organization_id"),
            key,
            self.getSessionKey(),
            auth_type=auth_type
        )
        AdminExternalHandler.handleEdit(self, confInfo)

    def handleCreate(self, confInfo):
        auth_type = self.payload.get("auth_type", "basic")
        key = (
            self.payload.get("organization_api_key") if auth_type == "basic" 
            else self.payload.get("access_token")
        )
        organization_validation(
            self.payload.get("region"),
            self.payload.get("base_url"),
            self.payload.get("organization_id"),
            key,
            self.getSessionKey(),
            auth_type=auth_type
        )
        self.index_name = self.payload.get("automatic_input_creation_index", const.DEFAULT_INDEX)
        if is_true(self.payload.get("automatic_input_creation")):
            self.create_inputs()
        AdminExternalHandler.handleCreate(self, confInfo)

    def create_inputs(self):
        """Create inputs into inputs.conf file if automatic_input_creation checkbox selected."""

        input_types = [
            "accesspoints",
            "airmarshal",
            "audit",
            "cameras",
            "organizationsecurity",
            "securityappliances",
            "switches",
            "devices",
            "power_modules_statuses_by_device",
            "device_availabilities_change_history",
            "device_uplink_addresses_by_device",
            "wireless_devices_ethernet_statuses",
            "wireless_packet_loss_by_device",
            "wireless_controller_availabilities_change_history",
            "wireless_controller_devices_interfaces_usage_history_by_interval",
            "wireless_controller_devices_interfaces_packets_overview_by_device",
            "wireless_devices_wireless_controllers_by_device",
            "sensor_readings_history",
            "summary_appliances_top_by_utilization",
            "summary_switch_power_history",
            "summary_top_clients_by_usage",
            "summary_top_devices_by_usage",
            "summary_top_switches_by_energy_usage",
            "assurance_alerts",
            "api_request_history",
            "api_request_response_code",
            "api_request_overview",
            "appliance_vpn_stats",
            "appliance_vpn_statuses",
            "licenses_overview",
            "licenses_coterm_licenses",
            "licenses_subscription_entitlements",
            "licenses_subscriptions",
            "switch_port_overview",
            "switch_ports_transceivers_readings_history_by_switch",
            "switch_ports_by_switch",
            "firmware_upgrades",
            "organization_networks",
            "organizations",
            "webhook_logs"
        ]

        inputs_created = []

        for input_type in input_types:

            input_stanza = {
                "name": "cisco_meraki_{}://{}_{}".format(
                    input_type, input_type, self.callerArgs.id
                ),
                "organization_name": self.callerArgs.id,
                "disabled": "true",
                "index": self.index_name,
            }

            # Using Splunk internal API to create default input
            try:
                rest.simpleRequest(
                    "/servicesNS/nobody/{}/configs/conf-inputs".format(
                        import_declare_test.ta_name
                    ),
                    self.getSessionKey(),
                    postargs=input_stanza,
                    method="POST",
                    raiseAllErrors=True,
                )
                inputs_created.append(input_type)

            except Exception as e:
                for _input in inputs_created:
                    encoded_stanza = quote_plus(
                        "cisco_meraki_{}://{}_{}".format(
                            _input, _input, self.callerArgs.id
                        ),
                        safe="",
                    )
                    rest.simpleRequest(
                        "/servicesNS/nobody/{}/configs/conf-inputs/{}".format(
                            import_declare_test.ta_name, encoded_stanza
                        ),
                        sessionKey=self.getSessionKey(),
                        method="DELETE",
                        getargs={"output_mode": "json"},
                        raiseAllErrors=True,
                    )
                if "409" in str(e):
                    e = "Cannot create the organization because one or more inputs with the same name\
                        are already present. Consider deleting those inputs or create the organization\
                        without creating new inputs."
                raise RestError(409, str(e))

    def handleRemove(self, confInfo):
        """
        This method is called when account is deleted. It deletes the account if it is not used in the input configurations.
        :param conf_info: The directory containing configurable parameters.
        """
        session_key = self.getSessionKey()
        stanza_name = self.callerArgs.id
        try:
            inputs_file = read_conf_file(session_key, "inputs")
            created_inputs = list(inputs_file.keys())
            input_list = []
            for each in created_inputs:
                each_meraki_input = each.split("://")
                if each.startswith("{}://".format(each_meraki_input[0])):
                    configured_account = inputs_file.get(each).get("organization_name")
                    if configured_account == stanza_name:
                        input_list.append(each.split("://")[1])
            if input_list:
                raise RestError(
                    409,
                    "Cannot delete the account as it is already been used in {}.".format(
                        ", ".join(input_list)
                    ),
                )
        except Exception as e:
            raise RestError(
                409, "Something went wrong while deleting the account.{}".format(str(e))
            )
        AdminExternalHandler.handleRemove(self, confInfo)


if __name__ == "__main__":
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=CiscoMerakiOrganizationExternalHandler,
    )
