import os.path as op
import sys

bin_path = op.dirname(op.abspath(__file__))
if bin_path not in sys.path:
    sys.path.append(bin_path)

import json

import splunk.rest

import splunk_app_stream.utils.stream_utils as stream_utils
import splunk_app_stream.models.user as user


logger = stream_utils.setup_logger('rest_users')

# REST Handler class to handle the API requests related to Users from clients using the Splunk Session key
# to authenticate. This class acts as a proxy to the user model class. Currently only supports to get and set tour attribute of user.
#All of the business logic is contained in the model class.

class Users(splunk.rest.BaseRestHandler):

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
            auth_success  = stream_utils.validate_streamfwd_auth(auth_key)
            if not auth_success:
                self.response.status = 401
                output = {}
                output['users'] = {'success': False, 'error': 'Unauthorized', 'status': 401}
                return output

        user_name = ''
        if ('tour' == self.pathParts[-1] or 'easysetup' == self.pathParts[-1]) and 'users' == self.pathParts[-3]:
            user_name = self.pathParts[-2]
            user_flag = self.pathParts[-1]
            if user_name == 'current':
                sessionKeyAuth = self.request['headers']['authorization'].replace("Splunk ", "")
                if sessionKeyAuth:
                    user_name = stream_utils.get_username(sessionKeyAuth)
                else:
                    user_name = stream_utils.get_username(sessionKey)
            logger.debug('get::user_name %s', user_name)
            result = user.User.get_user_flag(user_name, user_flag, sessionKey)
            
            if 'status' in result:
                self.response.status  = result['status']
            if self.response.status > 399:
                raise splunk.RESTException(self.response.status, result['error'])
            output = {}
            output['users'] = result
        else:
            raise splunk.RESTException(500, 'Internal error, bad request')

        return output
    
    def handle_POST(self):
        if 'authorization' in self.request['headers']:
            sessionKey = self.request['headers']['authorization'].replace("Splunk ", "")
            user_name = ''
            if ('tour' == self.pathParts[-1] or 'easysetup' == self.pathParts[-1]) and 'users' == self.pathParts[-3]:
                user_name = self.pathParts[-2]
                user_flag = self.pathParts[-1]
                if user_name == 'current':
                    user_name = stream_utils.get_username(sessionKey)
                result = {}
                try:
                    form_body = self.request['payload']
                    data = json.loads(form_body)
                    user_flag_visited = data['visited']
                    result = user.User.set_user_flag(user_name, user_flag, user_flag_visited, sessionKey)
                except Exception:
                    logger.exception("bad request")
                    output = {}
                    output['users'] = {'success': False, 'error': 'Internal error, bad request', 'status': 500}
                    raise splunk.RESTException(500, 'Internal error, bad request')

                if 'status' in result:
                    self.response.status  = result['status']
                if self.response.status > 399:
                    raise splunk.RESTException(self.response.status, result['error'])
                output = {}
                output['users'] = result
                logger.debug('save::result %s', result)
                # refresh cherrypy cache for apps metadata
                stream_utils.refresh_ping_cache()
                return output
            else:
                raise splunk.RESTException(500, 'Internal error, bad request')
        else:
            raise splunk.RESTException(401, "Unauthorized to perform POST or PUT operation")


    handle_PUT = handle_POST
