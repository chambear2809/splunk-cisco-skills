#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#

"""This module validates organization being saved by the user."""

import import_declare_test  # noqa: F401 # isort: skip

import traceback

import cisco_meraki_utils as utils
from splunktaucclib.rest_handler.error import RestError


def organization_validation(region, base_url, organization_id, key, session_key, auth_type="basic"):
    """This method verifies the credentials by making an API call."""
    logger = utils.set_logger(
        session_key, "splunk_ta_cisco_meraki_organization_validation"
    )
    logger.info(
        "Verifying {} credentials for the organization id {} ({} region)".format(
            auth_type, organization_id, region
        )
    )
    if not organization_id or not key:
        raise RestError(
            400,
            "Provide all necessary arguments: "
            "Organization Id and Organization API Key or Access Token.",
        )
    try:
        proxy_settings = utils.get_proxy_settings(logger, session_key)

        # For OAuth2, pass access_token parameter
        if auth_type == "oauth":
            dashboard = utils.build_dashboard_api(
                base_url, None, proxy_settings, session_key,
                auth_type=auth_type, access_token=key
            )
        else:
            dashboard = utils.build_dashboard_api(
                base_url, key, proxy_settings, session_key
            )
        organizations = dashboard.organizations.getOrganizations()
        valid_organization_id = False
        for organization in organizations:
            if str(organization["id"]) == str(organization_id):
                valid_organization_id = True
                break
        if not valid_organization_id:
            msg = "Failed to validate organization id: {} ({} region)".format(
                organization_id, region
            )
            logger.error(msg)
            raise RestError(400, msg)
    except Exception:
        logger.error(
            "Failed to connect to Meraki for organization id: {} ({} region). {}".format(
                organization_id, region, traceback.format_exc()
            )
        )
        msg = (
            "Could not connect to Meraki for organization id: {} ({} region). "
            "Check configuration and network settings".format(organization_id, region)
        )
        raise RestError(400, msg)
