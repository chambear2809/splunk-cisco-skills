import os.path as op
import sys

bin_path = op.dirname(op.abspath(__file__))
if bin_path not in sys.path:
    sys.path.append(bin_path)

import splunk.rest

import splunk_app_stream.utils.stream_utils as stream_utils
import splunk_app_stream.utils.stream_kvstore_utils as kv_utils

logger = stream_utils.setup_logger('rest_kvstore_status')

# REST Handler class to get the KVStore status. This is used by Cherrypy controllers to get the kvstore status without a session key

class KVStoreStatus(splunk.rest.BaseRestHandler):

    def handle_GET(self):
        '''Return kvstore status''' 
        output = {}
        output['kvStoreStatus'] = 'unknown' 
        sessionKey = None

        if 'systemAuth' in self.request and self.request['systemAuth']:
            sessionKey = self.request['systemAuth']
        else:
            sessionKey = self.sessionKey

        if sessionKey:
            output['kvStoreStatus'] = kv_utils.get_kv_store_status(sessionKey)
                          
        return output
