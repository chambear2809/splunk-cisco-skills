import sys
import os
import shutil
import json
import splunk.rest as rest
import splunk.appserver.mrsparkle.lib.util as app_util
try:
    # py3
    from urllib.parse import quote as urllibquote
except ImportError:
    # py2
    from urllib import quote as urllibquote

import cherrypy
import splunk.appserver.mrsparkle.controllers as controllers
import splunk.appserver.mrsparkle.lib.util as util
from splunk.appserver.mrsparkle.lib.decorators import expose_page
from splunk.appserver.mrsparkle.lib.decorators import set_cache_level
from splunk.appserver.mrsparkle.lib.routes import route
from splunk.appserver.mrsparkle.lib.util import make_splunkhome_path
import splunk_app_stream.models.stream as StreamModel

# STREAM-3375: if splunk_app_stream bin path is not present in the sys.path,
# then add it to sys.path to ensure python modules are loaded
bin_path = make_splunkhome_path(['etc', 'apps', 'splunk_app_stream', 'bin'])
if bin_path not in sys.path:
    sys.path.append(bin_path)

import splunk_app_stream.utils.stream_kvstore_utils as kv_utils
import splunk_app_stream.utils.stream_utils as stream_utils
from splunk_app_stream.models.vocabulary import Vocabulary

use_kv_store = kv_utils.is_kv_store_supported_in_splunk()
logger = stream_utils.setup_logger('vocabularies')

tmp_dir = os.path.join(util.get_apps_dir(), 'splunk_app_stream', '.tmp')

if os.path.exists(tmp_dir):
    shutil.rmtree(tmp_dir)

# Controller class to handle the API requests related to Vocabularies. This class acts as a proxy to the
# vocabulary model class. All of the business logic is contained in the model class.

class Vocabularies(controllers.BaseController):
    ''' Vocabularies Controller '''

    @route('/:id', methods=['GET'])
    @expose_page(must_login=False, methods=['GET'])
    @set_cache_level('never')
    def list(self, id='',**kwargs):

        '''Return list of vocabularies''' 
        session_key = cherrypy.session.get('sessionKey')
        header_auth_key = cherrypy.request.headers.get('X-SPLUNK-APP-STREAM-KEY', '')
        streamfwdCall=False
        if not session_key:
            streamfwdCall=True
            auth_success = stream_utils.validate_streamfwd_auth(header_auth_key)

            if not auth_success:
                cherrypy.response.status = 401
                return None

        # If session_key is not found in the controller, data is fetched from rest call using splunk.rest
        try:
            if not streamfwdCall:
                header_auth_key = kv_utils.get_internal_shared_key()
            serverResponse, serverContent = rest.simpleRequest(
                util.make_url_internal("/services/splunk_app_stream/vocabularies/"),    
                getargs={'output_mode':'json', 'id':id, 'X-SPLUNK-APP-STREAM-KEY':header_auth_key},
                method='GET',
                raiseAllErrors=True,
                rawResult=None,
                jsonargs=None,
                timeout=rest.SPLUNKD_CONNECTION_TIMEOUT
            )
            jsonResp = json.loads(serverContent)
            rest_response = jsonResp['entry'][0]['content']
            return rest_response
        except Exception as e:
            logger.error("Failed to fetch vocabularies from kvstore: %s"% e)

            if id:
                cherrypy.response.status = 400
                return self.render_json({'success': False, 'error': 'Internal error, Filename Doesnot exists', 'status': 400})
            else:
                cherrypy.response.status = 400
                return self.render_json({'success': False, 'error': 'Internal error, Failed to fetch vocabularies from kvstore', 'status': 400})
                
    @route('/:id', methods=['POST'])
    @expose_page(must_login=True, methods=['POST'])
    @set_cache_level('never')
    def write(self,id='',**kwargs):
        '''Return true''' 
        session_key = cherrypy.session.get('sessionKey')
        user = stream_utils.get_username(session_key)
        body = cherrypy.request.body.read()

        try:
            result = Vocabulary.validateXML(body)

            if result == True:

                if not id:
                    cherrypy.response.status = 400
                    return self.render_json({'success': False, 'error': "Internal Error", 'status': 400})

                file_path = os.path.join(util.get_apps_dir(), 'splunk_app_stream', 'default', 'vocabularies') + f"/{id}.xml"
                # Check if file exists in default folder

                if os.path.isfile(file_path):
                    cherrypy.response.status = 400
                    return self.render_json({'success': False, 'error': "Internal Error, filename already exists", 'status': 400})

                else:

                    if use_kv_store:
                        uri = kv_utils.vocabularies_kv_store_coll
                        response = kv_utils.read_from_kv_store_coll(uri, session_key)
                        # Check if file exists in kvstore
                        for i in response:
                            if i['_key'] == id:
                                cherrypy.response.status = 400
                                return self.render_json({'success': False, 'error': "Filename Already exists", 'status': 400})
                        
                        json_data = {'_key':id,'data': body.decode()}
                        try:
                            save_succeeded = kv_utils.save_to_kv_store(uri, None, json_data, session_key)

                            if save_succeeded:
                                StreamModel.update_vocab_terms()
                                cherrypy.response.status = 200
                                return json_data['data']
                            else:
                                cherrypy.response.status = 400
                                return self.render_json({'success': False, 'error': "Internal Error, file not able to save error", 'status': 400})

                        except Exception as e:
                            logger.error(e)
                            cherrypy.response.status = 400
                            return self.render_json({'success': False, 'error': e, 'status': 400})

                    else:
                        return self.render_json({'success': False, 'error': "Internal Error, kv store is not supported", 'status': 400})

            else:
                cherrypy.response.status = result['status']
                return self.render_json({'success': False, 'error': result['error'], 'status': result['status']})

        except Exception as e:
            cherrypy.response.status = 400
            return self.render_json({'success': False, 'error': 'Internal error, malformed payload in the request', 'status': 400})

    @route('/:id', methods=['DELETE'])
    @expose_page(must_login=True, methods=['DELETE'])
    @set_cache_level('never')
    def delete(self, id='', **params):
        """delete posted vocabularies"""
        session_key = cherrypy.session.get('sessionKey')

        if use_kv_store ==  False:
            cherrypy.response.status = 400
            return self.render_json({'success': False, 'error': "Internal Error, kv store is not supported", 'status': 400})

        else: 
            # Checking Dependency for STREAMS and CONFIGURATIONS
            netflow_ipfix_coll_info = kv_utils.read_from_kv_store_coll(kv_utils.netflow_ipfix_apps_info_kv_store_coll, session_key)
            main_data = []
            
            for i in netflow_ipfix_coll_info:
                if i["_key"] == "netflow_ipfix_apps_info":
                    main_data = i["data"]

            for i in main_data:
                
                if id in i['vocabularies']:
                    error_message = "Internal error, following streams and configurations are dependent on vocabulary asked to delete, please delete these streams and configurations before deleting vocabulary: "
                    for j in range(len(i['streams'])):
                        error_message = error_message+" STREAM-"+str(j+1)+"."+str(i['streams'][j])+","
                    
                    for k in range(len(i['configurations'])):
                        error_message = error_message+" CONFIGURATION-"+str(k+1)+"."+str(i['configurations'][k])+","

                    result = {'success': False, 'error': str(error_message), 'status': 400}
                    cherrypy.response.status = 400
                    return self.render_json({'success': False, 'error': str(error_message), 'status': 400})

        
        result = Vocabulary.delete(f"{id}.xml", session_key)
        result_status = ""

        if 'status' in result:
            cherrypy.response.status = result['status']
            result_status = result['status']
        
        if result_status == 200:
            StreamModel.update_vocab_terms()

        logger.debug("Deleted posted vocabulary. STATUS: %s", result_status)
        cherrypy.response.status = result_status
        return self.render_json(result)
