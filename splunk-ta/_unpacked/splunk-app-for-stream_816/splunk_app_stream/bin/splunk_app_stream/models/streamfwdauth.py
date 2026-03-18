import os
import re

import splunk.appserver.mrsparkle.lib.util as util

import splunk_app_stream.utils.stream_utils as stream_utils
import splunk_app_stream.utils.stream_kvstore_utils as kv_utils
from splunk_app_stream.models.ping import Ping

logger = stream_utils.setup_logger('streamfwdauth')

# Last updated time used to refresh cache
dateLastUpdated = 0

streamfwd_auth_file = os.path.join(util.get_apps_dir(), 'splunk_app_stream', 'local', 'streamfwdauth')
streamfwd_auth_kv_store_with_session_key_uri = kv_utils.misc_kv_store_uri + '/streamfwdauth'

def init_streamfwdauth(sessionKey=None):
    global dateLastUpdated
    try:
        pingData = Ping.ping(sessionKey)
        if pingData['dateLastUpdated'] > dateLastUpdated:
            logger.info("cacheDateLastUpdated::%d appsDateLastUpdated::%d", dateLastUpdated, pingData['dateLastUpdated'])
            dateLastUpdated = pingData['dateLastUpdated']
    except Exception:
        # Exception happens as appsMeta file is in the process of getting written to.
        # Do Nothing and return existing cache.
        logger.exception("failed to update streamfwd auth")

def create_streamfwdauth_data(enabled=False, authKey='', kvstore=False):
    data = {}
    if kvstore:
        data['id'] = 'streamfwdauth'
        data['_key'] = 'streamfwdauth'
    data['enabled'] = enabled
    data['authKey'] = authKey
    return data

def is_valid_streamfwd_auth(enabled, authKey):
    validChars = re.compile(r"^[0-9A-z@%+/'!#$^?:,(){}\[\]~`\-_]*$")
    if (enabled and len(authKey) == 0) or not validChars.match(authKey):
        return False
    return True

class StreamForwarderAuth:

    @staticmethod
    def get(sessionKey=None):
        try:
            if sessionKey:
                init_streamfwdauth(sessionKey)
                if kv_utils.is_kv_store_supported_in_splunk(sessionKey):
                    streamfwd_auth = kv_utils.read_from_kv_store_coll(streamfwd_auth_kv_store_with_session_key_uri, sessionKey)
                    if not streamfwd_auth:
                        return create_streamfwdauth_data(True, stream_utils.get_util_internal_shared_key())
                    return streamfwd_auth
                else:
                    streamfwd_auth = stream_utils.readAsJson(streamfwd_auth_file)
                    if streamfwd_auth == 'NotFound':
                        return create_streamfwdauth_data(True, stream_utils.get_util_internal_shared_key())
                    return streamfwd_auth
            else:
                return {'success': False, 'error': 'Unauthorized Access', 'status': 401}
        except Exception :
            logger.exception("failed to get streamfwd auth")

    @staticmethod
    def save(enabled=False, authKey='', sessionKey=None):
        try:
            if sessionKey:
                init_streamfwdauth(sessionKey)
                authKey = authKey.strip()

                if not is_valid_streamfwd_auth(enabled, authKey):
                    return {'success': False, 'error': 'Bad Request, Invalid stream forwarder auth configuration', 'status': 400}

                if kv_utils.is_kv_store_supported_in_splunk(sessionKey):
                    kv_utils.update_kv_store_apps_meta(sessionKey)
                    data = create_streamfwdauth_data(enabled, authKey, True)
                    if not kv_utils.save_to_kv_store(kv_utils.misc_kv_store_uri, 'streamfwdauth', data, sessionKey):
                        kv_utils.save_to_kv_store(kv_utils.misc_kv_store_uri, None, data, sessionKey)
                else:
                    data = create_streamfwdauth_data(enabled, authKey)
                    stream_utils.writeAsJson(os.path.join(streamfwd_auth_file), data)

                return data
            else:
                return {'success': False, 'error': 'Unauthorized Access', 'status': 401}
        except Exception:
            logger.exception("failed to save streamfwd auth")
