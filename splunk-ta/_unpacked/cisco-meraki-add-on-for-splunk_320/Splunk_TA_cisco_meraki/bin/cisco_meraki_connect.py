#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#

import datetime

import cisco_meraki_utils as utils

from meraki.exceptions import APIError

import cisco_meraki_rest_calls as restapi
import cisco_meraki_const as const

# Maps sourcetype to Meraki specific product type.
SOURCETYPE_PRODUCT_TYPE_MAPPING = {
    utils.SWITCHES_SOURCETYPE: "switch",
    utils.SECURITYAPPLIANCES_SOURCETYPE: "appliance",
    utils.ACCESSPOINTS_SOURCETYPE: "wireless",
    utils.CAMERAS_SOURCETYPE: "camera",
}


class MerakiConnect:
    """Class to make an object of meraki for data collection."""

    def __init__(self, config):
        """
        Initializes connection to Meraki API.

        :param config: Configuration dictionary
        """
        self.input_config = config
        try:
            self._logger = config["logger"]
            self.region = config["region"]
            self.base_url = config["base_url"]
            self.organization_id = config["organization_id"]
            self.max_api_calls_per_second = int(config["max_api_calls_per_second"])

            # Handle different authentication types
            self.auth_type = config.get("auth_type", "basic")
            if self.auth_type == "basic":
                self.organization_api_key = config["organization_api_key"]
                self.access_token = None
            else:  # OAuth2
                self.access_token = config["access_token"]
                self.refresh_token = config["refresh_token"]
                self.client_id = config["client_id"]
                self.client_secret = config["client_secret"]
                self.organization_name = config["organization_name"]
                self.organization_api_key = None
            self.sourcetype = config["sourcetype"]
            self.index = config["index"]
            self.proxies = config["proxies"]
            self.input_name = config["input_name"]
            self.session_key = config["session_key"]
            self.start_from_days_ago = config["start_from_days_ago"]
        except KeyError as e:
            self._logger.error(
                f"Could not find required field from the configuration. KeyError: {e}"
                "Check if all required fields are present and account is configured properly."
            )
            raise
        self.current_time = datetime.datetime.utcnow()
        self.current_time_formatted = self.current_time.strftime(
            const.TIME_FORMAT_WITH_MICRO_SECOND
        )
        self.checkpoint_success = False
        if self.input_name:
            self.checkpoint_name = utils.checkpoint_name_from_input_name(self.input_name)
            self.checkpoint_success, self.checkpoint_collection = utils.checkpoint_handler(
                self._logger, self.session_key, self.checkpoint_name
            )
            if self.checkpoint_success:
                self.start_time = self._get_start_time()

        if self.auth_type == "oauth" and not self.access_token:
            self._logger.error(
                f"No access token available for OAuth2 authentication for organization {self.organization_id}"
            )
            raise Exception(
                f"No access token available for OAuth2 authentication for organization {self.organization_id}"
            )

        # Build dashboard API client with appropriate authentication
        self.dashboard = utils.build_dashboard_api(
            self.base_url, self.organization_api_key, self.proxies, self.session_key,
            auth_type=self.auth_type, access_token=self.access_token
        )
        self.rest_calls = restapi.MerakiRestCalls(config)

        self.kv_ratelimiter_name = f"cisco_meraki_org_id_{self.organization_id}"

        self.rate_limiter = utils.RateLimiter(
            max_calls=self.max_api_calls_per_second,
            period=1,
            logger=self._logger,
            organization_id=self.organization_id,
        )

    def _get_start_time(self):
        checkpoint_data = self.checkpoint_collection.get(self.checkpoint_name)
        if not checkpoint_data:
            self._logger.debug(
                "No checkpoint found for {}".format(self.checkpoint_name)
            )
            if self.start_from_days_ago:
                self._logger.debug(
                    "Found start_from_days_ago for {}".format(self.checkpoint_name)
                )
                start_time = (
                    self.current_time
                    - datetime.timedelta(days=int(self.start_from_days_ago))
                ).strftime(const.TIME_FORMAT_WITH_MICRO_SECOND)
            else:
                self._logger.debug(
                    "No start_from_days_ago found for {}".format(self.checkpoint_name)
                )
                start_time = (self.current_time - datetime.timedelta(days=1)).strftime(
                    const.TIME_FORMAT_WITH_MICRO_SECOND
                )
        else:
            self._logger.debug("Found checkpoint for {}".format(self.checkpoint_name))
            start_time = checkpoint_data.get("start_time")
        self._logger.info(
            "Start time for checkpoint {} - {}".format(self.checkpoint_name, start_time)
        )
        return start_time

    def compare_time(self, input_time, time_delta):
        """Compares timestamp and gives maximum of them."""
        self._logger.debug(
            "Get the most recent time between a {} and a "
            "{} of days ago for {}".format(
                input_time, time_delta, self.input_name
            )
        )
        input_time = datetime.datetime.strptime(
            input_time, const.TIME_FORMAT_WITH_MICRO_SECOND
        ).replace(tzinfo=datetime.timezone.utc)
        current_time = datetime.datetime.now(datetime.timezone.utc)
        delta_time = current_time - datetime.timedelta(days=time_delta)
        result = max(input_time, delta_time)
        final_time = result.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
        self._logger.debug(
            "Set the starting time for data collection to {} for {}.".format(
                final_time, self.input_name
            )
        )
        return final_time

    def _handle_api_error(self, error):
        """Handle API errors, specifically for OAuth2 token refresh.

        :param error: The error that occurred
        :return: True if error was handled, False otherwise
        """
        error_str = str(error)

        # Check if this is a token expired error
        if self.auth_type == "oauth" and ("401" in error_str or "Unauthorized" in error_str):
            self._logger.info(
                f"Access token expired for organization {self.organization_name}."
                " Attempting to refresh access token."
            )

            # Try to refresh the token
            if utils.refresh_access_token(self._logger, self.session_key, self.organization_name):
                # Get updated token
                org_details = utils.get_organization_details(self._logger, self.session_key, self.organization_name)
                self.access_token = org_details.get("access_token")

                # Rebuild the dashboard API client
                self.dashboard = utils.build_dashboard_api(
                    self.base_url, self.organization_api_key, self.proxies, self.session_key,
                    auth_type=self.auth_type, access_token=self.access_token
                )

                return True
            else:
                self._logger.error(f"Failed to refresh token for {self.organization_id}")

        return False

    def check_module_name(self, potential_modules, func_str):
        """Check the module name from the function string."""
        for module in potential_modules:
            if module in func_str.lower():
                return module
        return None

    def check_dashboard_has_module_and_method(self, dashboard, module_name, method_name):
        """Check dashboard contain module and that module contain method."""
        if module_name and hasattr(dashboard, module_name):
            dashboard_module = getattr(dashboard, module_name)
            if hasattr(dashboard_module, method_name):
                return True, dashboard_module
        return False, None

    def _safe_api_call(self, api_func, *args, **kwargs):
        """Safely make API calls with token refresh handling.

        :param api_func: API function to call
        :param args: Positional arguments for the API function
        :param kwargs: Keyword arguments for the API function
        :return: API response
        """
        try:
            return api_func(*args, **kwargs)
        except Exception as e:
            # Try to handle the error (refresh token if needed)
            if self._handle_api_error(e):
                # The dashboard has been refreshed with a new token in _handle_api_error
                # We need to reconstruct the API call using the same module and method
                # from the updated dashboard instance

                # Extract info from the original function
                func_str = str(api_func)
                method_name = api_func.__name__

                # Look for module names in the function string
                # These are the main modules used in the Meraki dashboard API
                potential_modules = [
                    'organizations', 'networks', 'devices', 'appliance', 'wireless',
                    'switch', 'sensor', 'wirelessController', 'licensing'
                ]

                module_name = self.check_module_name(potential_modules, func_str)

                is_method, dashboard_module = self.check_dashboard_has_module_and_method(
                    self.dashboard, module_name, method_name
                )
                if is_method:
                    self._logger.debug("Retrying with refreshed token using {}.{}".format(module_name, method_name))
                    try:
                        # Get the method from the updated dashboard
                        new_api_func = getattr(dashboard_module, method_name)
                        # Call it with the same arguments
                        return new_api_func(*args, **kwargs)
                    except Exception as retry_e:
                        self._logger.error(f"API call failed even after token refresh: {str(retry_e)}")
                        raise
            else:
                # If error not handled, re-raise the exception
                raise

    def get_organization(self):
        """Returns organization information for a specific organization."""
        self._logger.debug(
            "Getting organization information for {}".format(self.organization_id)
        )
        return self._safe_api_call(self.dashboard.organizations.getOrganization, self.organization_id)

    def get_event_host_from_organization(self, organization_info):
        """Returns host derived from organization information."""
        url = organization_info["url"]
        return url.split("//")[1].split("/")[0]

    def get_organization_networks(self):
        """Returns networks information for a specific organization."""
        self._logger.debug(
            "Getting organization networks for {}".format(self.organization_id)
        )
        return self._safe_api_call(
            self.dashboard.organizations.getOrganizationNetworks,
            self.organization_id, perPage=100000
        )

    def get_organizations(self):
        """Returns organizations information."""
        self._logger.debug("Getting organizations for {}".format(self.organization_id))

        return self._safe_api_call(
            self.dashboard.organizations.getOrganizations,
            self.organization_id, perPage=9000
        )

    def get_organization_configuration_changes(self):
        """Returns configuration changes for a specific organization."""
        self._logger.debug(
            "Getting organization configuration changes for {}".format(
                self.organization_id
            )
        )
        return self._safe_api_call(
            self.dashboard.organizations.getOrganizationConfigurationChanges,
            self.organization_id,
            t0=self.compare_time(self.start_time, 60),
            t1=self.current_time_formatted,
            total_pages=-1,
        )

    def get_organization_security_events(self):
        """Returns security events for a specific organization."""
        self._logger.debug(
            "Getting organization appliance security events for {}".format(
                self.organization_id
            )
        )
        return self._safe_api_call(
            self.dashboard.appliance.getOrganizationApplianceSecurityEvents,
            self.organization_id,
            t0=self.compare_time(self.start_time, 60),
            t1=self.current_time_formatted,
            perPage=1000,
            total_pages=-1,
            sortOrder="descending",
        )

    def get_network_events(self, network_id, product_type):
        """Returns network events for a specific product."""
        self._logger.debug(
            "Getting network events for network {} and product type {}".format(
                network_id, product_type
            )
        )
        return self._safe_api_call(
            self.dashboard.networks.getNetworkEvents,
            network_id,
            productType=product_type,
            perPage=1000,
            startingAfter=self.compare_time(self.start_time, 30),
        )

    def get_airmarshal_events(self, network_id):
        """Returns Air Marshal events for specific network."""
        self._logger.debug("Getting network events for network {}".format(network_id))
        return self._safe_api_call(
            self.dashboard.wireless.getNetworkWirelessAirMarshal,
            network_id,
            t0=self.compare_time(self.start_time, 30),
        )

    def get_device_history_events(self):
        """Gets device history events."""
        self._logger.debug(
            "Getting organization change history events for {}".format(
                self.organization_id
            )
        )

        return self._safe_api_call(
            self.dashboard.organizations.getOrganizationDevicesAvailabilitiesChangeHistory,
            self.organization_id,
            total_pages=-1,
            t0=self.compare_time(self.start_time, 30),
            t1=self.current_time_formatted,
        )

    def get_devices_by_address(self):
        """Gets devices by address."""
        self._logger.debug(
            "Getting devices by addresses for {}".format(self.organization_id)
        )

        return self._safe_api_call(
            self.dashboard.organizations.getOrganizationDevicesUplinksAddressesByDevice,
            self.organization_id, total_pages=-1
        )

    def get_ethernet_status_of_devices(self):
        """Gets ethernet status devices."""
        self._logger.debug(
            " Getting ethrnet status of devices for {}".format(self.organization_id)
        )

        return self._safe_api_call(
            self.dashboard.wireless.getOrganizationWirelessDevicesEthernetStatuses,
            self.organization_id, total_pages=-1
        )

    def get_sensor_readings_history(self):
        """Gets sensor readings history."""
        self._logger.debug(
            "Getting sensor reading history for {}".format(self.organization_id)
        )

        return self._safe_api_call(
            self.dashboard.sensor.getOrganizationSensorReadingsHistory,
            self.organization_id,
            total_pages=-1,
            t0=self.compare_time(self.start_time, 7),
            t1=self.current_time_formatted,
        )

    def get_top_appliances(self):
        """Gets top appliances."""
        self._logger.debug("Getting top appliances for {}".format(self.organization_id))

        return self._safe_api_call(
            self.dashboard.organizations.getOrganizationSummaryTopAppliancesByUtilization,
            self.organization_id,
            t0=self.compare_time(self.start_time, 30),
            t1=self.current_time_formatted,
            quantity=self.input_config["top_count"],
        )

    def get_top_clients(self):
        """Gets top clients."""
        self._logger.debug("Getting top clients for {}".format(self.organization_id))

        return self._safe_api_call(
            self.dashboard.organizations.getOrganizationSummaryTopClientsByUsage,
            self.organization_id,
            t0=self.compare_time(self.start_time, 30),
            t1=self.current_time_formatted,
            quantity=self.input_config["top_count"],
        )

    def get_top_devices(self):
        """Gets top devices."""
        self._logger.debug("Getting top devices for {}".format(self.organization_id))

        return self._safe_api_call(
            self.dashboard.organizations.getOrganizationSummaryTopDevicesByUsage,
            self.organization_id,
            t0=self.compare_time(self.start_time, 30),
            t1=self.current_time_formatted,
            quantity=self.input_config["top_count"],
        )

    def get_avg_packet_loss(self):
        """Gets avg packet loss."""
        self._logger.debug("Getting packet loss for {}".format(self.organization_id))

        return self._safe_api_call(
            self.dashboard.wireless.getOrganizationWirelessDevicesPacketLossByDevice,
            self.organization_id,
            total_pages=-1,
            t0=self.compare_time(self.start_time, 30),
            t1=self.current_time_formatted
        )

    def get_assurance_alerts(self):
        """Gets assurance alerts."""
        self._logger.debug(
            "Getting assurance alerts for {}".format(self.organization_id)
        )

        return self._safe_api_call(
            self.dashboard.organizations.getOrganizationAssuranceAlerts,
            self.organization_id,
            total_pages=-1,
            sortOrder="descending",
            tsStart=self.compare_time(self.start_time, 30),
            tsEnd=self.current_time_formatted
        )

    def get_licenses_subscription_entitlements(self):
        """Gets licenses subscriptions entitlements."""
        self._logger.debug(
            "Getting licenses subscription entitlements for {}".format(
                self.organization_id
            )
        )

        return self._safe_api_call(
            self.dashboard.licensing.getAdministeredLicensingSubscriptionEntitlements
        )

    def get_top_switch_by_energy_usage(self):
        """Gets top switch by energy usage."""
        self._logger.debug("Getting top switches for {}".format(self.organization_id))

        return self._safe_api_call(
            self.dashboard.organizations.getOrganizationSummaryTopSwitchesByEnergyUsage,
            self.organization_id,
            total_pages=-1,
            t0=self.compare_time(self.start_time, 30),
            t1=self.current_time_formatted,
            quantity=self.input_config["top_count"],
        )

    def get_api_requests_history(self):
        """Gets api requests history."""
        self._logger.debug(
            "Getting api requests history for {}".format(self.organization_id)
        )

        return self._safe_api_call(
            self.dashboard.organizations.getOrganizationApiRequests,
            self.organization_id, t0=self.compare_time(self.start_time, 30), t1=self.current_time_formatted
        )

    def get_request_response_code(self):
        """Gets request response code."""
        self._logger.debug(
            "Getting api requests responses code for {}".format(self.organization_id)
        )

        return self._safe_api_call(
            self.dashboard.organizations.getOrganizationApiRequestsOverviewResponseCodesByInterval,
            self.organization_id, t0=self.compare_time(self.start_time, 30), t1=self.current_time_formatted
        )

    def get_requests_overview(self):
        """Gets requests overview."""
        self._logger.debug(
            "Getting api requests overview for {}".format(self.organization_id)
        )

        return self._safe_api_call(
            self.dashboard.organizations.getOrganizationApiRequestsOverview,
            self.organization_id, t0=self.compare_time(self.start_time, 30), t1=self.current_time_formatted
        )

    def get_appliance_vpn_stats(self):
        """Gets appliance vpn stats."""
        self._logger.debug(
            "Getting appliances vpn stats for {}".format(self.organization_id)
        )
        return self._safe_api_call(
            self.dashboard.appliance.getOrganizationApplianceVpnStats,
            self.organization_id,
            total_pages=-1,
            t0=self.compare_time(self.start_time, 30),
            t1=self.current_time_formatted
        )

    def get_appliance_vpn_status(self):
        """Gets appliance vpn status."""
        self._logger.debug(
            "Getting appliances vpn statuses for {}".format(self.organization_id)
        )
        return self._safe_api_call(
            self.dashboard.appliance.getOrganizationApplianceVpnStatuses,
            self.organization_id,
            total_pages=-1,
            t0=self.compare_time(self.start_time, 30),
            t1=self.current_time_formatted
        )

    def get_license_overview(self):
        """Gets licenses overview."""
        self._logger.debug(
            "Getting licenses overview for {}".format(self.organization_id)
        )
        return self._safe_api_call(
            self.dashboard.organizations.getOrganizationLicensesOverview,
            self.organization_id
        )

    def get_licenses_subscriptions(self):
        """Gets licenses subscriptions."""
        self._logger.debug(
            "Getting licenses subscriptions for {}".format(self.organization_id)
        )

        return self._safe_api_call(
            self.dashboard.licensing.getAdministeredLicensingSubscriptionSubscriptions,
            self.organization_id,
            startingAfter=self.compare_time(self.start_time, 30)
        )

    def get_licensing_coterm_licenses(self):
        """Gets licensing coterm licenses."""
        self._logger.debug(
            "Getting licensing coterm licenses for {}".format(self.organization_id)
        )

        return self._safe_api_call(
            self.dashboard.licensing.getOrganizationLicensingCotermLicenses,
            self.organization_id, total_pages=-1
        )

    def get_frimware_upgrades(self):
        """Gets firmware upgrades."""
        self._logger.debug(
            "Getting firmware upgrades for {}".format(self.organization_id)
        )

        return self._safe_api_call(
            self.dashboard.organizations.getOrganizationFirmwareUpgrades,
            self.organization_id, total_pages=-1
        )

    def get_switch_port_overview(self):
        """Gets switch port overview."""
        self._logger.debug(
            "Getting switch port overview for {}".format(self.organization_id)
        )

        return self._safe_api_call(
            self.dashboard.switch.getOrganizationSwitchPortsOverview,
            self.organization_id,
            t0=self.compare_time(self.start_time, 30),
            t1=self.current_time_formatted
        )

    def get_devices(self):
        """Gets devices."""
        self._logger.debug(
            "Getting devices for {}".format(self.organization_id)
        )

        return self._safe_api_call(
            self.dashboard.organizations.getOrganizationDevices,
            self.organization_id,
            total_pages=-1
        )

    def get_power_modules_statuses_by_device(self):
        """Gets power modules statuses by device."""
        self._logger.debug(
            "Getting power modules statuses by device for {}".format(self.organization_id)
        )

        return self._safe_api_call(
            self.dashboard.organizations.getOrganizationDevicesPowerModulesStatusesByDevice,
            self.organization_id,
            total_pages=-1
        )

    def get_ports_readings_history_by_switch(self):
        """Gets ports transceivers readings history by switch."""
        self._logger.debug(
            "Getting ports readings history by switch for {}".format(self.organization_id)
        )

        result = self.rest_calls.make_rest_call(params={"perPage": 100})
        return result

    def get_switch_ports_by_switch(self):
        """Gets switch ports by switch."""
        self._logger.debug(
            "Getting switch ports by switch for {}".format(self.organization_id)
        )

        return self._safe_api_call(
            self.dashboard.switch.getOrganizationSwitchPortsBySwitch,
            self.organization_id,
            total_pages=-1
        )

    def get_summary_switch_power_history(self):
        """Gets summary switch power history."""
        self._logger.debug(
            "Getting summary switch power history for {}".format(self.organization_id)
        )
        return self._safe_api_call(
            self.dashboard.switch.getOrganizationSummarySwitchPowerHistory,
            self.organization_id,
            t0=self.compare_time(self.start_time, 186),
            t1=self.current_time_formatted
        )

    def get_wireless_availabilities_change_history(self):
        """Gets wireless availabilities change history."""
        self._logger.debug(
            "Getting wireless availabilities change history for {}".format(self.organization_id)
        )

        result = self._safe_api_call(
            self.dashboard.wirelessController.getOrganizationWirelessControllerAvailabilitiesChangeHistory,
            self.organization_id,
            total_pages=-1
        )
        result = result.get("items", [])
        return result

    def get_wireless_devices_interfaces_usage_history_by_interval(self):
        """Gets wireless devices interfaces usage history by interval."""
        self._logger.debug(
            "Getting wireless devices interfaces usage history by interval for {}".format(self.organization_id)
        )

        result = self._safe_api_call(
            self.dashboard.wirelessController.getOrganizationWirelessControllerDevicesInterfacesUsageHistoryByInterval,
            self.organization_id,
            total_pages=-1,
            t0=self.compare_time(self.start_time, 31),
            t1=self.current_time_formatted
        )
        result = result.get("items", [])
        return result

    def get_wireless_devices_interfaces_packets_overview_by_device(self):
        """Gets wireless devices interfaces packets overview by device."""
        self._logger.debug(
            "Getting wireless devices interfaces packets overview by device for {}".format(self.organization_id)
        )

        result = self._safe_api_call(
            self.dashboard.wirelessController.getOrganizationWirelessControllerDevicesInterfacesPacketsOverviewByDevice,
            self.organization_id,
            total_pages=-1
        )
        result = result.get("items", [])
        return result

    def get_wireless_devices_wireless_controllers_by_device(self):
        """Gets wireless devices wireless controllers by device."""
        self._logger.debug(
            "Getting wireless devices wireless controllers by device for {}".format(self.organization_id)
        )

        result = self._safe_api_call(
            self.dashboard.wireless.getOrganizationWirelessDevicesWirelessControllersByDevice,
            self.organization_id,
            total_pages=-1
        )
        result = result.get("items", [])
        return result

    def get_webhook_logs(self):
        """Gets webhook logs."""
        self._logger.debug(
            "Getting webhook logs for {}".format(self.organization_id)
        )

        return self._safe_api_call(
            self.dashboard.organizations.getOrganizationWebhooksLogs,
            self.organization_id,
            total_pages=-1,
            t0=self.compare_time(self.start_time, 31),
            t1=self.current_time_formatted
        )

    def create_payload_template(self):
        """Create a payload template for webhook configuration."""
        name = "{}_{}".format(self.organization_id, self.input_config["webhook_name"])
        self._logger.info(
            "Creating payload template for input: {} with webhook name: {}".format(
                self.input_name, name
            )
        )
        network_id = self.input_config["network_id"]
        return self._safe_api_call(
            self.dashboard.networks.createNetworkWebhooksPayloadTemplate,
            network_id,
            name,
            body=const.WEBHOOK_BODY,
            headers=const.WEBHOOK_HEADER
        )

    def delete_payload_template(self, payload_id):
        """Delete a payload template using its ID."""
        self._logger.info(
            "Deleting payload template for {}".format(self.input_name)
        )
        network_id = self.input_config["network_id"]
        payload_template_id = payload_id
        return self._safe_api_call(
            self.dashboard.networks.deleteNetworkWebhooksPayloadTemplate,
            network_id,
            payload_template_id
        )

    def create_webhook_http_server(self, payload_id):
        """Create a webhook HTTP server with the specified payload template."""
        self._logger.info(
            "Creating webhook http server for {}".format(self.input_name)
        )
        name = self.input_config["webhook_name"]
        url = self.input_config["HEC_webhook_url"] + "/services/collector/event"
        shared_secret = utils.resolve_hec_token_value(
            self.session_key, self.input_config["hec_token"]
        )
        payload_template = {"payloadTemplateId": payload_id}
        network_id = self.input_config["network_id"]
        return self._safe_api_call(
            self.dashboard.networks.createNetworkWebhooksHttpServer,
            network_id,
            name,
            url,
            sharedSecret=shared_secret,
            payloadTemplate=payload_template
        )

    def delete_webhook_http_server(self, webhook_id):
        """Delete a webhook HTTP server using its ID."""
        self._logger.info(
            "Deleting webhook http server for {}".format(self.input_name)
        )
        network_id = self.input_config["network_id"]
        http_server_id = webhook_id
        return self._safe_api_call(
            self.dashboard.networks.deleteNetworkWebhooksHttpServer,
            network_id,
            http_server_id
        )

    def create_webhook_test(self, payload_id):
        """Create a test for the webhook HTTP server."""
        self._logger.info(
            "Creating test of webhook http server for {}".format(self.input_name)
        )
        url = self.input_config["HEC_webhook_url"] + "/services/collector/event"
        shared_secret = utils.resolve_hec_token_value(
            self.session_key, self.input_config["hec_token"]
        )
        network_id = self.input_config["network_id"]
        alert_type_id = const.WEBHOOK_TEST_ALERT_TYPE
        return self._safe_api_call(
            self.dashboard.networks.createNetworkWebhooksWebhookTest,
            network_id,
            url,
            sharedSecret=shared_secret,
            payloadTemplateId=payload_id,
            alertTypeId=alert_type_id
        )

    def check_status_test(self, test_id):
        """Check the status of a webhook test."""
        self._logger.info(
            "Checking status of webhook test for {}".format(self.input_name)
        )
        network_id = self.input_config["network_id"]
        return self._safe_api_call(
            self.dashboard.networks.getNetworkWebhooksWebhookTest,
            network_id,
            test_id
        )

    def _collect_events(self):
        """Returns all events for a specific sourcetype."""
        if self.sourcetype == utils.AUDIT_SOURCETYPE:
            return self.get_organization_configuration_changes()
        elif self.sourcetype == utils.ORGANIZATIONSECURITY_SOURCETYPE:
            return self.get_organization_security_events()
        elif self.sourcetype == utils.DEVICEHISTORY_SOURCETYPE:
            return self.get_device_history_events()
        elif self.sourcetype == utils.DEVICEADDRESSES_SOURCETYPE:
            return self.get_devices_by_address()
        elif self.sourcetype == utils.ETHERNET_SOURCETYPE:
            return self.get_ethernet_status_of_devices()
        elif self.sourcetype == utils.SENSORREADING_SOURCETYPE:
            return self.get_sensor_readings_history()
        elif self.sourcetype == utils.TOPAPPLIANCES_SOURCETYPE:
            return self.get_top_appliances()
        elif self.sourcetype == utils.TOPCLIENTS_SOURCETYPE:
            return self.get_top_clients()
        elif self.sourcetype == utils.TOPDEVICES_SOURCETYPE:
            return self.get_top_devices()
        elif self.sourcetype == utils.PACKETLOSS_SOURCETYPE:
            return self.get_avg_packet_loss()
        elif self.sourcetype == utils.TOPSWITCHES_SOUCETYPE:
            return self.get_top_switch_by_energy_usage()
        elif self.sourcetype == utils.REQUETSHISTORY_SOURCETYPE:
            return self.get_api_requests_history()
        elif self.sourcetype == utils.REQUESTRESPONSECODE_SOURCETYPE:
            return self.get_request_response_code()
        elif self.sourcetype == utils.REQUESTOVERVIEW_SOURCETYPE:
            return self.get_requests_overview()
        elif self.sourcetype == utils.APPLIANCEVPNSTATS_SOURCETPYE:
            return self.get_appliance_vpn_stats()
        elif self.sourcetype == utils.APPLIANCEVPNSTATUS_SOURCETPYE:
            return self.get_appliance_vpn_status()
        elif self.sourcetype == utils.LICENSEOVERVIEW_SOURCETYPE:
            return self.get_license_overview()
        elif self.sourcetype == utils.COTERMLICENSE_SOURCETYPE:
            return self.get_licensing_coterm_licenses()
        elif self.sourcetype == utils.LICENSESUBSCRIPTIONS_SOURCETPYE:
            return self.get_licenses_subscriptions()
        elif self.sourcetype == utils.FIRMWAREUPGRADE_SOURCETYPE:
            return self.get_frimware_upgrades()
        elif self.sourcetype == utils.ASSURANCEALERTS_SOURCETYPE:
            return self.get_assurance_alerts()
        elif self.sourcetype == utils.SUBSCRIPTIONENTITLEMENT_SOURCETPYE:
            return self.get_licenses_subscription_entitlements()
        elif self.sourcetype == utils.SWITCHPORTOVERVIEW_SOURCETYPE:
            return self.get_switch_port_overview()
        elif self.sourcetype == utils.DEVICES_SOURCETYPE:
            return self.get_devices()
        elif self.sourcetype == utils.POWER_MODULES_STATUSES_BY_DEVICE_SOURCETYPE:
            return self.get_power_modules_statuses_by_device()
        elif self.sourcetype == utils.PORTS_TRANSCEIVERS_READINGS_HISTORY_BY_SWITCH_SOURCETYPE:
            return self.get_ports_readings_history_by_switch()
        elif self.sourcetype == utils.SWITCH_PORTS_BY_SWITCH_SOURCETYPE:
            return self.get_switch_ports_by_switch()
        elif self.sourcetype == utils.SUMMARY_SWITCH_POWER_HISTORY_SOURCETYPE:
            return self.get_summary_switch_power_history()
        elif self.sourcetype == utils.WIRELESS_CONTROLLER_AVAILABILITIES_CHANGE_HISTORY_SOURCETYPE:
            return self.get_wireless_availabilities_change_history()
        elif self.sourcetype == utils.WIRELESS_CONTROLLER_DEVICES_INTERFACES_USAGE_HISTORY_BY_INTERVAL_SOURCETYPE:
            return self.get_wireless_devices_interfaces_usage_history_by_interval()
        elif self.sourcetype == utils.WIRELESS_CONTROLLER_DEVICES_INTERFACES_PACKETS_OVERVIEW_BY_DEVICE_SOURCETYPE:
            return self.get_wireless_devices_interfaces_packets_overview_by_device()
        elif self.sourcetype == utils.WIRELESS_DEVICES_WIRELESS_CONTROLLERS_BY_DEVICE_SOURCETYPE:
            return self.get_wireless_devices_wireless_controllers_by_device()
        elif self.sourcetype == utils.WEBHOOK_LOGS_SOURCETYPE:
            return self.get_webhook_logs()

        # to ingest data for all available networks
        elif self.sourcetype == utils.ORGANIZATIONNETWORKS_SOURCETYPE:
            return self.get_organization_networks()
        elif self.sourcetype == utils.ORGANIZATIONS_SOURCETYPE:
            return self.get_organizations()

        networks = self.get_organization_networks()
        self._logger.info(
            f"Fetched {len(networks)} networks for input: {self.input_name}"
        )

        all_events = []
        for network in networks:
            network_id = network["id"]
            product_types = network["productTypes"]
            product_type = None
            try:
                if self.sourcetype == utils.AIRMARSHAL_SOURCETYPE:
                    if 'wireless' in product_types:
                        all_events.extend(self.get_airmarshal_events(network_id))
                else:
                    product_type = SOURCETYPE_PRODUCT_TYPE_MAPPING[self.sourcetype]
                    if product_type in product_types:
                        events = self.get_network_events(network_id, product_type)
                        if events and "events" in events:
                            all_events.extend(events["events"])
            except Exception as e:
                if product_type:
                    self._logger.error(
                        f"Error while getting network events for network {network_id} "
                        f"and product type {product_type}: {e}"
                    )
                else:
                    self._logger.error(
                        f"Error while getting air marshal events for network {network_id}: {e}"
                    )
        return all_events

    def add_microsecond(self, time_str):
        """Add 1 microsecond to time."""
        dt = datetime.datetime.strptime(
            time_str, const.TIME_FORMAT_WITH_MICRO_SECOND
        ).replace(tzinfo=datetime.timezone.utc)
        dt += datetime.timedelta(microseconds=1)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"

    def _get_organization_info(self):
        """Get organization information or log warning and return None."""
        try:
            return self.get_organization()
        except APIError as e:
            self._logger.warning(
                f"Error while getting organization info for input: {self.input_name}, "
                f"organization: {self.organization_id}: {e}"
            )
            return None

    def _fetch_events(self):
        """Fetch events from API and handle exceptions."""
        try:
            return self._collect_events()
        except (APIError, Exception) as e:
            self._logger.error(f"Error while collecting data for input: {self.input_name}: {e}")
            raise Exception(f"Error for input: {self.input_name}: {e}")

    def _process_event(self, event, source, host, event_writer, ix):
        """Process a single event and update checkpoint if needed."""
        # Add organization_id if missing
        event.setdefault("organizationId", self.organization_id)

        # Write event to Splunk
        event_written = utils.write_event(
            self._logger,
            event_writer,
            event,
            self.sourcetype,
            self.index,
            source,
            host,
        )

        if not event_written:
            return False

        # Update checkpoint if this is time-series data
        self._update_checkpoint_if_needed(ix)
        return True

    def _update_checkpoint_if_needed(self, ix):
        """Update checkpoint for time-series data if this is the last event."""
        # Only update checkpoint for time-series data
        if self.sourcetype in utils.NOT_TS_SOURCETYPES:
            return

        # Prepare checkpoint data
        event_ts = self.current_time_formatted
        if self.sourcetype in utils.INCLUDE_TS_SOURCETYPES:
            event_ts = self.add_microsecond(event_ts)

        checkpoint_data = {"start_time": event_ts}

        # Only update checkpoint for the last event (first in reversed order)
        if ix == 0:
            self.checkpoint_collection.update(self.checkpoint_name, checkpoint_data)
            self._logger.debug(
                f"Checkpoint Updated for input: {self.input_name}, "
                f"organization id: {self.organization_id}, value: {checkpoint_data}."
            )

    def collect_events(self, event_writer):
        """
        Collects events from Meraki API and writes them to Splunk.

        :param event_writer: Event Writer object
        """

        @self.rate_limiter.limit
        def col_eve(self, event_writer):
            # Check if checkpoint retrieval was successful
            if not self.checkpoint_success:
                self._logger.info("Could not retrieve checkpoint. Not collecting events.")
                return

            # Get organization information
            organization_info = self._get_organization_info()
            if organization_info is None:
                return

            # Prepare source and host
            host = self.get_event_host_from_organization(organization_info)
            source = self.input_name.replace("://", "::")

            # event collection start time
            ec_start_time = datetime.datetime.now()
            self._logger.debug(
                "Data collection started for input: {}, organization id: {} at {}".format(
                    self.input_name, self.organization_id, ec_start_time
                )
            )

            # Fetch events
            events = self._fetch_events()

            # event collection end time
            ec_end_time = datetime.datetime.now()
            # Total duation for data ingestion
            duration = ec_end_time - ec_start_time
            self._logger.debug(
                "Data collection completed from API for input: {}, organization id: {} at {}".format(
                    self.input_name, self.organization_id, ec_end_time
                )
            )

            # Convert to list if it's a dictionary
            if isinstance(events, dict):
                events = [events]

            # Process events in reverse order (newest first)
            for ix in range(len(events) - 1, -1, -1):
                if not self._process_event(events[ix], source, host, event_writer, ix):
                    break

            # Log summary
            self._logger.info(
                "Events ingested in Splunk for input: {}, organization id: {}, "
                "count={} | Total time taken: {} seconds".format(
                    self.input_name,
                    self.organization_id,
                    len(events),
                    duration.total_seconds(),
                )
            )

        return col_eve(self, event_writer)
