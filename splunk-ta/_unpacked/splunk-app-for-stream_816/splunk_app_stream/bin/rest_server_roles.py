import os.path as op
import sys

bin_path = op.dirname(op.abspath(__file__))
if bin_path not in sys.path:
    sys.path.append(bin_path)

import splunk.rest

import splunk_app_stream.utils.stream_utils as stream_utils
import splunk_app_stream.utils.stream_kvstore_utils as kv_utils

logger = stream_utils.setup_logger('rest_server_roles')

# REST Handler class to get the server roles. This is used by Cherrypy controllers to get the server roles without a session key

class ServerRoles(splunk.rest.BaseRestHandler):

    def handle_GET(self):
        '''Return server roles''' 
        output = {}
        output['serverRoles'] = None
        sessionKey = None

        if 'systemAuth' in self.request and self.request['systemAuth']:
            sessionKey = self.request['systemAuth']
        else:
            sessionKey = self.sessionKey

        if sessionKey:
            output['serverRoles'] = kv_utils.get_server_roles(sessionKey)
                          
        return output
