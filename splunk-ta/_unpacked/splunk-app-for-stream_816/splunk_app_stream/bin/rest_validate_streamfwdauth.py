import os.path as op
import sys

bin_path = op.dirname(op.abspath(__file__))
if bin_path not in sys.path:
    sys.path.append(bin_path)

import base64
import os

import splunk
import splunk.appserver.mrsparkle.lib.util as util

from splunk_app_stream.models.streamfwdauth import StreamForwarderAuth
import splunk_app_stream.utils.stream_utils as stream_utils

logger = stream_utils.setup_logger('rest_validate_streamfwdauth')

# REST Handler class to handle the API requests related to Stream Forwarder Authentication from clients using
# the Splunk Session key to authenticate. This class acts as a proxy to the streamfwdauth model class. All of
# the business logic is contained in the model class.

class ValidateStreamfwdAuth(splunk.rest.BaseRestHandler):

    def handle_GET(self):
        sessionKey = None
        is_system_auth = False
        output = {}
        if 'systemAuth' in self.request and self.request['systemAuth']:
            auth_enabled = False
            auth_key = ""
            header_auth_key = ""
            sessionKey = self.request['systemAuth']
            if 'auth_key' in self.args:
                header_auth_key =  self.args['auth_key']
            # check the temp shared key file first
            shared_key_file = os.path.join(util.get_apps_dir(), 'splunk_app_stream', 'local', 'stream_shared_key')
            try:
                shared_auth_key = open(shared_key_file, 'r').read()
            except:
                shared_auth_key = ""
            jsonResp = StreamForwarderAuth.get(sessionKey)
            if 'enabled' in jsonResp:
                auth_enabled = jsonResp["enabled"]
            if 'authKey' in jsonResp:                
                auth_key = jsonResp["authKey"]
            
            # first check if it matches the shared_key stored in file for internal splunkd REST handlers
            if shared_auth_key and auth_enabled and header_auth_key == shared_auth_key:
                output['streamfwdauth'] = True
                return output
            elif auth_enabled:  
                try:
                    decoded_auth=base64.standard_b64decode(header_auth_key)
                    auth_string=decoded_auth.decode('utf-8')
                    if auth_string != auth_key:
                        output['streamfwdauth'] = False
                        return output
                except Exception:
                    logger.exception("Error decoding base64 auth key")
                    output['streamfwdauth'] = False
                    return output
              
        output['streamfwdauth'] = True
        return output
