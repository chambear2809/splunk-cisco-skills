import os.path as op
import sys

bin_path = op.dirname(op.abspath(__file__))
if bin_path not in sys.path:
    sys.path.append(bin_path)

import json

import splunk
import splunk.rest
import splunk.appserver.mrsparkle.lib.util as util

import splunk_app_stream.utils.stream_utils as stream_utils

logger = stream_utils.setup_logger('rest_indexers')

# REST Handler class to handle the API requests related to Indexers from clients using the Splunk Session key
# to authenticate.

class Indexers(splunk.rest.BaseRestHandler):

    def handle_GET(self):
        sessionKey = None

        if 'systemAuth' in self.request and self.request['systemAuth']:
            sessionKey = self.request['systemAuth']
        else:
            sessionKey = self.sessionKey

        # check for auth key
        auth_key = None
        if 'systemAuth' in self.request:
            auth_key = stream_utils.extract_auth_key(self.request, self.args)
            auth_success = stream_utils.validate_streamfwd_auth(auth_key)
            if not auth_success:
                self.response.status = 401
                output = {}
                output['indexers'] = {'success': False, 'error': 'Unauthorized', 'status': 401}
                return output
                
        output = {}
        try:
            # Get indexers list through Splunk REST API
            uri = '/services/search/distributed/peers?output_mode=json'
            serverResponse, serverContent = splunk.rest.simpleRequest(
                util.make_url_internal(uri),
                sessionKey,
                postargs=None,
                method='GET',
                raiseAllErrors=True,
                proxyMode=False,
                rawResult=None,
                jsonargs=None,
                timeout=splunk.rest.SPLUNKD_CONNECTION_TIMEOUT
            )

            jsonobj = json.loads(serverContent)
            output['indexers'] = jsonobj['entry']

        except Exception:
            logger.exception("failed to get indexers peer")
            raise splunk.RESTException(500, 'Internal error, failed to get indexers peer')
       
        return output
