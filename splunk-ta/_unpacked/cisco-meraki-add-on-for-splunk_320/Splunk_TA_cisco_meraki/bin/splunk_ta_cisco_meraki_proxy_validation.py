#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#

from splunktaucclib.rest_handler.endpoint.validator import Validator


class ProxyValidator(Validator):
    """This class extends base class of Validator."""

    def validate(self, value, data):
        """Custom proxy validator which checks only for required fields.

        Proxy information will be validated when the API call for fetching the data
        is performed.
        """
        try:
            if not data.get("proxy_enabled"):
                if not data.get("proxy_url"):
                    msg = "Proxy Host can not be empty"
                    raise Exception(msg)
                elif not data.get("proxy_port"):
                    msg = "Proxy Port can not be empty"
                    raise Exception(msg)
                elif (
                    data.get("proxy_username") and not data.get("proxy_password")
                ) or (not data.get("proxy_username") and data.get("proxy_password")):
                    msg = "Please provide both proxy username and proxy password"
                    raise Exception(msg)
            return True
        except Exception as e:
            msg = str(e)
            self.put_msg(msg)
            return False
