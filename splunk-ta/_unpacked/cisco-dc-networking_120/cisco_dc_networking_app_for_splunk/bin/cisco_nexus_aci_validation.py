import import_declare_test
from splunktaucclib.rest_handler.endpoint.validator import Validator
import re
import os
import json
import requests
import rsa
import base64
import sys
import common.log as log
import cisco_dc_aci_session as aci
import common.proxy as proxy
from common import consts
from common.utils import get_sslconfig
logger = log.get_logger("cisco_dc_aci_validation")
try:
    from urllib import unquote
except Exception:
    from urllib.parse import unquote

TIMEOUT_VAL = consts.TIMEOUT
contains_slash_regex = re.compile(r".*[/\\]$")
contains_space_regex = re.compile(r"\s+")


def validate_apic_creds(self, acc_data, host, port, user, passwd, remote=None, domain=None):
    """Validates APIC credentials."""
    hosts = host.split(",")
    session = requests.Session()
    error_msg_apic = ""
    for host in hosts:
        host = host.strip()
        api_user = user
        if port:
            host = f"{host}:{port}"
        if remote:
            api_user = f"apic#{domain}\\{user}"
        try:
            login_url = f"https://{host}/api/aaaLogin.json"
            api_data = {"aaaUser": {"attributes": {"name": api_user, "pwd": passwd}}}
            logger.info(f"Making an API call to the url {login_url}.")
            resp = session.post(login_url, data=json.dumps(api_data), verify=get_sslconfig(),
                                proxies=proxy.get_proxies(acc_data), timeout=TIMEOUT_VAL)

            if resp.ok:
                logger.info(f"Successfully received the response for the url {login_url}.")
                return True, error_msg_apic
            else:
                try:
                    error_data = resp.json()
                    if "imdata" in error_data:
                        error_msg = error_data["imdata"][0].get("error", {}).get("attributes", {}).get("text")
                        if error_msg:
                            logger.error(f"Error in validating APIC credentials: {error_msg}")
                            error_msg_apic = "Connection Unsuccessful. Please verify Hostname(s)/IP Address(es) and Username, Password are correct."
                    else:
                        logger.error(f"Error in validating APIC credentials: {resp.text}")
                        error_msg_apic = "Connection Unsuccessful. Please verify Hostname(s)/IP Address(es) and Username, Password are correct."
                except Exception as e:
                    logger.error(f"Host: {host}. Error occured: {str(e)}. Response: {resp.text}")
                    logger.error(
                        "Connection Unsuccessful. "
                        "Please verify Hostname(s)/IP Address(es) and Username, Password are correct.")
                    error_msg_apic = "Connection Unsuccessful. Please verify Hostname(s)/IP Address(es) and Username, Password are correct."
                
        except requests.exceptions.SSLError as e:
            logger.error(f"Host: {host}. Error occured: {str(e)}")
            error_msg_apic = "SSL certificate verification failed. Please add a valid SSL Certificate or change the verify_ssl  flag to False in cisco_dc_networking_app_for_splunk_settings.conf file."
            logger.error("SSL certificate verification failed. Please add a valid SSL Certificate or "
                     "change the verify_ssl  flag to False in cisco_dc_networking_app_for_splunk_settings.conf file.") 
        
        except Exception as e:
            logger.error(f"Host: {host}. Error occured: {str(e)}")
            logger.error(
                "Connection Unsuccessful. "
                "Please verify Hostname(s)/IP Address(es) and Username, Password are correct.")
            error_msg_apic = "Connection Unsuccessful. Please verify Hostname(s)/IP Address(es) and Username, Password are correct."
    logger.error("Error in validating APIC credentials for any of the provided hosts.")
    return False, error_msg_apic


class HostsValidator(Validator):
    """
    Validates the format of hostnames or IP addresses.
    """

    def validate(self, value, data):
        """Validates Hosts format."""
        hostnames = data.get("apic_hostname")
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
            logger.error(f"Invalid Hostname(s) or IP address(es) specified. Error {str(err)}")
            self.put_msg(f"Invalid Hostname(s) or IP address(es) specified. Error {str(err)}")
            return False
        return True


class AuthenticationValidator(Validator):
    """
    Validates the provided credentials.
    """

    def validate(self, value, data):
        "Validates the provided credentials."
        try:
            logger.info("Validating account details.")
            auth_type = data.get("apic_authentication_type")
            cisco_aci_username = data.get("apic_username")
            cisco_aci_password = data.get("apic_password")
            hostnames = data.get("apic_hostname")
            cisco_aci_port = data.get("apic_port")
            proxy_data = proxy.get_proxies(data)
            if proxy_data:
                logger.info("Proxy is enabled.")
            else:
                logger.info("Proxy is disabled.")
            if auth_type == "password_authentication":
                invalid_username = re.search(contains_space_regex, cisco_aci_username)
                if not cisco_aci_username or invalid_username:
                    logger.error(
                        "Invalid Username specified. Must be a string without spaces."
                    )
                    self.put_msg(
                        "Invalid Username specified. Must be a string without spaces."
                    )
                    return False
                invalid_password = re.search(contains_space_regex, cisco_aci_password)
                if not cisco_aci_password or invalid_password:
                    logger.error(
                        "Invalid Password specified. Must be a string without spaces."
                    )
                    self.put_msg(
                        "Invalid Password specified. Must be a string without spaces."
                    )
                    return False
                validation_success, error_msg_apic = validate_apic_creds(
                    self,
                    data,
                    host=str(hostnames),
                    port=str(cisco_aci_port),
                    user=str(cisco_aci_username),
                    passwd=str(cisco_aci_password),
                )
                if not validation_success:
                    self.put_msg(error_msg_apic)
                    return False

            elif auth_type == "remote_user_authentication":
                remote_user_domain_name = data.get("apic_login_domain")
                invalid_username = re.search(contains_space_regex, cisco_aci_username)
                if not cisco_aci_username or invalid_username:
                    logger.error(
                        "Invalid Username specified. Must be a string without spaces."
                    )
                    self.put_msg(
                        "Invalid Username specified. Must be a string without spaces."
                    )
                    return False
                invalid_password = re.search(contains_space_regex, cisco_aci_password)
                if not cisco_aci_password or invalid_password:
                    logger.error(
                        "Invalid Password specified. Must be a string without spaces."
                    )
                    self.put_msg(
                        "Invalid Password specified. Must be a string without spaces."
                    )
                    return False
                invalidDomainName = re.search(contains_space_regex, remote_user_domain_name)
                if not remote_user_domain_name or invalidDomainName:
                    logger.error(
                        "Invalid Domain Name specified. Must be a string without spaces."
                    )
                    self.put_msg(
                        "Invalid Domain Name specified. Must be a string without spaces."
                    )
                    return False
                validation_success, error_msg_apic = validate_apic_creds(
                    self,
                    data,
                    host=str(hostnames),
                    port=str(cisco_aci_port),
                    user=str(cisco_aci_username),
                    passwd=str(cisco_aci_password),
                    remote=True,
                    domain=str(remote_user_domain_name),
                )
                if not validation_success:
                    self.put_msg(error_msg_apic)
                    return False

            elif auth_type == "certificate_authentication":
                cert_name = data.get("apic_certificate_name")
                cert_private_key_path = data.get("apic_certificate_path")
                invalidCertName = re.search(contains_space_regex, cert_name)
                invalid_username = re.search(contains_space_regex, cisco_aci_username)
                if not cisco_aci_username or invalid_username:
                    logger.error(
                        "Invalid Username specified. Must be a string without spaces."
                    )
                    self.put_msg(
                        "Invalid Username specified. Must be a string without spaces."
                    )
                    return False
                if not cert_name or invalidCertName:
                    logger.error(
                        "Invalid Certificate Name specified. Must be a string without spaces."
                    )
                    self.put_msg(
                        "Invalid Certificate Name specified. Must be a string without spaces."
                    )
                    return False
                if not cert_private_key_path:
                    logger.error(
                        "Invalid Path of Private Key specified. Must be a string without spaces."
                    )
                    self.put_msg(
                        "Invalid Path of Private Key specified. Must be a string without spaces."
                    )
                    return False
                if not (os.path.exists(cert_private_key_path) and os.path.isfile(cert_private_key_path)):
                    logger.error(
                        "Invalid Path of Private Key specified for ACI device. "
                        "Private key doesn't exists or Invalid Private key path."
                    )
                    self.put_msg(
                        "Invalid Path of Private Key specified for ACI device. "
                        "Private key doesn't exists or Invalid Private key path."
                    )
                    return False
                with open(cert_private_key_path, "r") as f:
                    file_contents = f.read()
                    if file_contents == "":
                        logger.error(
                            "Invalid Private Key. Invalid Path of Private Key specified. "
                            "Private key doesn't exists or Invalid Private key path."
                        )
                        self.put_msg(
                            "Invalid Private Key. Invalid Path of Private Key specified. "
                            "Private key doesn't exists or Invalid Private key path."
                        )
                        return False
                    f.close()

        except Exception as er:
            logger.error(
                f"Error occured in validating the credentials. Error: {str(er)}. "
                "Please verify Hostname(s)/IP Address(es) and Username, Password are correct."
            )
            self.put_msg(
                f"Error occured in validating the credentials."
                "Please verify Hostname(s)/IP Address(es) and Username, Password are correct."
            )
            return False
        logger.info("Account validated successfully.")
        return True


class CertificateValidator(Validator):
    """
    Validates the certificate.
    """

    def validate(self, value, data):
        """Validates Ceritficate values."""
        auth_type = data.get("apic_authentication_type")
        hostnames = data.get("apic_hostname")
        if auth_type == "certificate_authentication":
            cert_name = data.get("apic_certificate_name")
            user = data.get("apic_username")
            cert_private_key_path = data.get("apic_certificate_path")
            with open(cert_private_key_path, "r") as f:
                file_contents = f.read()
                if file_contents == "":
                    logger.error(
                        "Invalid Path of Private Key specified."
                    )
                    self.put_msg(
                        "Invalid Path of Private Key specified."
                    )
                    return False
                f.close()
            private_key = file_contents
            try:
                private_key = rsa.PrivateKey.load_pkcs1(private_key)
                session = requests.Session()
                info_url = "/api/node/mo/info.json"
                cookie = self.create_cookie(info_url, user, cert_name, private_key)
            except Exception as e:
                logger.error(
                    f"Error while loading RSA Private key. Error: {str(e)}."
                )
                self.put_msg(
                    f"Error while loading RSA Private key."
                )
                return False
            hosts = hostnames.split(",")
            for host in hosts:
                host = host.strip()
                if data.get("apic_port"):
                    host = f"{host}:{data.get('apic_port')}"
                try:
                    get_url = f"https://{host}{info_url}"
                    logger.info(f"Making an API call to the url {get_url}.")

                    resp = session.get(get_url, cookies=cookie, verify=get_sslconfig(),
                                       proxies=proxy.get_proxies(data), timeout=TIMEOUT_VAL)
                    if not resp.ok:
                        logger.error(f"Error in validating Certificate: {resp.text}")
                        resp.raise_for_status()
                    else:
                        logger.info(f"Successfully received the response for the url {get_url}.")
                        return True

                except requests.exceptions.SSLError as e:
                    self.put_msg("SSL certificate verification failed. Please add a valid SSL Certificate or change the verify_ssl  flag to False in cisco_dc_networking_app_for_splunk_settings.conf file.")
                    logger.error("SSL certificate verification failed. Please add a valid SSL Certificate or "
                            f"change the verify_ssl  flag to False in cisco_dc_networking_app_for_splunk_settings.conf file. Error: {str(e)}") 
                    return False

                except Exception as e:
                    logger.error(f"Connection Unsuccessful. Please verify Hostname(s)/IP Address(es), Username, Certificate Name and Path of Private Key are correct. Error: {str(e)}")
                    self.put_msg("Connection Unsuccessful. Please verify Hostname(s)/IP Address(es), Username, Certificate Name and Path of Private Key are correct.")
                    return False

    def create_cookie(self, info_url, user, cert_name, private_key):
        """Create X509 header for cert based auth."""
        info_url = unquote(info_url)
        cert_dn = f"uni/userext/user-{user}/usercert-{cert_name}"
        payload = f"GET{info_url}"

        payload = payload.encode("utf-8")
        signature = base64.b64encode(rsa.sign(payload, private_key, "SHA-256"))

        if sys.version_info >= (3, 0, 0):
            signature = signature.decode("utf-8")

        cookie = {
            "APIC-Request-Signature": signature,
            "APIC-Certificate-Algorithm": "v1.0",
            "APIC-Certificate-Fingerprint": "fingerprint",
            "APIC-Certificate-DN": cert_dn,
        }
        return cookie


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