import json
import os.path
import sys
import traceback
import requests
import time
import threading
from functools import wraps
from solnlib import conf_manager, log
from solnlib.modular_input import checkpointer
from splunklib import modularinput as smi
import splunk.rest as rest
import import_declare_test
import base64

import meraki


SWITCHES_SOURCETYPE = "meraki:switches"
SECURITYAPPLIANCES_SOURCETYPE = "meraki:securityappliances"
ACCESSPOINTS_SOURCETYPE = "meraki:accesspoints"
AIRMARSHAL_SOURCETYPE = "meraki:airmarshal"
CAMERAS_SOURCETYPE = "meraki:cameras"
AUDIT_SOURCETYPE = "meraki:audit"
ORGANIZATIONSECURITY_SOURCETYPE = "meraki:organizationsecurity"
DEVICEHISTORY_SOURCETYPE = "meraki:devicesavailabilitieschangehistory"
DEVICEADDRESSES_SOURCETYPE = "meraki:devicesuplinksaddressesbydevice"
ETHERNET_SOURCETYPE = "meraki:wirelessdevicesethernetstatuses"
PACKETLOSS_SOURCETYPE = "meraki:wirelessdevicespacketlossbydevice"
SENSORREADING_SOURCETYPE = "meraki:sensorreadingshistory"
TOPAPPLIANCES_SOURCETYPE = "meraki:summarytopappliancesbyutilization"
TOPCLIENTS_SOURCETYPE = "meraki:summarytopclientsbyusage"
TOPDEVICES_SOURCETYPE = "meraki:summarytopdevicesbyusage"
TOPSWITCHES_SOUCETYPE = "meraki:summarytopswitchesbyenergyusage"
ASSURANCEALERTS_SOURCETYPE = "meraki:assurancealerts"
REQUETSHISTORY_SOURCETYPE = "meraki:apirequestshistory"
REQUESTRESPONSECODE_SOURCETYPE = "meraki:apirequestsresponsecodes"
REQUESTOVERVIEW_SOURCETYPE = "meraki:apirequestsoverview"
APPLIANCEVPNSTATS_SOURCETPYE = "meraki:appliancesdwanstatistics"
APPLIANCEVPNSTATUS_SOURCETPYE = "meraki:appliancesdwanstatuses"
LICENSEOVERVIEW_SOURCETYPE = "meraki:licensesoverview"
COTERMLICENSE_SOURCETYPE = "meraki:licensescotermlicenses"
SUBSCRIPTIONENTITLEMENT_SOURCETPYE = "meraki:licensessubscriptionentitlements"
LICENSESUBSCRIPTIONS_SOURCETPYE = "meraki:licensessubscriptions"
SWITCHPORTOVERVIEW_SOURCETYPE = "meraki:switchportsoverview"
FIRMWAREUPGRADE_SOURCETYPE = "meraki:firmwareupgrades"
ORGANIZATIONNETWORKS_SOURCETYPE = "meraki:organizationsnetworks"
ORGANIZATIONS_SOURCETYPE = "meraki:organizations"
DEVICES_SOURCETYPE = "meraki:devices"
POWER_MODULES_STATUSES_BY_DEVICE_SOURCETYPE = "meraki:powermodulesstatusesbydevice"
PORTS_TRANSCEIVERS_READINGS_HISTORY_BY_SWITCH_SOURCETYPE = "meraki:portstransceiversreadingshistorybyswitch"
SWITCH_PORTS_BY_SWITCH_SOURCETYPE = "meraki:switchportsbyswitch"
SUMMARY_SWITCH_POWER_HISTORY_SOURCETYPE = "meraki:summaryswitchpowerhistory"
WIRELESS_CONTROLLER_AVAILABILITIES_CHANGE_HISTORY_SOURCETYPE = "meraki:wirelesscontrolleravailabilitieschangehistory"
WIRELESS_CONTROLLER_DEVICES_INTERFACES_USAGE_HISTORY_BY_INTERVAL_SOURCETYPE = (
    "meraki:wirelesscontrollerdevicesinterfacesusagehistorybyinterval"
)
WIRELESS_CONTROLLER_DEVICES_INTERFACES_PACKETS_OVERVIEW_BY_DEVICE_SOURCETYPE = (
    "meraki:wirelesscontrollerdevicesinterfacespacketsoverviewbydevice"
)
WIRELESS_DEVICES_WIRELESS_CONTROLLERS_BY_DEVICE_SOURCETYPE = "meraki:wirelessdeviceswirelesscontrollersbydevice"
WEBHOOK_LOGS_SOURCETYPE = "meraki:webhooklogs:api"

# Sourcetypes with timestamps
NOT_TS_SOURCETYPES = [
    LICENSEOVERVIEW_SOURCETYPE,
    SUBSCRIPTIONENTITLEMENT_SOURCETPYE,
    FIRMWAREUPGRADE_SOURCETYPE,
    ORGANIZATIONNETWORKS_SOURCETYPE,
    ORGANIZATIONS_SOURCETYPE,
    DEVICEADDRESSES_SOURCETYPE,
    ETHERNET_SOURCETYPE,
    LICENSESUBSCRIPTIONS_SOURCETPYE,
    DEVICES_SOURCETYPE,
    POWER_MODULES_STATUSES_BY_DEVICE_SOURCETYPE,
    PORTS_TRANSCEIVERS_READINGS_HISTORY_BY_SWITCH_SOURCETYPE,
    SWITCH_PORTS_BY_SWITCH_SOURCETYPE,
    WIRELESS_CONTROLLER_AVAILABILITIES_CHANGE_HISTORY_SOURCETYPE,
    WIRELESS_CONTROLLER_DEVICES_INTERFACES_PACKETS_OVERVIEW_BY_DEVICE_SOURCETYPE,
    WIRELESS_DEVICES_WIRELESS_CONTROLLERS_BY_DEVICE_SOURCETYPE
]

INCLUDE_TS_SOURCETYPES = [
    ORGANIZATIONSECURITY_SOURCETYPE,
    REQUETSHISTORY_SOURCETYPE
]

APP_NAME = __file__.split(os.path.sep)[-3]


class RateLimiter:
    """Class to handle API rate limiting for Cisco Meraki."""

    def __init__(
        self,
        max_calls,
        period,
        logger,
        organization_id,
    ):
        """Initialize the rate limiter."""
        self.max_calls = max_calls
        self.period = period
        self.lock = threading.Lock()
        self.logger = logger
        self.organization_id = organization_id
        self.kv_ratelimiter_name = f"cisco_meraki_org_id_{self.organization_id}"

    def is_allowed(self, checkpoint_data):
        """
        Check if API call is allowed based on rate limits.

        :param checkpoint_data: Checkpoint data.
        :return: True if API call is allowed, False otherwise.
        """
        current_time = time.time()

        api_calls = checkpoint_data.get("api_calls", 0)
        last_call_ts = checkpoint_data.get("last_call")

        with self.lock:

            # if the time limit has passed reset the api calls counter to zero
            if last_call_ts and current_time - last_call_ts > self.period:
                checkpoint_data["api_calls"] = 0
                api_calls = 0

            # check if the numbers of calls limits is reached or not
            if api_calls < self.max_calls:
                checkpoint_data["api_calls"] = api_calls + 1
            else:
                self.logger.warning(
                    "Rate limit exceeded. Try again after few seconds."
                )
                time.sleep(1)  # sleep for 1 sec to reset api calls limit allowed
                checkpoint_data["api_calls"] = 0

            return True

    def limit(self, func):
        """Decorator to limit API calls based on rate limiting configuration."""
        @wraps(func)
        def wrapper(method_self, *args, **kwargs):

            # to use self of rate limiter class
            ratelimiter_self = self

            # fetch checkpoint data
            try:
                checkpoint_collection = checkpointer.KVStoreCheckpointer(
                    ratelimiter_self.kv_ratelimiter_name,
                    method_self.session_key,
                    APP_NAME,
                )
            except Exception:
                self.logger.error(
                    "Error in Checkpoint handling: {}".format(traceback.format_exc())
                )

            checkpoint_data = checkpoint_collection.get(method_self.kv_ratelimiter_name)

            # if the checpoint data doesn't exist,create
            #  a empty dict to store and update data
            checkpoint_data = checkpoint_data if checkpoint_data else {}

            # check if api calls are allowed
            if ratelimiter_self.is_allowed(checkpoint_data):
                checkpoint_data["last_call"] = time.time()
                response = func(method_self, *args, **kwargs)

                # update checkpoint after api call
                checkpoint_collection.update(
                    method_self.kv_ratelimiter_name, checkpoint_data
                )
                return response

        return wrapper


def build_dashboard_api(base_url, api_key, proxy, session_key, auth_type="basic", access_token=None):
    """Returns Meraki Dashboard API object."""
    base_url += "/api/v1"

    app_version = get_app_version(session_key)
    user_agent = f"SplunkAddOnForCiscoMeraki/{app_version} Cisco"

    # Use the appropriate key based on auth type
    actual_api_key = access_token if auth_type == "oauth" else api_key

    return meraki.DashboardAPI(
        api_key=actual_api_key,
        base_url=base_url,
        output_log=False,
        suppress_logging=True,
        requests_proxy=proxy,
        caller=user_agent,
        wait_on_rate_limit=True,
        maximum_retries=5,
        nginx_429_retry_wait_time=30,
    )


def set_logger(session_key, filename):
    """
    This function sets up a logger with configured log level.

    :param filename: Name of the log file

    :return logger: logger object
    """
    logger = log.Logs().get_logger(filename)
    log_level = conf_manager.get_log_level(
        logger=logger,
        session_key=session_key,
        app_name=APP_NAME,
        conf_name="splunk_ta_cisco_meraki_settings",
        default_log_level="DEBUG",
    )
    logger.setLevel(log_level)
    return logger


def get_proxy_settings(logger, session_key):
    """
    This function reads proxy settings if any, otherwise returns None.

    :param session_key: Session key for the particular modular input
    :return: A dictionary proxy having settings
    """
    try:
        settings_cfm = conf_manager.ConfManager(
            session_key,
            APP_NAME,
            realm="__REST_CREDENTIAL__#{}#configs/conf-splunk_ta_cisco_meraki_settings".format(
                APP_NAME
            ),
        )
        splunk_ta_cisco_meraki_settings_conf = settings_cfm.get_conf(
            "splunk_ta_cisco_meraki_settings"
        ).get_all()

        proxy_settings = None
        proxy_stanza = {}
        for k, v in splunk_ta_cisco_meraki_settings_conf["proxy"].items():
            proxy_stanza[k] = v

        if int(proxy_stanza.get("proxy_enabled", 0)) == 0:
            logger.debug("Proxy is disabled. Returning None")
            return proxy_settings
        proxy_type = "http"
        proxy_port = proxy_stanza.get("proxy_port")
        proxy_url = proxy_stanza.get("proxy_url")
        proxy_username = proxy_stanza.get("proxy_username", "")
        proxy_password = proxy_stanza.get("proxy_password", "")

        if proxy_username and proxy_password:
            proxy_username = requests.compat.quote_plus(proxy_username)
            proxy_password = requests.compat.quote_plus(proxy_password)
            proxy_uri = "%s://%s:%s@%s:%s" % (
                proxy_type,
                proxy_username,
                proxy_password,
                proxy_url,
                proxy_port,
            )
        else:
            proxy_uri = "%s://%s:%s" % (proxy_type, proxy_url, proxy_port)
        logger.debug("Successfully fetched configured proxy details.")
        return proxy_uri
    except Exception:
        logger.error(
            "Failed to fetch proxy details from configuration. {}".format(
                traceback.format_exc()
            )
        )
        sys.exit(1)


def get_base_url(region):
    """
    This function retrieves organization base URL using addon configuration file.

    :param region: Selected Region configured in the addon
    :return: Base URL
    """
    if region == "india":
        return "https://api.meraki.in"
    elif region == "canada":
        return "https://api.meraki.ca"
    elif region == "china":
        return "https://api.meraki.cn"
    elif region == "fedramp":
        return "https://api.gov-meraki.com"

    return "https://api.meraki.com"


def get_organization_details(logger, session_key, organization_name):
    """
    This function retrieves organization details from addon configuration file.

    :param session_key: Session key for the particular modular input
    :param organization_name: Organization name configured in the addon
    :return: Organization details in form of a dictionary
    """
    try:
        cfm = conf_manager.ConfManager(
            session_key,
            APP_NAME,
            realm="__REST_CREDENTIAL__#{}#configs/conf-splunk_ta_cisco_meraki_organization".format(
                APP_NAME
            ),
        )
        organization_conf_file = cfm.get_conf("splunk_ta_cisco_meraki_organization")
        logger.debug(
            "Reading organization info from splunk_ta_cisco_meraki_organization.conf for organization name {}".format(
                organization_name
            )
        )

        org_conf = organization_conf_file.get(organization_name)
        auth_type = org_conf.get("auth_type", "basic")

        region = org_conf.get("region")
        org_details = {
            "region": region,
            "organization_id": org_conf.get("organization_id"),
            "max_api_calls_per_second": org_conf.get("max_api_calls_per_second", 5),
            "auth_type": auth_type,
        }
        base_url = org_conf.get(
            "base_url", None
        )
        if not base_url:
            base_url = get_base_url(region)
        org_details["base_url"] = base_url

        if auth_type == "oauth":
            org_details["access_token"] = org_conf.get("access_token")
            org_details["refresh_token"] = org_conf.get("refresh_token")
            org_details["client_id"] = org_conf.get("client_id")
            org_details["client_secret"] = org_conf.get("client_secret")
        else:
            org_details["organization_api_key"] = org_conf.get("organization_api_key")

        return org_details
    except Exception:
        logger.error(
            "Failed to fetch the organization details from splunk_ta_cisco_meraki_organization.conf file "
            + "for the organization '{}': {}".format(
                organization_name, traceback.format_exc()
            )
        )
        sys.exit(
            "Error while fetching organization details. Terminating modular input."
        )


def validate_interval(input_params, interval_range):
    """
    This function validates the interval parameter.

    :param input_params: dictionary of input parameters
    """
    try:
        interval = int(input_params.get("interval"))
        if interval not in range(interval_range.start, interval_range.stop + 1):
            raise Exception(
                f"Interval should be between {interval_range.start} and {interval_range.stop} seconds."
            )
    except ValueError:
        raise Exception(
            f"Interval should be an integer and should be in a range from {interval_range.start} "
            f"to {interval_range.stop} seconds."
        )


def validate_top_count(input_params, top_count_range):
    """
    This function validates the top count parameter.

    :param input_params: dictionary of input parameters
    """
    try:
        interval = int(input_params.get("top_count"))
        if interval not in range(top_count_range.start, top_count_range.stop + 1):
            raise Exception(
                f"Top count should be between {top_count_range.start} and {top_count_range.stop}."
            )
    except ValueError:
        raise Exception(
            f"Top count should be an integer and should be in a range from {top_count_range.start} "
            f"to {top_count_range.stop}."
        )


def validate_start_from_days_ago(input_params, start_from_days_ago_range):
    """
    This function validates the input parameters for start from (days in the past) input.

    :param input_params: dictionary of input parameters
    :param start_from_days_ago_range: range of min and max allowed number of days
    """
    error_msg = (
        f"Start from should be an integer in a range from {start_from_days_ago_range.start}"
        + f" to {(start_from_days_ago_range.stop)}"
    )
    try:
        start_from_days_ago_raw = input_params.get("start_from_days_ago")
        if start_from_days_ago_raw is not None:
            start_from_days_ago = int(start_from_days_ago_raw)
            if start_from_days_ago not in range(
                start_from_days_ago_range.start, start_from_days_ago_range.stop + 1
            ):
                raise Exception(error_msg)
    except ValueError:
        raise Exception(error_msg)


def checkpoint_name_from_input_name(input_name):
    """
    Returns checkpoint name based on the input name.

    :param input_name: Input name
    :return checkpoint_name: Checkpoint name
    """
    return input_name.replace("://", "_")


def checkpoint_handler(logger, session_key, checkpoint_name):
    """
    This function creates as well as handles kv-store checkpoints for each input.

    :param logger: Logger object
    :param session_key: Session key for the particular modular input
    :param checkpoint_name: Name of the checkpoint file for the particular input
    :return checkpoint_exists: True, if checkpoint exists, else False
    :return checkpoint_collection: Checkpoint directory
    """
    try:
        checkpoint_collection = checkpointer.KVStoreCheckpointer(
            checkpoint_name, session_key, APP_NAME
        )
        return True, checkpoint_collection
    except Exception:
        logger.error("Error in Checkpoint handling: {}".format(traceback.format_exc()))
        return False, None


def write_event(logger, event_writer, raw_event, sourcetype, index, source, host):
    """
    This function ingests data into Splunk.

    :param logger: Logger instance
    :param event_writer: Event Writer object
    :param raw_event: Raw event to be ingested into Splunk
    :param sourcetype: Sourcetype of the data
    :param index: Index where to write data
    :param source: Source of the data
    :param host: URL which is getting used to fetch events
    :return: boolean value indicating if the event is successfully ingested
    """
    try:
        event = smi.Event(
            data=json.dumps(raw_event, ensure_ascii=False),
            sourcetype=sourcetype,
            source=source,
            host=host,
            index=index,
        )
        event_writer.write_event(event)
        return True
    except Exception:
        logger.error("Error writing event to Splunk: {}".format(traceback.format_exc()))
        return False


def read_conf_file(session_key, conf_file, stanza=None):
    """
    Get conf file content with conf_manager.

    :param session_key: Splunk session key
    :param conf_file: conf file name
    :param stanza: If stanza name is present then return only that stanza,
                    otherwise return all stanza
    """
    conf_file = conf_manager.ConfManager(
        session_key,
        import_declare_test.ta_name,
        realm="__REST_CREDENTIAL__#{}#configs/conf-{}".format(
            import_declare_test.ta_name, conf_file
        ),
    ).get_conf(conf_file)

    if stanza:
        return conf_file.get(stanza)
    return conf_file.get_all(only_current_app=True)


def get_app_version(session_key):
    """Return the version of TA specified in app.conf."""
    app_conf = read_conf_file(session_key, "app", stanza="launcher")
    version = app_conf.get("version")
    return version


def refresh_access_token(logger, session_key, organization_name):
    """
    Refresh OAuth2 access token using the refresh token.

    :param logger: Logger object
    :param session_key: Splunk session key
    :param organization_name: Name of the organization to refresh token for
    :return: True if token refreshed successfully, False otherwise
    """
    try:
        cfm = conf_manager.ConfManager(
            session_key,
            APP_NAME,
            realm="__REST_CREDENTIAL__#{}#configs/conf-splunk_ta_cisco_meraki_organization".format(
                APP_NAME
            ),
        )
        organization_conf = cfm.get_conf("splunk_ta_cisco_meraki_organization")
        org_stanza = organization_conf.get(organization_name)

        if not org_stanza or org_stanza.get("auth_type") != "oauth":
            logger.error(f"Organization {organization_name} not found or not using OAuth2")
            return False

        refresh_token = org_stanza.get("refresh_token")
        client_id = org_stanza.get("client_id")
        client_secret = org_stanza.get("client_secret")

        if not refresh_token or not client_id or not client_secret:
            logger.error(f"Missing required OAuth2 parameters for {organization_name}")
            return False

        # Get proxy settings
        proxy_info = get_proxy_settings(logger, session_key)

        # Define token refresh endpoint
        token_url = "https://as.meraki.com/oauth/token"

        # Prepare the request payload
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        # Import the required module for Basic Auth and URL encoding
        try:
            from urllib.parse import urlencode
        except ImportError:
            from urllib import urlencode

        # Create Basic Auth header using client_id and client_secret
        auth_string = f"{client_id}:{client_secret}"
        encoded_auth = base64.b64encode(auth_string.encode()).decode()

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {encoded_auth}"
        }

        # Send request to refresh token
        resp = requests.request(
            method="POST",
            url=token_url,
            headers=headers,
            data=urlencode(payload),
            proxies=proxy_info,
            timeout=90,
        )

        if resp.status_code == 200:
            try:
                content = resp.json()

                # Create a dictionary with the fields that need to be updated
                fields = {
                    "access_token": str(content.get("access_token")),
                    "refresh_token": str(content.get("refresh_token", refresh_token)),
                    "client_secret": str(client_secret)
                }

                # Update the organization config with new tokens
                # We need to create a new ConfManager instance to ensure we're not using a stale reference
                cfm_update = conf_manager.ConfManager(
                    session_key,
                    APP_NAME,
                    realm="__REST_CREDENTIAL__#{}#configs/conf-splunk_ta_cisco_meraki_organization".format(
                        APP_NAME
                    ),
                )
                conf = cfm_update.get_conf("splunk_ta_cisco_meraki_organization")
                conf.update(organization_name, fields, fields.keys())

                logger.info(
                    f"Successfully refreshed and updated access_token and refresh_token"
                    f" for organization {organization_name}."
                )
                return True
            except Exception as e:
                logger.error(f"Error parsing token refresh response: {str(e)}")
                return False
        else:
            logger.error(f"Failed to refresh token: HTTP {resp.status_code}, Response: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Error refreshing access token: {str(e)}")
        return False


def get_hec_tokens(session_key):
    """
    Get configured HEC tokens from API Query.

    :param session_key: Splunk session key

    :return: List containing HEC Tokens.
    """
    hec_url = "/servicesNS/nobody/-/data/inputs/http"
    _, content = rest.simpleRequest(
        hec_url,
        sessionKey=session_key,
        method="GET",
        getargs={"output_mode": "json"},
        raiseAllErrors=True
    )
    content = json.loads(content)
    return content


def get_hec_token_by_name(session_key, hec_reference):
    """
    Resolve a HEC input stanza name to its real token value.

    Returns None when the provided reference does not match a configured HEC
    input stanza.
    """
    content = get_hec_tokens(session_key)
    for http_stanza in content.get("entry", []):
        stanza_name = http_stanza.get("name", "")
        short_name = stanza_name.split("//")[-1]
        if hec_reference in (stanza_name, short_name):
            return http_stanza.get("content", {}).get("token")
    return None


def resolve_hec_token_value(session_key, hec_reference):
    """
    Resolve a stored HEC reference to the real shared secret.

    Newer configurations store the HEC input stanza name instead of the raw
    token value. Older configurations might still contain the token directly, so
    fall back to the original value if no stanza match is found.
    """
    resolved_token = get_hec_token_by_name(session_key, hec_reference)
    if resolved_token:
        return resolved_token
    return hec_reference
