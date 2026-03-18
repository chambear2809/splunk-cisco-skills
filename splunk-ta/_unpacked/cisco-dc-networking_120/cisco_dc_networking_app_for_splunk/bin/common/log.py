import import_declare_test  # noqa: F401

import common.consts as consts


import logging
import logging.handlers

from splunk.clilib.bundle_paths import make_splunkhome_path
from splunk.clilib import cli_common as cli

DEFAULT_LOG_LEVEL = logging.INFO
DEFAULT_LOG_FORMAT = (
    "%(asctime)s %(levelname)s pid=%(process)d tid=%(threadName)s "
    "file=%(filename)s:%(funcName)s:%(lineno)d | %(message)s"
)


def get_file_handler(log_file):
    """Return file handler."""
    file_handler = logging.handlers.RotatingFileHandler(log_file, mode="a", maxBytes=25000000, backupCount=10)
    formatter = logging.Formatter(DEFAULT_LOG_FORMAT)
    file_handler.setFormatter(formatter)
    return file_handler


def get_log_file_name(file_name):
    """Generate log file name from path."""
    return "{}.log".format(file_name)


def get_logger(file_name=None):
    """
    Return Logger.

    :param level: log level
    :return: logger object
    """
    logger = logging.getLogger(consts.APP_NAME)
    logger.propagate = False

    cfg = cli.getConfStanza("cisco_dc_networking_app_for_splunk_settings", "logging")
    log_level = str(cfg.get("loglevel")).upper()
    log_level = getattr(logging, log_level) if hasattr(logging, log_level) else DEFAULT_LOG_LEVEL
    logger.setLevel(log_level)

    if file_name is None:
        return logger

    file_name = get_log_file_name(file_name)
    log_file = make_splunkhome_path(["var", "log", "splunk", file_name])

    file_handler_exists = any(
        [
            True for handler in logger.handlers if hasattr(handler, "baseFilename") and handler.baseFilename == log_file
        ]  # noqa: E501
    )
    if not file_handler_exists:
        file_handler = get_file_handler(log_file)
        logger.addHandler(file_handler)

    return logger
