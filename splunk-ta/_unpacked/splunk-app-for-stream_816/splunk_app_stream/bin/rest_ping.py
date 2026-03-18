import os.path as op
import sys

bin_path = op.dirname(op.abspath(__file__))
if bin_path not in sys.path:
    sys.path.append(bin_path)

import splunk.rest

import splunk_app_stream.utils.stream_utils as stream_utils
from splunk_app_stream.models.ping import Ping as MPing

logger = stream_utils.setup_logger('rest_ping')

# REST Handler class to handle the ping API requests from clients using the Splunk Session key to authenticate.

class Ping(splunk.rest.BaseRestHandler):

    def handle_GET(self):
        '''Return last update status and app version''' 
        sessionKey = None

        if 'systemAuth' in self.request and self.request['systemAuth']:
            sessionKey = self.request['systemAuth']
        else:
            sessionKey = self.sessionKey

        # check for auth key
        auth_key = None
        if 'systemAuth' in self.request:
            auth_key = stream_utils.extract_auth_key(self.request, self.args)
            auth_success  = stream_utils.validate_streamfwd_auth(auth_key)
            if not auth_success:
                self.response.status = 401
                output = {}
                output['ping'] = {'success': False, 'error': 'Unauthorized', 'status': 401}
                return output

        output = {}
        output['ping'] = MPing.ping(sessionKey)                   
        return output
