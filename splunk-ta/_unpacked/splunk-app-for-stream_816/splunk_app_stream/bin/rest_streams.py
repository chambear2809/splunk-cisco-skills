import os.path as op
import sys

bin_path = op.dirname(op.abspath(__file__))
if bin_path not in sys.path:
    sys.path.append(bin_path)

import json

import splunk
import splunk.rest

import splunk_app_stream.models.stream_forwarder_group
import splunk_app_stream.models.stream 
import splunk_app_stream.utils.stream_utils as stream_utils


logger = stream_utils.setup_logger('rest_streams')


# REST Handler class to handle the API requests related to Streams from clients using the Splunk Session key
# to authenticate. This class acts as a proxy to the stream model class. All of the business logic is contained in
# the model class.

class Streams(splunk.rest.BaseRestHandler):

    def handle_GET(self):
        id = ''
        try:
            id = self.args['id']
            del self.args['id']
        except:
            pass

        sessionKey = None

        if 'systemAuth' in self.request and self.request['systemAuth']:
            sessionKey = self.request['systemAuth']
        else:
            sessionKey = self.sessionKey

        if 'user-agent' in self.request['headers']:
            self.args['user_agent'] = self.request['headers']['user-agent']

        # check for auth key
        auth_key = None
        if 'systemAuth' in self.request:
            auth_key = stream_utils.extract_auth_key(self.request, self.args)
            auth_success = stream_utils.validate_streamfwd_auth(auth_key)
            if not auth_success:
                self.response.status = 401
                output = {}
                output['streams'] = {'success': False, 'error': 'Unauthorized', 'status': 401}
                return output

        #Need to do this since splunkd REST controllers are reloaded for every request and is not persisted
        splunk_app_stream.models.stream.update_streams_cache(sessionKey)

        result = splunk_app_stream.models.stream.Stream.list(sessionKey, id, **self.args)      
        if 'status' in result:
            self.response.status  = result['status']
        if self.response.status > 399:
            raise splunk.RESTException(self.response.status, result['error'])
        output = {}
        output['streams'] = result
        return output
    
    def handle_POST(self):
        if 'authorization' in self.request['headers']:
            sessionKey = self.request['headers']['authorization'].replace("Splunk ", "")
            form_body = self.request['payload']
            id = ''
            try:
                id = self.args['id']
                del self.args['id']
            except:
                pass

            splunk_app_stream.models.stream.update_streams_cache(sessionKey)
           
            action = ''
            try:
                action = self.args['action']
                del self.args['action']
            except:
                pass
            if action in ['enable', 'disable', 'statsOnly']:
                if not id:
                    self.response.status = 400
                    raise splunk.RESTException(self.response.status, "Invalid id specified")
                else:
                    result = splunk_app_stream.models.stream.Stream.save('', sessionKey, id, action, None, **self.args)
                    if 'status' in result:
                        self.response.status  = result['status']
                    if self.response.status > 399:
                        raise splunk.RESTException(self.response.status, result['error'])
                    output = {}
                    output['streams'] = result
                    logger.debug("save::result %s", result)
                    # refresh cherrypy cache for apps metadata
                    stream_utils.refresh_ping_cache()
                    return output

            try:
                data = json.loads(form_body)
                result = splunk_app_stream.models.stream.Stream.save(data, sessionKey, id, None, None, **self.args)
                # refresh cherrypy cache for apps metadata
                stream_utils.refresh_ping_cache()
            except Exception:
                logger.exception("failed to refresh ping cache")
                output = {}
                output['streams'] = {'success': False, 'error': 'Internal error, malformed payload in the request', 'status': 500}
                raise splunk.RESTException(500, 'Internal error, malformed payload in the request')

            if 'status' in result:
                self.response.status  = result['status']
            if self.response.status > 399:
                raise splunk.RESTException(self.response.status, result['error'])
            output = {}
            output['streams'] = result
            logger.debug("save::result %s", result)
            return output
        else:
            raise splunk.RESTException(401, "Unauthorized to perform POST or PUT operation")

    handle_PUT = handle_POST

    def handle_DELETE(self):
        if 'authorization' in self.request['headers']:
            sessionKey = self.request['headers']['authorization'].replace("Splunk ", "")
            id = ''
            netflow_script = False 
            try:
                id = self.args['id']
            except:
                pass

            try:
                netflow_script = self.args['from_netflow_script']
            except:
                pass
            
            splunk_app_stream.models.stream.update_streams_cache(sessionKey)
            result = splunk_app_stream.models.stream.Stream.delete(sessionKey, id, netflow_script)
            if 'status' in result:
                self.response.status  = result['status']
            if self.response.status > 399:
                raise splunk.RESTException(self.response.status, result['error'])
            output = {}
            output['streams'] = result
            logger.debug("delete::result %s", result)
            # refresh cherrypy cache for apps metadata
            stream_utils.refresh_ping_cache()
            return output
        else:
            raise splunk.RESTException(401, "Unauthorized to perform DELETE operation")
