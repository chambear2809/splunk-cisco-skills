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


class DeviceAvailabilitiesChangeHistory(base_script.BaseScript):
    """Class for collecting Device Availabilities Change History data from Cisco Meraki."""

    def __init__(self):
        """Initialize the DeviceAvailabilitiesChangeHistory class."""
        super(DeviceAvailabilitiesChangeHistory, self).__init__()
        self.logfile_prefix = (
            "splunk_ta_cisco_meraki_device_availabilities_change_history"
        )
        self.sourcetype = utils.DEVICEHISTORY_SOURCETYPE

    def get_scheme(self):
        """Overloaded splunklib modularinput method to get scheme for the modular input."""
        scheme = smi.Scheme("device_availabilities_change_history")
        scheme.description = "Device Availabilities Change History"
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
        utils.validate_start_from_days_ago(definition.parameters, range(1, 30))


if __name__ == "__main__":
    exit_code = DeviceAvailabilitiesChangeHistory().run(sys.argv)
    sys.exit(exit_code)
