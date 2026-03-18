import os.path as op
import os
import sys
try:
    import xml.etree.cElementTree as ET
except:
    import xml.etree.ElementTree as ET
import splunk.appserver.mrsparkle.lib.util as util
import splunk
from splunk_app_stream.models.configuration import Configuration
from splunk_app_stream.models.vocabulary import Vocabulary
import splunk_app_stream.utils.stream_utils as stream_utils
import splunk_app_stream.utils.stream_kvstore_utils as kv_utils

bin_path = op.dirname(op.abspath(__file__))
if bin_path not in sys.path:
    sys.path.append(bin_path)

logger = stream_utils.setup_logger('rest_configurations')
use_kv_store = kv_utils.is_kv_store_supported_in_splunk()

# REST Handler class to handle the API requests related to configurations from clients using the Splunk Session key
# to authenticate. This class acts as a proxy to the vocabulary model class. All of the business logic is contained in
# the model class.

class Configurations(splunk.rest.BaseRestHandler):

    def handle_GET(self):
        '''Return list of configurations GET/GET-ALL'''
        id = ''

        try:
            id = self.args['id']
            del self.args['id']

        except:
            pass
        output = {}
        sessionKey = None
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
                output['configurations'] = {'success': False, 'error': 'Unauthorized', 'status': 401}
                return output

        try:
            vocab_terms = Vocabulary.list(sessionKey)
            if vocab_terms:
                try:
                    root = ET.fromstring(vocab_terms)
                    all_terms = []
                    for terms in root.find('{http://purl.org/cloudmeter/config}Vocabulary'):
                        for term in terms.iter('{http://purl.org/cloudmeter/config}Term'):
                            all_terms.append(term.attrib.get('id'))
                except Exception as e:
                    logger.error(e)
                    output['configurations'] = {'success': False, 'error': e, 'status': 400}
                    self.response.status = 400
                    raise splunk.RESTException(self.response.status, e)

            # Controller-call Logic  
            if id == 'CONTROLLER_CALL':

                if use_kv_store:
                    uri = kv_utils.configurations_kv_store_coll
                    response = kv_utils.read_from_kv_store_coll(uri, sessionKey)
                    output['configurations'] = response
                    self.response.status = 200
                    return output
                else:
                    output['configurations'] = {'success': False, 'error': 'Internal Error, kv store is not supported', 'status': 400}
                    self.response.status = 400
                    raise splunk.RESTException(self.response.status, "Internal Error, kv store is not supported")

            # GET-ALL logic
            elif id == '':

                if use_kv_store:
                    # Get the data from kv store
                    uri = kv_utils.configurations_kv_store_coll
                    response = kv_utils.read_from_kv_store_coll(uri, sessionKey)
                else:
                    output['configurations'] = {'success': False, 'error': 'Internal Error, kv store is not supported', 'status': 400}
                    self.response.status = 400
                    raise splunk.RESTException(self.response.status, "Internal Error, kv store is not supported")

                mappings_data = Configuration.validate_get(vocab_terms, response)

                if mappings_data['status'] != 200:
                    logger.error(mappings_data['error'])
                    output['configurations'] = {'success': False, 'error': mappings_data['error'], 'status': mappings_data['status']}
                    self.response.status = mappings_data['status']
                    raise splunk.RESTException(self.response.status, mappings_data['error'])
            
                term_count = 0
                content = ''
                # Return the data in a formatted manner
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

                output = {}
                output['configurations'] = content
                self.response.status = 200
                return output

            # GET By Id logic
            else:

                if use_kv_store:
                    # Get the data from kv store
                    uri = kv_utils.configurations_kv_store_coll
                    response = kv_utils.read_from_kv_store_coll(uri, sessionKey)

                    for i in response:
                        if i['_key'] == id :
                            self.response.status = 200
                            return i['data']
                    
                    output['configurations'] = {'success': False, 'error': "Internal Error, Filename doesn't exists", 'status': 400}
                    self.response.status = 400
                    raise splunk.RESTException(self.response.status, "Internal Error, Filename doesn't exists")
                else:
                    output['configurations'] = {'success': False, 'error': "Internal Error, kv store is not supported", 'status': 400}
                    self.response.status = 400
                    raise splunk.RESTException(self.response.status, "Internal Error, kv store is not supported")

        except Exception as e:
            logger.error(e)
            output = {}
            output['configurations'] = {'success': False, 'error': 'Internal error, malformed payload in the request', 'status': 400}
            self.response.status = 400
            raise splunk.RESTException(self.response.status, "Internal error, malformed payload in the request")

        finally:
            return output 
    
    def handle_POST(self):
        if 'authorization' in self.request['headers']:
            sessionKey = self.request['headers']['authorization'].replace("Splunk ", "")
            body = self.request['payload']
            output = {}
            id = ''

            try:
                id = self.args['id']
                del self.args['id']
            except:
                pass

            try:
                vocab_terms = Vocabulary.list(sessionKey)
                if vocab_terms:
                    try:
                        root = ET.fromstring(vocab_terms)
                        all_terms = []
                        for terms in root.find('{http://purl.org/cloudmeter/config}Vocabulary'):
                            for term in terms.iter('{http://purl.org/cloudmeter/config}Term'):
                                all_terms.append(term.attrib.get('id'))
                    except Exception as e:
                        logger.error(e)
                        output = {}
                        output['configurations'] = {'success': False, 'error': e, 'status': 400}
                        self.response.status = 400
                        raise splunk.RESTException(self.response.status, e)
                
                if use_kv_store:
                    # Read the data from kvstore to check if filename already exists
                    uri = kv_utils.configurations_kv_store_coll
                    response = kv_utils.read_from_kv_store_coll(uri, sessionKey)

                # validate_get and validate functions are used for cleaning and data validation
                mappings_data = Configuration.validate_get(vocab_terms, response)
                result= Configuration.validate(body, all_terms, mappings_data['data'])

                if result['success'] == True:

                    if use_kv_store:
                    
                        for i in response:

                            if i['_key'] == id:
                                self.response.status = 400
                                output['configurations'] = {'success': False, 'error': "Filename Already exists", 'status': 400}
                                raise splunk.RESTException(self.response.status, "Filename Already exists")

                        json_data = {'_key': id,'data': body}

                        try:
                            save_succeeded = kv_utils.save_to_kv_store(uri, None, json_data, sessionKey)

                            if save_succeeded:
                                self.response.status = 200
                                output['configurations'] = json_data['data']
                                return json_data['data']

                            else:
                                self.response.status = 400
                                output['configurations'] = {'success': False, 'error': "Internal Error, file not able to save error", 'status': 400}
                                raise splunk.RESTException(self.response.status, "Internal Error, file not able to save error")

                        except Exception as e:
                            logger.error(e)
                            self.response.status = 400
                            output['configurations'] = {'success': False, 'error': e, 'status': 400}
                            raise splunk.RESTException(self.response.status, e)

                    else:
                        self.response.status = 400
                        output['configurations'] = {'success': False, 'error': "Internal Error, kv store is not supported", 'status': 400}
                        raise splunk.RESTException(self.response.status, "Internal Error, kv store is not supported")

                else:
                    output = {}
                    output['configurations'] = {'success': False, 'error': result['error'], 'status': 400}
                    self.response.status = 400
                    raise splunk.RESTException(self.response.status, result['error'])

            except Exception as e:
                logger.error(e)
                output = {}
                output['configurations'] = {'success': False, 'error': e, 'status': 400}
                self.response.status = 400
                raise splunk.RESTException(self.response.status, e)

            finally:
                return output

        else:
            raise splunk.RESTException(401, "Unauthorized to perform POST operation")

    def handle_DELETE(self):
        if 'authorization' in self.request['headers']:
            sessionKey = self.request['headers']['authorization'].replace("Splunk ", "")

            id = ''
            try:
                id = self.args['id']
            except:
                pass

            if use_kv_store == False:
                self.response.status = 400
                output['configurations'] = {'success': False, 'error': "Internal Error, kv store is not supported", 'status': 400}
                raise splunk.RESTException(self.response.status, "Internal Error, kv store is not supported")

            # delete function deletes intended data from kvstore
            result = Configuration.delete(id, sessionKey)

            if 'status' in result:
                self.response.status = result['status']

            if self.response.status > 399:
                output['configurations'] = {'success': False, 'error': result['error'], 'status': result['status']}
                raise splunk.RESTException(self.response.status, result['error'])

            output = {}
            output['configurations'] = result
            return output
        else:
            raise splunk.RESTException(401, "Unauthorized to perform DELETE operation")
