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

import splunk_app_stream.models.stream_forwarder_group
import splunk_app_stream.utils.stream_utils as stream_utils
import splunk_app_stream.utils.stream_kvstore_utils as kv_utils
import splunk_app_stream.models.stream as stream


logger = stream_utils.setup_logger('streamforwardergroups')

if not kv_utils.is_splunkd_ready():
    logger.error("Exiting since splunkd is not ready")
else:
    logger.info("Initializing streamforwardergroups...")
#    splunk_app_stream.models.stream_forwarder_group.init_date_last_updated()
    stream.init_streams_collection()
#    splunk_app_stream.models.stream_forwarder_group.init_stream_forwarder_groups()

# Controller class to handle the API requests related to Stream Forwarder Groups. This class acts as a proxy to the
# stream forwarder group model class. All of the business logic is contained in the model class.

class StreamForwarderGroups(controllers.BaseController):
    """Stream Forwarder Groups Controller """

    @route('/:id', methods=['GET'])
    @expose_page(must_login=False, methods=['GET'])
    @set_cache_level('never')
    def list(self, id='', **kwargs):
        """Return list of saved stream forwarder groups"""
        session_key = cherrypy.session.get('sessionKey')
        header_auth_key = cherrypy.request.headers.get('X-SPLUNK-APP-STREAM-KEY', '')
        if not session_key:
            auth_success = stream_utils.validate_streamfwd_auth(header_auth_key)
            if not auth_success:
                cherrypy.response.status = 401
                return None
        stream.update_streams_cache(session_key)
        result = splunk_app_stream.models.stream_forwarder_group.StreamForwarderGroup.list(session_key, id, **kwargs)
        if 'status' in result:
            cherrypy.response.status = result['status']
        return self.render_json(result)


    @route('/:id', methods=['POST', 'PUT'])
    @expose_page(must_login=True, methods=['POST', 'PUT'])
    @set_cache_level('never')
    def save(self, id='', **params):
        """Update posted stream forwarder group """
        session_key = cherrypy.session.get('sessionKey')
        user = stream_utils.get_username(session_key)
        # read POST data of type application/json
        try:
            json_dict = self.parse_json_payload()
        except Exception:
            logger.exception("invalid request")
            cherrypy.response.status = 500
            return self.render_json({'success': False, 'error': 'Internal error, malformed payload in the request', 'status': 500})
        result = splunk_app_stream.models.stream_forwarder_group.StreamForwarderGroup.save(json_dict, id, user, session_key)
        result_status = ""
        if 'status' in result:
            cherrypy.response.status = result['status']
            result_status = result['status']
        #logger.debug('save::result %s', result)
        logger.debug("Saved posted stream forwarder group. STATUS: %s", result_status)
        return self.render_json(result)


    @route('/:id', methods=['DELETE'])
    @expose_page(must_login=True, methods=['DELETE'])
    @set_cache_level('never')
    def delete(self, id='', **params):
        """delete posted stream forwarder group"""
        session_key = cherrypy.session.get('sessionKey')
        result = splunk_app_stream.models.stream_forwarder_group.StreamForwarderGroup.delete(id, session_key)
        result_status = ""
        if 'status' in result:
            cherrypy.response.status = result['status']
            result_status = result['status']
        #logger.debug('delete::result %s', result)
        logger.debug("Deleted posted stream forwarder group. STATUS: %s", result_status)
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
