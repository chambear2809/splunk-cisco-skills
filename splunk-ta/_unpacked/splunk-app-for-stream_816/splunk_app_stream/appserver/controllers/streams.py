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

import splunk_app_stream.models.stream as stream
import splunk_app_stream.utils.stream_utils as stream_utils
import splunk_app_stream.utils.stream_kvstore_utils as kv_utils


logger = stream_utils.setup_logger('streams')
if not kv_utils.is_splunkd_ready():
    logger.error("Exiting since splunkd is not ready")
else:
    stream.init_date_last_updated()


# Controller class to handle the API requests related to Streams. This class acts as a proxy to the
# stream model class. All of the business logic is contained in the model class.

class Streams(controllers.BaseController):
    """Streams Controller """

    @route('/:id', methods=['GET'])
    @expose_page(must_login=False, methods=['GET'])
    @set_cache_level('never')
    def list(self, id='', **kwargs):
        """Return list of saved streams"""
        session_key = cherrypy.session.get('sessionKey')
        user_agent = cherrypy.request.headers.get('User-Agent', '').strip()
        kwargs['user_agent'] = user_agent
        header_auth_key = cherrypy.request.headers.get('X-SPLUNK-APP-STREAM-KEY', '')

        if not session_key:
            auth_success  = stream_utils.validate_streamfwd_auth(header_auth_key)
            if not auth_success:
                cherrypy.response.status = 401
                return None

        result = stream.Stream.list(session_key, id, **kwargs)
        if 'status' in result:
            cherrypy.response.status = result['status']
        return self.render_json(result)


    @route('/:id/:action', methods=['POST', 'PUT'])
    @expose_page(must_login=True, methods=['POST', 'PUT'])
    @set_cache_level('never')
    def save(self, id='', action='save', **params):
        """Update posted stream """
        session_key = cherrypy.session.get('sessionKey')
        user = stream_utils.get_username(session_key)
        if cherrypy.request.method == 'PUT' and action in ['enable', 'disable', 'statsOnly']:
            if not id:
                cherrypy.response.status = 400
                return self.render_json({'success': False, 'error': str("Invalid id specified")})
            else:
                try:
                    orig_stream = stream.Stream.save('', session_key, id, action, user, **params)
                    logger.debug("saved posted stream")
                    #logger.debug('save::result %s', orig_stream)
                except Exception:
                    logger.exception("failed to save stream. STATUS: 500")
                    cherrypy.response.status = 500
                    return self.render_json({'success': False, 'error': 'Bad Request', 'status': 500})
                return self.render_json(orig_stream)
        else:
            # read POST data of type application/json
            try:
                json_dict = self.parse_json_payload()
            except Exception:
                logger.exception("invalid request")
                cherrypy.response.status = 500
                return self.render_json({'success': False, 'error': 'Internal error, malformed payload in the request', 'status': 500})
            result = stream.Stream.save(json_dict, session_key, id, None, user, **params)
            result_status = ""
            if 'status' in result:
                cherrypy.response.status = result['status']
                result_status = result['status']
            logger.debug("Saved posted stream. STATUS: %s", result_status)
            #logger.debug('save::result %s', result)
            return self.render_json(result)


    @route('/:id', methods=['DELETE'])
    @expose_page(must_login=True, methods=['DELETE'])
    @set_cache_level('never')
    def delete(self, id='', **params):
        """delete posted stream """
        session_key = cherrypy.session.get('sessionKey')
        result = stream.Stream.delete(session_key, id)
        result_status = ""
        if 'status' in result:
            cherrypy.response.status = result['status']
            result_status = result['status']
        logger.debug("Deleted posted stream. STATUS: %s", result_status)
        #logger.debug('delete::result %s', result)
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
