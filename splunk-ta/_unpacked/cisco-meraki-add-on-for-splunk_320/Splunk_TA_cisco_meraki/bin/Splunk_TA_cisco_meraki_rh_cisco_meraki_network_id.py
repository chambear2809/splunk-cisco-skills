import import_declare_test  # noqa: F401 # isort: skip

from splunktaucclib.rest_handler import util
import splunk.admin as admin
import cisco_meraki_utils as utils
import cisco_meraki_connect as connect

util.remove_http_proxy_env_vars()


class GetNetworkId(admin.MConfigHandler):
    """Class to get Network ids from organization."""

    def setup(self):
        """Setup before handling list."""
        self.supportedArgs.addOptArg("organization_name")

    def handleList(self, conf_info):
        """Defined method to handle list."""
        meraki_org = self.callerArgs.get("organization_name")[0]
        if meraki_org:
            session_key = self.getSessionKey()
            _logger = utils.set_logger(session_key, "splunk_ta_cisco_meraki_network_id")
            account_info = utils.get_organization_details(
                logger=_logger,
                session_key=session_key,
                organization_name=meraki_org
            )
            account_info["logger"] = _logger
            account_info["session_key"] = session_key
            account_info["proxies"] = utils.get_proxy_settings(_logger, session_key)
            try:
                _logger.info("Started collecting Network ids of organization.")
                if account_info["auth_type"] == "oauth":
                    dashboard = utils.build_dashboard_api(
                        account_info["base_url"], None, account_info["proxies"], session_key,
                        auth_type=account_info["auth_type"], access_token=account_info["access_token"]
                    )
                else:
                    dashboard = utils.build_dashboard_api(
                        account_info["base_url"], account_info["organization_api_key"], account_info["proxies"], session_key
                    )
                config = {
                    "input_name": None,
                    "sourcetype": utils.ORGANIZATIONNETWORKS_SOURCETYPE,
                    "start_from_days_ago": None,
                    "index": "dummy_index",
                    "top_count": None,
                    "organization_name": meraki_org,  # Add organization_name needed for token refresh
                }
                account_info.update(config)
                api = connect.MerakiConnect(account_info)
                networks = api.get_organization_networks()

                _logger.info("Network ids collected successfully.")
            except Exception as e:
                _logger.error("Something went wrong while fetching Network Ids. Error: {}".format(e))
                raise admin.ArgValidationException("Something went wrong while fetching Network Ids. Error: {}".format(e))
            else:
                for network in networks:
                    conf_info[network["id"]].append('label', network["name"])


if __name__ == "__main__":
    admin.init(GetNetworkId, admin.CONTEXT_NONE)