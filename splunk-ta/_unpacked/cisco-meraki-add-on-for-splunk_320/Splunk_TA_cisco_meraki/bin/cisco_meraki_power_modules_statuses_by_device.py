import import_declare_test  # noqa: F401 # isort: skip

import sys

import cisco_meraki_base_script as base_script
import cisco_meraki_utils as utils
from splunklib import modularinput as smi


class PowerModulesStatusesByDevice(base_script.BaseScript):
    """Class for collecting Power Modules Statuses by Device data from Cisco Meraki."""

    def __init__(self):
        """Initialize the PowerModulesStatusesByDevice class."""
        super(PowerModulesStatusesByDevice, self).__init__()
        self.logfile_prefix = (
            "splunk_ta_cisco_meraki_power_modules_statuses_by_device"
        )
        self.sourcetype = utils.POWER_MODULES_STATUSES_BY_DEVICE_SOURCETYPE

    def get_scheme(self):
        """Overloaded splunklib modularinput method to get scheme for the modular input."""
        scheme = smi.Scheme("power_modules_statuses_by_device")
        scheme.description = "Power Modules Statuses By Device"
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
        """Validate the input parameters for this modular input."""
        utils.validate_interval(definition.parameters, range(360, 3600))


if __name__ == "__main__":
    exit_code = PowerModulesStatusesByDevice().run(sys.argv)
    sys.exit(exit_code)
