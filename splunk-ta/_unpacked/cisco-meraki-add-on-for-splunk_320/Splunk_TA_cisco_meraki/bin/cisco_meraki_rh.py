#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#

import os

import splunk.rest as rest
from solnlib import log
from splunktaucclib.rest_handler import admin_external

APP_NAME = __file__.split(os.path.sep)[-3]


class CiscoMerakiExternalHandler(admin_external.AdminExternalHandler):
    """This class contains methods related to Checkpointing."""

    def __init__(self, *args, **kwargs):
        """Initialize the CiscoMerakiExternalHandler class."""
        admin_external.AdminExternalHandler.__init__(self, *args, **kwargs)

    def handleList(self, conf_info):
        """Handle the list action for the REST endpoint."""
        admin_external.AdminExternalHandler.handleList(self, conf_info)

    def handleEdit(self, conf_info):
        """Handle the edit action for the REST endpoint."""
        admin_external.AdminExternalHandler.handleEdit(self, conf_info)

    def handleCreate(self, conf_info):
        """Handle the create action for the REST endpoint."""
        admin_external.AdminExternalHandler.handleCreate(self, conf_info)

    def handleRemove(self, conf_info):
        """Handle the remove action for the REST endpoint."""
        self.delete_checkpoint()
        admin_external.AdminExternalHandler.handleRemove(self, conf_info)

    def delete_checkpoint(self):
        """Delete the checkpoint when user deletes input."""
        log_filename = "splunk_ta_cisco_meraki_delete_checkpoint"
        logger = log.Logs().get_logger(log_filename)
        try:
            session_key = self.getSessionKey()
            input_type = self.handler.get_endpoint().input_type
            input_types = [
                "cisco_meraki_accesspoints",
                "cisco_meraki_airmarshal",
                "cisco_meraki_api_request_history",
                "cisco_meraki_api_request_overview",
                "cisco_meraki_api_request_response_code",
                "cisco_meraki_appliance_vpn_stats",
                "cisco_meraki_appliance_vpn_statuses",
                "cisco_meraki_assurance_alerts",
                "cisco_meraki_audit",
                "cisco_meraki_cameras",
                "cisco_meraki_organization_networks",
                "cisco_meraki_organizations",
                "cisco_meraki_device_availabilities_change_history",
                "cisco_meraki_device_uplink_addresses_by_device",
                "cisco_meraki_devices",
                "cisco_meraki_power_modules_statuses_by_device",
                "cisco_meraki_webhook_logs",
                "cisco_meraki_firmware_upgrades",
                "cisco_meraki_licenses_coterm_licenses",
                "cisco_meraki_licenses_overview",
                "cisco_meraki_licenses_subscription_entitlements",
                "cisco_meraki_licenses_subscriptions",
                "cisco_meraki_organizationsecurity",
                "cisco_meraki_securityappliances",
                "cisco_meraki_sensor_readings_history",
                "cisco_meraki_summary_appliances_top_by_utilization",
                "cisco_meraki_summary_switch_power_history",
                "cisco_meraki_summary_top_clients_by_usage",
                "cisco_meraki_summary_top_devices_by_usage",
                "cisco_meraki_summary_top_switches_by_energy_usage",
                "cisco_meraki_switch_port_overview",
                "cisco_meraki_switch_ports_transceivers_readings_history_by_switch",
                "cisco_meraki_switch_ports_by_switch",
                "cisco_meraki_switches",
                "cisco_meraki_wireless_devices_ethernet_statuses",
                "cisco_meraki_wireless_packet_loss_by_device",
                "cisco_meraki_wireless_controller_availabilities_change_history",
                "cisco_meraki_wireless_controller_devices_interfaces_usage_history_by_interval",
                "cisco_meraki_wireless_controller_devices_interfaces_packets_overview_by_device",
                "cisco_meraki_wireless_devices_wireless_controllers_by_device"
            ]

            if input_type in input_types:
                checkpoint_name = input_type + "_" + str(self.callerArgs.id)
                rest_url = (
                    "/servicesNS/nobody/{}/storage/collections/config/{}/".format(
                        APP_NAME, checkpoint_name
                    )
                )
                _, _ = rest.simpleRequest(
                    rest_url,
                    sessionKey=session_key,
                    method="DELETE",
                    getargs={"output_mode": "json"},
                    raiseAllErrors=True,
                )

                logger.info(
                    "Removed checkpoint for {} input".format(str(self.callerArgs.id))
                )
        except Exception as e:
            logger.error(
                "Error while deleting checkpoint for {} input. Error: {}".format(
                    str(self.callerArgs.id), str(e)
                )
            )
