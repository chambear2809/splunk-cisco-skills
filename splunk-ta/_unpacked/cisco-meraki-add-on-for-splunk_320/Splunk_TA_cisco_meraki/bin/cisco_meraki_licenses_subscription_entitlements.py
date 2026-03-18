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


class LicensesSubscriptionEntitlements(base_script.BaseScript):
    """Class for licenses subscription entitlements data collection."""

    def __init__(self):
        """Initialize the class."""
        super(LicensesSubscriptionEntitlements, self).__init__()
        self.logfile_prefix = (
            "splunk_ta_cisco_meraki_licenses_subscription_entitlements"
        )
        self.sourcetype = utils.SUBSCRIPTIONENTITLEMENT_SOURCETPYE

    def get_scheme(self):
        """Get scheme for modular input."""
        scheme = smi.Scheme("licenses_subscription_entitlements")
        scheme.description = "Licenses Subscription Entitlements"
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
    exit_code = LicensesSubscriptionEntitlements().run(sys.argv)
    sys.exit(exit_code)
