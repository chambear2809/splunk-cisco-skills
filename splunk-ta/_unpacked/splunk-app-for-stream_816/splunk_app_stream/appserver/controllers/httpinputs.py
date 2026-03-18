import json
import sys

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


logger = stream_utils.setup_logger('httpinputs')

# Controller class to handle the API requests to get HttpInputs

class HttpInputs(controllers.BaseController):
    ''' HttpInputs Controller '''

    def get_tokens(self, session_key):
        '''Retrieves the list of http tokens'''
        uri = 'services/data/inputs/http'
        serverResponse, serverContent = splunk.rest.simpleRequest(
            util.make_url_internal(uri + '?output_mode=json&count=0'),
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
        tokens = []
        for entry in jsonResp['entry']:
            entry['content']['name'] = entry['name']
            tokens.append(entry['content'])
        return tokens

    def get_cloud_tokens(self, session_key):
        '''Retrieves the list of http tokens'''
        uri = 'services/dmc/config/inputs/-/http'
        serverResponse, serverContent = splunk.rest.simpleRequest(
            util.make_url_internal(uri + '?output_mode=json&count=0'),
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
        tokens = []
        for entry in jsonResp['entry']:
            entry['content']['name'] = "http://"+entry['name']
            if entry['content']['disabled']=="false":
                entry['content']['disabled'] = False
            elif entry['content']['disabled']=="true":
                entry['content']['disabled'] = True
            tokens.append(entry['content'])
        return tokens

    def get_http_inputs(self, session_key):
        '''Retrieves the list of all http inputs'''
        uri = 'services/data/inputs/http/http'
        serverResponse, serverContent = splunk.rest.simpleRequest(
            util.make_url_internal(uri + '?output_mode=json&count=0'),
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
        httpinputs = jsonResp['entry'][0]['content']
        if stream_utils.isClassicCloudInstance():
            httpinputs['tokens'] = self.get_cloud_tokens(session_key)
        else:
            httpinputs['tokens'] = self.get_tokens(session_key)
        version = jsonResp['generator']['version']
        httpinputs['version'] = version
        return self.render_json(httpinputs)

    @route('/', methods=['GET'])
    @expose_page(must_login=True, methods=['GET'])
    @set_cache_level('never')
    def list(self, **params):
        '''Proxies to splunkd REST API that queries the current status of hec configuration'''
        try:
            session_key = cherrypy.session.get('sessionKey')
            return self.get_http_inputs(session_key)
        except Exception:
            logger.exception("failed to list HEC inputs")
            cherrypy.response.status = 500
            return self.render_json({'success': False, 'error': 'Internal error', 'status': 500})
