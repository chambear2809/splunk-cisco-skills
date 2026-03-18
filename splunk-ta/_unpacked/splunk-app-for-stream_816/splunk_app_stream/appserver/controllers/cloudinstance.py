import sys

import cherrypy
import splunk.appserver.mrsparkle.controllers as controllers
from splunk.appserver.mrsparkle.lib.routes import route
from splunk.appserver.mrsparkle.lib.decorators import expose_page
from splunk.appserver.mrsparkle.lib.decorators import set_cache_level
from splunk.appserver.mrsparkle.lib.util import make_splunkhome_path

# if splunk_app_stream bin path is not present in the sys.path,
# then add the bin path to sys.path to load the python modules
bin_path = make_splunkhome_path(['etc', 'apps', 'splunk_app_stream', 'bin'])
if bin_path not in sys.path:
    sys.path.append(bin_path)


import splunk_app_stream.utils.stream_utils as stream_utils


logger = stream_utils.setup_logger('cloud_instance')

# Controller class to handle the API requests to get the cloud instance status

class CloudInstance(controllers.BaseController):
    ''' Cloud Instance Controller '''

    @route('/', methods=['GET'])
    @expose_page(must_login=True, methods=['GET'])
    @set_cache_level('never')
    def list(self, **params):
        try:
            return self.render_json(stream_utils.isCloudInstance())
        except Exception as e:
            logger.exception(e)
            cherrypy.response.status = 500
            return self.render_json({'success': False, 'error': 'Internal error', 'status': 500})
