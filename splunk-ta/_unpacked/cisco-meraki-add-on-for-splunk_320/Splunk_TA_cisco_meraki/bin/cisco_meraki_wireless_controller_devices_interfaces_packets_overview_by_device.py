import import_declare_test  # noqa: F401 # isort: skip

import sys

import cisco_meraki_base_script as base_script
import cisco_meraki_utils as utils
from splunklib import modularinput as smi


class WirelessControllerDevicesInterfacesPacketsOverviewByDevice(base_script.BaseScript):
    """Class for interfaces packets overview data collection."""

    def __init__(self):
        """Initialize the class."""
        super(WirelessControllerDevicesInterfacesPacketsOverviewByDevice, self).__init__()
        self.logfile_prefix = "splunk_ta_cisco_meraki_wireless_controller_devices_interfaces_packets_overview_by_device"
        self.sourcetype = utils.WIRELESS_CONTROLLER_DEVICES_INTERFACES_PACKETS_OVERVIEW_BY_DEVICE_SOURCETYPE

    def get_scheme(self):
        """Get scheme for modular input."""
        scheme = smi.Scheme("wireless_controller_devices_interfaces_packets_overview_by_device")
        scheme.description = "Wireless Controller Devices Interfaces Packets Overview By Device"
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


if __name__ == "__main__":
    exit_code = WirelessControllerDevicesInterfacesPacketsOverviewByDevice().run(sys.argv)
    sys.exit(exit_code)
