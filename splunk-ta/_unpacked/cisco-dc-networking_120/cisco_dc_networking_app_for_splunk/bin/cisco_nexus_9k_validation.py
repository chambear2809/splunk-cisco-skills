import common.log as log
import common.proxy as proxy
from common.utils import get_sslconfig
from nexus_9k_utils.nxapi_utils import NXAPITransport
from splunktaucclib.rest_handler.endpoint.validator import Validator

logger = log.get_logger("cisco_dc_n9k_validation")


class ValidateNexus9kCreds(Validator):
    def validate(self, value, data):
        """Validation method to validate Nexus 9k Credentials."""
        try:
            logger.info("Validating account details.")
            COMMAND = "show version"
            username = data.get("nexus_9k_username")
            password = data.get("nexus_9k_password")
            device_ip = data.get("nexus_9k_device_ip")
            device_port = data.get("nexus_9k_port")
            target_url = f"https://{str(device_ip)}:{str(device_port)}/ins"
            proxies = proxy.get_proxies(data)
            if proxies:
                logger.info("Proxy is enabled.")
            else:
                logger.info("Proxy is disabled.")
            nxapi_class = NXAPITransport(
                target_url=target_url,
                username=username,
                password=password,
                timeout=600,
                verify=get_sslconfig(),
                proxies=proxies,
            )

            response = nxapi_class.clid(COMMAND)

            if response:
                logger.info("Account validated successfully.")
                return True
            else:
                logger.error(self.get_validation_message())
                self.put_msg(self.get_validation_message())
                return False

        except Exception as e:
            SSL_ERROR = "_ssl.c"
            if SSL_ERROR in str(e):
                logger.error(f"SSL certificate verification failed. Please add a valid SSL Certificate or change the verify_ssl  flag to False in cisco_dc_networking_app_for_splunk_settings.conf file. Error: {str(e)}")
                self.put_msg("SSL certificate verification failed. Please add a valid SSL Certificate or change the verify_ssl  flag to False in cisco_dc_networking_app_for_splunk_settings.conf file.")
                return False
            else:
                msg = f"Invalid Nexus 9k credentials: {str(e)}"
                self.put_msg(self.get_validation_message())
                logger.error(msg)
                return False

    def get_validation_message(self):
        return "Connection Unsuccessful. Please ensure the Hostname/IP Address, Port, Username, and Password are correct."


class IntervalValidator(Validator):
    """This class validates if the interval passed for validation in input is valid or not."""

    def validate(self, value, data):
        """We define Custom validation here for verifying interval field."""
        try:
            interval = int(value)
            if interval < 60:
                self.put_msg("Interval must be greater than or equal to 60.")
                logger.error("Interval must be greater than or equal to 60.")
                return False
        except ValueError:
            self.put_msg("Invalid Interval. Please enter valid interval.")
            logger.error("Invalid Interval. Please enter valid interval.")
            return False
        return True
