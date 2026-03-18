import os
import tempfile
import threading

try:
    import xml.etree.cElementTree as ET
except:
    import defusedxml.ElementTree as ET

from lxml import etree
import splunk.appserver.mrsparkle.lib.util as util

import splunk_app_stream.utils.stream_utils as stream_utils
import splunk_app_stream.utils.stream_kvstore_utils as kv_utils
import splunk
import re
import shutil
from splunk_app_stream.models.configuration import Configuration

lock = threading.Lock()

# flag to wait for upgrade to finish
run_once = True

default_terms = []

logger = stream_utils.setup_logger('vocabulary')
use_kv_store = kv_utils.is_kv_store_supported_in_splunk()

vocabsDir = os.path.join(util.get_apps_dir(), 'splunk_app_stream', 'default', 'vocabularies')
schema_file = os.path.join(util.get_apps_dir(), 'splunk_app_stream', 'default', 'vocabulary')

def get_default_vocabs_terms():
    global default_terms
    for fname in os.listdir(vocabsDir):
        tree = ET.parse(vocabsDir + os.sep + fname)
        vocab = tree.find('{http://purl.org/cloudmeter/config}Vocabulary')
        for term in vocab.findall('{http://purl.org/cloudmeter/config}Term'):
            default_terms.append(term)

get_default_vocabs_terms()

class Vocabulary:

    @staticmethod
    # This function will return the list of vocabularies, if session_key is available we will get the data of kvstore as well
    # Else default vocabularies will be returned
    def list(session_key=None):
       
        global lock, run_once, default_terms

        ET.register_namespace("", "http://purl.org/cloudmeter/config")
        combinedVocab = ET.Element('Vocabulary')
        content = None

        '''Return list of vocabularies'''
        
        if use_kv_store:

            if session_key:
                uri = kv_utils.vocabularies_kv_store_coll
                response = kv_utils.read_from_kv_store_coll(uri, session_key)
            else:
                response = {}

        else:
            return {'success': False, 'error': 'Internal error, kvstore is not supported', 'status': 400}
        
        for i in response:
            tree = ET.fromstring(i['data'])
            vocab = tree.find('{http://purl.org/cloudmeter/config}Vocabulary')
            for term in vocab.findall('{http://purl.org/cloudmeter/config}Term'):
                combinedVocab.append(term)

        if not default_terms:
            logger.error("models::vocabulary No default terms")
            get_default_vocabs_terms()

        for i in default_terms:
            combinedVocab.append(i)

        xmlOut = ET.ElementTree(ET.Element("CmConfig"))
        xmlOut.getroot().set('version', stream_utils.getAppVersion())
        xmlOut.getroot().append(combinedVocab)
        # FIXME, get rid of temp file

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

    @staticmethod
    # This function will use dummy XML file in default folder to validate the incoming new data for vocabs
    def validateXML(body):

        '''Validate the XML file'''
        global lock
        lock.acquire()
        # Parse the XML
        xml_schema_data = open(schema_file, 'rb' ).read()
        schema_root = etree.XML(xml_schema_data)

        try:
            schema = etree.XMLSchema(schema_root)
            xmlparser = etree.XMLParser(schema=schema)
            root = ET.fromstring(body, xmlparser)

            # Find the duplicate element id
            listOfElems = []
            listOfTypes = []

            # Validate Type
            allowedTypes = ["string", "blob", "object", "datetime", "uint16", "uint32", "uint8", "shortstring", "double", "uint64", "int64"]

            for terms in root.find('{http://purl.org/cloudmeter/config}Vocabulary'):
                for term in terms.iter('{http://purl.org/cloudmeter/config}Term'):
                    for eachType in term.iter('{http://purl.org/cloudmeter/config}Type'):
                        listOfTypes.append(eachType.text)
                    if term.attrib.get('id'):
                        listOfElems.append(term.attrib.get('id'))

            # Commenting validation for version field
            # if root.attrib.get('version') == None:
            #     return {'success': False, 'error': "Missing version attribute", 'status': 400}

            # if stream_utils.getAppVersion() != root.attrib.get('version'):
            #     return {'success': False, 'error': "Version field value should be same as Stream app version", 'status': 400}

            if None in listOfTypes:
                return {'success': False, 'error': "Empty Type element found", 'status': 400}

            for eachType in listOfTypes:
                if (eachType not in allowedTypes):
                    return {'success': False, 'error': str(eachType) + " Type is not valid", 'status': 400}

            if len(listOfElems) != len(set(listOfElems)):
                return {'success': False, 'error': "Found duplicate element id", 'status': 400}
            return True

        except etree.XMLSyntaxError as e:
            logger.error(e)
            return {'success': False, 'error': "XML Syntax Error: " + str(e), 'status': 400}
        finally:
            lock.release()

    @staticmethod
    # This function will delete the vocabulary finding the dependent configurations and streams
    def delete(id='', session_key=None):

        global lock
        lock.acquire()
        try:
            if not id:
                return {'success': False, 'error': str("Invalid Request Data"), 'status': 400}

            # Sanitize id to prevent directory traversal attack
            id = os.path.basename(id)
        
            if use_kv_store:
                uri = kv_utils.vocabularies_kv_store_coll
                main_id = id.split(".")

                try:
                    response = kv_utils.delete_by_id_from_kv_store_coll(uri, main_id[0], session_key)
                    return response
                except Exception as e:
                    logger.error(e)
                    return {'success': False, 'error': e, 'status': 400}
                        
            return {'success': True, 'deleted': 'File' + str(id) + ' has been deleted successfully'}

        except Exception as e:
            logger.error(e)
            return {'success': False, 'error': 'Internal error while deleting vocabulary', 'status': 400}
        finally:
            lock.release()
