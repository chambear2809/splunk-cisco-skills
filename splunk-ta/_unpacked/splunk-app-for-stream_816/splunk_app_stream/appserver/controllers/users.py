import sys
import json

import cherrypy
import splunk.appserver.mrsparkle.controllers as controllers
from splunk.appserver.mrsparkle.lib.decorators import expose_page
from splunk.appserver.mrsparkle.lib.decorators import set_cache_level
from splunk.appserver.mrsparkle.lib.routes import route
from splunk.appserver.mrsparkle.lib.util import make_splunkhome_path

# STREAM-3375: if splunk_app_stream bin path is not present in the sys.path,
# then add it to sys.path to ensure python modules are loaded
bin_path = make_splunkhome_path(['etc', 'apps', 'splunk_app_stream', 'bin'])
if bin_path not in sys.path:
    sys.path.append(bin_path)

import splunk_app_stream.utils.stream_utils as stream_utils
import splunk_app_stream.utils.stream_kvstore_utils as kv_utils
import splunk_app_stream.models.user as user


logger = stream_utils.setup_logger('users')
if not kv_utils.is_splunkd_ready():
    logger.error("Exiting since splunkd is not ready")
else:
    user.init_users()

# Controller class to handle the API requests related to Users. Currently only supports setting/getting the tour attribute of a user.
#This class acts as a proxy to the user model class. All of the business logic is contained in the model class.

class Users(controllers.BaseController):
    """Users Controller """

    @route('/:user_name/:user_flag', methods=['GET'])
    @expose_page(must_login=True, methods=['GET'])
    @set_cache_level('never')
    def get_user_flag(self, user_name, user_flag, **kwargs):
        """Return tour property of username"""
        sessionKey = cherrypy.session.get('sessionKey')
        if user_name == 'current':
            user_name = stream_utils.get_username(sessionKey)
        result = {}
        if user_flag == 'tour' or user_flag == 'easysetup':
            result = user.User.get_user_flag(user_name, user_flag, sessionKey)
        else:
            return self.render_json({'success': False, 'error': 'Bad Request', 'status': 500})

        if 'status' in result:
            cherrypy.response.status = result['status']
        return self.render_json(result)


    @route('/:user_name/:user_flag', methods=['POST', 'PUT'])
    @expose_page(must_login=True, methods=['POST', 'PUT'])
    @set_cache_level('never')
    def set_user_flag(self, user_name, user_flag, **params):
        """Update tour property of the user """
        sessionKey = cherrypy.session.get('sessionKey')
        if user_name == 'current':
            user_name = stream_utils.get_username(sessionKey)
        # read POST data of type application/json
        try:
            json_dict = self.parse_json_payload()
            user_flag_visited = json_dict['visited']
        except Exception:
            logger.exception("invalid request")
            cherrypy.response.status = 400
            return self.render_json({'success': False, 'error': "Bad request", 'status': 400})
        result = {}
        if user_flag == 'tour' or user_flag == 'easysetup':
            result = user.User.set_user_flag(user_name, user_flag, user_flag_visited, sessionKey)
        else:
            return self.render_json({'success': False, 'error': 'Bad Request', 'status': 500})

        if 'status' in result:
            cherrypy.response.status = result['status']
        logger.debug('save::result %s', result)
        return self.render_json(result)
               

    def parse_json_payload(self):
        """Read request payload and parse it as JSON"""
        body = cherrypy.request.body.read()
        if not body:
            raise Exception('request payload empty')

        try:
            data = json.loads(body)
        except Exception:
            logger.exception("invalid json")
            raise Exception('could not parse JSON payload')
        return data
