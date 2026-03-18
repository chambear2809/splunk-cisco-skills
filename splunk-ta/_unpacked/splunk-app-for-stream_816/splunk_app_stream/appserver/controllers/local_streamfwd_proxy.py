import sys
import json

import cherrypy
import splunk
import splunk.appserver.mrsparkle.controllers as controllers
import splunk.appserver.mrsparkle.lib.util as util
from splunk.appserver.mrsparkle.lib.decorators import expose_page
from splunk.appserver.mrsparkle.lib.decorators import set_cache_level
from splunk.appserver.mrsparkle.lib.routes import route

# STREAM-3375: if splunk_app_stream bin path is not present in the sys.path,
# then add it to sys.path to ensure python modules are loaded
bin_path = util.make_splunkhome_path(['etc', 'apps', 'splunk_app_stream', 'bin'])
if bin_path not in sys.path:
    sys.path.append(bin_path)

import splunk_app_stream.utils.stream_utils as stream_utils


logger = stream_utils.setup_logger('local_streamforwarder_proxy')

# Controller class to handle the API requests to get/set status of the local Splunk_TA_stream modular input 

class LocalStreamForwarderProxy(controllers.BaseController):
    ''' LocalStreamForwarderProxy Controller '''


    def get_status(self, session_key):
        '''Retrieves the status of local Splunk_TA_stream modular input'''
        uri = 'services/data/inputs/streamfwd/'
        serverResponse, serverContent = splunk.rest.simpleRequest(
            util.make_url_internal(uri + '?output_mode=json'),
            sessionKey=session_key,
            postargs=None,
            method='GET',
            raiseAllErrors=True,
            proxyMode=False,
            rawResult=None,
            jsonargs=None,
            timeout=splunk.rest.SPLUNKD_CONNECTION_TIMEOUT
            )
        jsonResp = json.loads(serverContent)
        return self.render_json(jsonResp["entry"][0]["content"])

    def set_disabled(self, session_key, disabled):
        '''Sets the disabled state of the local Splunk_TA_stream modular input'''
        logger.info("set_disabled=%s", disabled)
        uri = 'servicesNS/nobody/Splunk_TA_stream/data/inputs/streamfwd/streamfwd/'
        if disabled == "0":
            uri = uri + 'enable'
        else:
            uri = uri + 'disable'
        serverResponse, serverContent = splunk.rest.simpleRequest(
                    util.make_url_internal(uri),
                    session_key,
                    postargs=None,
                    method='POST',
                    raiseAllErrors=True,
                    proxyMode=False,
                    rawResult=None,
                    jsonargs=None,
                    timeout=splunk.rest.SPLUNKD_CONNECTION_TIMEOUT
                )

 
    def reload(self, session_key):
        '''Reloads local Splunk_TA_Stream modular input'''
        uri = 'services/data/inputs/streamfwd/_reload'
        serverResponse, serverContent = splunk.rest.simpleRequest(
            util.make_url_internal(uri + '?output_mode=json'),
            sessionKey=session_key,
            postargs=None,
            method='GET',
            raiseAllErrors=True,
            proxyMode=False,
            rawResult=None,
            jsonargs=None,
            timeout=splunk.rest.SPLUNKD_CONNECTION_TIMEOUT
            )

    @route('/', methods=['GET'])
    @expose_page(must_login=True, methods=['GET'])
    @set_cache_level('never')
    def list(self, **params):
        '''Proxies to splunkd REST API that queries the current status of local Splunk_TA_Stream instance'''
        try:
            session_key = cherrypy.session.get('sessionKey')
            return self.get_status(session_key)
        except Exception:
            logger.exception("failed to list status")
            cherrypy.response.status = 500
            return self.render_json({'success': False, 'error': 'Internal error', 'status': 500})

        
    @route('/:id', methods=['POST', 'PUT'])
    @expose_page(must_login=True, methods=['POST', 'PUT'])
    @set_cache_level('never')
    def save(self, id='', **params):
        try:
            session_key = cherrypy.session.get('sessionKey')
            request_body = json.loads(cherrypy.request.body.read())

            if ('disabled' in request_body):
                self.set_disabled(session_key, request_body["disabled"])
            else:
                self.reload(session_key)

            return self.get_status(session_key)
        except Exception:
            logger.exception("failed to handle post request")
            cherrypy.response.status = 500
            return self.render_json({'success': False, 'error': 'Internal error', 'status': 500})


