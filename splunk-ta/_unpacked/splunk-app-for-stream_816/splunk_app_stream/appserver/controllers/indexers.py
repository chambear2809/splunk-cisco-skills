import sys
import json

import cherrypy
import splunk.appserver.mrsparkle.controllers as controllers
from splunk.appserver.mrsparkle.lib.decorators import expose_page
from splunk.appserver.mrsparkle.lib.decorators import set_cache_level
from splunk.appserver.mrsparkle.lib.routes import route
from splunk.appserver.mrsparkle.lib.util import make_splunkhome_path
from splunk.appserver.mrsparkle.lib.util import isCloud

from splunk_app_stream.models.indexer import Indexer

# STREAM-3375: if splunk_app_stream bin path is not present in the sys.path,
# then add it to sys.path to ensure python modules are loaded
bin_path = make_splunkhome_path(['etc', 'apps', 'splunk_app_stream', 'bin'])
if bin_path not in sys.path:
    sys.path.append(bin_path)

import splunk_app_stream.utils.stream_utils as stream_utils


logger = stream_utils.setup_logger('indexers')

def getHECTokenCloud(jsonIndexers):
    if jsonIndexers:
        try:
            dictIndexers=json.loads(jsonIndexers)
            hecToken=dictIndexers["token"]
            return hecToken
        except Exception as e:
            hecToken=None
    logger.error("Unable to get the HEC token entry for streamfwd. Sending data to HEC requires a valid token. Please create an HEC token called streamfwd.")
    return None

def getHECEndpoints(hecEndPoints):
    return hecEndPoints.split(',')
    
def transformToCloudHECEndpoints(hecEndpointList):
    return ['https://' + endpoint.strip() for endpoint in hecEndpointList if endpoint]

def makeCollectorEndpointsCloud():
    cloudConfig = stream_utils.isCloudInstance()
    outVals = {}
    if cloudConfig:
        try:
            hecEndpoints = cloudConfig["hecEndpoint"]
        except KeyError:
            hecEndpoints = None
        if hecEndpoints:
            outVals["collectors"] = transformToCloudHECEndpoints(getHECEndpoints(hecEndpoints))
            outVals["token"] = ""
            outVals["headerMeta"] = False
            return outVals
    logger.error("Instance Type is set to cloud but hecEndPoints are not set in cloud.conf. hecEndpoints will be set to default ones.")
    return None
        
    


# Controller class to handle the API requests related to Indexers. This class acts as a proxy to the
# indexer model class. All of the business logic is contained in the model class.

class Indexers(controllers.BaseController):
    ''' Indexers Controller '''

    @route('/:id', methods=['GET'])
    @expose_page(must_login=False, methods=['GET'])
    @set_cache_level('never')
    def list(self, id='', **kwargs):
    
        '''Return list of indexers'''  
        session_key = cherrypy.session.get('sessionKey')
        header_auth_key = cherrypy.request.headers.get('X-SPLUNK-APP-STREAM-KEY', '')
        if not session_key:
            auth_success = stream_utils.validate_streamfwd_auth(header_auth_key)
            if not auth_success:
                cherrypy.response.status = 401
                return None
                
        if isCloud():
            endPoints = makeCollectorEndpointsCloud()
            if endPoints:
                indexersInfo = Indexer.list(id, **kwargs)
                token=getHECTokenCloud(indexersInfo)
                if token:
                    endPoints["token"] = token
                cherrypy.response.headers['Content-Type'] = 'application/json'
                return json.dumps(endPoints)
            cherrypy.response.status = 503
            return self.render_json({
                'success': False,
                'error': 'Splunk Cloud Stream endpoints are not configured. Populate cloud.conf with hecEndpoint and serverFQDN before connecting forwarders.',
                'status': 503
            })

        content = Indexer.list(id, **kwargs)
        cherrypy.response.headers['Content-Type'] = 'application/json'
        '''Address IE6 security issue - SPL-34355'''
        return ' ' * 256 + '\n' + content

    @route('/', methods=['DELETE'])
    @expose_page(must_login=True, methods=['DELETE'])
    @set_cache_level('never')
    def delete(self, **kwargs):
        '''Return list of indexers'''                
        result = Indexer.delete()
        if 'status' in result:
            cherrypy.response.status = result['status']

        return self.render_json(result)
