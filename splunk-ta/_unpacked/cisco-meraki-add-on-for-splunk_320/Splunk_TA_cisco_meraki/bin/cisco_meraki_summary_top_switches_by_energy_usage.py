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


class SummaryTopSwitchesByEnergyUsage(base_script.BaseScript):
    """Class for switches top by energy usage data collection."""

    def __init__(self):
        """Initialize the class."""
        super(SummaryTopSwitchesByEnergyUsage, self).__init__()
        self.logfile_prefix = (
            "splunk_ta_cisco_meraki_summary_top_switches_by_energy_usage"
        )
        self.sourcetype = utils.TOPSWITCHES_SOUCETYPE

    def get_scheme(self):
        """Get scheme for modular input."""
        scheme = smi.Scheme("summary_top_switches_by_energy_usage")
        scheme.description = "Summary Top Switches By Energy Usage"
        scheme.use_external_validation = True
        scheme.streaming_mode_xml = True
        scheme.use_single_instance = False

        scheme.add_argument(
            smi.Argument(
                "name", title="Name", description="Name", required_on_create=True
            )
        )

        scheme.add_argument(
            smi.Argument(
                "top_count",
                title="Top Count",
                description="Returns the top (n) devices, by deafult set to 10",
                required_on_create=True,
            )
        )

        return scheme

    def validate_input(self, definition):
        """Validate input parameters."""
        utils.validate_interval(definition.parameters, range(1800, 86400))
        utils.validate_start_from_days_ago(definition.parameters, range(1, 30))
        utils.validate_top_count(definition.parameters, range(1, 30))


if __name__ == "__main__":
    exit_code = SummaryTopSwitchesByEnergyUsage().run(sys.argv)
    sys.exit(exit_code)
