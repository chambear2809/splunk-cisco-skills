#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#

import import_declare_test  # noqa: F401 # isort: skip

import sys

import cisco_meraki_base_script as base_script
import cisco_meraki_utils as utils
from splunklib import modularinput as smi


class SwitchPortOverview(base_script.BaseScript):
    """Class for collecting Switch Port Overview data from Cisco Meraki."""

    def __init__(self):
        """Initialize the SwitchPortOverview class."""
        super(SwitchPortOverview, self).__init__()
        self.logfile_prefix = "splunk_ta_cisco_meraki_switch_port_overview"
        self.sourcetype = utils.SWITCHPORTOVERVIEW_SOURCETYPE

    def get_scheme(self):
        """Overloaded splunklib modularinput method to get scheme for the modular input."""
        scheme = smi.Scheme("switch_port_overview")
        scheme.description = "Switch Port Overview"
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
        utils.validate_interval(definition.parameters, range(43200, 86400))
        utils.validate_start_from_days_ago(definition.parameters, range(1, 30))


if __name__ == "__main__":
    exit_code = SwitchPortOverview().run(sys.argv)
    sys.exit(exit_code)
