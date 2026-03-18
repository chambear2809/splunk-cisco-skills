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

logger = stream_utils.setup_logger('rest_httpinputs')

# REST Handler class to handle the API requests related to Indexers from clients using the Splunk Session key
# to authenticate. This class acts as a proxy to the stream model class.  All of the business logic is contained in
# the model class.

class Httpinputs(splunk.rest.BaseRestHandler):

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
                output['httpinputs'] = {'success': False, 'error': 'Unauthorized', 'status': 401}
                return output

        output = {}
        try:
            inputs = []

            if stream_utils.isClassicCloudInstance():
                uri = '/services/dmc/config/inputs/-/http?output_mode=json&count=0'
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

                if serverResponse['status'] == '200':
                    jsonResp = json.loads(serverContent)
                    output['httpinputs'] = jsonResp['entry']
            else:

                # Get list of HEC inputs
                uri = '/services/data/inputs/http?output_mode=json&count=0'
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

                if serverResponse['status'] == '200':
                    jsonResp = json.loads(serverContent)
                    output['httpinputs'] = jsonResp['entry']

        except Exception:
            logger.exception("failed to get HEC inputs")
            raise splunk.RESTException(500, 'Internal error, failed to get HEC inputs')

        return output


class HttpinputsConfigs(splunk.rest.BaseRestHandler):

    def handle_GET(self):
        sessionKey = None

        if 'systemAuth' in self.request and self.request['systemAuth']:
            sessionKey = self.request['systemAuth']
        else:
            sessionKey = self.sessionKey

        output = {}
        # check for auth key
        auth_key = None
        if 'systemAuth' in self.request:
            auth_key = stream_utils.extract_auth_key(self.request, self.args)
            auth_success  = stream_utils.validate_streamfwd_auth(auth_key)
            if not auth_success:
                self.response.status = 401
                output = {}
                output['httpinputs'] = {'success': False, 'error': 'Unauthorized', 'status': 401}
                return output

        try:
            inputs = []

            # Get list of HEC inputs
            uri = '/services/data/inputs/http/http?output_mode=json&count=0'
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

            if serverResponse['status'] == '200':
                jsonResp = json.loads(serverContent)
                config = jsonResp['entry'][0]['content']

            output['httpinputsconfigs'] = config

        except Exception:
            logger.exception("failed to get HEC config")
            raise splunk.RESTException(500, 'Internal error, failed to get HEC config')
       
        return output
