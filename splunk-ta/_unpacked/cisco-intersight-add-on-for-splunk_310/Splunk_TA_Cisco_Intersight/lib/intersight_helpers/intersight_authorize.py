"""
Module to handle authentication for Cisco Intersight API using OAuth2.

This module provides a custom authentication class for requests to handle
OAuth2 authentication with Cisco Intersight. It handles token retrieval
and refresh, authentication of API requests, and error handling and logging.

Classes:
    IntersightAuth: Implements requests custom authentication for Cisco Intersight using OAuth2.
    IntersightAuthException: Raised when an error occurs during OAuth authentication.
"""
import time
import requests
from requests.auth import AuthBase
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from oauthlib.oauth2 import BackendApplicationClient
from typing import Dict, Optional


class IntersightAuth(AuthBase):
    """
    Implements requests custom authentication for Cisco Intersight using OAuth2.

    This class handles:
    - Token retrieval and refresh
    - Authentication of API requests
    - Error handling and logging
    """

    def __init__(self, kwargs: Dict[str, Optional[str]]) -> None:
        """
        Initialize the IntersightAuth class.

        Args:
            kwargs (dict): A dictionary containing configuration parameters.
                - client_id (str): The client ID for authentication.
                - client_secret (str): The client secret for authentication.
                - instance_url (str, optional): URL to retrieve the token. Defaults to Intersight's token URL.
                - logger (logging.Logger): Logger for logging messages.
                - verify (bool): Whether to verify SSL certificates.

        Initializes the OAuth2 client and fetches an initial token.
        """
        # Store configuration parameters
        self.client_id = kwargs["client_id"]
        self.client_secret = kwargs["client_secret"]
        self.token_url = kwargs.get("instance_url", "https://intersight.com/iam/token")
        self.token = None
        self.token_expires = 0
        self.logger = kwargs["logger"]
        self.verify = kwargs["verify"]
        self.proxy = kwargs["proxy"]
        self.user_agent = kwargs["user-agent"]

        # Initialize OAuth2 client
        self.oauth_client = BackendApplicationClient(client_id=kwargs["client_id"])

        # Log initialization and fetch the initial token
        self.logger.info("message=intersight_auth | Initializing IntersightAuth.")
        self.refresh_token()

    def refresh_token(self) -> dict:
        """Fetch a new OAuth2 token, update expiration time, and retry on failures."""
        # Prepare the request body with client credentials
        body = self.oauth_client.prepare_request_body(
            include_client_id=True, client_secret=self.client_secret
        )
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        self.logger.info("message=intersight_auth | Requesting new OAuth2 token.")

        # Create a session with a retry policy for network-related errors
        session = requests.Session()
        session.verify = self.verify
        session.proxies = self.proxy
        session.headers["User-Agent"] = self.user_agent
        retries = Retry(
            total=2,  # Maximum number of retry attempts
            backoff_factor=2,  # Backoff time multiplier
            status_forcelist=[500, 502, 503, 504],  # HTTP status codes that trigger a retry
            allowed_methods={"POST"},  # HTTP methods allowed to retry
        )
        session.verify = self.verify
        session.mount("https://", HTTPAdapter(max_retries=retries))

        # Attempt to fetch a new token with retry mechanism
        for retry_count in range(1, retries.total + 1):
            try:
                self.logger.info(
                    f"message=intersight_auth | type=Post, endpoint={self.token_url}, retry={retry_count}, "
                    f"verify={self.verify}, proxy={bool(self.proxy)}, initiating..."
                )
                # Send POST request to token URL
                response = session.post(self.token_url, data=body, headers=headers, timeout=30)
                self.logger.debug(
                    f"message=intersight_auth | Response received. "
                    f"Status: {response.status_code}"
                )

                if response.ok:
                    # Parse token and update expiration time
                    token_data = response.json()
                    self.token = token_data.get("access_token")
                    expires_in = token_data.get("expires_in")
                    self.token_expires = time.time() + expires_in

                    self.logger.info(
                        f"message=intersight_auth | Token refreshed successfully. "
                        f"Expires in {expires_in} seconds."
                    )
                    return response.json()

                # Handle specific retryable HTTP errors
                if response.status_code in retries.status_forcelist:
                    self.logger.warning(
                        f"message=intersight_auth | Retrying token request ({retry_count}/3). "
                        f"Status Code: {response.status_code}, Response: {response.text}"
                    )
                else:
                    self.logger.error(
                        f"message=intersight_auth | Token refresh failed. "
                        f"Status Code: {response.status_code}, Response: {response.text}"
                    )
                    response.raise_for_status()

            except (requests.exceptions.SSLError, requests.exceptions.ProxyError) as e:
                # Handle SSL and Proxy errors with retries
                self.logger.warning(
                    f"message=intersight_auth | SSL/Proxy error, retrying ({retry_count}/3). "
                    f"Error: {str(e)}"
                )
                if retry_count == retries.total:
                    self.logger.error(f"message=intersight_auth | SSL/Proxy error: {str(e)}")
                    raise IntersightAuthException(
                        "SSL verification failed. Please check the SSL certificate and proxy settings."
                    )
            except requests.exceptions.RequestException as e:
                # Handle general request exceptions
                try:
                    status_code = response.status_code
                except Exception:
                    status_code = None

                try:
                    resp_error_msg = response.json().get("error_description")
                except Exception:
                    resp_error_msg = str(e)

                self.logger.warning(
                    f"message=intersight_auth | Retrying token request ({retry_count}/3). "
                    f"Error: Status Code: {status_code}, Description: {resp_error_msg}"
                )
                if retry_count == retries.total:
                    resp_error_msg = (
                        f"Failed to fetch OAuth token and validate account. {resp_error_msg}"
                    )
                    self.logger.error(
                        f"message=intersight_auth | {resp_error_msg}"
                    )
                    raise IntersightAuthException(resp_error_msg)

        return None

    def ensure_valid_token(self) -> None:
        """
        Ensure that a valid token is available before making a request.

        This method checks if the current token is either missing or expired.
        If so, it refreshes the token by obtaining a new one. Otherwise, logs
        a debug message indicating the token is still valid.
        """
        # Check if the token is missing or expired
        if self.token is None or time.time() >= self.token_expires:
            # Log the need to refresh the token
            self.logger.info("message=intersight_auth | Token expired or missing, refreshing token.")
            # Refresh the token
            self.refresh_token()
        else:
            # Log that the token is still valid
            self.logger.debug("message=intersight_auth | Token is still valid, no refresh needed.")

    def __call__(self, r: requests.Request) -> None:
        """
        Injects the authentication token into the request headers.

        This method is a callable that takes in a request object and
        adds the authentication token to the headers of the request.
        """
        # Ensure that we have a valid token
        self.ensure_valid_token()
        # Add the token to the Authorization header of the request
        r.headers["Authorization"] = f"Bearer {self.token}"
        # Return the modified request
        return r


class IntersightAuthException(Exception):
    """Raised when an error occurs during OAuth authentication."""

    pass
