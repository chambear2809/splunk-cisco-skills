################################################################################
#                                  _    ____ ___                               #
#                                 / \  / ___|_ _|                              #
#                                / _ \| |    | |                               #
#                               / ___ \ |___ | |                               #
#                         _____/_/   \_\____|___|_ _                           #
#                        |_   _|__   ___ | | | _(_) |_                         #
#                          | |/ _ \ / _ \| | |/ / | __|                        #
#                          | | (_) | (_) | |   <| | |_                         #
#                          |_|\___/ \___/|_|_|\_\_|\__|                        #
#                                                                              #
################################################################################
#                                                                              #
# Copyright (c) 2024 Cisco Systems                                        #
# All Rights Reserved.                                                         #
#                                                                              #
#    Licensed under the Apache License, Version 2.0 (the "License"); you may   #
#    not use this file except in compliance with the License. You may obtain   #
#    a copy of the License at                                                  #
#                                                                              #
#         http://www.apache.org/licenses/LICENSE-2.0                           #
#                                                                              #
#    Unless required by applicable law or agreed to in writing, software       #
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT #
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the  #
#    License for the specific language governing permissions and limitations   #
#    under the License.                                                        #
#                                                                              #
################################################################################
"""This module contains the Session class that controls communication with the APIC."""
import import_declare_test
import copy
import json
import ssl
import threading
import time
import socket
import base64
import requests
import sys
from collections import namedtuple

if sys.version_info < (3, 0, 0):
    from urllib import unquote
else:
    from urllib.parse import unquote

try:
    from requests.packages.urllib3.exceptions import InsecureRequestWarning
except ImportError:
    pass
from six.moves.queue import Queue
from websocket import create_connection, WebSocketException
from requests.exceptions import ConnectionError
import common.log as logger_manager
from common.consts import API_RETRY_COUNT

try:
    import rsa

    NO_RSA = False
except ImportError:
    NO_RSA = True
try:
    import urllib3
except (ImportError, AttributeError):
    pass


class CredentialsError(Exception):
    """Exception class for errors with Credentials class."""

    def __init___(self, message):
        Exception.__init__(self, f"Session Credentials Error:{message}")
        self.message = message


class Login(threading.Thread):
    """Login thread responsible for refreshing the APIC login before timeout."""

    def __init__(self, apic, logger):
        """Initializing the Login thread."""
        threading.Thread.__init__(self)
        self._apic = apic
        self._login_timeout = 0
        self._exit = False
        self.logger = logger

    def exit(self):
        """Indicate that the thread should exit."""
        self._exit = True

    def _check_callbacks(self):
        """
        Invoke the callback functions on a successful relogin if there was an error response.

        :param resp: Instance of requests.Response
        """
        if self._apic.login_error:
            self.logger.info("Logged back into the APIC")
            self._apic.login_error = False
            self._apic.invoke_login_callbacks()

    def run(self):
        while not self._exit:
            time.sleep(self._login_timeout)
            try:
                resp = self._apic.refresh_login(timeout=120)
            except ConnectionError:
                self.logger.debug("Could not refresh APIC login due to ConnectionError")
                self._login_timeout = 30
                self._apic.login_error = True
            except requests.exceptions.Timeout:
                self.logger.debug("Could not refresh APIC login due to Timeout")
            else:
                if resp.ok:
                    self._check_callbacks()
                    continue
            try:
                resp = self._apic._send_login()
                self._apic.resubscribe()
                if resp.ok:
                    self._check_callbacks()
                else:
                    self.logger.debug("Could not re-login to APIC.")
                    self._login_timeout = 30
            except ConnectionError:
                self.logger.debug("Could not relogin to APIC due to ConnectionError")
                self._apic.login_error = True


class EventHandler(threading.Thread):
    """
    Thread responsible for websocket communication.

    Receives events through the websocket and places them into a Queue
    """

    def __init__(self, subscriber):
        """Initializing the Event Handler thread."""
        threading.Thread.__init__(self)
        self.subscriber = subscriber
        self._exit = False

    def exit(self):
        """Indicate that the thread should exit."""
        self._exit = True

    def run(self):
        while not self._exit:
            try:
                event = self.subscriber._ws.recv()
            except Exception:
                break
            if not len(event):
                continue
            self.subscriber._event_q.put(event)


class Subscriber(threading.Thread):
    """
    Thread responsible for event subscriptions.

    Issues subscriptions, creates the websocket, and refreshes the
    subscriptions before timer expiry.  It also reissues the
    subscriptions when the APIC login is refreshed.
    """

    def __init__(self, apic, logger):
        """Initializing the Subscriber thread."""
        threading.Thread.__init__(self)
        self._apic = apic
        self._subscriptions = {}
        self._ws = None
        self._ws_url = None
        self._refresh_time = 30
        self._event_q = Queue()
        self._events = {}
        self._exit = False
        self.event_handler_thread = None
        self.logger = logger

    def exit(self):
        """Indicate that the thread should exit."""
        self._exit = True

    def _send_subscription(self, url, only_new=False):
        """
        Send the subscription for the specified URL.

        :param url: URL string to issue the subscription
        """
        try:
            resp = self._apic.get(url)
        except ConnectionError:
            self._subscriptions[url] = None
            self.logger.error(f"Could not send subscription to APIC for url {url}")
            resp = requests.Response()
            resp.status_code = 404
            resp._content = '{"error": "Could not send subscription to APIC"}'
            return resp
        if not resp.ok:
            self._subscriptions[url] = None
            self.logger.error(f"Could not send subscription to APIC for url {url}")
            resp = requests.Response()
            resp.status_code = 404
            resp._content = '{"error": "Could not send subscription to APIC"}'
            return resp
        resp_data = json.loads(resp.text)
        if "subscriptionId" not in resp_data:
            self.logger.error(
                f"Did not receive proper subscription response from APIC for url {url} response: {resp_data}"
            )
            resp = requests.Response()
            resp.status_code = 404
            resp._content = '{"error": "Could not send subscription to APIC"}'
            return resp
        subscription_id = resp_data["subscriptionId"]
        self._subscriptions[url] = subscription_id
        if not only_new:
            while len(resp_data["imdata"]):
                event = {
                    "totalCount": "1",
                    "subscriptionId": [resp_data["subscriptionId"]],
                    "imdata": [resp_data["imdata"][0]],
                }
                self._event_q.put(json.dumps(event))
                resp_data["imdata"].remove(resp_data["imdata"][0])
        return resp

    def refresh_subscriptions(self):
        """Refresh all of the subscriptions."""
        # Make a copy of the current subscriptions in case of changes
        # while we are refreshing
        current_subscriptions = {}
        for subscription in self._subscriptions:
            try:
                current_subscriptions[subscription] = self._subscriptions[subscription]
            except KeyError:
                self.logger.warning("Subscription removed while copying")

        # Refresh the subscriptions
        for subscription in current_subscriptions:
            if self._ws is not None:
                if not self._ws.connected:
                    self.logger.warning("Websocket not established on subscription refresh. Re-establishing websocket")
                    self._open_web_socket("https://" in subscription)
            try:
                subscription_id = self._subscriptions[subscription]
            except KeyError:
                self.logger.warning("Subscription has been removed while trying to refresh")
                continue
            if subscription_id is None:
                self._send_subscription(subscription)
                continue
            refresh_url = "/api/subscriptionRefresh.json?id=" + str(subscription_id)
            resp = self._apic.get(refresh_url)
            if not resp.ok:
                self.logger.warning(f"Could not refresh subscription: {refresh_url}")
                # Try to resubscribe
                self._resubscribe()

    def _open_web_socket(self, use_secure=True):
        """
        Opens the web socket connection with the APIC.

        :param use_secure: Boolean indicating whether the web socket
                           should be secure.  Default is True.
        """
        sslopt = {}
        if use_secure:
            if self._apic.verify_ssl is False:
                sslopt["cert_reqs"] = ssl.CERT_NONE
            else:
                sslopt["cert_reqs"] = ssl.CERT_REQUIRED
                if isinstance(self._apic.verify_ssl, str):
                    sslopt["ca_certs"] = self._apic.verify_ssl
            self._ws_url = f"wss://{self._apic.ipaddr}/socket{self._apic.token}"
        else:
            self._ws_url = f"ws://{self._apic.ipaddr}/socket{self._apic.token}"

        kwargs = {}
        if self._ws is not None:
            if self._ws.connected:
                self._ws.close()
                self.event_handler_thread.exit()
        try:
            self._ws = create_connection(self._ws_url, sslopt=sslopt, **kwargs)
            if not self._ws.connected:
                self.logger.error("Unable to open websocket connection")
            self.event_handler_thread = EventHandler(self)
            self.event_handler_thread.daemon = True
            self.event_handler_thread.start()
        except WebSocketException:
            self.logger.error("Unable to open websocket connection due to WebSocketException")
        except socket.error:
            self.logger.error("Unable to open websocket connection due to Socket Error")

    def _resubscribe(self):
        """
        Reissue the subscriptions.

        Used to when the APIC login timeout occurs and a new subscription
        must be issued instead of simply a refresh.  Not meant to be called
        directly by end user applications.
        """
        self._process_event_q()
        urls = []
        for url in self._subscriptions:
            urls.append(url)
        self._subscriptions = {}
        for url in urls:
            self.subscribe(url, only_new=True)

    def _process_event_q(self):
        """Put the event into correct bucket based on URLs that have been subscribed."""
        if self._event_q.empty():
            return

        while not self._event_q.empty():
            event = self._event_q.get()
            orig_event = event
            try:
                event = json.loads(event)
            except ValueError:
                self.logger.error(f"Non-JSON event: {orig_event}")
                continue
            # Find the URL for this event
            num_subscriptions = len(event["subscriptionId"])
            for i in range(0, num_subscriptions):
                url = None
                for k in self._subscriptions:
                    if self._subscriptions[k] == str(event["subscriptionId"][i]):
                        url = k
                        break
                if url not in self._events:
                    self._events[url] = []
                self._events[url].append(event)
                if num_subscriptions > 1:
                    event = copy.deepcopy(event)

    def subscribe(self, url, only_new=False):
        """
        Subscribe to a particular APIC URL. Used internally by the Class and Instance subscriptions.

        :param url: URL string to send as a subscription
        """
        self.logger.info(f"Subscribing to url: {url}")
        # Check if already subscribed.  If so, skip
        if url in self._subscriptions:
            return

        if self._ws is not None:
            if not self._ws.connected:
                self._open_web_socket("https://" in url)

        resp = self._send_subscription(url, only_new=only_new)
        return resp

    def is_subscribed(self, url):
        """
        Check if subscribed to a particular APIC URL.

        :param url: URL string to send as a subscription
        """
        return url in self._subscriptions

    def has_events(self, url):
        """
        Check if a particular APIC URL subscription has any events.

        Used internally by the Class and Instance subscriptions.
        :param url: URL string to check for pending events
        """
        self._process_event_q()
        if url not in self._events:
            return False
        result = len(self._events[url]) != 0
        return result

    def get_event_count(self, url):
        """
        Check the number of subscription events for a particular APIC URL.

        :param url: URL string to check for pending events
        :returns: Interger number of events in event queue
        """
        self._process_event_q()
        if url not in self._events:
            return 0
        return len(self._events[url])

    def get_event(self, url):
        """
        Get an event for a particular APIC URL subscription. Used internally by the Class and Instance subscriptions.

        :param url: URL string to get pending event
        """
        self._process_event_q()
        if url not in self._events:
            raise ValueError
        event = self._events[url].pop(0)
        self.logger.debug(f"Event received {event}")
        return event

    def unsubscribe(self, url):
        """
        Unsubscribe from a particular APIC URL.  Used internally by the Class and Instance subscriptions.

        :param url: URL string to unsubscribe
        """
        self.logger.info(f"Unsubscribing from url: {url}")
        if url not in self._subscriptions:
            return
        if "&subscription=yes" in url:
            unsubscribe_url = url.split("&subscription=yes")[0] + "&subscription=no"
        elif "?subscription=yes" in url:
            unsubscribe_url = url.split("?subscription=yes")[0] + "?subscription=no"
        else:
            raise ValueError("No subscription string in URL being unsubscribed")
        resp = self._apic.get(unsubscribe_url)
        if not resp.ok:
            self.logger.warning(f"Could not unsubscribe from url: {unsubscribe_url}")
        # Chew up any outstanding events
        while self.has_events(url):
            self.get_event(url)
        del self._subscriptions[url]
        if not self._subscriptions:
            self._ws.close(timeout=0)

    def run(self):
        while not self._exit:
            # Sleep for some interval and send subscription list
            time.sleep(self._refresh_time)
            try:
                self.refresh_subscriptions()
            except ConnectionError:
                self.logger.debug("Could not refresh subscriptions due to ConnectionError")


class Session(object):
    """This class is responsible for all communication with the APIC."""

    def __init__(
        self,
        url,
        uid,
        pwd=None,
        cert_name=None,
        key=None,
        verify_ssl=True,
        appcenter_user=False,
        subscription_enabled=True,
        proxies=None,
        relogin_forever=False,
        logger=None,
    ):
        """
        Session class for making the http requests.

        :param url:  String containing the APIC URL such as ``https://1.2.3.4``
        :param uid: String containing the username that will be used as\
        part of the  the APIC login credentials.
        :param pwd: String containing the password that will be used as\
        part of the  the APIC login credentials.
        :param cert_name: String containing the certificate name that will be used\
        as part of the  the APIC certificate authentication credentials.
        :param key: String containing the private key file name that will be used\
        as part of the  the APIC certificate authentication credentials.
        :param verify_ssl:  Used only for SSL connections with the APIC.\
        Indicates whether SSL certificates must be verified.  Possible\
        values are True and False with the default being False.
        :param appcenter_user:  Set True when using certificate authentication from\
        the context of an APIC appcenter app
        :param proxies: Optional dictionary containing the proxies passed\
        directly to the Requests library
        :param relogin_forever: Boolean that when set to True will attempt to re-login
                                forever regardless of the error returned from APIC.
        """
        self.logger = logger
        if not isinstance(url, str):
            url = str(url)
        if not isinstance(uid, str):
            uid = str(uid)
        if not isinstance(pwd, str):
            pwd = str(pwd)
        if not isinstance(url, str):
            raise CredentialsError("The URL or APIC address must be a string")
        if not isinstance(uid, str):
            raise CredentialsError("The user ID must be a string")
        if (pwd is None or pwd == "None") and not cert_name and not key:
            raise CredentialsError("An authentication method must be provided")
        if pwd:
            if not isinstance(pwd, str):
                raise CredentialsError("The password must be a string")
        if cert_name:
            if not isinstance(cert_name, str):
                raise CredentialsError("The certificate name must be a string")
        if key:
            if not isinstance(key, str):
                raise CredentialsError("The key path must be a string")
        if (cert_name and not key) or (not cert_name and key):
            raise CredentialsError("Both a certificate name and private key must be provided")
        if not isinstance(relogin_forever, bool):
            raise CredentialsError("relogin_forever must be a boolean")

        if "https://" in url:
            self.ipaddr = url[len("https://"):]
        else:
            self.ipaddr = url[len("http://"):]
        self.uid = uid
        self.pwd = pwd
        self.key = key
        self.cert_name = cert_name
        self.appcenter_user = appcenter_user
        if key and cert_name:
            if NO_RSA:
                raise ImportError(
                    'Cannot use certificate authentication because rsa is not available.\n\
                Please install it using "pip install rsa"'
                )

            self.cert_auth = True
            # Cert based auth does not support subscriptions :(
            # there's an exception for appcenter_user relying on the requestAppToken api
            if subscription_enabled and not self.appcenter_user:
                self.logger.warning("Disabling subscription support as certificate authentication does not support it.")
                self.logger.warning("Consider passing subscription_enabled=False to hide this warning message.")
                subscription_enabled = False
            # Disable the warnings for SSL
            if verify_ssl is False:
                try:
                    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
                except (AttributeError, NameError):
                    pass
            with open(self.key, "r") as f:
                key_text = f.read()
            try:
                self.private_key = rsa.PrivateKey.load_pkcs1(key_text)
            except Exception:
                self.logger.error("Are you sure you provided the private key? (Not the certificate)")
                self.logger.error(
                    "Make sure that you had converted your key to RSA private key. if not, follow the steps given in setup guide for the same."
                )
                raise TypeError(f"Could not load private key file {self.key}")
        else:
            self.cert_auth = False
        # self.api = 'http://%s:80/api/' % self.ip # 7580
        self.api = url
        self.session = None
        if verify_ssl in (False, "False", "false"):
            self.verify_ssl = False
        elif isinstance(verify_ssl, str) and verify_ssl not in ("True", "true", ""):
            self.verify_ssl = verify_ssl
        else:
            self.verify_ssl = True
        self.token = None
        self.login_thread = Login(self, logger=self.logger)
        self._relogin_callbacks = []
        self.login_error = False
        self._logged_in = False
        self.relogin_forever = relogin_forever
        self._subscription_enabled = subscription_enabled
        self._proxies = proxies
        if subscription_enabled:
            self.subscription_thread = Subscriber(self, logger=self.logger)
            self.subscription_thread.daemon = True
            self.subscription_thread.start()

    def __reduce__(self):
        """
        This will enable this class to be pickled by only saving api, uid and pwd when pickling.

        :return:
        """
        return self.__class__, (self.api, self.uid, self.pwd)

    def _prep_x509_header(self, method, url, data=None):
        """
        This function returns a dictionary containing the authentication signature for a given.

        request based on the private key and certificate name given to the session object.
        If the session object is using normal (user/pass) authentication an empty dictionary
        is returned.
        To calculate the signature the request is calculated on a string with format:
           '<HTTP-METHOD><URL><PAYLOAD>'
        > Note, the URL *does not* include the DNS/IP of the APIC
        """
        if not self.cert_auth:
            return {}

        # for appcenter_user with subscription enabled and currently logged_in
        # no need to build x509 header since authentication is using token
        if self.appcenter_user and self._subscription_enabled and self._logged_in:
            return {}

        if not self.session:
            self.session = requests.Session()

        if self.appcenter_user:
            cert_dn = f"uni/userext/appuser-{self.uid}/usercert-{self.cert_name}"
        else:
            cert_dn = f"uni/userext/user-{self.uid}/usercert-{self.cert_name}"

        url = unquote(url)

        self.logger.debug(
            f"Preparing certificate based authentication with:\n"
            f"Cert DN: {cert_dn}\n"
            f"Request: {method} {url}\n"
            "Data: [redacted]"
        )

        payload = f"{method}{url}"
        if data:
            payload += data
        payload = payload.encode("utf-8")
        signature = base64.b64encode(rsa.sign(payload, self.private_key, "SHA-256"))
        if sys.version_info >= (3, 0, 0):
            signature = signature.decode("utf-8")
        cookie = {
            "APIC-Request-Signature": signature,
            "APIC-Certificate-Algorithm": "v1.0",
            "APIC-Certificate-Fingerprint": "fingerprint",
            "APIC-Certificate-DN": cert_dn,
        }

        self.logger.debug("Prepared certificate-based authentication cookie.")
        return cookie

    def _send_login(self, timeout=None):
        """Send the actual login request to the APIC and open the web socket interface."""
        if self.verify_ssl is False:
            try:
                requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
            except (AttributeError, NameError):
                pass
        self.session = requests.Session()
        self._logged_in = False

        if self.appcenter_user and self._subscription_enabled:
            login_url = "/api/requestAppToken.json"
            data = {"aaaAppToken": {"attributes": {"appName": self.cert_name}}}
        elif self.cert_auth:
            self.logger.warning(
                "Will not explicitly login because certificate based authentication" " is being used for this session."
            )
            self.logger.warning("If permanently using cert auth, consider removing the call to login().")
            CertAuthResponse = namedtuple("CertAuthResponse", ["ok"])
            return CertAuthResponse(ok=True)
        else:
            login_url = "/api/aaaLogin.json"
            data = {"aaaUser": {"attributes": {"name": self.uid, "pwd": self.pwd}}}
        ret = self.push_to_apic(login_url, data=data, timeout=timeout)
        if not ret.ok:
            if self.relogin_forever:
                self.logger.debug("Could not relogin to APIC. Relogin forever enabled...")
                self.login_error = True
                return ret
            self.logger.debug("Could not relogin to APIC. Aborting login thread.")
            self.login_thread.exit()
            self.subscription_thread.exit()
            return ret
        self._logged_in = True
        ret_data = json.loads(ret.text)["imdata"][0]
        timeout = ret_data["aaaLogin"]["attributes"]["refreshTimeoutSeconds"]
        self.token = str(ret_data["aaaLogin"]["attributes"]["token"])
        if self._subscription_enabled:
            self.subscription_thread._open_web_socket("https://" in self.api)
        timeout = int(timeout)
        self.login_thread._login_timeout = timeout / 2
        return ret

    def login(self, timeout=None):
        """
        Initiate login to the APIC.  Opens a communication session with the APIC.

        using the python requests library.
        :returns: Response class instance from the requests library.\
        response.ok is True if login is successful.
        """
        self.logger.debug("Initializing connection to the APIC")
        try:
            resp = self._send_login(timeout)
        except ConnectionError as e:
            self.logger.debug(f"Could not relogin to APIC due to ConnectionError: {str(e)}")
            resp = requests.Response()
            resp.status_code = 404
            resp._content = '{"error": "Could not relogin to APIC due to ConnectionError"}'
        if (self.appcenter_user and self._subscription_enabled) or not self.cert_auth:
            self.login_thread.daemon = True
            self.login_thread.start()
        return resp

    def logged_in(self):
        """
        Returns whether the session is logged in to the APIC.

        :return: True or False. True if the session is logged in to the APIC.
        """
        return self._logged_in and not self.login_error

    def refresh_login(self, timeout=None):
        """
        Refresh the login to the APIC.

        :param timeout: Integer containing the number of seconds for connection timeout
        :return: Instance of requests.Response
        """
        refresh_url = "/api/aaaRefresh.json"
        resp = self.get(refresh_url, timeout=timeout)
        if resp.ok:
            ret_data = json.loads(resp.text)["imdata"][0]
            self.token = str(ret_data["aaaLogin"]["attributes"]["token"])
        return resp

    def close(self):
        """Close the session."""
        self.session.close()
        self._logged_in = False

    def subscribe(self, url, only_new=False):
        """
        Subscribe to events for a particular URL.  Used internally by the class and instance subscriptions.

        :param url:  URL string to issue subscription
        """
        if self._subscription_enabled:
            resp = self.subscription_thread.subscribe(url, only_new=only_new)
            return resp

    def is_subscribed(self, url):
        """
        Check if subscribed to events for a particular URL.

        :param url:  URL string to issue subscription
        """
        if not self._subscription_enabled:
            return False
        return self.subscription_thread.is_subscribed(url)

    def resubscribe(self):
        """
        Resubscribe to the current subscriptions.  Used by the login thread after a re-login.

        :return: None
        """
        if self._subscription_enabled:
            return self.subscription_thread._resubscribe()

    def has_events(self, url):
        """
        Check if there are events for a particular URL. Used internally by the class and instance subscriptions.

        :param url:  URL string belonging to subscription
        :returns: True or False. True if an event exists for this subscription.
        """
        return self.subscription_thread.has_events(url)

    def get_event_count(self, url):
        """
        Check the number of subscription events for a particular APIC URL.

        :param url:  URL string belonging to subscription
        :returns: Interger number of events in event queue
        """
        return self.subscription_thread.get_event_count(url)

    def get_event(self, url):
        """
        Get an event for a particular URL.  Used internally by the class and instance subscriptions.

        :param url:  URL string belonging to subscription
        :returns: Object belonging to the instance or class that the
                  subscription was made.
        """
        return self.subscription_thread.get_event(url)

    def unsubscribe(self, url):
        """
        Unsubscribe from events for a particular URL.  Used internally by the.

        class and instance subscriptions.
        :param url:  URL string to remove issue subscription
        """
        if self._subscription_enabled:
            self.subscription_thread.unsubscribe(url)

    def push_to_apic(self, url, data, timeout=None):
        """
        Push the object data to the APIC.

        :param url: String containing the URL that will be used to\
                    send the object data to the APIC.
        :param data: Dictionary containing the JSON objects to be sent\
                     to the APIC.
        :returns: Response class instance from the requests library.\
                  response.ok is True if request is sent successfully.
        """
        post_url = self.api + url
        self.logger.debug(f"Posting url: {post_url}")

        if self.cert_auth and not (self.appcenter_user and self._subscription_enabled and self._logged_in):
            data = json.dumps(data, sort_keys=True)
            cookies = self._prep_x509_header("POST", url, data)
            resp = self.session.post(
                post_url,
                data=data,
                verify=self.verify_ssl,
                timeout=timeout,
                proxies=self._proxies,
                cookies=cookies,
            )
            if resp.status_code == 403:
                self.logger.error("Certificate authentication failed. Please check all settings are correct.")
                resp.raise_for_status()
        else:
            resp = self.session.post(
                post_url,
                data=json.dumps(data, sort_keys=True),
                verify=self.verify_ssl,
                timeout=timeout,
                proxies=self._proxies,
            )
            if resp.status_code == 403:
                self.logger.error("Received 403 response from APIC during POST request.")
                self.logger.debug("Trying to login again....")
                resp = self._send_login()
                self.resubscribe()
                self.logger.debug("Trying post call again...")
                self.logger.debug(f"Posting url: {post_url}")
                resp = self.session.post(
                    post_url,
                    data=json.dumps(data, sort_keys=True),
                    verify=self.verify_ssl,
                    timeout=timeout,
                    proxies=self._proxies,
                )
        self.logger.debug(f'Received response for the url: {post_url}.')
        return resp

    def get(self, url, timeout=None):
        """
        Perform a REST GET call to the APIC.

        :param url: String containing the URL that will be used to\
        send the object data to the APIC.
        :returns: Response class instance from the requests library.\
        response.ok is True if request is sent successfully.\
        response.json() will return the JSON data sent back by the APIC.
        """
        get_url = self.api + url

        cookies = self._prep_x509_header("GET", url)
        resp = self.session.get(
            get_url, timeout=timeout, verify=self.verify_ssl, proxies=self._proxies, cookies=cookies
        )
        if resp.status_code == 403:
            if self.cert_auth and not (self.appcenter_user and self._subscription_enabled):
                self.logger.error("Certificate authentication failed. Please check all settings are correct.")
                resp.raise_for_status()
            else:
                self.logger.error("Received 403 response from APIC during GET request.")
                self.logger.debug("Trying to login again....")
                resp = self._send_login()
                self.resubscribe()
                self.logger.debug("Trying get call again...")
                resp = self.session.get(get_url, timeout=timeout, verify=self.verify_ssl, proxies=self._proxies)
        elif resp.status_code == 400 and "Unable to process the query, result dataset is too big" in resp.text:
            # Response is too big so we will need to get the response in pages
            # Get the first chunk of entries
            self.logger.debug("Response too big. Need to collect it in pages. Starting collection...")
            page_number = 0
            self.logger.debug("Getting first page")
            cookies = self._prep_x509_header("GET", url + f"&page={page_number}&page-size=10000")
            resp = self.session.get(
                get_url + f"&page={page_number}&page-size=10000",
                timeout=timeout,
                verify=self.verify_ssl,
                proxies=self._proxies,
                cookies=cookies,
            )
            entries = []
            if resp.ok:
                entries += resp.json()["imdata"]
                orig_total_count = int(resp.json()["totalCount"])
                total_count = orig_total_count - 10000
                while total_count > 0 and resp.ok:
                    page_number += 1
                    self.logger.debug(f"Getting page {page_number}")
                    # Get the next chunk
                    cookies = self._prep_x509_header("GET", url + f"&page={page_number}&page-size=10000")
                    resp = self.session.get(
                        get_url + f"&page={page_number}&page-size=10000",
                        timeout=timeout,
                        verify=self.verify_ssl,
                        proxies=self._proxies,
                        cookies=cookies,
                    )
                    if resp.ok:
                        entries += resp.json()["imdata"]
                        total_count -= 10000
                resp_content = {"imdata": entries, "totalCount": orig_total_count}
                resp._content = json.dumps(resp_content)
        elif resp.status_code == 429 or 500 <= resp.status_code < 600:
            self.logger.error(f"Received error: {str(resp.status_code)} {resp.text}")
            retries = API_RETRY_COUNT
            while retries > 0:
                self.logger.info("Retrying query")
                if resp.status_code == 429:
                    time.sleep(15)
                cookies = self._prep_x509_header("GET", url)
                resp = self.session.get(
                    get_url, timeout=timeout, verify=self.verify_ssl, proxies=self._proxies, cookies=cookies
                )
                if resp.status_code != 200:
                    self.logger.info("Retry was not successful.")
                    retries -= 1
                else:
                    self.logger.info("Retry was successful.")
                    break
            if retries == 0:
                self.logger.debug("Raising ConnectionError")
                raise ConnectionError
        self.logger.debug(f"Received response for the url {get_url}.")
        return resp

    def register_login_callback(self, callback_fn):
        """
        Register a callback function that will be called when the session performs a.

        successful relogin attempt after disconnecting from the APIC.
        :param callback_fn: function to be called
        """
        if callback_fn not in self._relogin_callbacks:
            self._relogin_callbacks.append(callback_fn)

    def deregister_login_callback(self, callback_fn):
        """
        Delete the registration of a callback function that was registered via the.

        register_login_callback function.
        :param callback_fn: function to be deregistered
        """
        if callback_fn in self._relogin_callbacks:
            self._relogin_callbacks.remove(callback_fn)

    def invoke_login_callbacks(self):
        """
        Invoke registered callback functions when the session performs a.

        successful relogin attempt after disconnecting from the APIC.
        """
        self.logger.info("Invoking login callbacks")
        for callback_fn in self._relogin_callbacks:
            self.logger.info("Invoking login callback...")
            callback_fn(self)
