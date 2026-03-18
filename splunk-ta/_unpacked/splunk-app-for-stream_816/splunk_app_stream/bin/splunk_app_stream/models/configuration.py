import os
import tempfile
import threading
try:
    import xml.etree.cElementTree as ET
except:
    import xml.etree.ElementTree as ET

from lxml import etree
import splunk.appserver.mrsparkle.lib.util as util

import splunk_app_stream.utils.stream_utils as stream_utils
import splunk_app_stream.utils.stream_kvstore_utils as kv_utils
import splunk
import re
import shutil

lock = threading.Lock()

# flag to wait for upgrade to finish
run_once = True

logger = stream_utils.setup_logger('configuration')
default_conf_dir = os.path.join(util.get_apps_dir(), 'splunk_app_stream', 'default', 'configurations')
local_conf_dir = os.path.join(util.get_apps_dir(), 'splunk_app_stream', 'local', 'configurations')
content = None
use_kv_store = kv_utils.is_kv_store_supported_in_splunk()

# This function will clean data for the configuration data, this includes removing comments
def clean_data(body):
    initial_data = re.split("\n",body)
        
    data_clean = [ele for ele in initial_data if ele.strip()]
    temp = []

    for i in range(len(data_clean)):
        data_clean[i] = data_clean[i].strip()

    for i in data_clean:
        if i[0] == "#":
            temp.append(i)

    for i in temp:
        data_clean.remove(i)

    return data_clean

# This function will validate the configuration and create a dictionary of that data to be used in get-all functionality    
def create_dict(final_mappings, content_mappings_arr, existing_numbers, vocab_terms, mapping_count, validation_flag=True, vocab_new=[]):

    # Regex for validation of different types of terms
    enterpriseid_regex = "(^(netflowElement.)\d+(.enterpriseid)\s*(=)\s*\d+$)"
    id_regex = "(^(netflowElement.)\d+(.id)\s*(=)\s*\d+$)"
    termid_regex = "(^(netflowElement.)\d+(.termid)\s*(=)\s*[a-zA-Z]+.[a-zA-Z]+)"
    termtype_regex = "(^(netflowElement.)\d+(.termtype)\s*(=)\s*(ipaddress\s*|macaddress\s*))$"
   

    for i in range(0,len(content_mappings_arr),1):

        outer_number = content_mappings_arr[i].split(".")
        regex_result_1 = re.search(enterpriseid_regex,content_mappings_arr[i])
        regex_result_2 = re.search(id_regex,content_mappings_arr[i])
        regex_result_3 = re.search(termid_regex,content_mappings_arr[i])
        regex_result_4 = re.search(termtype_regex,content_mappings_arr[i])
        count = 0
        inner_regex_1 = 0
        inner_regex_2 = 0
        inner_regex_3 = 0
        inner_regex_4 = 0

        if regex_result_1 or regex_result_2 or regex_result_3 or regex_result_4:

            if outer_number[1] not in existing_numbers:

                for j in range(i,len(content_mappings_arr),1):
                    inner_number = content_mappings_arr[j].split(".")

                    if outer_number[1] == inner_number[1]:

                        if re.search(enterpriseid_regex,content_mappings_arr[j]):
                            inner_regex_1 = content_mappings_arr[j].split("=")

                        if re.search(id_regex,content_mappings_arr[j]):
                            inner_regex_2 = content_mappings_arr[j].split("=")
                                
                        if re.search(termid_regex,content_mappings_arr[j]):
                            vocab_single_term = content_mappings_arr[j].split("=")

                            if (vocab_single_term[1].strip() in vocab_terms or not validation_flag or vocab_single_term[1].strip() in vocab_new):
                                inner_regex_3 = content_mappings_arr[j].split("=")
                            else:
                                return {'success': False, 'error': "Validation Error: Vocab for term id not found", 'status': 400}

                        if re.search(termtype_regex,content_mappings_arr[j]):
                            inner_regex_4 = content_mappings_arr[j].split("=")
                        count = count + 1
                        if count>4:
                            return {'success': False, 'error': "Validation Error: Have more than 4 terms for same inner-id", 'status': 400}
        else:
            return {'success': False, 'error': "Validation Error: bad data request the format is not appropriate", 'status': 400}

        # final_mappings object contains data in following manner:
        # {mapping_count(serial number of mapping): [data of enterprise id, data of id, data of termid, data of ipaddress/macaddress, duplication status for script]
        if ((count == 2 and inner_regex_2 and inner_regex_3) or (count == 3 and inner_regex_1 and inner_regex_2 and inner_regex_3) or (count == 4 and inner_regex_1 and inner_regex_2 and inner_regex_3 and inner_regex_4)):
            
            existing_numbers.append(outer_number[1])

            if count == 2:
                final_mappings.update({mapping_count:[False, inner_regex_2[1].strip(), inner_regex_3[1].strip(), False, False]})
                mapping_count = mapping_count + 1
            elif count == 3:
                final_mappings.update({mapping_count:[inner_regex_1[1].strip(), inner_regex_2[1].strip(), inner_regex_3[1].strip(), False, False]})
                mapping_count = mapping_count + 1
            elif count == 4:
                final_mappings.update({mapping_count:[inner_regex_1[1].strip(), inner_regex_2[1].strip(), inner_regex_3[1].strip(), inner_regex_4[1].strip(), False]})
                mapping_count = mapping_count + 1
                
            continue

        elif outer_number[1] not in existing_numbers:
            return {'success': False, 'error': "Validation Error: bad data request the terms don't match the required format", 'status': 400}

    return {'success': True, 'error': "None", 'status': 200, 'data': final_mappings, 'mapping_count': mapping_count}
    
class Configuration:
      
    @staticmethod
    # This function is used for getting all the configurations present in the app
    def validate_get(vocab_terms=[], response=[], validation_flag=True):
        global lock
        lock.acquire()

        try:
            final_mappings={}
            mapping_count = 0
            data = {'success': True, 'error': "None", 'status': 200, 'data': {}, 'mapping_count': 0}

            for i in response:
                content_mappings_arr = clean_data(i['data'])
                existing_numbers = []
                data=create_dict(final_mappings, content_mappings_arr, existing_numbers, vocab_terms, mapping_count, validation_flag)

                if data['status'] == 200:
                    mapping_count = data['mapping_count']
                    final_mappings.update(data['data'])
                    data['data'].update(final_mappings)
                else:
                    return data

            return data

        except Exception as e:
            logger.error(e)
            return {'success': False, 'error': "Cannot open File " + str(e), 'status': 400}

        finally:
            lock.release()

    @staticmethod
    # This function will be used to validate if the configuration to be pushed is in proper format or not
    def validate(body, vocab_terms=[], mapping_all_terms={}, vocab_new=[]):
        global lock
        lock.acquire()

        try:

            if type(body) == str:
                content_mappings_arr = clean_data(body)
            else:
                body = body.decode('utf-8')
                content_mappings_arr = clean_data(body)

            existing_numbers = []
            final_mappings = {}
            mapping_count = 0
            data = create_dict(final_mappings, content_mappings_arr, existing_numbers, vocab_terms, mapping_count, True, vocab_new)

            if data['status'] == 200:

                for x in data['data'].values():

                    for y in data['data'].values():

                        if x[2] == y[2] and x[0] == y[0] and x[0] != False and y[0] != False:

                            if x[1] != y[1]:
                                return {'success': False, 'error': "Validation Error: bad data request, two terms in same enterprise id, have same term.id and different id", 'status': 400}
                            else:
                                continue

                        elif x[1] == y[1] and x[0] == y[0] and x[0] != False and y[0] != False:

                            if x[2] != y[2]:
                                return {'success': False, 'error': "Validation Error: bad data request, two terms in same enterprise id, have same id and different term.id", 'status': 400}
                            else:
                                continue
            
                for x in data['data'].values():

                    for y in mapping_all_terms.values():

                        if x[2] == y[2] and x[0] == y[0] and x[0] != False and y[0] != False:

                            if x[1] != y[1]:
                                return {'success': False, 'error': "Validation Error: bad data request, two terms in same enterprise id, have same term.id and different id", 'status': 400}
                            else:
                                continue

                        elif x[1] == y[1] and x[0] == y[0] and x[0] != False and y[0] != False:

                            if x[2] != y[2]:
                                return {'success': False, 'error': "Validation Error: bad data request, two terms in same enterprise id, have same id and different term.id", 'status': 400}
                            else:
                                continue

                return {'success': True, 'error': "None", 'status': 200}

            else:
                return data

        except Exception as e:
            logger.exception(e)
            return {'success': False, 'error': "Validation Error " + str(e), 'status': 400}

        finally:
            lock.release()

    @staticmethod
    # This function is used to delete the configuration from the kvstore
    def delete(id='', session_key=None):

        global lock
        lock.acquire()

        try:

            if not id:
                return {'success': False, 'error': "Invalid Request Data", 'status': 400}

            if use_kv_store:

                uri = kv_utils.configurations_kv_store_coll

                try:
                    response = kv_utils.delete_by_id_from_kv_store_coll(uri, id, session_key)
                    return response

                except Exception as e:
                    logger.error(e)
                    return {'success': False, 'error': e, 'status': 400}

            else:
                return{'success': False, 'error': 'kv Store error', 'status': 400}
            
        except Exception as e:
            logger.exception(e)
            return {'success': False, 'error': 'Internal error while deleting vocabulary', 'status': 400}

        finally:
            lock.release()
