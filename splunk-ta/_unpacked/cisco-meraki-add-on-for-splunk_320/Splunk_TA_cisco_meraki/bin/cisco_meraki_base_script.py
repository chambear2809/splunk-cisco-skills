#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#

import import_declare_test  # noqa: F401 # isort: skip

import traceback

import cisco_meraki_connect as connect
import cisco_meraki_utils as utils
from splunklib import modularinput as smi


class BaseScript(smi.Script):
    """Base class for all Cisco Meraki modular inputs."""

    def __init__(self):
        """Initialize the base script class."""
        super(BaseScript, self).__init__()

    def get_scheme(self):
        """Get scheme for modular input. Should be implemented by child classes."""
        pass

    def validate_input(self, definition):
        """Child class should override this method."""
        pass

    def stream_events(self, inputs, event_writer):
        """Stream events for the modular input.

        This method processes inputs and streams events to Splunk.
        """
        session_key = self._input_definition.metadata["session_key"]
        input_name = (list(inputs.inputs.keys())[0]).split("//")[1]
        logfile_name = self.logfile_prefix + input_name
        _logger = utils.set_logger(session_key, logfile_name)
        try:
            for input_name, input_items in inputs.inputs.items():
                input_items["input_name"] = input_name
            organization_name = input_items.get("organization_name")
            organization_details = utils.get_organization_details(
                _logger, session_key, organization_name
            )
            config = {
                "session_key": session_key,
                "input_name": input_items["input_name"],
                "sourcetype": self.sourcetype,
                "start_from_days_ago": input_items.get("start_from_days_ago"),
                "index": input_items["index"],
                "logger": _logger,
                "proxies": utils.get_proxy_settings(_logger, session_key),
                "top_count": input_items.get("top_count"),
                "organization_name": organization_name,  # Add organization_name needed for token refresh
            }
            config.update(organization_details)
            api = connect.MerakiConnect(config)
            api.collect_events(event_writer)
        except Exception:
            _logger.error(
                "Error while streaming events for input {}: {}".format(
                    input_name, traceback.format_exc()
                )
            )
