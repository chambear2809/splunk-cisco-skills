import json
import requests
import time

try:
    import urllib3

    urllib3.disable_warnings()
except (ImportError, AttributeError):
    pass
else:
    try:
        urllib3.disable_warnings()
    except AttributeError:
        pass
try:
    from requests.packages.urllib3.exceptions import InsecureRequestWarning
except ImportError:
    pass

import common.cisco_dc_mso_urls as mso_urls
from common.consts import API_RETRY_COUNT


class CredentialsError(Exception):
    """Exception class for errors with Credentials class."""

    def __init___(self, message):
        """Initialize with error message."""
        Exception.__init__(self, f"Session Credentials Error:{message}")
        self.message = message


class LoginDomainError(Exception):
    """Exception class for errors with Credentials class."""

    def __init___(self, message):
        """Initialize with error message."""
        Exception.__init__(self, f"{message}")
        self.message = message


class Session(object):
    """Session class responsible for all communication with the MSO."""

    def __init__(self, url, username, password, domain_name, timeout, auth_type="mso",
                 verify_ssl=True, logger=None, proxies=None):
        """
        Initialize object with given parameters.

        :param url:  MSO URL such as https://<host>
        :type url: string
        :param username: Username that will be used as part of the MSO login credentials.
        :type username: string
        :param password: Password that will be used as part of the MSO login credentials.
        :type password: string
        :param domain_name: Fetch id of domain name which will be used as part of the MSO login credentials.
        :type domain_name: string
        :param timeout: The timeout interval for http/https request.
        :type timeout: int
        :param verify_ssl: Used only for SSL connections with the MSO.\
        Indicates whether SSL certificates must be verified.  Possible\
        values are True and False with the default being False.
        :type verify_ssl: string
        """
        self.logging = logger
        if not isinstance(url, str):
            url = str(url)
        if not isinstance(username, str):
            username = str(username)
        if not isinstance(password, str):
            password = str(password)
        if not isinstance(url, str):
            raise CredentialsError("The URL or MSO address must be a string")
        if not isinstance(username, str):
            raise CredentialsError("The username must be a string")
        if domain_name and not isinstance(domain_name, str):
            raise CredentialsError("The domain_name name must be a string")
        if password is None or password == "None":
            raise CredentialsError("An authentication method must be provided")
        if password:
            if not isinstance(password, str):
                raise CredentialsError("The password must be a string")

        if "https://" in url:
            self.ipaddr = url[len("https://"):]
        else:
            self.ipaddr = url[len("http://"):]
        self.username = username
        self.password = password
        self.domain_name = domain_name
        self.timeout = timeout
        self.auth_type = auth_type

        # self.api = "http://<host>:<port>/api/"
        self.api = url
        self.token = None
        self.session = requests.Session()
        self.proxies = proxies

        # Disable the warnings for SSL
        if not verify_ssl:
            try:
                requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
            except (AttributeError, NameError):
                pass

        if verify_ssl == "False":
            self.verify_ssl = False
        elif not verify_ssl:
            self.verify_ssl = False
        else:
            self.verify_ssl = True

    def get_headers(self, request_type):
        """
        Create headers for GET and POST calls.

        :param request_type: Indicates the type of HTTP Request. GET or POST.
        :type request_type: string
        """
        headers = {"Content-Type": "application/json"}
        if request_type == "GET":
            headers["Authorization"] = "Bearer " + self.token
        return headers

    def fetch_domain_id(self):
        """Fetch ID for domain."""
        try:
            url = f"https://{self.ipaddr}/{mso_urls.LOGIN_DOMAIN}"

            headers = {"Content-Type": "application/json"}
            self.logging.info(f"Making an API call to the url {url}.")

            response = self.session.get(
                url=url,
                headers=headers,
                timeout=self.timeout,
                verify=self.verify_ssl,
                proxies=self.proxies
            )

            if response.ok:
                self.logging.info(f"Successfully received the response for the url {url}.")
                response = response.json()
                for data in response:
                    for key in response[data]:
                        if key.get("name") == self.domain_name and key.get("id"):
                            return key.get("id")
            else:
                response.raise_for_status()

        except Exception as err:
            raise LoginDomainError(
                f"Failed fetching ID for domain {self.domain_name}. Exception: {str(err)}"
            )

    def login(self):
        """Perfrom MSO login and initialize token variable."""
        self.logging.debug("Initializing connection to the MSO")

        credentials = {"userName": self.username, "userPasswd": self.password}
        login_url = f"https://{self.ipaddr}/{mso_urls.ND_LOGIN_URL}"
        credentials["domain"] = self.domain_name
        credentials = json.dumps(credentials)

        headers = self.get_headers(request_type="POST")
        self.logging.info(f"Making an API call to the url {login_url}.")
        response = self.session.post(
            url=login_url,
            data=credentials,
            headers=headers,
            timeout=self.timeout,
            verify=self.verify_ssl,
            proxies=self.proxies
        )

        self.logging.debug(f"MSO Login Response: {response}")
        response.raise_for_status()

        if response.ok:
            self.logging.info(f"Successfully received the response for the url {login_url}.")
            self.token = response.json()["token"]

        return response

    def get(self, api_endpoint, params=None):
        """
        Hit the REST endpoint and return data of api response.

        :param api_endpoint: The MSO API endpoint from data is to be fetched.
        :type api_endpoint: string
        :param params: The parameters to be passed in GET request.
        :type params: dict
        :returns: API response in JSON format
        """
        headers = self.get_headers(request_type="GET")

        url = f"https://{self.ipaddr}/{api_endpoint}"
        self.logging.info(f"Making an API call to the url {url} with params {params}.")

        response = self.session.get(
            url=url, headers=headers, params=params, timeout=self.timeout, verify=self.verify_ssl, proxies=self.proxies
        )

        if response.ok:
            self.logging.info(f"Successfully received the response for the url {url}.")
            return response.json()

        elif response.status_code == 401:
            self.logging.info(
                "MSO Error: Performing MSO relogin, because token expired or there is some error in token format."
            )
            try:
                self.login()
                return self.get(api_endpoint, params)
            except Exception as err:
                self.logging.error(f"MSO Error: Could not re-login to MSO. Error: {str(err)}.")
                raise

        # retry only when exception occurs from server side and not client side
        elif response.status_code == 429 or 500 <= response.status_code < 600:
            self.logging.info(f"Received error: {str(response.status_code)} {response.text}")
            retries = API_RETRY_COUNT
            while retries > 0:
                self.logging.info("Retrying query")
                if response.status_code == 429:
                    time.sleep(15)
                response = self.session.get(url=url, timeout=self.timeout, verify=self.verify_ssl, proxies=self.proxies)
                if response.status_code != 200:
                    self.logging.info("Retry was not successful.")
                    retries -= 1
                else:
                    self.logging.info("Retry was successful.")
                    break
            if retries == 0:
                self.logging.error(
                    f"MSO Error: An error occurred while collecting data for url: {url}. "
                    f"Status Code: {response.status_code}. Response message: {response.text}"
                )
                response.raise_for_status()
        else:
            self.logging.error(
                f"MSO Error: An error occurred while collecting data for url: {url}. "
                f"Status Code: {response.status_code}. Response Reason: {response.reason}"
            )
            response.raise_for_status()

    def close(self):
        """Close the session."""
        self.session.close()
