import os.path as op
import sys

bin_path = op.dirname(op.abspath(__file__))
if bin_path not in sys.path:
    sys.path.append(bin_path)

import json

import splunk
import splunk.rest

import splunk_app_stream.models.stream_forwarder_group
import splunk_app_stream.models.stream as stream
import splunk_app_stream.utils.stream_utils as stream_utils

logger = stream_utils.setup_logger('rest_stream_forwarder_groups')


# REST Handler class to handle the API requests related to Stream forwarder groups from clients using the Splunk Session key
# to authenticate. This class acts as a proxy to the stream model class. All of the business logic is contained in
# the model class.

class StreamForwarderGroups(splunk.rest.BaseRestHandler):

    def handle_GET(self):
        id = ''
        try:
            id = self.args['id']
            #because id is being passed in explicitly
            if id:
                self.args.pop('id')
        except:
            pass

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
                output['streamforwardergroups'] = {'success': False, 'error': 'Unauthorized', 'status': 401}
                return output

        queried_all_streams = stream.update_streams_cache(sessionKey)
 
        result = splunk_app_stream.models.stream_forwarder_group.StreamForwarderGroup.list(sessionKey, id, queried_all_streams, **self.args)
        if 'status' in result:
            self.response.status  = result['status']
        if self.response.status > 399:
            raise splunk.RESTException(self.response.status, result['error'])
        output = {}
        output['streamforwardergroups'] = result
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
                   
            stream.update_streams_cache(sessionKey)
            splunk_app_stream.models.stream_forwarder_group.init_stream_forwarder_groups(sessionKey)

            try:
                data = json.loads(form_body)
                result = splunk_app_stream.models.stream_forwarder_group.StreamForwarderGroup.save(data, id, None, sessionKey)
                # refresh cherrypy cache for apps metadata
                stream_utils.refresh_ping_cache()
            except Exception:
                logger.exception("failed to refresh ping cache")
                output = {}
                output['streamforwardergroups'] = {'success': False, 'error': 'Internal error, malformed payload in the request', 'status': 500}
                raise splunk.RESTException(500, 'Internal error, malformed payload in the request')

            if 'status' in result:
                self.response.status  = result['status']
            if self.response.status > 399:
                raise splunk.RESTException(self.response.status, result['error'])
            output = {}
            output['streamforwardergroups'] = result
            logger.debug("save::result %s", result)
            return output
        else:
            raise splunk.RESTException(401, "Unauthorized to perform POST or PUT operation")


    handle_PUT = handle_POST

    def handle_DELETE(self):
        if 'authorization' in self.request['headers']:
            sessionKey = self.request['headers']['authorization'].replace("Splunk ", "")

            id = ''
            try:
                id = self.args['id']
            except:
                pass
            result = splunk_app_stream.models.stream_forwarder_group.StreamForwarderGroup.delete(id, sessionKey)
            if 'status' in result:
                self.response.status  = result['status']
            if self.response.status > 399:
                raise splunk.RESTException(self.response.status, result['error'])
            output = {}
            output['streamforwardergroups'] = result
            logger.debug("delete::result %s", result)
            # refresh cherrypy cache for apps metadata
            stream_utils.refresh_ping_cache()
            return output
        else:
            raise splunk.RESTException(401, "Unauthorized to perform DELETE operation")
