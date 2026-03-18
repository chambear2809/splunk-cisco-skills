import import_declare_test  # noqa: F401
from splunktaucclib.rest_handler.endpoint.validator import Validator
import requests
from splunktaucclib.rest_handler import util
import common.log as log
import common.proxy as proxy
from common.utils import get_sslconfig, to_seconds
import re

contains_slash_regex = re.compile(r".*[/\\]$")

util.remove_http_proxy_env_vars()


logger = log.get_logger("cisco_dc_nd_validation")


class ValidateNexusDashboardCreds(Validator):
    """
    Validator class for Nexus Dashboard credentials.

    This class validates the Nexus Dashboard credentials by sending a POST request to the login endpoint.
    """

    def hostname_validate(self, value, data):
        hostnames = data.get("nd_hostname")
        try:
            hostname_list = hostnames.split(",")
            for hostname in hostname_list:
                invalid_hostname = re.search(contains_slash_regex, hostname)
                if invalid_hostname:
                    self.put_msg(
                        "Invalid Hostname(s) or IP address(es) specified. "
                        "Must be in a valid IPv4 or IPv6 format."
                    )
                    return False
        except Exception as err:
            logger.error(
                f"Invalid Hostname(s) or IP address(es) specified. Error {str(err)}"
            )
            self.put_msg(
                f"Invalid Hostname(s) or IP address(es) specified. Error {str(err)}"
            )
            return False
        return True

    def validate(self, value, data):
        """
        Validate Nexus Dashboard credentials.

        Args:
            value (str): Not used
            data (dict): Contains the following keys:
                - nd_hostname (str): Comma-separated list of hostnames
                - nd_username (str): Username
                - nd_password (str): Password
                - nd_port (str): Port number
                - nd_authentication_type (str): Authentication type
                - nd_login_domain (str): Login domain (default: "DefaultAuth")
                - nd_enable_proxy (bool): Enable proxy
                - nd_proxy_type (str): Proxy type
                - nd_proxy_url (str): Proxy URL
                - nd_proxy_port (str): Proxy port
                - nd_proxy_username (str): Proxy username
                - nd_proxy_password (str): Proxy password

        Returns:
            bool: True if validation is successful, False otherwise
        """
        logger.info("Validating account details.")
        hostname_validate = self.hostname_validate(value, data)
        if not hostname_validate:
            return False
        nd_hosts = [host.strip() for host in data.get("nd_hostname").split(",")]
        user_name = data.get("nd_username")
        password = data.get("nd_password")
        port = data.get("nd_port")
        authentication_type = data.get("nd_authentication_type")
        login_domain = data.get("nd_login_domain")

        if authentication_type == "remote_user_authentication" and (not login_domain):
            self.put_msg("Field Login Domain is required")
            return False

        if authentication_type == "local_user_authentication" and not login_domain:
            login_domain = "local"

        proxy_settings = proxy.get_proxies(data)
        if proxy_settings:
            logger.info("Proxy is enabled.")
        else:
            logger.info("Proxy is disabled.")

        AllData = {
            "userName": user_name,
            "userPasswd": password,
            "domain": login_domain,
        }

        for host_name in nd_hosts:
            try:
                response = requests.post(
                    f"https://{host_name}:{port}/login",
                    json=AllData,
                    verify=get_sslconfig(),
                    proxies=proxy_settings,
                    timeout=600,
                )
                if response.status_code in (200, 201):
                    logger.info("Account validated successfully.")
                    return True
                else:
                    logger.error(
                        f"Could not validate account provided IP Address {host_name}"
                    )
                    put_msg = (
                        "Connection Unsuccessful. Please verify Hostname(s)/IP Address(es) and "
                        "Username, Password are correct."
                    )
            except requests.exceptions.SSLError:
                logger.error(
                    "SSL certificate verification failed. Please add a valid SSL Certificate or "
                    "Change verify_ssl flag to False in cisco_dc_networking_app_for_splunk_settings.conf file."
                )
                put_msg = (
                    "SSL certificate verification failed. Please add a valid SSL Certificate or "
                    "Change verify_ssl flag to False in cisco_dc_networking_app_for_splunk_settings.conf file."
                )
            except Exception as e:
                logger.error(
                    f"Could not validate account provided IP Address {host_name}. Error: {str(e)}"
                )
                put_msg = (
                    "Connection Unsuccessful. Please verify Hostname(s)/IP Address(es) and "
                    "Username, Password are correct."
                )

        self.put_msg(put_msg)
        return False


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

class SliceValidator(Validator):
    """This class validates if the Slice passed for validation in input is valid or not."""

    def validate(self, value, data):
        """We define Custom validation here for verifying interval field."""
        nd_time_interval = int(data.get('interval'))
        try:
            nd_time_slice = int(value)
        except ValueError:
            self.put_msg("Invalid Slice. Please enter valid Slice.")
            logger.error("Invalid Slice. Please enter valid Slice.")
            return False
        try:
            if nd_time_slice is not None and int(nd_time_interval) / int(nd_time_slice) > 500:
                self.put_msg("The slice value must be small enough so that the ratio of interval to slice is greater than 500. Please adjust the slice value accordingly.")
                logger.error("The slice value must be small enough so that the ratio of interval to slice is greater than 500. Please adjust the slice value accordingly.")
                return False
        except ValueError:
            self.put_msg("Invalid Slice. Please enter valid Slice.")
            logger.error("Invalid Slice. Please enter valid Slice.")
            return False
        return True
    

class GranualarityValidator(Validator):
    """This class validates if the Granualarity passed for validation in input is valid or not."""

    def validate(self, value, data):
        """We define Custom validation here for verifying interval field."""
        nd_time_interval = int(data.get('interval'))
        try:
            nd_granularity = to_seconds(value)
        except ValueError:
            self.put_msg("Invalid Granularity. Please enter valid Granularity.")
            logger.error("Invalid Granularity. Please enter valid Granularity.")
            return False
        try:
            if nd_granularity > nd_time_interval:
                self.put_msg("The granularity value should not be larger than the interval. Please choose a smaller granularity or increase the interval.")
                logger.error("The granularity value should not be larger than the interval. Please choose a smaller granularity or increase the interval.")
                return False
        except ValueError:
            self.put_msg("Invalid Granularity. Please enter valid Granularity.")
            logger.error("Invalid Granularity. Please enter valid Granularity.")
            return False
        return True
