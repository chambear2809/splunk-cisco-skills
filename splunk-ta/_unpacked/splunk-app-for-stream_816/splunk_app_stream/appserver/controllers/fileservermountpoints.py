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

import splunk_app_stream.models.file_server_mount_point
import splunk_app_stream.utils.stream_utils as stream_utils
import splunk_app_stream.utils.stream_kvstore_utils as kv_utils


logger = stream_utils.setup_logger('fileservermountpoints')
if not kv_utils.is_splunkd_ready():
    logger.error("Exiting since splunkd is not ready")
else:
    logger.info("Initializing fileservermountpoints...")
    splunk_app_stream.models.file_server_mount_point.init_file_server_mount_points()

## Controller class to handle the API requests related to file server mount points. This class acts as a proxy to the
## file_server_mount_point model class.

class FileServerMountPoints(controllers.BaseController):
    """ File Server Mount Points Controller """

    @route('/:id', methods=['GET'])
    @expose_page(must_login=True, methods=['GET'])
    @set_cache_level('never')
    def list(self, id='', **kwargs):
        """Return list of saved file server mount points"""
        session_key = cherrypy.session.get('sessionKey')
        header_auth_key = cherrypy.request.headers.get('X-SPLUNK-APP-STREAM-KEY', '')
        if not session_key:
            auth_success = stream_utils.validate_streamfwd_auth(header_auth_key)
            if not auth_success:
                cherrypy.response.status = 401
                return None
        result = splunk_app_stream.models.file_server_mount_point.FileServerMountPoint.list(session_key, id, **kwargs)
        if 'status' in result:
            cherrypy.response.status = result['status']
        return self.render_json(result)


    @route('/:id', methods=['POST', 'PUT'])
    @expose_page(must_login=True, methods=['POST', 'PUT'])
    @set_cache_level('never')
    def save(self, id='', **params):
        """ Create or Update File Server Mount Point """
        session_key = cherrypy.session.get('sessionKey')

        # read POST data of type application/json
        try:
            json_dict = self.parse_json_payload()
        except Exception:
            logger.exception("failed to save file server mount point")
            cherrypy.response.status = 500
            return self.render_json({'success': False, 'error': 'Internal error, malformed payload in the request', 'status': 500})

        logger.debug('FileServerMountPoints::save:id = %s, json_dict = %s', id, json_dict)

        if id:
            # update the item specified in the URI
            result = splunk_app_stream.models.file_server_mount_point.FileServerMountPoint.update(json_dict, id, session_key, **params)
        else:
            # no item was specified in the URI, so create a new item
            result = splunk_app_stream.models.file_server_mount_point.FileServerMountPoint.create(json_dict, session_key, **params)

        if 'status' in result:
            cherrypy.response.status = result['status']
        logger.debug('FileServerMountPoints::save::result %s', result)
        return self.render_json(result)


    @route('/:id', methods=['DELETE'])
    @expose_page(must_login=True, methods=['DELETE'])
    @set_cache_level('never')
    def delete(self, id='', **params):
        """delete file server mount point"""
        session_key = cherrypy.session.get('sessionKey')
        result = splunk_app_stream.models.file_server_mount_point.FileServerMountPoint.delete(id, session_key, **params)
        if 'status' in result:
            cherrypy.response.status = result['status']
        logger.debug('delete::result %s', result)
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
