import import_declare_test  # noqa: F401 # isort: skip

import sys

import cisco_meraki_base_script as base_script
import cisco_meraki_utils as utils
from splunklib import modularinput as smi


class SummarySwitchPowerHistory(base_script.BaseScript):
    """Class for Summary Switch Power History data collection."""

    def __init__(self):
        """Initialize the class."""
        super(SummarySwitchPowerHistory, self).__init__()
        self.logfile_prefix = (
            "splunk_ta_cisco_meraki_summary_switch_power_history"
        )
        self.sourcetype = utils.SUMMARY_SWITCH_POWER_HISTORY_SOURCETYPE

    def get_scheme(self):
        """Get scheme for modular input."""
        scheme = smi.Scheme("summary_switch_power_history")
        scheme.description = "Summary Switch Power History"
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
        utils.validate_interval(definition.parameters, range(1800, 86400))
        utils.validate_start_from_days_ago(definition.parameters, range(1, 186))


if __name__ == "__main__":
    exit_code = SummarySwitchPowerHistory().run(sys.argv)
    sys.exit(exit_code)
