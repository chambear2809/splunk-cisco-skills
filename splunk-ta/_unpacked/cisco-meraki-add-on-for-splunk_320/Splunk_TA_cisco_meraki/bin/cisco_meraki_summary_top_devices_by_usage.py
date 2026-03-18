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


class SummaryTopDevicesByUsage(base_script.BaseScript):
    """Class for collecting Summary Top Devices By Usage data from Cisco Meraki."""

    def __init__(self):
        """Initialize the SummaryTopDevicesByUsage class."""
        super(SummaryTopDevicesByUsage, self).__init__()
        self.logfile_prefix = "splunk_ta_cisco_meraki_summary_top_devices_by_usage"
        self.sourcetype = utils.TOPDEVICES_SOURCETYPE

    def get_scheme(self):
        """Overloaded splunklib modularinput method to get scheme for the modular input."""
        scheme = smi.Scheme("summary_top_devices_by_usage")
        scheme.description = "Summary Top Devices By Usage"
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
        """Validate the input parameters for this modular input."""
        utils.validate_interval(definition.parameters, range(28800, 86400))
        utils.validate_start_from_days_ago(definition.parameters, range(1, 30))
        utils.validate_top_count(definition.parameters, range(1, 30))


if __name__ == "__main__":
    exit_code = SummaryTopDevicesByUsage().run(sys.argv)
    sys.exit(exit_code)
