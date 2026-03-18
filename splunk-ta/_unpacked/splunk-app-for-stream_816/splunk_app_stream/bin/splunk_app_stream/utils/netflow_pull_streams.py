import logging
import os
import re
import json
import tempfile
import jsonschema
import splunk
import splunk.clilib.cli_common

try:
    import xml.etree.cElementTree as ET
except:
    import defusedxml.ElementTree as ET

from splunk.clilib import cli_common as cli
import splunk.appserver.mrsparkle.lib.util as util
import splunk_app_stream.utils.stream_utils as stream_utils
import splunk.appserver.mrsparkle.lib.apps as apps
from splunk_app_stream.models.vocabulary import Vocabulary
import splunk_app_stream.utils.netflow_utils as netflow_utils
from splunk_app_stream.models.ping import Ping

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

# It will use Vocabulary GET ALL method
# Also it will go to each ipfix app and find vocabulary file and merge the term with GET ALL terms
def get_all_vocab_terms(app_full_path, sessionKey):
    
    default_path = os.path.join(app_full_path, "default")
    local_path = os.path.join(app_full_path, "local")
    
    try:
        ET.register_namespace("", "http://purl.org/cloudmeter/config")
        combinedVocab = ET.Element('Vocabulary')

        response = Vocabulary.list(sessionKey)

        tree = ET.fromstring(response)
        vocab = tree.find('{http://purl.org/cloudmeter/config}Vocabulary')

        for term in vocab.findall('{http://purl.org/cloudmeter/config}Term'):
            combinedVocab.append(term)

        if os.path.exists(default_path):
            for file in os.listdir(default_path):
                if file.endswith('.xml'):
                    tree = ET.parse(os.path.join(default_path, file))
                    vocab = tree.find('{http://purl.org/cloudmeter/config}Vocabulary')
                    for term in vocab.findall('{http://purl.org/cloudmeter/config}Term'):
                        combinedVocab.append(term)
        
        if os.path.exists(local_path):
            for file in os.listdir(local_path):
                if file.endswith(".xml"):
                    tree = ET.parse(os.path.join(local_path, file))
                    vocab = tree.find("{http://purl.org/cloudmeter/config}Vocabulary")
                    for term in vocab.findall("{http://purl.org/cloudmeter/config}Term"):
                        combinedVocab.append(term)
        
        xmlOut = ET.ElementTree(ET.Element("CmConfig"))
        xmlOut.getroot().set('version', stream_utils.getAppVersion())
        xmlOut.getroot().append(combinedVocab)

        try:
            temp = tempfile.TemporaryFile()

            try:
                xmlOut.write(temp, xml_declaration=True, encoding='UTF-8')
                temp.seek(0)
                content = temp.read().decode('utf-8')
            finally:
                temp.close()
                return content

        except Exception:
            logger.error("IOerror, unable to create temp file")

    except Exception as e:
        logger.error(e)

def fetch_fields(filePath):
    try:
        if not filePath:
            return "Please provide absolute file path"

        all_fields = []
        with open(filePath) as fp:
            data = json.load(fp)
            if len(data):
                for index in range(len(data['fields'])):
                    all_fields.append(data['fields'][index]['term'])
        return all_fields
    except (OSError, ValueError):
        logger.exception("Exception occured while fetching fields from streams")
        logger.error(OSError)

def validateStreamFile(app_full_path, file_path, session_key):
    content = open(file_path, 'rb').read()
    stream_json = json.loads(content)
    all_terms = get_all_vocab_terms(app_full_path, session_key)
    is_valid_stream, stream_validation_messages = stream_utils.is_valid_stream_definition_new(stream_json, all_terms)
    return is_valid_stream, stream_validation_messages

def streams_apply_layering(app_full_path, validStreams, session_key):

    global dateLastUpdated

    is_error = False
    default_path = os.path.join(app_full_path, 'default')
    local_path = os.path.join(app_full_path, 'local')

    full_app_name = app_full_path.split("/")[-1]
    app_short_name = full_app_name.split("splunk_app_stream_ipfix_")[-1]

    final_streams = []
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
            if file.endswith('.json'):
                default_files.add(file)

                file_path = os.path.join(default_path, file)
                is_valid_stream, stream_validation_messages = validateStreamFile(app_full_path, file_path, session_key)

                if not is_valid_stream:
                    validStreams[app_short_name] = False
                    break

                # Checking if file content has changed or not
                isFileChangedInIpfixApp = stream_utils.is_file_modified(file_path, dateLastUpdated)
                if isFileChangedInIpfixApp:
                    isAppContentChanged = True

    if os.path.exists(local_path):
        local_files = set()

        # Checking if directory has changed or not
        isFileChangedInIpfixApp = stream_utils.is_file_modified(os.path.join(local_path), dateLastUpdated)
        if isFileChangedInIpfixApp:
            isAppContentChanged = True

        for file in os.listdir(local_path):
            if file.endswith('.json'):
                local_files.add(file)

                file_path = os.path.join(local_path, file)
                is_valid_stream, stream_validation_messages = validateStreamFile(app_full_path, file_path, session_key)

                if not is_valid_stream:
                    validStreams[app_short_name] = False
                    break

                # Checking if file content has changed or not
                isFileChangedInIpfixApp = stream_utils.is_file_modified(file_path, dateLastUpdated)
                if isFileChangedInIpfixApp:
                    isAppContentChanged = True

    vocab_terms = netflow_utils.fetch_terms(session_key=session_key)

    matched_file_names = list(default_files & local_files)
    Unmatch_default_files = list(default_files - local_files)
    Unmatch_local_files = list(local_files - default_files)
    
    if validStreams[app_short_name] == False:
        return default_path, local_path, default_files, local_files, final_streams, validStreams, isAppContentChanged

    # Validate unmatched default file
    if len(Unmatch_default_files):
        for i, val in enumerate(Unmatch_default_files):
            default_fields = fetch_fields(os.path.join(default_path, val))

            b = netflow_utils.fetch_new_vocab_terms()
            foundUnmatchedTerms = set(default_fields) - set(vocab_terms) - set(b)
            
            if len(foundUnmatchedTerms):
                logger.info("Some of the term that is present in the stream file, which is not matching with vocabulary terms")
                logger.info("File location: %s"% os.path.join(default_path, val))
                validStreams[app_short_name] = False
                break

    # Validate unmatched local file
    if len(Unmatch_local_files):
        for i, val in enumerate(Unmatch_local_files):
            local_fields = fetch_fields(os.path.join(local_path, val))

            b = netflow_utils.fetch_new_vocab_terms()
            foundUnmatchedTerms = set(local_fields) - set(vocab_terms) - set(b)
            
            # If found unmatched terms we are setting valid streams to false
            if len(foundUnmatchedTerms):
                logger.info("Some of the term that is present in the stream file, which is not matching with vocabulary terms")
                logger.info("File location: %s"% os.path.join(default_path, val))
                validStreams[app_short_name] = False
                break

    # Validate matched files
    if len(matched_file_names) and validStreams[app_short_name] == True:
        for fileName in matched_file_names:
            default_fields = fetch_fields(os.path.join(default_path, fileName))
            local_fields = fetch_fields(os.path.join(local_path, fileName))

            # unique_field = default_fields + local_fields
            b = netflow_utils.fetch_new_vocab_terms()
            foundUnmatchedTermsInDefault = set(default_fields) - set(vocab_terms) - set(b)
            foundUnmatchedTermsInLocal = set(local_fields) - set(vocab_terms) - set(b)
            
            if len(foundUnmatchedTermsInDefault):
                validStreams[app_short_name] = False
                logger.info("Some of the term that is present in the stream file, which is not matching with vocabulary terms")
                logger.info("File location: %s"% os.path.join(default_path, fileName))
                break
            
            if len(foundUnmatchedTermsInLocal):
                validStreams[app_short_name] = False
                logger.info("Some of the term that is present in the stream file, which is not matching with vocabulary terms")
                logger.info("File location: %s"% os.path.join(local_path, fileName))
                break

            matched_field = list(set(default_fields) & set(local_fields))
            updated_fields = []
            updated_streams = {}

            with open(os.path.join(default_path, fileName)) as fp:
                data = json.load(fp)
                updated_streams = data.copy()
                updated_fields = updated_streams['fields']

                if len(data):
                    for index in range(len(data['fields'])):
                        term = data['fields'][index]['term']
                        if term in matched_field:
                            updated_fields[index] = False

            with open(os.path.join(local_path, fileName)) as fp:
                data = json.load(fp)
                updated_streams = data.copy()
                if len(data):
                    for index in range(len(data['fields'])):
                        term = data['fields'][index]['term']
                        updated_fields.append(data['fields'][index])

            try:
                while True:
                    updated_fields.remove(False)
            except ValueError:
                pass
            
            updated_streams['fields'] = updated_fields
            config = {
                'fileName': str(app_short_name) + "_" + str(fileName.split('.')[0]),
                'content': updated_streams
            }
            final_streams.append(config)

    return default_path, local_path, default_files, local_files, final_streams, validStreams, isAppContentChanged

def get_streams(PATH, session_key, validConfigurations, apps_stored_in_kvstore):

    try:
        if len(PATH):

            get_last_updated_date_time(session_key)
            stream_full_path = []
            validStreams = {}
            
            for i in range(len(PATH)):

                full_app_name = str(PATH[i]).split("/")[-1]
                app_short_name = full_app_name.split("splunk_app_stream_ipfix_")[-1]
                
                stream_file_path = {}
                stream_file_path['is_valid'] = True
                stream_file_path["app_short_name"] = app_short_name
                
                # Pull the Stream from the ipfix app only if the configurations is valid for that app
                if validConfigurations.get(app_short_name) == True:
                    validStreams[app_short_name] = True

                    default_path, local_path, default_files, local_files, final_streams, validStreams, isAppContentChanged = streams_apply_layering(str(PATH[i]), validStreams, session_key)
                    stream_file_path['final_streams'] = final_streams
                    stream_file_path['isAppContentChanged'] = isAppContentChanged
                    stream_file_path['is_valid'] = validStreams[app_short_name]

                    # Streams: Removing the duplicates files from default/local directory
                    default_streams = list(set(default_files) - set(local_files))
                    local_streams = list(set(local_files) - set(default_files))

                    # Streams: Make default full path
                    default_tmpArr = []
                    if len(default_streams):
                        for j in default_streams:
                            default_tmpArr.append(os.path.join(str(PATH[i]), 'default', str(j)))
                    stream_file_path['default_path'] = default_tmpArr

                    # Streams: Make local full path
                    local_tmpArr = []
                    if len(local_streams):
                        for j in local_streams:
                            local_tmpArr.append(os.path.join(str(PATH[i]), 'local', str(j)))

                    stream_file_path['local_path'] = local_tmpArr
                else:
                    stream_file_path['is_valid'] = False
                    
                stream_full_path.append(stream_file_path)
            return validStreams, stream_full_path
        return []
    except Exception as e:
        logger.exception("Error in pulling streams from vendor apps")
        logger.error(e)

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
logger = setup_logger('netflow_pull_streams')
