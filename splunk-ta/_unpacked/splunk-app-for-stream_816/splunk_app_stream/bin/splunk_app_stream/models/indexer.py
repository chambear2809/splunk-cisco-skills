import json
import os
import re
import time

import splunk
import splunk.appserver.mrsparkle.lib.util as util

import splunk_app_stream.utils.stream_utils as stream_utils
import splunk_app_stream.utils.stream_kvstore_utils as kv_utils

from splunk_app_stream.models.stream_forwarder_group import StreamForwarderGroup

logger = stream_utils.setup_logger('indexer')

indexerCacheMaxAge = 10

# Cache indexers list and modified time of the file
indexersFile = os.path.join(util.get_apps_dir(), 'splunk_app_stream', 'local', 'indexers')
try:
    indexersFileMtime = int(os.stat(indexersFile).st_mtime)
    indexers = open(indexersFile, 'r').read()
except Exception as e:
    indexersFileMtime = 0
    indexers = '{"collectors":[]}'


# get indexers list by making API call to splunkd
def get_indexers():
    content = None
    auth_key = kv_utils.get_internal_shared_key()
    try:
        uri = 'splunk_app_stream/indexers?output_mode=json&X-SPLUNK-APP-STREAM-KEY=' + auth_key
        serverResponse, serverContent = splunk.rest.simpleRequest(
            util.make_url(uri, translate=False, relative=True, encode=False),
            '',
            postargs=None,
            method='GET',
            raiseAllErrors=True,
            proxyMode=False,
            rawResult=None,
            jsonargs=None,
            timeout=splunk.rest.SPLUNKD_CONNECTION_TIMEOUT
        )

        if serverResponse['status'] == '200':
            jsonResp = json.loads(serverContent)
            if len(jsonResp['entry'][0]['content']) > 0:
                content = jsonResp['entry'][0]['content']

    except Exception:
        logger.exception("failed to list indexers")
        raise splunk.RESTException(500, 'Internal error, failed to get indexers')

    return content

# Get global HEC config and return JSON
def get_http_inputs_configs():
    config = {}
    auth_key = kv_utils.get_internal_shared_key()
    try:
        uri = 'splunk_app_stream/httpinputs/configs?output_mode=json&X-SPLUNK-APP-STREAM-KEY=' + auth_key
        serverResponse, serverContent = splunk.rest.simpleRequest(
            util.make_url(uri, translate=False, relative=True, encode=False),
            '',
            postargs=None,
            method='GET',
            raiseAllErrors=True,
            proxyMode=False,
            rawResult=None,
            jsonargs=None,
            timeout=splunk.rest.SPLUNKD_CONNECTION_TIMEOUT
        )

        if serverResponse['status'] == '200':
            jsonResp = json.loads(serverContent)
            config = jsonResp['entry'][0]['content']

    except Exception:
        logger.exception("failed to get HEC config")
        raise splunk.RESTException(500, 'Internal error, failed to get HEC config')

    return config

# Get HTTP inputs config and return collection
def get_http_inputs():
    inputs = []
    auth_key = kv_utils.get_internal_shared_key()
    try:
        uri = 'splunk_app_stream/httpinputs?output_mode=json&X-SPLUNK-APP-STREAM-KEY=' + auth_key
        serverResponse, serverContent = splunk.rest.simpleRequest(
            util.make_url(uri, translate=False, relative=True, encode=False),
            '',
            postargs=None,
            method='GET',
            raiseAllErrors=True,
            proxyMode=False,
            rawResult=None,
            jsonargs=None,
            timeout=splunk.rest.SPLUNKD_CONNECTION_TIMEOUT
        )

        if serverResponse['status'] == '200':
            jsonResp = json.loads(serverContent)
            inputs = jsonResp['entry'][0]['content']

    except Exception:
        logger.exception("failed to get HEC inputs")
        raise splunk.RESTException(500, 'Internal error, failed to get HEC inputs')

    return inputs

# Construct JSON object with list of indexers
def construct_indexers():
    output = {}
    output["collectors"] = []

    disabled = True
    try:
        httpInputs = get_http_inputs()
        for input in httpInputs:
            matchObj = re.match(r'^http://streamfwd', input['name'])
            matchObj2 = re.match(r'^streamfwd', input['name'])
            if matchObj or matchObj2:
                output['token'] = input['content']['token']
                if input['content']['disabled']=="false":
                    input['content']['disabled'] = False
                elif input['content']['disabled']=="true":
                    input['content']['disabled'] = True
                disabled = input['content']['disabled']
                try:
                    flutterShy = input['content']['useACK']
                    output['headerMeta'] = True
                except KeyError:
                    output['headerMeta'] = False
                break
    except Exception:
        logger.exception("failed to get HEC streamfwd endpoint")
        raise splunk.RESTException(500, 'Internal error, failed to get HEC streamfwd endpoint')

    jsonResp = get_indexers()
    if jsonResp:
        try:
            # List of indexers only has host name, assume enableSSL and port are based on local HEC config
            config = get_http_inputs_configs()
            if config['disabled'] == False:
                enableSSL = (config['enableSSL'] == "1")
                port = config['port']
            else:
                enableSSL = True
                port = 8088

            for entry in jsonResp:
                if entry['content']['host_fqdn'] != '':
                    if enableSSL:
                        uri = 'https://' + entry['content']['host_fqdn'] + ':' + str(port)
                    else:
                        uri = 'http://' + entry['content']['host_fqdn'] + ':' + str(port)
                    output["collectors"].append(uri)

        except Exception:
            logger.exception("failedto construct indexer list from cluster setup")
            raise splunk.RESTException(500, 'Internal error, failed to construct indexers list from indexers cluster setup')
    else:
        logger.info("no indexer cluster and SH is not an indexer or HEC is not enabled")
        # assume single-tier SH+IDX instance
        try:
            config = get_http_inputs_configs()
            if config['disabled'] == False:
                if disabled == False:
                    if config['host'] != '':
                        if config['enableSSL'] == "1":
                            uri = 'https://' + config['host'] + ':' + config['port']
                        else:
                            uri = 'http://' + config['host'] + ':' + config['port']

                        output['collectors'].append(uri)

        except Exception:
            logger.exception("failed to construct indexer list from standalone setup")
            raise splunk.RESTException(500, 'Internal error, failed to construct indexers list from stand alone setup')

    return json.dumps(output)

def is_cache_expired():
    global indexersFileMtime, indexerCacheMaxAge
    now = int(time.time())
    if indexersFileMtime + indexerCacheMaxAge < now:
        return True
    else:
        return False

# Return True if indexers list is updated
def update_indexers():
    global indexers, indexersFile, indexersFileMtime

    # Check if cache is expired
    if not is_cache_expired():
        return False

    tmp_indexers = construct_indexers()
    indexersFileMtime = int(time.time())

    if stream_utils.ordered(tmp_indexers) != stream_utils.ordered(indexers):
        indexers = tmp_indexers
        fio = open(indexersFile, 'w')
        fio.write(indexers)
        return True

    return False


class Indexer:

    @staticmethod
    def list(id='', **kwargs):
        global indexersFile, indexers
        update_indexers()  
        stream_forwarder_id_param_supplied = 'streamForwarderId' in kwargs
        # streamForwarderId param not present, then return the autoConfig indexers, GUI will not send this parameter
        if not id and not stream_forwarder_id_param_supplied:
            return indexers  
        elif not id:
            id = kwargs.get('streamForwarderId', '')
  
        stream_forwarder_groups = StreamForwarderGroup.match(id)
        hec_indexers = set()
        json_indexers = json.loads(indexers)
        for group in stream_forwarder_groups:
            if 'hec' in group:
                #autoConfig is False
                if 'urls' in group['hec']:
                    hec_indexers = hec_indexers | set(group['hec']['urls'])
                else:
                    if 'collectors' in json_indexers:
                        hec_indexers = hec_indexers | set(json_indexers['collectors'])

        stream_fwder_indexers = json_indexers
        stream_fwder_indexers['collectors'] = list(hec_indexers)
        return json.dumps(stream_fwder_indexers)


    @staticmethod
    def delete():
        global indexersFileMtime, indexers
        try:
            '''Reset Mtime to 0, so that force to GET latest indexers'''
            indexersFileMtime = 0
            return {'success': True}

        except Exception:
            logger.exception("failed to flush indexer cache")
            return {'success': False, 'error': 'Internal error, flush indexers cache', 'status': 500}
