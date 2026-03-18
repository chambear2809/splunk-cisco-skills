#
# Copyright 2025 Splunk Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import json
from enum import Enum
from typing import Tuple, Union, Optional

from solnlib import splunk_rest_client as rest_client


class AlertType(Enum):
    CUSTOM = "custom"
    NUMBER_OF_EVENTS = "number of events"
    NUMBER_OF_HOSTS = "number of hosts"
    NUMBER_OF_SOURCES = "number of sources"


class AlertSeverity(Enum):
    DEBUG = 1
    INFO = 2
    WARN = 3
    ERROR = 4
    SEVERE = 5
    FATAL = 6


class AlertComparator(Enum):
    GREATER_THAN = "greater than"
    LESS_THAN = "less than"
    EQUAL_TO = "equal to"
    RISES_BY = "rises by"
    DROPS_BY = "drops by"
    RISES_BY_PERC = "rises by perc"
    DROPS_BY_PERC = "drops by perc"


class AlertsRestClient:
    """REST client for handling alerts."""

    ENDPOINT = "/servicesNS/{owner}/{app}/saved/searches"
    headers = [("Content-Type", "application/json")]

    def __init__(
        self,
        session_key: str,
        app: str,
        owner: str = "nobody",
        **context: dict,
    ):
        """Initializes AlertsRestClient.

        Arguments:
            session_key: Splunk access token.
            app: App name of namespace.
            context: Other configurations for Splunk rest client.
        """
        self.session_key = session_key
        self.app = app

        self._rest_client = rest_client.SplunkRestClient(
            self.session_key,
            app=self.app,
            owner=owner,
            **context,
        )

        self.endpoint = self.ENDPOINT.format(owner=owner, app=app)

    def create_search_alert(
        self,
        name: str,
        search: str,
        *,
        disabled: bool = True,
        description: str = "",
        alert_type: AlertType = AlertType.NUMBER_OF_EVENTS,
        alert_condition: str = "",
        alert_comparator: AlertComparator = AlertComparator.GREATER_THAN,
        alert_threshold: Union[int, float, str] = 0,
        time_window: Tuple[str, str] = ("-15m", "now"),
        alert_severity: AlertSeverity = AlertSeverity.WARN,
        cron_schedule: str = "* * * * *",
        expires: Union[int, str] = "24h",
        **kwargs,
    ):
        """Creates a search alert in Splunk.

        Arguments:
            name: Name of the alert.
            search: Search query for the alert.
            disabled: Whether the alert is disabled. Default is True.
            description: Description of the alert.
            alert_type: Type of the alert (see AlertType). If it equals to CUSTOM, Splunk executes a check in
                alert_condition. Otherwise, alert_comparator and alert_threshold are used.
            alert_condition: Condition for the alert.
            alert_comparator: Comparator for the alert. Default is GREATER_THAN.
            alert_threshold: Threshold for the alert. Default is 0.
            time_window: Time window for the alert. Tuple of earliest and latest time. Default is ("-15m", "now").
            alert_severity: Severity level of the alert. Default is WARN.
            cron_schedule: Cron schedule for the alert. Default is "* * * * *".
            expires: Expiration time for the alert (i.e. how long you can access the result of triggered alert).
                Default is "24h".
            kwargs: Additional parameters for the alert. See Splunk documentation for more details.
        """
        params = {
            "output_mode": "json",
            "name": name,
            "search": search,
            "description": description,
            "alert_type": alert_type.value,
            "alert_condition": alert_condition,
            "alert_comparator": alert_comparator.value,
            "alert_threshold": alert_threshold,
            "alert.severity": str(alert_severity.value),
            "is_scheduled": "1",
            "cron_schedule": cron_schedule,
            "dispatch.earliest_time": time_window[0],
            "dispatch.latest_time": time_window[1],
            "alert.digest_mode": "1",
            "alert.expires": str(expires),
            "disabled": "1" if disabled else "0",
            "realtime_schedule": "1",
        }

        params.update(kwargs)

        self._rest_client.post(self.endpoint, body=params, headers=self.headers)

    def delete_search_alert(self, name: str):
        """Deletes a search alert in Splunk.

        Arguments:
            name: Name of the alert to delete.
        """
        self._rest_client.delete(f"{self.endpoint}/{name}")

    def get_search_alert(self, name: str):
        """Retrieves a specific search alert from Splunk.

        Arguments:
            name: Name of the alert to retrieve.

        Returns:
            A dictionary containing the alert details.
        """
        response = (
            self._rest_client.get(f"{self.endpoint}/{name}", output_mode="json")
            .body.read()
            .decode("utf-8")
        )

        return json.loads(response)

    def get_all_search_alerts(self):
        """Retrieves all search alerts from Splunk.

        Returns:
            A dictionary containing all search alerts.
        """
        response = (
            self._rest_client.get(self.endpoint, output_mode="json")
            .body.read()
            .decode("utf-8")
        )

        return json.loads(response)

    def update_search_alert(
        self,
        name: str,
        *,
        search: Optional[str] = None,
        disabled: Optional[bool] = None,
        description: Optional[str] = None,
        alert_type: Optional[AlertType] = None,
        alert_condition: Optional[str] = None,
        alert_comparator: Optional[AlertComparator] = None,
        alert_threshold: Optional[Union[int, float, str]] = None,
        time_window: Optional[Tuple[str, str]] = None,
        alert_severity: Optional[AlertSeverity] = None,
        cron_schedule: Optional[str] = None,
        expires: Optional[Union[int, str]] = None,
        **kwargs,
    ):
        """Updates a search alert in Splunk.

        Arguments:
            name: Name of the alert to update.
            search: Search query for the alert.
            disabled: Whether the alert is disabled.
            description: Description of the alert.
            alert_type: Type of the alert (see AlertType). If it equals to CUSTOM, Splunk executes a check in
                alert_condition. Otherwise, alert_comparator and alert_threshold are used.
            alert_condition: Condition for the alert.
            alert_comparator: Comparator for the alert.
            alert_threshold: Threshold for the alert.
            time_window: Time window for the alert. Tuple of earliest and latest time.
            alert_severity: Severity level of the alert.
            cron_schedule: Cron schedule for the alert.
            expires: Expiration time for the alert.
            kwargs: Additional parameters for the alert. See Splunk documentation for more details.
        """
        params = {
            "output_mode": "json",
        }

        if search:
            params["search"] = search

        if disabled is not None:
            params["disabled"] = "1" if disabled else "0"

        if description:
            params["description"] = description

        if alert_type:
            params["alert_type"] = alert_type.value

        if alert_condition:
            params["alert_condition"] = alert_condition

        if alert_comparator:
            params["alert_comparator"] = alert_comparator.value

        if alert_threshold:
            params["alert_threshold"] = str(alert_threshold)

        if time_window:
            params["dispatch.earliest_time"] = time_window[0]
            params["dispatch.latest_time"] = time_window[1]

        if alert_severity:
            params["alert.severity"] = str(alert_severity.value)

        if cron_schedule:
            params["is_scheduled"] = "1"
            params["cron_schedule"] = cron_schedule

        if expires:
            params["alert.expires"] = str(expires)

        params.update(kwargs)

        self._rest_client.post(
            f"{self.endpoint}/{name}", body=params, headers=self.headers
        )
