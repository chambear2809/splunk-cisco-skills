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

from solnlib import splunk_rest_client as rest_client
from typing import Optional, List
import json

__all__ = ["BulletinRestClient"]


class BulletinRestClient:
    """REST client for handling Bulletin messages."""

    MESSAGES_ENDPOINT = "/services/messages"

    headers = [("Content-Type", "application/json")]

    class Severity:
        INFO = "info"
        WARNING = "warn"
        ERROR = "error"

    def __init__(
        self,
        message_name: str,
        session_key: str,
        app: str,
        **context: dict,
    ):
        """Initializes BulletinRestClient.
            When creating a new bulletin message, you must provide a name, which is a kind of ID.
            If you try to create another message with the same name (ID), the API will not add another message
            to the bulletin, but it will overwrite the existing one. Similar behaviour applies to deletion.
            To delete a message, you must indicate the name (ID) of the message.
            To provide better and easier control over bulletin messages, this client works in such a way
            that there is one instance responsible for handling one specific message.
            If you need to add another message to bulletin create another instance
            with a different 'message_name'
            e.g.
            msg_1 = BulletinRestClient("message_1", "<some session key>")
            msg_2 = BulletinRestClient("message_2", "<some session key>")

        Arguments:
            message_name: Name of the message in the Splunk's bulletin.
            session_key: Splunk access token.
            app: App name of namespace.
            context: Other configurations for Splunk rest client.
        """

        self.message_name = message_name
        self.session_key = session_key
        self.app = app

        self._rest_client = rest_client.SplunkRestClient(
            self.session_key, app=self.app, **context
        )

    def create_message(
        self,
        msg: str,
        severity: Severity = Severity.WARNING,
        capabilities: Optional[List[str]] = None,
        roles: Optional[List] = None,
    ):
        """Creates a message in the Splunk's bulletin. Calling this method
        multiple times for the same instance will overwrite existing message.

        Arguments:
            msg: The message which will be displayed in the Splunk's bulletin
            severity: Severity level of the message. It has to be one of: 'info', 'warn', 'error'.
                If wrong severity is given, ValueError will be raised.
            capabilities: One or more capabilities that users must have to view the message.
                Capability names are validated.
                This argument should be provided as a list of string/s e.g. capabilities=['one', 'two'].
                If a non-existent capability is used, HTTP 400 BAD REQUEST exception will be raised.
                If argument is not a List[str] ValueError will be raised.
            roles: One or more roles that users must have to view the message. Role names are validated.
                This argument should be provided as a list of string/s e.g. roles=['user', 'admin'].
                If a non-existent role is used, HTTP 400 BAD REQUEST exception will be raised.
                If argument is not a List[str] ValueError will be raised.
        """
        body = {
            "name": self.message_name,
            "value": msg,
            "severity": severity,
            "capability": [],
            "role": [],
        }

        if severity not in (
            self.Severity.INFO,
            self.Severity.WARNING,
            self.Severity.ERROR,
        ):
            raise ValueError(
                "Severity must be one of ("
                "'BulletinRestClient.Severity.INFO', "
                "'BulletinRestClient.Severity.WARNING', "
                "'BulletinRestClient.Severity.ERROR'"
                ")."
            )

        if capabilities:
            body["capability"] = self._validate_and_get_body_value(
                capabilities, "Capabilities must be a list of strings."
            )

        if roles:
            body["role"] = self._validate_and_get_body_value(
                roles, "Roles must be a list of strings."
            )

        self._rest_client.post(self.MESSAGES_ENDPOINT, body=body, headers=self.headers)

    def get_message(self):
        """Get specific message created by this instance."""
        endpoint = f"{self.MESSAGES_ENDPOINT}/{self.message_name}"
        response = self._rest_client.get(endpoint, output_mode="json").body.read()
        return json.loads(response)

    def get_all_messages(self):
        """Get all messages in the bulletin."""
        response = self._rest_client.get(
            self.MESSAGES_ENDPOINT, output_mode="json"
        ).body.read()
        return json.loads(response)

    def delete_message(self):
        """Delete specific message created by this instance."""
        endpoint = f"{self.MESSAGES_ENDPOINT}/{self.message_name}"
        self._rest_client.delete(endpoint)

    @staticmethod
    def _validate_and_get_body_value(arg, error_msg) -> List:
        if type(arg) is list and (all(isinstance(el, str) for el in arg)):
            return [el for el in arg]
        else:
            raise ValueError(error_msg)
