"""This modules contain method to setup logging."""
import os
import logging
import logging.handlers
from splunk.clilib import cli_common as cli
from splunk.clilib.bundle_paths import make_splunkhome_path


DEFAULT_LOG_LEVEL = "INFO"


# Remove handler by name
def remove_handler_by_name(logger, handler_name):
    """
    Remove the handler with a particular name.

    :param Logger object logger: logger object.
    :param str handler_name: The name of handler to remove from logger object.
    :return: None.
    :rtype: NoneType
    """
    for h in logger.handlers[:]:
        val = getattr(h, "baseFilename", None)
        if val and handler_name in val:
            logger.removeHandler(h)
            h.close()  # good practice to close the handler


def setup_logging(log_name: str, input_name: str = None, account_name: str = None) -> logging.Logger:
    """
    Set logger for the given log_name.

    :param str log_name: The name of log file.
    :param str input_name: The name of input.
    :param str account_name: The name of account.
    :return: Logger object.
    :rtype: logging.Logger
    """
    custom_msg = ""
    if input_name:
        custom_msg = f"input={input_name} | "
    elif account_name:
        custom_msg = f"account={account_name} | "
    # Make path till log file
    log_file = make_splunkhome_path(
        ["var", "log", "splunk", "%s.log" % log_name])
    # Get directory in which log file is present
    log_dir = os.path.dirname(log_file)
    # Create directory at the required path to store log file, if not found
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Read log level from conf file
    cfg = cli.getConfStanza('splunk_ta_cisco_intersight_settings', 'logging')
    log_level = str(cfg.get('loglevel'))

    logger = logging.getLogger(log_name)
    # Do not propagate logs to the parent logger
    logger.propagate = False

    # Set log level
    try:
        logger.setLevel(log_level)
    except Exception:
        # If log level is not valid use default log level
        logger.setLevel(DEFAULT_LOG_LEVEL)

    # if not handler_exists:
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, mode="a", maxBytes=10485760, backupCount=10)
    # Format logs
    fmt_str = (
        f"%(asctime)s %(levelname)s pid=%(process)d tid=%(threadName)s "
        f"file=%(filename)s:%(funcName)s:%(lineno)d | {custom_msg}%(message)s"
    )
    formatter = logging.Formatter(fmt_str)
    file_handler.setFormatter(formatter)

    # Remove handler to the logger
    remove_handler_by_name(logger, log_name)
    # Add handler to the logger
    logger.addHandler(file_handler)

    try:
        # Set log level for the file handler
        file_handler.setLevel(log_level)
    except Exception:
        # If log level is not valid use default log level
        file_handler.setLevel(DEFAULT_LOG_LEVEL)

    return logger
