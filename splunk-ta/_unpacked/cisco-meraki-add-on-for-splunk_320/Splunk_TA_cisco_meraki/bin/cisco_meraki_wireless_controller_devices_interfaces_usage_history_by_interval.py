import import_declare_test  # noqa: F401 # isort: skip

import sys

import cisco_meraki_base_script as base_script
import cisco_meraki_utils as utils
from splunklib import modularinput as smi


class WirelessControllerDevicesInterfacesUsageHistoryByInterval(base_script.BaseScript):
    """Class for Wireless Controller Devices Interfaces Usage History By Interval."""

    def __init__(self):
        """Initialize the class."""
        super(WirelessControllerDevicesInterfacesUsageHistoryByInterval, self).__init__()
        self.logfile_prefix = "splunk_ta_cisco_meraki_wireless_controller_devices_interfaces_usage_history_by_interval"
        self.sourcetype = utils.WIRELESS_CONTROLLER_DEVICES_INTERFACES_USAGE_HISTORY_BY_INTERVAL_SOURCETYPE

    def get_scheme(self):
        """Get scheme for modular input."""
        scheme = smi.Scheme("wireless_controller_devices_interfaces_usage_history_by_interval")
        scheme.description = "Wireless Controller Devices Interfaces Usage History By Interval"
        scheme.use_external_validation = True
        scheme.streaming_mode_xml = True
        scheme.use_single_instance = False

        scheme.add_argument(
            smi.Argument(
                "name", title="Name", description="Name", required_on_create=True
            )
        )

        return scheme

    def validate_input(self, definition):
        """Validate input parameters."""
        utils.validate_interval(definition.parameters, range(360, 86400))
        utils.validate_start_from_days_ago(definition.parameters, range(1, 31))


if __name__ == "__main__":
    exit_code = WirelessControllerDevicesInterfacesUsageHistoryByInterval().run(sys.argv)
    sys.exit(exit_code)
