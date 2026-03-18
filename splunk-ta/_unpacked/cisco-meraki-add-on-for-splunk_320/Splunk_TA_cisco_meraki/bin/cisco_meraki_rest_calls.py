import time
import requests
import cisco_meraki_utils as utils
import json

input_endpoints = {
    utils.PORTS_TRANSCEIVERS_READINGS_HISTORY_BY_SWITCH_SOURCETYPE: (
        "/organizations/{organization_id}/switch/ports/transceivers/readings/history/bySwitch"
    ),
}


class MerakiRestCalls:
    """Class for making REST calls to Cisco Meraki API."""

    def __init__(self, config):
        """Initialize the class."""
        try:
            self._logger = config["logger"]
            self.sourcetype = config["sourcetype"]
            self.session_key = config["session_key"]
            self.input_name = config["input_name"]
            self.proxies = config["proxies"]
            self.base_url = config["base_url"] + "/api/v1"
            self.organization_id = config["organization_id"]

            # Handle different authentication types
            self.auth_type = config.get("auth_type", "basic")
            if self.auth_type == "basic":
                self.organization_api_key = config["organization_api_key"]
                self.access_token = None
            else:  # OAuth2
                self.access_token = config["access_token"]
                self.refresh_token = config["refresh_token"]
                self.client_id = config["client_id"]
                self.client_secret = config["client_secret"]
                self.organization_name = config["organization_name"]
                self.organization_api_key = None

            if self.sourcetype == utils.PORTS_TRANSCEIVERS_READINGS_HISTORY_BY_SWITCH_SOURCETYPE:
                self.endpoint = input_endpoints.get(self.sourcetype).format(
                    organization_id=config["organization_id"]
                )
            else:
                self.endpoint = input_endpoints.get(self.sourcetype)
        except KeyError as e:
            self._logger.error(
                f"Could not find required field from the configuration. KeyError: {e}"
                "Check if all required fields are present and account is configured properly."
            )
            raise

    def _extract_next_url(self, link_header):
        """Extract the next URL from the header.

        Args:
            link_header (str): The header from the response

        Returns:
            str: The next URL or None if not found
        """
        if not link_header:
            return None

        links = link_header.split(",")
        for link in links:
            link = link.strip()
            if "rel=next" in link:
                # Extract URL between < and >
                url = link.split(";")[0].strip()
                if url.startswith("<") and url.endswith(">"):
                    return url[1:-1]  # Remove < and >
        return None

    def _make_single_rest_call(self, url, method="GET", payload=None, params={}, headers=None, proxies=None, retries=5):
        """Make a single REST API call to Cisco Meraki.

        Args:
            url (str): The URL to make the request to
            method (str): The HTTP method to use
            payload (dict): The request payload
            params (dict): The request parameters
            headers (dict): The request headers
            proxies (dict): The proxies to use
            retries (int): The number of retries

        Returns:
            tuple: (response_json, next_url)
        """
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                data=payload,
                proxies=proxies,
                params=params,
                timeout=60,
            )

            if response.status_code == 429 and retries > 0:
                self._logger.debug(
                    "Retrying after {} seconds".format(
                        response.headers["Retry-After"]
                    )
                )
                time.sleep(int(response.headers["Retry-After"]))
                return self._make_single_rest_call(url, method, payload, params, headers, proxies, retries - 1)

            # Handle token expired for OAuth2
            if response.status_code == 401 and self.auth_type == "oauth" and retries > 0:
                self._logger.info(
                    f"Access token expired for organization {self.organization_name}."
                    " Attempting to refresh access token."
                )

                # Try to refresh the token
                if utils.refresh_access_token(self._logger, self.session_key, self.organization_name):
                    # Get updated token
                    org_details = utils.get_organization_details(self._logger, self.session_key, self.organization_name)
                    self.access_token = org_details.get("access_token")

                    self._logger.info(f"Successfully refreshed token for {self.organization_name}, retrying request")
                    # Retry the request with new token
                    return self._make_single_rest_call(url, method, payload, params, headers, proxies, retries - 1)
                else:
                    self._logger.error(f"Failed to refresh token for {self.organization_name}")

            response.raise_for_status()
            next_url = self._extract_next_url(response.headers.get("Link"))
            return response.json(), next_url

        except json.JSONDecodeError as e:
            self._logger.error(
                f"JSON Decode Error while fetching data for input: {self.input_name} with exception: {e}"
            )
            raise Exception(e)
        except requests.exceptions.HTTPError as e:
            if response.status_code == 429:
                self._logger.error(
                    f"Rate limit exceeded for input: {self.input_name}"
                )
            else:
                self._logger.error(
                    f"Error fetching data for input: {self.input_name} "
                    f"with status code: {response.status_code}, {response.text}"
                )
            raise Exception(e)
        except Exception as e:
            self._logger.error(
                f"Error fetching data for input: {self.input_name} with exception: {e}"
            )
            raise Exception(e)

    def make_rest_call(self, method="GET", payload=None, params={}, retries=5):
        """Make REST API call to Cisco Meraki with pagination support.

        This method handles pagination by processing the header in the response
        and making additional API calls until all data is retrieved.

        Args:
            method (str): The HTTP method to use
            payload (dict): The request payload
            params (dict): The request parameters
            retries (int): The number of retries

        Returns:
            list: The combined results from all paginated responses
        """
        app_version = utils.get_app_version(self.session_key)
        user_agent = f"SplunkAddOnForCiscoMeraki/{app_version} Cisco"

        # Get the appropriate auth token based on auth type
        auth_token = self.access_token if self.auth_type == "oauth" else self.organization_api_key

        headers = {
            "Authorization": f"Bearer {auth_token}",
            "Accept": "application/json",
            "User-Agent": user_agent,
        }

        proxies = {"http": self.proxies, "https": self.proxies} if self.proxies else None
        request_url = "{}{}".format(self.base_url, self.endpoint)

        all_results = []
        current_url = request_url

        while current_url:
            self._logger.debug(f"Making request to: {current_url}")
            data, next_url = self._make_single_rest_call(
                url=current_url,
                method=method,
                payload=payload,
                params=params,
                headers=headers,
                proxies=proxies,
                retries=retries
            )

            # Add the current results to our collection
            result = data.get("items", [])
            all_results.extend(result)

            # Update the URL for the next request
            current_url = next_url

            # Log pagination progress
            if next_url:
                self._logger.debug(f"Found next page URL: {next_url}")
            else:
                self._logger.debug("No more pages")

        self._logger.info(f"Retrieved a total of {len(all_results)} records")
        return all_results
