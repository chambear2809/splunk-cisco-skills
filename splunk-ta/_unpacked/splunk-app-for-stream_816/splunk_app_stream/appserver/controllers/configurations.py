import sys
import os
import re
import shutil
import json
import ast
import splunk.rest as rest
import splunk.appserver.mrsparkle.lib.util as app_util
try:
    # py3
    from urllib.parse import quote as urllibquote
except ImportError:
    # py2
    from urllib import quote as urllibquote

try:
    import xml.etree.cElementTree as ET
except:
    import xml.etree.ElementTree as ET

import cherrypy
import splunk.appserver.mrsparkle.controllers as controllers
import splunk.appserver.mrsparkle.lib.util as util
from splunk.appserver.mrsparkle.lib.decorators import expose_page
from splunk.appserver.mrsparkle.lib.decorators import set_cache_level
from splunk.appserver.mrsparkle.lib.routes import route
from splunk.appserver.mrsparkle.lib.util import make_splunkhome_path
bin_path = make_splunkhome_path(['etc', 'apps', 'splunk_app_stream', 'bin'])
if bin_path not in sys.path:
    sys.path.append(bin_path)

import splunk_app_stream.utils.stream_kvstore_utils as kv_utils
import splunk_app_stream.utils.stream_utils as stream_utils
from splunk_app_stream.models.configuration import Configuration
from splunk_app_stream.models.vocabulary import Vocabulary

logger = stream_utils.setup_logger('configurations')
use_kv_store = kv_utils.is_kv_store_supported_in_splunk()

tmp_dir = os.path.join(util.get_apps_dir(), 'splunk_app_stream', '.tmp')

if os.path.exists(tmp_dir):
    shutil.rmtree(tmp_dir)

# Controller class to handle the API requests related to Configuration Mappings. This class acts as a proxy to the
# configuration model class. All of the business logic is contained in the model class.

class Configurations(controllers.BaseController):
    ''' Configurations Controller '''
    @route('/:id', methods=['GET'])
    @expose_page(must_login=False, methods=['GET'])
    @set_cache_level('never')
    def list(self,id='',**kwargs):
        '''Return list of Configurations''' 

        session_key = cherrypy.session.get('sessionKey')
        header_auth_key = cherrypy.request.headers.get('X-SPLUNK-APP-STREAM-KEY', '')

        if not session_key:
            auth_success = stream_utils.validate_streamfwd_auth(header_auth_key)
            if not auth_success:
                cherrypy.response.status = 401
                return None

        # Rest Call to get the data as we have to maintain single data variables to avoid multiprocessing
        try:

            serverResponse, serverContent = rest.simpleRequest(
                util.make_url_internal("/services/splunk_app_stream/configurations/"),    
                getargs={'output_mode':'json', 'id':'CONTROLLER_CALL', 'X-SPLUNK-APP-STREAM-KEY':header_auth_key},
                method='GET',
                raiseAllErrors=True,
                rawResult=None,
                jsonargs=None,
                timeout=rest.SPLUNKD_CONNECTION_TIMEOUT
            )
            jsonResp = json.loads(serverContent)
            rest_response = jsonResp['entry'][0]['content']

        except Exception as e:
            logger.error("Failed to fetch vocabularies from kvstore: %s"% e)
            cherrypy.response.status = 400
            return self.render_json({'success': False, 'error': "Internal Error, Failed to fetch vocabularies from kvstore", 'status': 400})

        try:
            vocab_terms = Vocabulary.list(session_key)
            
            #GET-all files default logic
            if id == '':
                
                if use_kv_store:
                    response = rest_response
                else:
                    cherrypy.response.status = 400
                    return self.render_json({'success': False, 'error': 'Internal error, kvstore is not supported', 'status': 400})

                validation_flag = False
                mappings_data = Configuration.validate_get(vocab_terms, response, validation_flag)

                if mappings_data['status'] != 200:
                    logger.error(mappings_data['error'])
                    cherrypy.response.status = mappings_data['status']
                    return self.render_json(mappings_data)

                term_count = 0
                content = ''
                
                for x in mappings_data['data'].values():

                    if x[0] != False:
                        content = content + f"netflowElement.{term_count}.enterpriseid = {x[0]}\n"

                    if x[1] != False:
                        content = content + f"netflowElement.{term_count}.id = {x[1]}\n"

                    if x[2] != False:
                        content = content + f"netflowElement.{term_count}.termid = {x[2]}\n"

                    if x[3] != False:
                        content = content + f"netflowElement.{term_count}.termtype = {x[3]}\n"

                    term_count = term_count + 1
                cherrypy.response.status = 200
                return content

            # GET logic
            else:

                if use_kv_store:
                    response = rest_response

                    for i in response:
                        if(i['_key']==id):
                            cherrypy.response.status = 200
                            return i['data']

                    cherrypy.response.status = 400
                    return self.render_json({'success': False, 'error': "Internal Error, Filename doesn't exists", 'status': 400})

                else:
                    cherrypy.response.status = 400
                    return self.render_json({'success': False, 'error': "Internal Error, kv store is not supported", 'status': 400})
                    
        except Exception as e:
            logger.error(e)
            cherrypy.response.status = 400
            return self.render_json({'success': False, 'error': 'Internal error, malformed payload in the request', 'status': 400})

    @route('/:id', methods=['POST'])
    @expose_page(must_login=True, methods=['POST'])
    @set_cache_level('never')
    def write(self,id='',**kwargs):
        '''Return true''' 
        session_key = cherrypy.session.get('sessionKey')
        user = stream_utils.get_username(session_key)
        # Read POST data of type xml
        try:
            body = cherrypy.request.body.read()
            if body:

                vocab_terms = Vocabulary.list(session_key)
                if vocab_terms:

                    try:
                        root = ET.fromstring(vocab_terms)
                        all_terms = []
                        for terms in root.find('{http://purl.org/cloudmeter/config}Vocabulary'):
                            for term in terms.iter('{http://purl.org/cloudmeter/config}Term'):
                                all_terms.append(term.attrib.get('id'))
                    except Exception as e:
                        logger.error(e)

                if use_kv_store:
                    # Read data from kvstore to check if filename already exists
                    uri = kv_utils.configurations_kv_store_coll
                    response = kv_utils.read_from_kv_store_coll(uri,session_key)
                # validate_get and validate function are used to clean and validate the data
                mappings_data = Configuration.validate_get(vocab_terms,response)

                if mappings_data['status'] == 200:
                    result = Configuration.validate(body,all_terms,mappings_data['data'])
                else:
                    cherrypy.response.status = 400
                    return self.render_json({'success': False, 'error': mappings_data['error'], 'status': 400})

                if result['success'] == True:

                    if use_kv_store:

                        for i in response:

                            if i['_key'] == id:
                                cherrypy.response.status = 400
                                return self.render_json({'success': False, 'error': "Filename Already exists", 'status': 400})
                        
                        json_data = {'_key':id,'data': body.decode()}

                        try:
                            save_succeeded = kv_utils.save_to_kv_store(uri, None, json_data, session_key)
                            if save_succeeded:
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
                        cherrypy.response.status = 400
                        return self.render_json({'success': False, 'error': "Internal Error, kv store is not supported", 'status': 400})

                else:
                    cherrypy.response.status = 400
                    return self.render_json({'success': False, 'error': result['error'], 'status': 400}) 

            else:
                cherrypy.response.status = 400
                return self.render_json({'success': False, 'error': "Internal Error, Please input the body", 'status': 400})

        except Exception as e:
            logger.error(e)
            cherrypy.response.status = 400
            return self.render_json({'success': False, 'error': 'Internal error, malformed payload in the request', 'status': 400})

    @route('/:id', methods=['DELETE'])
    @expose_page(must_login=True, methods=['DELETE'])
    @set_cache_level('never')
    def delete(self, id='', **params):
        """delete posted vocabularies"""

        session_key = cherrypy.session.get('sessionKey')
        # delete function deletes the intended data from kvstore
        result = Configuration.delete(id, session_key)
        result_status = ""

        if 'status' in result:
            cherrypy.response.status = result['status']
            result_status = result['status']

        logger.debug("Deleted posted posted conf. STATUS: %s", result_status)
        return self.render_json(result)