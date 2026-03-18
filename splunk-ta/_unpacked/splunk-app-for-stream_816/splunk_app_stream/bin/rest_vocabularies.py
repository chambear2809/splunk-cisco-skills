import os.path as op
import os
import io
import sys

from lxml import etree
import splunk.appserver.mrsparkle.lib.util as util
import splunk
from splunk_app_stream.models.vocabulary import Vocabulary
import splunk_app_stream.utils.stream_utils as stream_utils
import splunk_app_stream.utils.stream_kvstore_utils as kv_utils
# import splunk_app_stream.models.stream as StreamModel

bin_path = op.dirname(op.abspath(__file__))
if bin_path not in sys.path:
    sys.path.append(bin_path)

logger = stream_utils.setup_logger('rest_vocabularies')
use_kv_store = kv_utils.is_kv_store_supported_in_splunk()
xml_schema_file = op.join(util.get_apps_dir(), 'splunk_app_stream', 'default', "vocabulary")

# REST Handler class to handle the API requests related to Vocabularies from clients using the Splunk Session key
# to authenticate. This class acts as a proxy to the vocabulary model class. All of the business logic is contained in
# the model class.

class Vocabularies(splunk.rest.BaseRestHandler):

    def handle_GET(self):
        '''Return list of vocabularies'''
        output = {}
        sessionKey = None
        id = ''

        try:
            id = self.args['id']
            del self.args['id']
        except:
            pass

        if 'systemAuth' in self.request and self.request['systemAuth']:
            sessionKey = self.request['systemAuth']
        else:
            sessionKey = self.sessionKey

        # Check for auth key
        auth_key = None

        if 'systemAuth' in self.request:
            auth_key = stream_utils.extract_auth_key(self.request, self.args)
            auth_success  = stream_utils.validate_streamfwd_auth(auth_key)
            if not auth_success:
                self.response.status = 401
                output = {}
                output['vocabularies'] = {'success': False, 'error': 'Unauthorized', 'status': 401}
                return output

        if id:

            if use_kv_store:
                # Read data from kvstore to check that filename already exists or not
                uri = kv_utils.vocabularies_kv_store_coll
                response = kv_utils.read_from_kv_store_coll(uri,sessionKey)
                for i in response:

                    if i['_key'] == id:
                        self.response.status = 200
                        output['vocabularies'] = i['data']
                        return output

                output['vocabularies'] = {'success': False, 'error': 'Internal error, Filename Doesnot exists', 'status': 400}
                self.response.status = 400
                raise splunk.RESTException(self.response.status, "Internal error, Filename Doesnot exists")

            else:
                output['vocabularies'] = {'success': False, 'error': 'Internal Error, kv store is not supported', 'status': 400}
                self.response.status = 400
                raise splunk.RESTException(self.response.status, "Internal Error, kv store is not supported")
        else:

            if use_kv_store:
                output['vocabularies'] = Vocabulary.list(sessionKey)
                
            else:
                output['vocabularies'] = {'success': False, 'error': 'Internal Error, kv store is not supported', 'status': 400}
                self.response.status = 400
                raise splunk.RESTException(self.response.status, "Internal Error, kv store is not supported")

        return output

    def handle_POST(self):
        '''POST/ADD vocabularies in the system'''

        if 'authorization' in self.request['headers']:
            session_key = self.request['headers']['authorization'].replace("Splunk ", "")
            body = self.request['payload']
            id = ''
            output = {}

            try:
                id = self.args['id']
            except:
                pass
            
            # Read POST data of type xml
            try:
                body = etree.tostring(etree.parse(io.BytesIO(bytes(body, 'UTF-8'))))
                result = Vocabulary.validateXML(body)

                if result == True:

                    try:
                        # Check if file exists in default folder
                        file_path = os.path.join(util.get_apps_dir(), 'splunk_app_stream', 'default', 'vocabularies') + f"/{id}.xml"
                        
                        if os.path.isfile(file_path):

                            self.response.status = 400
                            output['vocabulary'] = {'success': False, 'error': 'Internal Error, filename already exists', 'status': 400}
                            raise splunk.RESTException(400, "Internal Error, filename already exists")
                        else:

                            if use_kv_store:
                                uri = kv_utils.vocabularies_kv_store_coll
                                response = kv_utils.read_from_kv_store_coll(uri, session_key)

                                for i in response:
                                    # Check if file exists in kvstore
                                    if i['_key'] == id:
                                        self.response.status = 400
                                        output['vocabulary'] = {'success': False, 'error': 'Internal Error, filename already exists', 'status': 400}
                                        raise splunk.RESTException(400, "Internal Error, filename already exists")

                                json_data = {'_key':id, 'data': body.decode()}

                                try:
                                    save_succeeded = kv_utils.save_to_kv_store(uri, None, json_data, session_key)

                                    if save_succeeded:
                                        # StreamModel.update_vocab_terms()
                                        self.response.status = 200
                                        output['vocabulary'] = json_data['data']
                                        return json_data['data']
                                    else:
                                        self.response.status = 400
                                        output['vocabulary']= {'success': False, 'error': "Internal Error, not able to save the file", 'status': 400}
                                        raise splunk.RESTException(400, "Internal Error, not able to save the file")

                                except Exception as e:
                                    logger.error(e)
                                    self.response.status = 400
                                    output['vocabulary'] = {'success': False, 'error': e, 'status': 400}
                                    raise splunk.RESTException(400, e)

                            else:
                                self.response.status = 400
                                output['vocabulary'] = {'success': False, 'error': "Internal Error, kv store is not supported", 'status': 400}
                                raise splunk.RESTException(400,"Internal Error, kv store is not supported")

                    except Exception as e:
                        logger.error(e)
                        self.response.status = 400
                        output['vocabulary'] = {'success': False, 'error': e, 'status': 400}
                        raise splunk.RESTException(400,e)

                else:
                    self.response.status = 400
                    output['vocabulary'] = {'success': False, 'error': 'Internal Error', 'status': 400}
                    raise splunk.RESTException(result['status'], result['error'])

            except Exception as e:
                output['streams'] = {'success': False, 'error': e, 'status': 400}
                self.response.status = 400
                raise splunk.RESTException(400, e)

            finally:
                return output
        else:
            raise splunk.RESTException(401, "Unauthorized to perform POST or PUT operation")
    
    def handle_DELETE(self):

        if 'authorization' in self.request['headers']:
            sessionKey = self.request['headers']['authorization'].replace("Splunk ", "")

            id = ''

            try:
                id = self.args['id']
            except:
                pass

            dependency_flag = False
            main_data = []
            if use_kv_store ==  False:
                self.response.status = 400
                raise splunk.RESTException(self.response.status, "Internal Error, kv store is not supported")

            else:    
                # Checking Dependency for STREAMS and CONFIGURATIONS            
                netflow_ipfix_coll_info = kv_utils.read_from_kv_store_coll(kv_utils.netflow_ipfix_apps_info_kv_store_coll, sessionKey)

                for i in netflow_ipfix_coll_info:

                    if i["_key"] == "netflow_ipfix_apps_info":
                        main_data = i["data"]

                for i in main_data:

                    if id in i['vocabularies']:
                        dependency_flag = True
                        error_message = "Internal error, following streams and configurations are dependent on vocabulary asked to delete, please delete these streams and configurations before deleting vocabulary: "

                        for j in range(len(i['streams'])):
                            error_message = error_message+"STREAM-"+str(j+1)+"."+str(i['streams'][j])+","
                        
                        for k in range(len(i['configurations'])):
                            error_message = error_message+"CONFIGURATION-"+str(k+1)+"."+str(i['configurations'][k])+","

                        result = {'success': False, 'error': str(error_message), 'status': 400}
                        self.response.status = 400
                        raise splunk.RESTException(self.response.status, result['error'])

            if dependency_flag == False:
                result = Vocabulary.delete(f"{id}.xml", sessionKey)

            if 'status' in result:
                self.response.status  = result['status']

            if self.response.status > 399:
                raise splunk.RESTException(self.response.status, result['error'])
            # elif self.response.status == 200:
            #     StreamModel.update_vocab_terms()

            output = {}
            self.response.status = result['status']
            output['vocabularies'] = result
            return output
        else:
            raise splunk.RESTException(401, "Unauthorized to perform DELETE operation")