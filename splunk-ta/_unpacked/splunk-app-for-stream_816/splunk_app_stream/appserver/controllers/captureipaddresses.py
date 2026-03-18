import sys

import cherrypy
import splunk.appserver.mrsparkle.controllers as controllers
from splunk.appserver.mrsparkle.lib.decorators import expose_page
from splunk.appserver.mrsparkle.lib.decorators import set_cache_level
from splunk.appserver.mrsparkle.lib.routes import route
from splunk.appserver.mrsparkle.lib.util import make_splunkhome_path

# if splunk_app_stream bin path is not present in the sys.path,
# then add the bin path to sys.path to load the python modules
bin_path = make_splunkhome_path(['etc', 'apps', 'splunk_app_stream', 'bin'])
if bin_path not in sys.path:
    sys.path.append(bin_path)

import splunk_app_stream.models.captureipaddress
import splunk_app_stream.utils.stream_utils as stream_utils
import splunk_app_stream.utils.stream_kvstore_utils as kv_utils


logger = stream_utils.setup_logger('captureipaddresses')
logger.info('starting splunk app stream .....')
if not kv_utils.is_splunkd_ready():
    logger.error("Exiting since splunkd is not ready")
else:
    logger.info("Initializing captureipaddress...")
    kv_utils.migrate_to_kv_store()
    splunk_app_stream.models.captureipaddress.initialize()

# Controller class to handle the API requests related to Capture IP Addresses. This class acts as a proxy to the
# captureipaddress model class. All of the business logic is contained in the model class.

class CaptureIpAddresses(controllers.BaseController):
    ''' CaptureIpAddresses Controller '''

    @route('/:id', methods=['GET'])
    @expose_page(must_login=False, methods=['GET'])
    @set_cache_level('never')
    def list(self, id=None, **kwargs):
        '''Return list of captureipaddresses including whiteList and blackList'''
        session_key = cherrypy.session.get('sessionKey')
        header_auth_key = cherrypy.request.headers.get('X-SPLUNK-APP-STREAM-KEY', '')
        if not session_key:
            auth_success = stream_utils.validate_streamfwd_auth(header_auth_key)
            if not auth_success:
                cherrypy.response.status = 401
                return None

        captureIpAddressesJsonList = splunk_app_stream.models.captureipaddress.CaptureIpAddress.list(id, session_key)
        return self.render_json(captureIpAddressesJsonList)

    @route('/:id', methods=['POST', 'PUT'])
    @expose_page(must_login=True, methods=['POST', 'PUT'])
    @set_cache_level('never')
    def save(self, id='', **params):
        '''Update posted captureipaddresses '''
        session_key = cherrypy.session.get('sessionKey')
        result = splunk_app_stream.models.captureipaddress.CaptureIpAddress.save(cherrypy.request.body.read().decode('utf-8'), id, session_key)
        if 'status' in result:
            cherrypy.response.status = result['status']
        return self.render_json(result)
