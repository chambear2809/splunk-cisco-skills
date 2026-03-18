import import_declare_test  # noqa: F401 # isort: skip

from splunktaucclib.rest_handler import util
import splunk.admin as admin
import cisco_meraki_utils as utils

util.remove_http_proxy_env_vars()


class GetHECToken(admin.MConfigHandler):
    """Class to get Network ids from organization."""

    def setup(self):
        """Setup before handling list."""
        pass

    def handleList(self, conf_info):
        """Defined method to handle list."""
        session_key = self.getSessionKey()
        _logger = utils.set_logger(session_key, "splunk_ta_cisco_meraki_hec_token")
        try:
            content = utils.get_hec_tokens(session_key)
            _logger.info("HEC Tokens collected successfully.")
        except Exception as e:
            _logger.error("Something went wrong while fetching HEC Tokens. Error: {}".format(e))
            raise admin.ArgValidationException("Something went wrong while fetching HEC Tokens. Error: {}".format(e))
        else:
            for http_stanza in content["entry"]:
                if http_stanza["content"].get("disabled"):
                    continue
                name = http_stanza["name"].split("//")[1]
                # Return the HEC input stanza name, not the raw token value.
                conf_info[name].append('label', name)


if __name__ == "__main__":
    admin.init(GetHECToken, admin.CONTEXT_NONE)