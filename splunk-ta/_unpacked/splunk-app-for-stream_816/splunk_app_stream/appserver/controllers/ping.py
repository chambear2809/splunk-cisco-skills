import sys

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
from splunk_app_stream.models.ping import Ping as MPing


logger = stream_utils.setup_logger('ping')

# API versions of each of the splunk app stream controllers
# increment this version by 1 when the controllers change the api/format/schema of the response
# clients conusimng splunk app stream REST APIs to use /ping to get the API versions 
streams_api_version = 1
captureipaddresses_api_version = 1
httpinputs_api_version = 1
indexers_api_version = 1
ping_api_version  = 1
streamforwardergroups_api_version = 1
users_api_version = 1
vocabularies_api_version = 1


# Controller class to handle the ping API requests. Acts as a proxy to the ping model class.

class Ping(controllers.BaseController):
    ''' Ping Controller '''

    @route('/', methods=['GET'])
    @expose_page(must_login=False, methods=['GET'])
    @set_cache_level('never')
    def ping(self, **kwargs):
        '''Return last update status and app version''' 
        session_key = cherrypy.session.get('sessionKey')
        header_auth_key = cherrypy.request.headers.get('X-SPLUNK-APP-STREAM-KEY', '')
        if not header_auth_key:
            header_auth_key=kwargs.get('X-SPLUNK-APP-STREAM-KEY', '')
        if not session_key:
            auth_success  = stream_utils.validate_streamfwd_auth(header_auth_key)
            if not auth_success:
                cherrypy.response.status = 401
                return None

        refresh = kwargs.get('refresh', '')
        if refresh == 'true':
        	result = MPing.ping('', True)
        else:
        	result = MPing.ping()  
        # add the versions of the controllers 
        result['api_versions'] = {}
        result['api_versions']['streams'] = streams_api_version   
        result['api_versions']['captureipaddresses'] = captureipaddresses_api_version
        result['api_versions']['httpinputs'] = httpinputs_api_version
        result['api_versions']['indexers'] = indexers_api_version
        result['api_versions']['ping'] = ping_api_version 
        result['api_versions']['streamforwardergroups'] = streamforwardergroups_api_version
        result['api_versions']['users'] = users_api_version
        result['api_versions']['vocabularies'] = vocabularies_api_version      

        return self.render_json(result)
