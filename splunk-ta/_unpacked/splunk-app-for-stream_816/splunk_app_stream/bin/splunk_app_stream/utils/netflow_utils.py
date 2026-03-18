import logging
import os
import json
import tempfile
import re
import copy

try:
    import xml.etree.cElementTree as ET
except:
    import defusedxml.ElementTree as ET

import splunk
import splunk.clilib.cli_common
from splunk.clilib import cli_common as cli
import splunk.appserver.mrsparkle.lib.util as util
import splunk_app_stream.utils.stream_kvstore_utils as kv_utils
import splunk.appserver.mrsparkle.lib.apps as apps
import splunk_app_stream.utils.netflow_pull_vocabs as netflow_vocabs
import splunk_app_stream.utils.netflow_pull_streams as netflow_streams
import splunk_app_stream.utils.netflow_pull_mappings as netflow_mappings
from splunk_app_stream.models.vocabulary import Vocabulary
use_kv_store = kv_utils.is_kv_store_supported_in_splunk()
kv_store_not_supported_err_msg = "Internal Error, kv store is not supported"

# vocabulary endpoint
rest_vocab_uri = "/services/splunk_app_stream/vocabularies/"

# mappings endpoint
rest_configurations_uri = "/services/splunk_app_stream/configurations/"

# streams endpoint
rest_streams_uri = "/services/splunk_app_stream/streams/"

# netflow app info endpoint
netflow_ipfix_coll_uri = kv_utils.netflow_ipfix_apps_info_kv_store_coll

netflow_ipfix_coll_info = []

# Get list of installed apps
def get_apps():
    try:
        all_apps = apps.local_apps.items()
        ipfix_apps = []

        for app in all_apps:
            app_name = app[0]
            regex_result_ipfix = re.search("^splunk_app_stream_ipfix_", app_name)
            app_location = app[1]['full_path']

            if regex_result_ipfix:
                ipfix_apps.append(app_location)

        return ipfix_apps
    except Exception as e:
        logger.exception("Failed to get apps")

def fetch_terms(filePath="", session_key=False):
    try:
        all_terms = []
        if session_key:
            xml_schema_data = Vocabulary.list(session_key)
        elif filePath:
            xml_schema_data = open(filePath, 'rb' ).read()
        else:
            xml_schema_data = Vocabulary.list()

        root = ET.fromstring(xml_schema_data)
        for terms in root.find('{http://purl.org/cloudmeter/config}Vocabulary'):
            for term in terms.iter('{http://purl.org/cloudmeter/config}Term'):
                all_terms.append(term.attrib.get('id'))
        return all_terms
    except Exception as e:
        logger.exception("Exception occured while pulling terms from vocabulary")
        logger.error(e)

def fetch_new_vocab_terms():
    try:
        all_apps = get_apps()
        all_terms = []

        for i in all_apps:
            default_path = os.path.join(i, 'default')
            local_path = os.path.join(i, 'local')

            ET.register_namespace("", "http://purl.org/cloudmeter/config")
            combinedVocab = ET.Element('Vocabulary')

            for fname in os.listdir(default_path):
                if fname.endswith('.xml'):
                    tree = ET.parse(default_path + os.sep + fname)
                    vocab = tree.find('{http://purl.org/cloudmeter/config}Vocabulary')
                    for term in vocab.findall('{http://purl.org/cloudmeter/config}Term'):
                        combinedVocab.append(term)

            if os.path.exists(local_path):
                for fname in os.listdir(local_path):
                    if fname.endswith('.xml'):
                        tree = ET.parse(local_path + os.sep +fname)
                        vocab = tree.find('{http://purl.org/cloudmeter/config}Vocabulary')
                        for term in vocab.findall('{http://purl.org/cloudmeter/config}Term'):
                            combinedVocab.append(term)

            xmlOut = ET.ElementTree(ET.Element("CmConfig"))
            xmlOut.getroot().append(combinedVocab)

            temp = tempfile.NamedTemporaryFile(suffix='new', prefix='vocabs_')
            xmlOut.write(temp)
            temp.seek(0)
            content = temp.read().decode('utf-8')
            root = ET.fromstring(content)

            if root.find('{http://purl.org/cloudmeter/config}Vocabulary') != None:
                for terms in root.find('{http://purl.org/cloudmeter/config}Vocabulary'):
                    for term in terms.iter('{http://purl.org/cloudmeter/config}Term'):
                        all_terms.append(term.attrib.get('id'))

        return all_terms
    except Exception as e:
        logger.error(e)

# We might not need this function, remove when we sure
def fetch_terms_and_all_info(filePath):
    try:
        if not filePath:
            return "Please provide absolute file path"
        terms_info = []
        all_terms = []
        xml_schema_data = open(filePath, 'rb' ).read()
        root = ET.fromstring(xml_schema_data)
        for terms in root.find('{http://purl.org/cloudmeter/config}Vocabulary'):
            for term in terms.iter('{http://purl.org/cloudmeter/config}Term'):
                element_id = term.attrib.get('id')
                type = term.find('{http://purl.org/cloudmeter/config}Type').text
                comment = term.find('{http://purl.org/cloudmeter/config}Comment').text
                terms_info.append(element_id)
                terms_info.append(type)
                terms_info.append(comment)
        all_terms.append(terms_info)
        return all_terms
    except Exception as e:
        logger.error("Exception occured while pulling terms from vocabulary")

# This function will return the app short name of ipfix app which are installed
def get_ipfix_app_name(ipfix_app_full_path):
    try:
        ipfix_apps_name = []
        if len(ipfix_app_full_path):
            for val in ipfix_app_full_path:
                full_app_name = str(val).split("/")[-1]
                app_short_name = full_app_name.split("splunk_app_stream_ipfix_")[-1]
                ipfix_apps_name.append(app_short_name)
        return ipfix_apps_name
    except Exception as e:
        logger.exception(e)

# This function will return the array of app name if the content of that app has changed and the new content is valid
def get_app_name_of_updated_files(vocab_full_path, mapping_full_path, stream_full_path):

    apps_name = []

    for v in vocab_full_path:
        if v.get('isAppContentChanged') == True and v.get('is_valid') == True:
            apps_name.append(v['app_short_name'])

    for m in mapping_full_path:
        if m.get('isAppContentChanged') == True and m.get('is_valid') == True and not m.get('app_short_name') in apps_name:
            apps_name.append(m['app_short_name'])
        elif m.get("is_valid") == False and m.get('app_short_name') in apps_name:
            apps_name.remove(m["app_short_name"])

    for s in stream_full_path:
        if s.get('isAppContentChanged') == True and s.get('is_valid') == True and not s.get('app_short_name') in apps_name:
            apps_name.append(s['app_short_name'])
        elif s.get("is_valid") == False and s.get('app_short_name') in apps_name:
            apps_name.remove(s["app_short_name"])

    return apps_name

def get_ipfix_coll_main_data(session_key):
    try:
        main_data = []
        if use_kv_store:
            ipfix_coll_info = kv_utils.read_from_kv_store_coll(netflow_ipfix_coll_uri, session_key)
            if len(ipfix_coll_info):
                for i in ipfix_coll_info:
                    if i["_key"] == "netflow_ipfix_apps_info":
                        main_data = i["data"]
            return main_data
        else:
            logger.error(kv_store_not_supported_err_msg)
            return main_data
    except Exception as e:
        logger.error(e)

def get_ipfix_coll_deleted_streams_data(session_key):
    try:
        deleted_streams = []
        if use_kv_store:
            ipfix_coll_info = kv_utils.read_from_kv_store_coll(netflow_ipfix_coll_uri, session_key)
            if len(ipfix_coll_info):
                for i in ipfix_coll_info:
                    if i['_key'] == "DELETED_STREAMS":
                        deleted_streams = i['data']
            return deleted_streams
        else:
            logger.error(kv_store_not_supported_err_msg)
            return deleted_streams
    except Exception as e:
        logger.error(e)

def pull_vendor_apps_configuration(session_key):
    global netflow_ipfix_coll_info

    try:
        PATH = get_apps()

        netflow_ipfix_coll_info = get_ipfix_coll_main_data(session_key)

        if netflow_ipfix_coll_info == None:
            netflow_ipfix_coll_info = []

        delete_apps_info_from_kvstore(PATH, session_key)

        if not len(PATH):
            logger.info("No matching ipfix app found, terminating the process of pulling configuration from vendor app...")
            return True

        # Pulling the configurations from ipfix app
        apps_stored_in_kvstore = []
        try:
            logger.info("Pulling configurations from ipfix app...")
            
            for index, val in enumerate(netflow_ipfix_coll_info):
                apps_stored_in_kvstore.append(val['app_short_name'])

            validVocabs, vocab_full_path = netflow_vocabs.get_vocabs(PATH, session_key, apps_stored_in_kvstore)
            validConfigurations, mapping_full_path = netflow_mappings.get_configurations(PATH, session_key, validVocabs, apps_stored_in_kvstore)
            validStreams, stream_full_path = netflow_streams.get_streams(PATH, session_key, validConfigurations, apps_stored_in_kvstore)

            # Deleting the app content from kvstore
            try:
                # If we found updated content in ipfix app then
                # we have to delete the content from the kvstore for that app
                # and push the updated content in the kvstore again
                updated_apps_name = get_app_name_of_updated_files(vocab_full_path, mapping_full_path, stream_full_path)
                for val in updated_apps_name:
                    if val in apps_stored_in_kvstore:
                        delete_streams(session_key, val)
                        delete_configurations(session_key, val)
                        delete_vocabs(session_key, val)
                        apps_stored_in_kvstore.remove(val)
            except Exception as e:
                logger.error(e)

        except Exception as e:
            logger.error(e)

        # Pushing the app content to kvstore
        # If the content has changed and valid, or if the content is not present in the kvstore
        try:
            ipfix_app_name = get_ipfix_app_name(PATH)
            for val in ipfix_app_name:
                if val not in apps_stored_in_kvstore:
                    vocab_arr = pushVocabularyToKvStore(vocab_full_path, val, validStreams, session_key)
                    config_arr = pushConfigurationsToKvStore(mapping_full_path, val, validStreams, session_key, vocab_arr)
                    final_arr = pushStreamsToKvStore(stream_full_path, val, validStreams, session_key, config_arr)

                    if len(final_arr):
                        update_netflow_ipfix_apps_kvstore_coll(final_arr, session_key)
                    else:
                        logger.error("Invalid configurations found in %s app"% val)
        except Exception as e:
            logger.error(e)

    except Exception as e:
        logger.info(e)   
 
    return True

# Push the vocabularies in the kvstore if the content is valid
def pushVocabularyToKvStore(vocab_full_path, app_name, validStreams, session_key):
    tmp_arr = []
    for index in range(len(vocab_full_path)):

        app_short_name = vocab_full_path[index]['app_short_name']
        final_vocabs = vocab_full_path[index].get('final_vocabs')

        if validStreams.get(app_short_name) == True and app_name == app_short_name:

            default_path = vocab_full_path[index]['default_path']
            local_path = vocab_full_path[index]['local_path']
            app_vocab_file = {
                "app_short_name": "",
                "vocabularies": []
            }
            app_vocab_file["app_short_name"] = app_short_name

            for path in default_path:
                fileNameWithoutExt = path.split("/")[-1].split(".")[0]
                xml_schema_data = open(path, 'rb' ).read()
                keyName = app_short_name + "_" + fileNameWithoutExt

                try:
                    save_vocabs_to_kvstore(session_key, xml_schema_data, keyName)
                    app_vocab_file["vocabularies"].append(keyName)
                except Exception as e:
                    pass

            for path in local_path:
                fileNameWithoutExt = path.split("/")[-1].split(".")[0]
                xml_schema_data = open(path, 'rb' ).read()
                keyName = app_short_name + "_" + fileNameWithoutExt

                try:
                    save_vocabs_to_kvstore(session_key, xml_schema_data, keyName)
                    app_vocab_file["vocabularies"].append(keyName)
                except Exception as e:
                    pass

            if len(final_vocabs):
                for vocab in final_vocabs:
                    keyName = vocab['fileName']

                    try:
                        save_vocabs_to_kvstore(session_key, vocab['content'], keyName)
                        app_vocab_file["vocabularies"].append(keyName)
                    except Exception as e:
                        pass

            tmp_arr.append(app_vocab_file)
    return tmp_arr

def pushConfigurationsToKvStore(mapping_full_path, app_name, validStreams, session_key, vocab_arr):
    for index in range(len(mapping_full_path)):

        app_short_name = mapping_full_path[index]['app_short_name']
        final_configs = mapping_full_path[index].get('final_configs')

        if validStreams.get(app_short_name) == True and app_name == app_short_name:

            default_path = mapping_full_path[index]['default_path']
            local_path = mapping_full_path[index]['local_path']
            index = -1
            
            item = {
                "app_short_name": app_short_name,
                "configurations": []
            }

            for idx, val in enumerate(vocab_arr):
                if val.get('app_short_name') == app_short_name:
                    item = val
                    item["configurations"] = []
                    index = idx

            for path in default_path:
                fileNameWithoutExt = path.split("/")[-1].split(".")[0]
                content = open(path, 'rb' ).read()
                keyName = app_short_name + "_" + fileNameWithoutExt

                try:
                    save_configurations_to_kvstore(session_key, content, keyName)
                    item["configurations"].append(keyName)
                except Exception as e:
                    pass

            for path in local_path:
                fileNameWithoutExt = path.split("/")[-1].split(".")[0]
                content = open(path, 'rb' ).read()
                keyName = app_short_name + "_" + fileNameWithoutExt

                try:
                    save_configurations_to_kvstore(session_key, content, keyName)
                    item["configurations"].append(keyName)
                except Exception as e:
                    pass

            if len(final_configs):
                for config in final_configs:
                    keyName = config['fileName']

                    try:
                        save_configurations_to_kvstore(session_key, config['content'], keyName)
                        item["configurations"].append(keyName)
                    except Exception as e:
                        pass

            if index > -1:
                vocab_arr[index] = item
            else:
                vocab_arr.append(item)
    return vocab_arr

def pushStreamsToKvStore(stream_full_path, app_name, validStreams, session_key, config_arr):
    for index in range(len(stream_full_path)):

        app_short_name = stream_full_path[index]['app_short_name']
        final_streams = stream_full_path[index].get('final_streams')

        if validStreams.get(app_short_name) == True and app_name == app_short_name:

            default_path = stream_full_path[index]['default_path']
            local_path = stream_full_path[index]['local_path']
            deleted_streams = get_ipfix_coll_deleted_streams_data(session_key)
            index = -1

            item = {
                "app_short_name": app_short_name,
                "streams": []
            }

            for idx, val in enumerate(config_arr):
                if val.get('app_short_name') == app_short_name:
                    item = val
                    item["streams"] = []
                    index = idx

            for path in default_path:
                content = open(path, 'rb').read()
                content = json.loads(content)
                keyName = app_short_name + "_" + content['id']
                content['id'] = keyName
                content = json.dumps(content)

                # Before pushing the streams in kvstore we are looking into the DELETED_STREAMS list
                # If the stream id is not present in the list then only will allow to push
                if keyName not in deleted_streams:
                    try:
                        save_streams_to_kvstore(session_key, content)
                        item["streams"].append(keyName)
                    except Exception as e:
                        pass

            for path in local_path:
                content = open(path, 'rb').read()
                content = json.loads(content)
                keyName = app_short_name + "_" + content['id']
                content['id'] = keyName
                content = json.dumps(content)

                if keyName not in deleted_streams:
                    try:
                        save_streams_to_kvstore(session_key, content)
                        item["streams"].append(keyName)
                    except Exception as e:
                        pass

            if len(final_streams):
                for stream in final_streams:
                    content = stream['content']
                    keyName = app_short_name + "_" + content['id']
                    content['id'] = keyName

                    tfile = tempfile.NamedTemporaryFile(mode="w+")
                    json.dump(content, tfile)
                    tfile.seek(0)
                    _content = tfile.read()

                    if keyName not in deleted_streams:
                        try:
                            save_streams_to_kvstore(session_key, _content)
                            item["streams"].append(keyName)
                        except Exception as e:
                            pass
            
            # Manage the ipfix collection data for Streams
            if index > -1:
                config_arr[index] = item
            else:
                config_arr.append(item)
    return config_arr

def save_vocabs_to_kvstore(session_key, body, fileName):
    try:
        auth_key = kv_utils.get_internal_shared_key()
        serverResponse, serverContent = splunk.rest.simpleRequest(
            util.make_url_internal(rest_vocab_uri),    
            sessionKey=session_key,
            getargs={'output_mode': 'json', 'id': fileName,'X-SPLUNK-APP-STREAM-KEY':auth_key},
            method='POST',
            raiseAllErrors=True,
            rawResult=None,
            jsonargs=body,
            timeout=splunk.rest.SPLUNKD_CONNECTION_TIMEOUT
        )
    except Exception as e:
        logger.error("Failed to push vocabularies in kvstore %s"% e)
        raise Exception("Failed to push vocabularies in kvstore")

def save_configurations_to_kvstore(session_key, body, fileName):
    try:
        auth_key = kv_utils.get_internal_shared_key()
        serverResponse, serverContent = splunk.rest.simpleRequest(
            util.make_url_internal(rest_configurations_uri),    
            sessionKey=session_key,
            getargs={'id': fileName,'X-SPLUNK-APP-STREAM-KEY':auth_key},
            method='POST',
            raiseAllErrors=True,
            rawResult=None,
            jsonargs=body,
            timeout=splunk.rest.SPLUNKD_CONNECTION_TIMEOUT
        )
    except Exception as e:
        logger.error("Failed to push configurations in kvstore %s"% e)
        raise Exception("Failed to push configurations in kvstore")

def save_streams_to_kvstore(session_key, data):
    try:
        auth_key = kv_utils.get_internal_shared_key()
        serverResponse, serverContent = splunk.rest.simpleRequest(
            util.make_url_internal(rest_streams_uri),    
            sessionKey=session_key,
            getargs={'output_mode':'json','X-SPLUNK-APP-STREAM-KEY':auth_key},
            method='POST',
            raiseAllErrors=True,
            rawResult=None,
            jsonargs=data,
            timeout=splunk.rest.SPLUNKD_CONNECTION_TIMEOUT
        )
    except Exception as e:
        logger.error("Failed to push streams in kvstore %s"% e)
        raise Exception("Failed to push streams in kvstore")

def delete_streams(session_key, app_short_name):
    global netflow_ipfix_coll_info
    if app_short_name and len(netflow_ipfix_coll_info):
        for index, val in enumerate(netflow_ipfix_coll_info):
            if val['app_short_name'] == app_short_name:
                for keyName in val['streams']:
                    delete_streams_from_kvstore(session_key, str(keyName))

def delete_configurations(session_key, app_short_name):
    global netflow_ipfix_coll_info
    if app_short_name and len(netflow_ipfix_coll_info):
        for index, val in enumerate(netflow_ipfix_coll_info):
            if val['app_short_name'] == app_short_name:
                for keyName in val['configurations']:
                    delete_configs_from_kvstore(session_key, str(keyName))

def delete_vocabs(session_key, app_short_name):
    global netflow_ipfix_coll_info
    if app_short_name and len(netflow_ipfix_coll_info):
        for index, val in enumerate(netflow_ipfix_coll_info):
            if val['app_short_name'] == app_short_name:
                for keyName in val['vocabularies']:
                    delete_vocabs_from_kvstore(session_key, str(keyName))

def delete_streams_from_kvstore(session_key, keyName):
    try:
        auth_key = kv_utils.get_internal_shared_key()
        serverResponse, serverContent = splunk.rest.simpleRequest(
            util.make_url_internal(rest_streams_uri),    
            sessionKey=session_key,
            getargs={'output_mode': 'json', 'id': keyName, 'from_netflow_script': True,'X-SPLUNK-APP-STREAM-KEY':auth_key},
            method='DELETE',
            raiseAllErrors=True,
            rawResult=None,
            jsonargs=None,
            timeout=splunk.rest.SPLUNKD_CONNECTION_TIMEOUT
        )
    except Exception as e:
        logger.error("Failed to delete streams from kvstore %s"% e)

def delete_configs_from_kvstore(session_key, keyName):
    try:
        if use_kv_store:
            uri = kv_utils.configurations_kv_store_coll
            response = kv_utils.delete_by_id_from_kv_store_coll(uri, keyName, session_key)
        else:
            logger.error(kv_store_not_supported_err_msg)
    except Exception as e:
        logger.error("Failed to delete configurations from kvstore %s"% e)

def delete_vocabs_from_kvstore(session_key, keyName):
    try:
        if use_kv_store:
            uri = kv_utils.vocabularies_kv_store_coll
            response = kv_utils.delete_by_id_from_kv_store_coll(uri, keyName, session_key)
            if 'status' in response:
                status = response['status']
                if status == 200:
                    logger.info('delete_vocabs_from_kvstore:- Deleting vocabularies from kvstore succeded.')
        else:
            logger.error(kv_store_not_supported_err_msg) 
    except Exception as e:
        logger.error("Failed to delete vocabularies from kvstore %s"% e)

# Update the kvstore netflow_ipfix collection after pushing the ipfix data in kvstore
def update_netflow_ipfix_apps_kvstore_coll(data, session_key):
    netflow_ipfix_coll_info = get_ipfix_coll_main_data(session_key)

    try:
        if use_kv_store:
            kv_utils.delete_by_id_from_kv_store_coll(netflow_ipfix_coll_uri, 'netflow_ipfix_apps_info', session_key)
            updated_data = copy.deepcopy(netflow_ipfix_coll_info)

            if len(updated_data):
                index = -1
                for i, x1 in enumerate(updated_data):
                    if x1['app_short_name'] == data[0]['app_short_name']:
                        index = i

                if index > -1:
                    updated_data[index] = data[0]
                else:
                    updated_data.append(data[0])

                json_data = {'_key': 'netflow_ipfix_apps_info', 'data': updated_data}
                kv_utils.save_to_kv_store(netflow_ipfix_coll_uri, None, json_data, session_key)
            else:
                json_data = {'_key': 'netflow_ipfix_apps_info', 'data': data}
                kv_utils.save_to_kv_store(netflow_ipfix_coll_uri, None, json_data, session_key)

        else:
            logger.error(kv_store_not_supported_err_msg)
    except Exception as e:
        logger.error(e)

# When ipfix app gets deleted then all data related to that app is to be removed from kv store
# also update the neflow_kvstore collection
def delete_apps_info_from_kvstore(PATH, session_key):
    global netflow_ipfix_coll_info
    try:
        if use_kv_store:

            apps_stored_in_kvstore = set()
            ipfix_apps = set()

            deleted_streams = get_ipfix_coll_deleted_streams_data(session_key)
            updated_deleted_streams = copy.deepcopy(deleted_streams)
            
            if len(netflow_ipfix_coll_info):
                for index, val in enumerate(netflow_ipfix_coll_info):
                    apps_stored_in_kvstore.add(val['app_short_name'])

            if len(PATH):
                ipfix_apps = set(get_ipfix_app_name(PATH))

            diff = apps_stored_in_kvstore - ipfix_apps

            if len(diff):
                logger.info("It seems ipfix app have been deleted, hence deleting the related data of that app from KV Store")

                updated_netflow_ipfix_coll_info = copy.deepcopy(netflow_ipfix_coll_info)

                for app_short_name in diff:
                    delete_streams(session_key, app_short_name)
                    delete_configurations(session_key, app_short_name)
                    delete_vocabs(session_key, app_short_name)

                    for index, a in enumerate(updated_netflow_ipfix_coll_info):
                        if a['app_short_name'] == app_short_name:
                            updated_netflow_ipfix_coll_info.pop(index)
                    
                    for stream_name in deleted_streams:
                        if re.search(app_short_name + "_", stream_name):
                            updated_deleted_streams.remove(stream_name)

                if len(deleted_streams) > 0:
                    json_data_deleted_streams = {'_key': 'DELETED_STREAMS', 'data': updated_deleted_streams}
                    kv_utils.save_to_kv_store(netflow_ipfix_coll_uri, 'DELETED_STREAMS', json_data_deleted_streams, session_key)

                json_data = {'_key': 'netflow_ipfix_apps_info', 'data': updated_netflow_ipfix_coll_info}
                kv_utils.delete_by_id_from_kv_store_coll(netflow_ipfix_coll_uri, 'netflow_ipfix_apps_info', session_key)
                kv_utils.save_to_kv_store(netflow_ipfix_coll_uri, None, json_data, session_key)

        else:
            logger.error(kv_store_not_supported_err_msg)

    except Exception as e:
        logger.exception(e)

def setup_rotating_log_file():
    try:
        SPLUNK_HOME_LOG_PATH = util.make_splunkhome_path(["var", "log", "splunk"])
        LOG_FILENAME = ''
        # check to see if the SPLUNK_HOME based log path exists
        if not os.path.exists(SPLUNK_HOME_LOG_PATH):
            # check to see if the relative path based log path exists
            SPLUNK_BASE = os.path.abspath(os.path.join(os.path.dirname( __file__ ), '..', '..', '..', '..'))
            SPLUNK_BASE_LOG_PATH = os.path.join(SPLUNK_BASE, 'var', 'log', 'splunk')
            if not os.path.exists(SPLUNK_BASE_LOG_PATH):
                # disable logging with noop handler
                logger.addHandler(logging.NullHandler())
                return logger
            else:
                LOG_FILENAME = os.path.join(SPLUNK_BASE_LOG_PATH, 'splunk_app_stream.log')
        else:
            LOG_FILENAME = os.path.join(SPLUNK_HOME_LOG_PATH, 'splunk_app_stream.log')
        # valid log file path exists and rotate at 10 MB
        file_handler = logging.handlers.RotatingFileHandler(LOG_FILENAME, maxBytes=10240000, backupCount=10)
        LOGGING_FORMAT = "%(asctime)s %(levelname)-s\t%(name)s:%(lineno)d - %(message)s"
        file_handler.setFormatter(logging.Formatter(LOGGING_FORMAT))
        return file_handler
    except:
        # disable logging with noop handler
        return logging.NullHandler()

def setup_logger(modulename):
    logger = logging.getLogger(modulename)
    logger.propagate = False # Prevent the log messages from being duplicated in the python.log file
    logger.setLevel(logging.INFO)
    logger.addHandler(rotating_log_file)
    return logger

# Initialize the rotating log file which we will use for multiple loggers.
rotating_log_file = setup_rotating_log_file()

# Initialize the first such logger.
logger = setup_logger('netflow_utils')
