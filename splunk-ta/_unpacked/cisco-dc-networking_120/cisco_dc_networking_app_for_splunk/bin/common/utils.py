import import_declare_test  # noqa: F401
from solnlib import conf_manager
import urllib.parse
import traceback
from splunk import admin
import common.consts as consts
import common.log as log

logger = log.get_logger("cisco_dc_utils")


class GetSessionKey(admin.MConfigHandler):
    """To get Splunk session key."""

    def __init__(self):
        """Initialize."""
        self.session_key = self.getSessionKey()


def get_sslconfig(session_key=None):
    """Get the verify_ssl flag or ca_cert file to be used for network calls."""
    if session_key is None:
        session_key = GetSessionKey().session_key

    app = consts.APP_NAME
    conf_name = "cisco_dc_networking_app_for_splunk_settings"
    session_key = urllib.parse.unquote(session_key.encode("ascii").decode("ascii"))
    session_key = session_key.encode().decode("utf-8")

    verify_ssl = True

    try:
        # Default value will be used for ca_certs_path if there is any error
        ssl_config = True
        ca_certs_path = ""

        cfm = conf_manager.ConfManager(
            session_key,
            app,
            realm="__REST_CREDENTIAL__#{}#configs/conf-{}".format(app, conf_name),
        )
        stanza = cfm.get_conf(conf_name, refresh=True).get("additional_parameters", {})
        verify_ssl = is_true((stanza.get("verify_ssl") or "").strip().upper())
        ca_certs_path = (stanza.get("ca_certs_path") or "").strip()

    except Exception:
        msg = f"Error while fetching ca_certs_path from '{conf_name}' conf. Traceback: {traceback.format_exc()}"
        logger.error(msg)

    if not verify_ssl:
        logger.debug("SSL Verification is set to False.")
        ssl_config = False
    elif verify_ssl and ca_certs_path:
        logger.debug(
            f"SSL Verification is set to True and will use the cert from this path. {ca_certs_path}.",
        )
        ssl_config = ca_certs_path
    else:
        logger.debug(
            "SSL Verification is set to True. Use cert from 'cisco_dc_networking_app_for_splunk/default/cisco_dc_networking_app_for_splunk_settings.conf'"  # noqa: E501
        )
        ssl_config = True

    return ssl_config


def is_true(val):
    """
    Check truthy value of the given parameter.

    :param val: Parameter of which truthy value is to be checkeds

    :return: True / False
    """
    value = str(val).strip().upper()
    if value in ("1", "TRUE", "T", "Y", "YES"):
        return True
    return False


def get_credentials(account_name, account_type, session_key):
    """Provide credentials of the configured account.

    Args:
        session_key: current session session key
        logger: log object

    Returns:
        Dict: A Dictionary having account information.
    """
    try:
        cfm = conf_manager.ConfManager(
            session_key,
            consts.APP_NAME,
            realm=f"__REST_CREDENTIAL__#{consts.APP_NAME}"
            f"#configs/conf-cisco_dc_networking_app_for_splunk_{account_type}",
        )
        account_conf_file = cfm.get_conf(
            f"cisco_dc_networking_app_for_splunk_{account_type}"
        )
        acc_creds = account_conf_file.get(account_name)
    except Exception:
        logger.error(f"Error in fetching account details. {traceback.format_exc()}")
    return acc_creds


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
        "cisco_dc_networking_app_for_splunk",
        realm="__REST_CREDENTIAL__#{}#configs/conf-{}".format(
            "cisco_dc_networking_app_for_splunk", conf_file
        ),
    ).get_conf(conf_file)

    if stanza:
        return conf_file.get(stanza)
    return conf_file.get_all()


def to_seconds(time_str):
    """Get time in seconds from str time."""
    unit = time_str[-1]
    value = int(time_str[:-1])
    if unit == 's' or unit == "S":
        return value
    elif unit == 'm' or unit == "M":
        return value * 60
    elif unit == 'h' or unit == "H":
        return value * 3600
    elif unit == 'd' or unit == "D":
        return value * 86400
    else:
        raise ValueError(f"Unsupported time unit: {unit}")
