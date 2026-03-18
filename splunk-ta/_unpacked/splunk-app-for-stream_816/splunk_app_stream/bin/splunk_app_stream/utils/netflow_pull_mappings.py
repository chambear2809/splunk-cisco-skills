import logging
import os
import json
import tempfile
import fnmatch
import re

try:
    import xml.etree.cElementTree as ET
except:
    import xml.etree.ElementTree as ET

import splunk
import splunk.clilib.cli_common
from splunk.clilib import cli_common as cli
import splunk.appserver.mrsparkle.lib.util as util
import splunk_app_stream.utils.stream_utils as stream_utils
import splunk_app_stream.utils.stream_kvstore_utils as kv_utils
import splunk.appserver.mrsparkle.lib.apps as apps
from splunk_app_stream.models.vocabulary import Vocabulary
import splunk_app_stream.models.configuration as Configuration
import splunk_app_stream.utils.netflow_utils as netflow_utils
from splunk_app_stream.models.ping import Ping

# kv store
use_kv_store = kv_utils.is_kv_store_supported_in_splunk()

# mappings endpoint
rest_configurations_uri = "/services/splunk_app_stream/configurations/"

# Last updated time used to refresh cache
dateLastUpdated = 0

mapping_file_name = 'ipfixmap.conf'


def get_last_updated_date_time(session_key):
    global dateLastUpdated
    try:
        if not dateLastUpdated:
            appsMeta = Ping.ping(session_key)
            dateLastUpdated = appsMeta['dateLastUpdated']
    except Exception:
        # Exception happens as appsMeta file is in the process of getting written to.
        logger.exception("Failed to get appsMeta")

def fetch_mappings(filePath, session_key):

    try:

        if not filePath:
            return "Please provide absolute file path"

        final_mappings = {}
        existing_numbers = []
        mapping_count = 0

        content_mappings = open(filePath, 'r').read()
        content_mappings_arr = Configuration.clean_data(content_mappings)
        vocab_terms = netflow_utils.fetch_terms(session_key=session_key)
        vocab_new = netflow_utils.fetch_new_vocab_terms()

        result = Configuration.create_dict(final_mappings, content_mappings_arr, existing_numbers, vocab_terms, mapping_count, True, vocab_new)

        return result

    except (OSError, ValueError):
        logger.exception("Exception occured while fetching fields from streams")
        logger.error(OSError)
        
def mappings_apply_layering(app_full_path, session_key, validConfigurations):

    global dateLastUpdated

    default_path = os.path.join(app_full_path, 'default')
    local_path = os.path.join(app_full_path, 'local')
    full_app_name = app_full_path.split("/")[-1]
    app_short_name = full_app_name.split("splunk_app_stream_ipfix_")[-1]
    vocab_terms = netflow_utils.fetch_terms(session_key=session_key)
    vocab_new = netflow_utils.fetch_new_vocab_terms()
    response = kv_utils.read_from_kv_store_coll(kv_utils.configurations_kv_store_coll, session_key)
    mappings_data = Configuration.Configuration.validate_get(vocab_terms, response)

    final_configs = []
    isAppContentChanged = False

    # Stores the files name
    default_files = set()
    local_files = set()

    if os.path.exists(default_path):
        default_files = set()

        # Checking if directory has changed or not
        isFileChangedInIpfixApp = stream_utils.is_file_modified(os.path.join(default_path), dateLastUpdated)
        if isFileChangedInIpfixApp:
            isAppContentChanged = True

        for file in os.listdir(default_path):
            if fnmatch.fnmatch(file, mapping_file_name):
                default_files.add(file)

                # Checking if file content has changed or not
                isFileChangedInIpfixApp = stream_utils.is_file_modified(os.path.join(default_path, file), dateLastUpdated)
                if isFileChangedInIpfixApp:
                    isAppContentChanged = True

    if os.path.exists(local_path):
        local_files = set()

        # Checking if directory has changed or not
        isFileChangedInIpfixApp = stream_utils.is_file_modified(os.path.join(local_path), dateLastUpdated)
        if isFileChangedInIpfixApp:
            isAppContentChanged = True

        for file in os.listdir(local_path):
            if fnmatch.fnmatch(file, mapping_file_name):
                local_files.add(file)

                # Checking if file content has changed or not
                isFileChangedInIpfixApp = stream_utils.is_file_modified(os.path.join(local_path, file), dateLastUpdated)
                if isFileChangedInIpfixApp:
                    isAppContentChanged = True

    matched_file_names = list(default_files & local_files)
    Unmatch_default_files = list(default_files - local_files)
    Unmatch_local_files = list(local_files - default_files)

    # Validate unmatched default file
    if len(Unmatch_default_files):
        for i, val in enumerate(Unmatch_default_files):
            default_mappings = fetch_mappings(os.path.join(default_path, val), session_key)
            content_mappings = open(os.path.join(default_path, val), 'r').read()
            final_result = Configuration.Configuration.validate(content_mappings, vocab_terms, mappings_data['data'], vocab_new)

            if default_mappings['success'] == False:
                validConfigurations[app_short_name] = False
                logger.error(default_mappings["error"])
                break

            elif final_result['success'] == False:
                validConfigurations[app_short_name] = False
                logger.error(final_result["error"])
                break

    # Validate unmatched local file
    if len(Unmatch_local_files):
        for i, val in enumerate(Unmatch_local_files):
            local_mappings = fetch_mappings(os.path.join(local_path, val), session_key)
            content_mappings = open(os.path.join(local_path, val), 'r').read()
            final_result = Configuration.Configuration.validate(content_mappings, vocab_terms, mappings_data['data'], vocab_new)

            if local_mappings['success'] == False:
                validConfigurations[app_short_name] = False
                logger.error(local_mappings["error"])
                break

            elif final_result['success'] == False:
                validConfigurations[app_short_name] = False
                logger.error(final_result["error"])
                break

    if len(matched_file_names):
        
        for i, val in enumerate(matched_file_names):
            default_mappings = fetch_mappings(os.path.join(default_path, val), session_key)
            local_mappings = fetch_mappings(os.path.join(local_path, val), session_key)
            temp_mappings = {}

            if default_mappings['success'] == False:
                validConfigurations[app_short_name] = False
                logger.error(default_mappings["error"])
                break
            default_mappings = default_mappings['data']

            if local_mappings['success'] == False:
                validConfigurations[app_short_name] = False
                logger.error(local_mappings["error"])
                break
            local_mappings = local_mappings['data']  

            count = len(local_mappings)

            for x in default_mappings.keys():

                for y in local_mappings.keys():

                    if(default_mappings[x] == local_mappings[y]):
                        default_mappings[x] = [default_mappings[x][0],default_mappings[x][1],default_mappings[x][2],default_mappings[x][3],True]
                        break
            
            for x in default_mappings.keys():

                if default_mappings[x][4] == False:
                    count = count +  1
                    temp_mappings.update({count: [default_mappings[x][0],default_mappings[x][1],default_mappings[x][2],default_mappings[x][3],False]})

            local_mappings.update(temp_mappings)
            term_count = 0
            content = ''

            for x in local_mappings.values():
                if(x[0]!=False):
                    content = content + f"netflowElement.{term_count}.enterpriseid = {x[0]}\n"
                if(x[1]!=False):
                    content = content + f"netflowElement.{term_count}.id = {x[1]}\n"
                if(x[2]!=False):
                    content = content + f"netflowElement.{term_count}.termid = {x[2]}\n"
                if(x[3]!=False):
                    content = content + f"netflowElement.{term_count}.termtype = {x[3]}\n"
                term_count = term_count + 1

            final_result = Configuration.Configuration.validate(content, vocab_terms, mappings_data['data'], vocab_new)
            if final_result['success'] == False:
                validConfigurations[app_short_name] = False
                logger.error(final_result["error"])
                break

            temp = val.split(".")
            config = {
                'appName': app_short_name,
                'fileName': app_short_name + "_" + temp[0],
                'content': content
            }
            final_configs.append(config)

    return default_path, local_path, default_files, local_files, final_configs, validConfigurations, isAppContentChanged

def get_configurations(PATH, session_key, validVocabs, apps_stored_in_kvstore):
    try:
        if len(PATH):

            get_last_updated_date_time(session_key)
            mapping_full_path = []
            validConfigurations = {}
            isValidConfiguration = True
            isFileExists = False

            for i in range(len(PATH)):

                full_app_name = str(PATH[i]).split("/")[-1]
                app_short_name = full_app_name.split("splunk_app_stream_ipfix_")[-1]

                mapping_file_path = {}
                mapping_file_path['is_valid'] = True
                mapping_file_path["app_short_name"] = app_short_name
                
                # Pull the configurations from the ipfix app only if the vocabulary is valid for that app
                if validVocabs[app_short_name] == True:
                    validConfigurations[app_short_name] = True

                    default_path, local_path, default_files, local_files, final_configs, validConfigurations, isAppContentChanged = mappings_apply_layering(str(PATH[i]), session_key, validConfigurations)
                    mapping_file_path["final_configs"] = final_configs
                    mapping_file_path["isAppContentChanged"] = isAppContentChanged
                    mapping_file_path['is_valid'] = validConfigurations[app_short_name]

                    default_mappings = list(set(default_files) - set(local_files))
                    local_mappings = list(set(local_files) - set(default_files))

                    default_tmpArr = []
                    if len(default_mappings):
                        for j in default_mappings:
                            default_tmpArr.append(os.path.join(str(PATH[i]), 'default', str(j)))
                    mapping_file_path['default_path'] = default_tmpArr

                    local_tmpArr = []
                    if len(local_mappings):
                        for j in local_mappings:
                            local_tmpArr.append(os.path.join(str(PATH[i]), 'local', str(j)))

                    mapping_file_path['local_path'] = local_tmpArr
                else:
                    mapping_file_path['is_valid'] = False

                mapping_full_path.append(mapping_file_path)
                
            return validConfigurations, mapping_full_path
        return False, [], []
    except Exception as e:
        logger.exception("Error in pulling mappings from vendor apps")
        logger.error(e)

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
            timeout=180
        )
    except Exception as e:
        logger.info("Failed push configurations into kvstore: %s"% e)

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
logger = setup_logger('netflow_pull_mappings')
