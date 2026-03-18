import os.path as op
import sys

bin_path = op.dirname(op.abspath(__file__))
if bin_path not in sys.path:
    sys.path.append(bin_path)

import splunk.rest

import splunk_app_stream.models.captureipaddress
import splunk_app_stream.utils.stream_utils as stream_utils


logger = stream_utils.setup_logger('rest_captureipaddresses')

# REST Handler class to handle the API requests related to Capture IP Addresses from clients using the Splunk Session key
# to authenticate. This class acts as a proxy to the captureipaddress model class. All of the business logic is
# contained in the model class.

class CaptureIpAddresses(splunk.rest.BaseRestHandler):

    def handle_GET(self):
        '''Return list of vocabularies'''
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
                output['captureipaddresses'] = {'success': False, 'error': 'Unauthorized', 'status': 401}
                return output

        id = None
        try:
            id = self.args['id']
        except:
            pass
        output = {}
        output['captureipaddresses'] = splunk_app_stream.models.captureipaddress.CaptureIpAddress.list(id, sessionKey)
        return output

    def handle_POST(self):
        if 'authorization' in self.request['headers']:
            sessionKey = self.request['headers']['authorization'].replace("Splunk ", "")
            form_body = self.request['payload']
            id = ''
            try:
                id = self.args['id']
            except:
                pass
            result = splunk_app_stream.models.captureipaddress.CaptureIpAddress.save(form_body, id, sessionKey)
            if 'status' in result:
                self.response.status  = result['status']
            if self.response.status > 399:
                raise splunk.RESTException(self.response.status, result['error'])
            output = {}
            output['captureipaddresses'] = result
            logger.debug('save::result %s', result)
            # refresh cherrypy cache for apps metadata
            stream_utils.refresh_ping_cache()
            return output
        else:
            raise splunk.RESTException(401, "Unauthorized to perform POST or PUT operation")

    handle_PUT = handle_POST
