import import_declare_test  # noqa: F401 # isort: skip

import sys

import cisco_meraki_base_script as base_script
import cisco_meraki_utils as utils
from splunklib import modularinput as smi


class SwitchPortsTransceiversReadingsHistoryBySwitch(base_script.BaseScript):
    """Class for Switch Ports Transceivers Readings History By Switch data collection."""

    def __init__(self):
        """Initialize the class."""
        super(SwitchPortsTransceiversReadingsHistoryBySwitch, self).__init__()
        self.logfile_prefix = "splunk_ta_cisco_meraki_switch_ports_transceivers_readings_history_by_switch"
        self.sourcetype = utils.PORTS_TRANSCEIVERS_READINGS_HISTORY_BY_SWITCH_SOURCETYPE

    def get_scheme(self):
        """Get scheme for modular input."""
        scheme = smi.Scheme("switch_ports_transceivers_readings_history_by_switch")
        scheme.description = "Switch Ports Transceivers Readings History By Switch"
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
        utils.validate_interval(definition.parameters, range(43200, 86400))


if __name__ == "__main__":
    exit_code = SwitchPortsTransceiversReadingsHistoryBySwitch().run(sys.argv)
    sys.exit(exit_code)
