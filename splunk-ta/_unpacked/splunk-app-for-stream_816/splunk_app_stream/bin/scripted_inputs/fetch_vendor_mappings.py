import logging.handlers
import os
import sys
import splunk

import splunk.appserver.mrsparkle.lib.util as app_util
import splunk_app_stream.utils.netflow_utils as netflow_utils

SPLUNK_HOME = os.environ.get('SPLUNK_HOME')
INSTALLER_LOG_FILENAME = os.path.join(SPLUNK_HOME,'var','log','splunk','splunk_app_stream.log')
logger = logging.getLogger('vocabs_installer')
logger.setLevel(logging.DEBUG)
handler = logging.handlers.RotatingFileHandler(INSTALLER_LOG_FILENAME, maxBytes=1024000, backupCount=5)
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
handler.setLevel(logging.DEBUG)
logger.addHandler(handler)

if __name__ == '__main__':
    session_key = sys.stdin.readlines()[0].strip()

    if session_key:
        netflow_utils.pull_vendor_apps_configuration(session_key)
