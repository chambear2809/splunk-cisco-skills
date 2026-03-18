import logging
import os
import json
import tempfile
import re

try:
    import xml.etree.cElementTree as ET
except:
    import defusedxml.ElementTree as ET

import splunk
import splunk.clilib.cli_common
from splunk.clilib import cli_common as cli
import splunk.appserver.mrsparkle.lib.util as util
import splunk_app_stream.utils.stream_utils as stream_utils
import splunk_app_stream.utils.netflow_utils as netflow_utils
import splunk_app_stream.utils.stream_kvstore_utils as kv_utils
import splunk.appserver.mrsparkle.lib.apps as apps
from splunk_app_stream.models.vocabulary import Vocabulary
from splunk_app_stream.models.ping import Ping

# kv store
use_kv_store = kv_utils.is_kv_store_supported_in_splunk()

# vocabulary endpoint
rest_vocab_uri = "/services/splunk_app_stream/vocabularies/"

# Last updated time used to refresh cache
dateLastUpdated = 0

def get_last_updated_date_time(session_key):
    global dateLastUpdated
    try:
        if not dateLastUpdated:
            appsMeta = Ping.ping(session_key)
            dateLastUpdated = appsMeta['dateLastUpdated']
    except Exception:
        # Exception happens as appsMeta file is in the process of getting written to.
        logger.exception("Failed to get appsMeta")

# This function will validate the xml files
def validate_xml_files(filePath):
    xml_schema_data = open(filePath, "rb").read()
    try:
        result = Vocabulary.validateXML(xml_schema_data)
        if (type(result) is dict) and result["success"] == False:
            logger.error("Found issue in vocabulary file: %s"% result["error"])
            return False
        else:
            return True
    except Exception as e:
        logger.error(e)

# This function will find duplicates files from default and local directory, validate common files and apply layering concept
def vocabulary_apply_layering(app_full_path, session_key):

    global dateLastUpdated

    default_path = os.path.join(app_full_path, 'default')
    local_path = os.path.join(app_full_path, 'local')
    full_app_name = app_full_path.split("/")[-1]
    app_short_name = full_app_name.split("splunk_app_stream_ipfix_")[-1]

    default_files = set()
    local_files = set()
    final_vocabs = []
    isAppContentChanged = False

    if os.path.exists(default_path):
        default_files = set()

        # Checking if directory has changed or not
        isFileChangedInIpfixApp = stream_utils.is_file_modified(os.path.join(default_path), dateLastUpdated)
        if isFileChangedInIpfixApp:
            isAppContentChanged = True

        for file in os.listdir(default_path):
            if file.endswith('.xml'):
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
            if file.endswith('.xml'):
                local_files.add(file)

                # Checking if file content has changed or not
                isFileChangedInIpfixApp = stream_utils.is_file_modified(os.path.join(local_path, file), dateLastUpdated)
                if isFileChangedInIpfixApp:
                    isAppContentChanged = True

    matched_file_names = list(default_files & local_files)

    if len(matched_file_names):
        for fileName in matched_file_names:

            # Validate matched XML files
            isValidDefaultFile = validate_xml_files(os.path.join(default_path, fileName))
            isValidLocalFile = validate_xml_files(os.path.join(local_path, fileName))

            if isValidDefaultFile == False or isValidLocalFile == False:
                return default_path, local_path, default_files, local_files, final_vocabs, isAppContentChanged, False

            default_terms = netflow_utils.fetch_terms(os.path.join(default_path, fileName))
            local_terms = netflow_utils.fetch_terms(os.path.join(local_path, fileName))
            matched_terms = list(set(default_terms) & set(local_terms))

            ET.register_namespace("", "http://purl.org/cloudmeter/config")
            combinedVocab = ET.Element('Vocabulary')

            tree = ET.parse(os.path.join(default_path, fileName))
            vocab = tree.find('{http://purl.org/cloudmeter/config}Vocabulary')
            for term in vocab.findall('{http://purl.org/cloudmeter/config}Term'):
                element_id = term.attrib.get('id')
                if element_id not in matched_terms: 
                    combinedVocab.append(term)

            local_tree = ET.parse(os.path.join(local_path, fileName))
            local_vocab = local_tree.find('{http://purl.org/cloudmeter/config}Vocabulary')
            for term in local_vocab.findall('{http://purl.org/cloudmeter/config}Term'):
                combinedVocab.append(term)

            xmlOut = ET.ElementTree(ET.Element("CmConfig"))
            xml_schema_data = open(os.path.join(default_path, fileName), 'rb' ).read()
            root = ET.fromstring(xml_schema_data)
            version = root.attrib.get('version')
            xmlOut.getroot().set('version', version)

            xmlOut.getroot().append(combinedVocab)
            
            temp = tempfile.NamedTemporaryFile(suffix=fileName, prefix='vocabs_')
            xmlOut.write(temp)
            temp.seek(0)
            content = temp.read().decode('utf-8')
            vocab_content = {
                'fileName': str(app_short_name) + "_" + str(fileName.split('.')[0]),
                'content': content
            }
            final_vocabs.append(vocab_content)

    return default_path, local_path, default_files, local_files, final_vocabs, isAppContentChanged, True

def is_vocab_file_exist_in_local_dir(fileName):
    LOCAL_DIR = os.path.join(util.get_apps_dir(), 'splunk_app_stream', 'local')
    if not os.path.exists(LOCAL_DIR):
        os.makedirs(LOCAL_DIR)

    VOCAB_DIR = os.path.join(util.get_apps_dir(), 'splunk_app_stream', 'local', 'vocabularies')
    if not os.path.exists(VOCAB_DIR):
        os.makedirs(VOCAB_DIR)

    file_path = os.path.join(util.get_apps_dir(), 'splunk_app_stream', 'local', 'vocabularies') + f"/{fileName}.xml"

    if os.path.isfile(file_path):
        logger.error("Found issue in vocabulary file: Filename is already exists..")
        return True
    
    return False

def get_vocabs(PATH, session_key, apps_stored_in_kvstore):

    try:
        if len(PATH):

            get_last_updated_date_time(session_key)
            vocab_full_path = []
            validVocabs = {}
            isValidVocabulary = True
            isFileExists = False

            for i in range(len(PATH)):

                full_app_name = str(PATH[i]).split("/")[-1]
                app_short_name = full_app_name.split("splunk_app_stream_ipfix_")[-1]

                vocab_file_path = {}
                vocab_file_path["is_valid"] = True
                vocab_file_path["app_short_name"] = app_short_name
                
                validVocabs[app_short_name] = True

                default_path, local_path, default_files, local_files, final_vocabs, isAppContentChanged, isValidCommonFiles = vocabulary_apply_layering(str(PATH[i]), session_key)
                vocab_file_path['final_vocabs'] = final_vocabs
                vocab_file_path['isAppContentChanged'] = isAppContentChanged

                # If any issues found in the common XML files then break the code from here
                if isValidCommonFiles == False:
                    vocab_file_path["is_valid"] = False
                    validVocabs[app_short_name] = False
                    break

                default_vocabs = list(set(default_files) - set(local_files))
                local_vocabs = list(set(local_files) - set(default_files))

                default_tmpArr = []
                if len(default_vocabs):
                    for j in default_vocabs:
                        default_tmpArr.append(os.path.join(str(PATH[i]), 'default', str(j)))

                vocab_file_path["default_path"] = default_tmpArr

                local_tmpArr = []
                if len(local_vocabs):
                    for j in local_vocabs:
                        local_tmpArr.append(os.path.join(str(PATH[i]), 'local', str(j)))

                vocab_file_path["local_path"] = local_tmpArr

                # Validate Unmatched XML files
                default_local_tmpArr = default_tmpArr + local_tmpArr
                for index in range(len(default_local_tmpArr)):
                    isValid = validate_xml_files(default_local_tmpArr[index])
                    if isValid == False:
                        vocab_file_path["is_valid"] = False
                        validVocabs[app_short_name] = False
                        break
                    
                vocab_full_path.append(vocab_file_path)

            return validVocabs, vocab_full_path
        return False, []
    except Exception as e:
        logger.error("Error in pulling vocabularies from vendor apps")

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
logger = setup_logger('netflow_pull_vocabs')
