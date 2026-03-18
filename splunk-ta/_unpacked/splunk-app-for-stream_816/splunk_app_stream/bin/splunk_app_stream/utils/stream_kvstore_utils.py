import json
import os
import time
import uuid

import splunk
import splunk.appserver.mrsparkle.lib.util as util

import splunk_app_stream.utils.stream_utils as stream_utils


logger = stream_utils.setup_logger('stream_kvstore_utils')
data_store_file = os.path.join(util.get_apps_dir(), 'splunk_app_stream', 'local') + os.sep + ".data_store"
misc_kv_store_uri = '/servicesNS/nobody/splunk_app_stream/storage/collections/data/miscellaneous'
streams_kv_store_coll = '/servicesNS/nobody/splunk_app_stream/storage/collections/data/streams'
configurations_kv_store_coll = '/servicesNS/nobody/splunk_app_stream/storage/collections/data/configurations'
netflow_ipfix_apps_info_kv_store_coll = '/servicesNS/nobody/splunk_app_stream/storage/collections/data/netflow_ipfix_apps_info'
vocabularies_kv_store_coll = '/servicesNS/nobody/splunk_app_stream/storage/collections/data/vocabularies'
stream_forwarder_groups_kv_store_coll = '/servicesNS/nobody/splunk_app_stream/storage/collections/data/streamforwardergroups'
file_server_mount_points_kv_store_coll = '/servicesNS/nobody/splunk_app_stream/storage/collections/data/fileservermountpoints'
kv_store_ready = None
is_supported = None
server_roles = None
splunkd_ready = None
splunkd_fatal_error = False
kvstore_fatal_error = False
splunkd_time_out = splunk.rest.SPLUNKD_CONNECTION_TIMEOUT - 1
splunkd_connection_exceptions = ['The handshake operation timed out', 'Connection refused']

def is_splunkd_ready(sessionKey=None):
    global splunkd_ready
    if splunkd_ready is None:
        server_info = get_server_roles(sessionKey)
        if server_info is not None:
            splunkd_ready = True
        elif splunkd_fatal_error:
            splunkd_ready = False
    if kvstore_fatal_error:
        splunkd_ready = False
    else:
        kvStoreStatus = get_kv_store_status()
        if kvstore_fatal_error:
            splunkd_ready = False

    return splunkd_ready


def is_search_head_shc_member(sessionKey=None):
    global server_roles
    if server_roles is None:
        server_roles = get_server_roles(sessionKey)
    if server_roles is not None and ('shc_member' in server_roles or 'shc_captain' in server_roles):
        return True
    else:
        return False

def get_vocab_terms():
    auth_key = get_internal_shared_key()
    try:
        serverResponse, serverContent = splunk.rest.simpleRequest(
            util.make_url_internal("/services/splunk_app_stream/vocabularies/"),    
            getargs={'output_mode':'json' , 'X-SPLUNK-APP-STREAM-KEY':auth_key},
            method='GET',
            raiseAllErrors=True,
            rawResult=None,
            jsonargs=None,
            timeout=splunk.rest.SPLUNKD_CONNECTION_TIMEOUT
        )
        jsonResp = json.loads(serverContent)
        vocab_terms = jsonResp['entry'][0]['content']
        return vocab_terms
    except Exception as e:
        logger.info("Failed to fetch vocabularies from kvstore: %s"% e)

def get_server_info(server_info_key, proxy_uri, sessionKey=None):
    global splunkd_fatal_error
    
    if splunkd_fatal_error:
        return None
        
    try:
        if not sessionKey:
            # proxy via splunkd REST endpoint         
            serverResponse, serverContent = splunk.rest.simpleRequest(
                util.make_url_internal(proxy_uri + '?output_mode=json'),
                sessionKey='',
                postargs=None,
                method='GET',
                raiseAllErrors=True,
                proxyMode=False,
                rawResult=None,
                jsonargs=None,
                timeout=splunkd_time_out
            )
            jsonResp = json.loads(serverContent)
            server_info_val = jsonResp["entry"][0]["content"]
        else:
            uri = '/services/server/info'
            serverResponse, serverContent = splunk.rest.simpleRequest(
                util.make_url_internal(uri + '?output_mode=json'),
                sessionKey,
                postargs=None,
                method='GET',
                raiseAllErrors=True,
                proxyMode=False,
                rawResult=None,
                jsonargs=None,
                timeout=splunkd_time_out
            )
            jsonResp = json.loads(serverContent)
            server_info_val = jsonResp["entry"][0]["content"][server_info_key]
        logger.debug('get_server_info: server_info key::val::%s::%s', server_info_key, server_info_val)
        return server_info_val
    except Exception as e:
        logger.exception("failed to get server info")
        if any(s in str(e) for s in splunkd_connection_exceptions):
            splunkd_fatal_error = True

        return None

def get_server_roles(sessionKey=None):
    return get_server_info("server_roles", '/services/splunk_app_stream/serverroles', sessionKey)


def get_kv_store_status(sessionKey=None):
    global kvstore_fatal_error
    kvStoreStatus = get_server_info("kvStoreStatus", '/services/splunk_app_stream/kvstorestatus', sessionKey)
    if kvStoreStatus == 'failed':
        logger.error("KV store failed to start, setting the  kv store fatal error flag to true")
        kvstore_fatal_error = True
    logger.info('get_kv_store_status::kvStoreStatus::%s', kvStoreStatus)

    if kvStoreStatus is not None:
        return kvStoreStatus
    else:
        return 'unknown'

def is_kv_store_supported_in_splunk(sessionKey=None):
    # check the version for 6.3+ and if KV store is enabled
    global is_supported

    if is_supported is not None:
        return is_supported

    splunk_version = int (splunk.getReleaseVersion().replace('.', ''))
    data_store = stream_utils.readAsJson(data_store_file)

    is_supported = True
    if data_store != 'NotFound':
        if data_store['type'] == 'kv_store':
            return is_supported
    
    data_store = {}
    data_store['type'] = 'json_file'
    if splunk_version > 630:
        kvStoreStatus = get_kv_store_status(sessionKey)
        logger.debug("is_kv_store_supported_in_splunk kvStore Status :: %s", kvStoreStatus)
        if kvStoreStatus != 'unavailable' and kvStoreStatus != 'unknown':
            'save the state in a datastore file'                
            data_store['type'] = 'kv_store'
        else:
            is_supported = False
    else:
        is_supported = False

    # save it to file
    try:
        base_local_dir = os.path.join(util.get_apps_dir(), 'splunk_app_stream', 'local')
        if not os.path.exists(base_local_dir):
            stream_utils.createDir(base_local_dir + os.sep)
        f = open( data_store_file, 'w+' )
        f.write(json.dumps(data_store, sort_keys=True, indent=2))
        f.close()
    except:
        logger.error('Unable to create the data_store file')

    return is_supported

def is_kv_store_ready(sessionKey=None):
    tries = 1
    is_ready = False
    global kvstore_fatal_error
    kvStoreStatus = get_kv_store_status(sessionKey)
    while not splunkd_fatal_error and not kvstore_fatal_error and kvStoreStatus != 'ready' and tries < 6: 
        # incremental wait duration with a total wait of 30secs if max tries is reached   
        sleep_time = 2 * tries       
        logger.info('is_kv_store_ready: waiting for %s seconds, number of tries %s', sleep_time, tries)
        time.sleep(sleep_time)
        tries = tries + 1
        kvStoreStatus = get_kv_store_status(sessionKey)

    logger.debug('splunk_fatal_error: %s, kv_store_fatal_error: %s, kv_store_status: %s, server_roles %s',
                 splunkd_fatal_error, kvstore_fatal_error, kvStoreStatus, server_roles)
    if kvStoreStatus == 'ready':
        is_ready = True
    else:
        kvstore_fatal_error=True

    return is_ready

def kv_store_rest_request(uri, method, sessionKey=None, repository=False, req_data=None):
    global kv_store_ready, splunkd_fatal_error
    jsonargs = None

    if splunkd_fatal_error:
        logger.error('kv_store_rest_request: fatal error splunkd is not responding hence returning error')
        return (500, {'success': False, 'error': str("fatal error splunkd is not responding hence returning error"), 'status': 500})

    if kvstore_fatal_error:
        logger.error('kv_store_rest_request: fatal error kv store failed to start')
        return (500, {'success': False, 'error': str("fatal error kv store failed to start"), 'status': 500})
        
    if kv_store_ready is None:
        kv_store_ready = is_kv_store_ready(sessionKey)

    if not kv_store_ready:
        logger.error('kv_store_rest_request: Timedout waiting for KVstore status %s to be ready', kv_store_ready)
        return (500, {'success': False, 'error': str("Timedout waiting for KVstore status to be ready "), 'status': 500})

    auth_key = get_internal_shared_key()

    if not sessionKey and method == 'GET':
        #proxy via splunkd REST endpoint
        logger.debug('kv_store_rest_request: No session key')
        uri_tail = uri[uri.index('data') + len('data')+1:]
        uri_segments = uri_tail.split('/')
        uri_resource = uri_segments[0]
        uri_id = ''
        if len(uri_segments) == 2:
            uri_id = uri_segments[1]
        else:
            uri_resource = uri_tail

        if repository:
            uri = '/services/splunk_app_stream/' + uri_resource + '?output_mode=json&repository=true&X-SPLUNK-APP-STREAM-KEY=' + auth_key 
        elif uri_id:
            uri = '/services/splunk_app_stream/' + uri_resource + '?output_mode=json' + '&id=' + uri_id + '&X-SPLUNK-APP-STREAM-KEY=' + auth_key
        else:
            uri = '/services/splunk_app_stream/' + uri_resource + '?output_mode=json&X-SPLUNK-APP-STREAM-KEY=' + auth_key

        logger.info('kv_store_rest_request: new uri generated for no session key ')
        try:
            serverResponse, serverContent = splunk.rest.simpleRequest(
                util.make_url_internal(uri),            
                sessionKey='',
                postargs=None,
                method='GET',
                raiseAllErrors=True,
                proxyMode=False,
                rawResult=None,
                jsonargs=None,
                timeout=splunkd_time_out
            )
            jsonResp = json.loads(serverContent)
            content = jsonResp["entry"][0]["content"]
            return (serverResponse, json.dumps(content))
        except splunk.ResourceNotFound:
            # no need to log the 404s since it will return empty result in response
            raise
        except Exception as e:
            logger.exception("failed to send kvstore rest request")
            if any(s in str(e) for s in splunkd_connection_exceptions):
                splunkd_fatal_error = True
            raise

    if req_data:
        jsonargs = json.dumps(req_data)
    try:
        url_internal = util.make_url_internal(uri + '?output_mode=json&X-SPLUNK-APP-STREAM-KEY=' + auth_key + '&auth_key=' + auth_key)
        serverResponse, serverContent = splunk.rest.simpleRequest(
            url_internal,
            sessionKey,
            postargs=None,
            method=method,
            raiseAllErrors=True,
            proxyMode=False,
            rawResult=None,
            jsonargs=jsonargs,
            timeout=splunkd_time_out
        )
        return serverResponse, serverContent.decode('utf-8')
    except splunk.ResourceNotFound:
        # no need to log the 404s since it will return empty result in response
        raise
    except Exception as e:
        logger.exception("failed to send kvstore rest request")
        if any(s in str(e) for s in splunkd_connection_exceptions):
            splunkd_fatal_error = True
        raise

def read_from_kv_store_coll(coll_name, session_key, repository=False):
    try:
        serverResponse, serverContent = kv_store_rest_request( coll_name, 'GET', session_key, repository)
        jsonResp = json.loads(serverContent)
        return jsonResp
    except splunk.ResourceNotFound:
        return []
    except splunk.RESTException as re:
        logger.error("read_from_kv_store_coll: REST Exception Caught when invoking REST API:: %s, collection %s", re, coll_name)
        return []

def read_by_id_from_kv_store_coll(coll_name, id, session_key, repository=False):
    try:
        # The id should be URL escaped: this is just double checking.
        if '\\' in id or '/' in id:
            # Might be a directory traversal attack (and definitely a programming error).
            raise Exception('Invalid id')

        uri = coll_name + '/' + id
        serverResponse, serverContent = kv_store_rest_request(uri, 'GET', session_key, repository)
        if 'status' in serverResponse:
            status = serverResponse['status']

            # TODO: We need to be more consistent with status reporting!
            if status != 200 and status != '200':
                return serverResponse

        jsonResp = json.loads(serverContent)
        return jsonResp
    except splunk.ResourceNotFound:
        return {'success': False, 'error': 'Could not find record with id = %s' % id, 'status': 404}
    except splunk.RESTException as re:
        logger.error("read_by_id_from_kv_store_coll: REST Exception Caught when invoking REST API:: %s, collection %s, id %s", re, coll_name, id)
        return {'success': False, 'error': str(re), 'status': 500}

def delete_by_id_from_kv_store_coll(coll_name, id, session_key, repository=False):
    try:
        # The id should be URL escaped: this is just double checking.
        if '\\' in id or '/' in id:
            # Might be a directory traversal attack (and definitely a programming error).
            raise Exception('Invalid id')

        uri = coll_name + '/' + id
        serverResponse, serverContent = kv_store_rest_request(uri, 'DELETE', session_key, repository)
        if 'status' in serverResponse:
            status = serverResponse['status']
            if status == '200':
                update_kv_store_apps_meta(session_key)

            return {'success':True,'error': None, 'deleted':'Entry ' + str(id) + ' has been deleted successfully','status':200}
            
    except splunk.ResourceNotFound:
        return {'success': False, 'error': 'Could not find record with id = %s' % id, 'status': 404}
    except splunk.RESTException as re:
        logger.error("read_by_id_from_kv_store_coll: REST Exception Caught when invoking REST API:: %s, collection %s, id %s", re, coll_name, id)
        return {'success': False, 'error': str(re), 'status': 500}

def update_kv_store_apps_meta(session_key, create=False):
    if not session_key:
        return {}

    # FIXME, this is really bad
    import splunk_app_stream.models.ping as ping

    try:
        jsonData = {}
        jsonData['id'] = 'appsmeta'
        jsonData['_key'] = jsonData['id']
        jsonData["dateLastUpdated"] = int(round(time.time() * 1000))
        jsonData["version"] = stream_utils.getAppVersion()
        uri =  misc_kv_store_uri + '/appsmeta'
        if create:
            uri = misc_kv_store_uri
        serverResponse, serverContent = kv_store_rest_request(uri, 'POST', session_key, False, jsonData)
        # update the cached apps meta to avoid rest_handler access
        ping.Ping.update_cache(jsonData)
        return jsonData
    except splunk.RESTException as re:
        logger.error("update_kv_store_apps_meta: REST Exception Caught when invoking REST API :: %s", re)
        return {}

def read_kv_store_apps_meta(session_key):
    serverContent = {}
    try:
        # uri when there is no session key is to use rest_ping handler
        uri = '/servicesNS/nobody/splunk_app_stream/storage/collections/data/ping'
        if session_key:
            uri =  misc_kv_store_uri + '/appsmeta'
        logger.debug('in read_kv_store_apps_meta: ')
        serverResponse, serverContent = kv_store_rest_request(uri, 'GET', session_key, False)
        if serverResponse == 404 or 'error' in serverContent:
            logger.error('read_kv_store_apps_meta: Error getting apps meta from kv store collection, reason %s', serverContent['error'])            
            serverContent = '{"dateLastUpdated" : 0}'
        return json.loads(serverContent)
    except splunk.ResourceNotFound:
        return serverContent
    except splunk.RESTException as re:
        logger.error("read_kv_store_apps_meta: REST Exception Caught when invoking REST API :: %s", re)
        return serverContent

def save_to_kv_store(coll_name, id, json_data, session_key):
    try:
        uri = coll_name

        if id:
            # The id should be URL escaped: this is just double checking.
            if '\\' in id or '/' in id:
                # Might be a directory traversal attack (and definitely a programming error).
                raise Exception('Invalid id')
            uri = uri + '/' + id

        serverResponse, serverContent = kv_store_rest_request(uri, 'POST', session_key, False, json_data)
        update_kv_store_apps_meta(session_key)
        return True
    except splunk.ResourceNotFound:
        return False
    except splunk.RESTException as re:
        logger.error("save_to_kv_store: REST Exception Caught when invoking REST API :: %s", re)
        return False

def migrate_to_kv_store():
    if is_kv_store_supported_in_splunk() and is_kv_store_ready():
        logger.info("starting migration...")
        auth_key = get_internal_shared_key()
        uri = '/services/splunk_app_stream/kvstoremigrate?output_mode=json&X-SPLUNK-APP-STREAM-KEY=' + auth_key

        try:
            serverResponse, serverContent = splunk.rest.simpleRequest(
                        util.make_url_internal(uri),
                        sessionKey='',
                        postargs=None,
                        method='POST',
                        raiseAllErrors=True,
                        proxyMode=False,
                        rawResult=None,
                        jsonargs=None,
                        timeout=splunkd_time_out
                    )              
        except splunk.RESTException:
            logger.exception("failed to migrate to kv store")

def get_internal_shared_key():
    # create the shared auth key and save it to a file for IPC with splunkd REST handlers
    shared_key_file = os.path.join(util.get_apps_dir(), 'splunk_app_stream', 'local', 'stream_shared_key')
    auth_key = ""
    try:
        shared_key_file_mtime = int(os.stat(shared_key_file).st_mtime)
    except Exception as e:
        shared_key_file_mtime = 0
    now = int(time.time())
    if shared_key_file_mtime + 86400 < now:
        auth_key = str(uuid.uuid4())
        # save it to shared file
        try:
            base_local_dir = os.path.join(util.get_apps_dir(), 'splunk_app_stream', 'local')
            if not os.path.exists(base_local_dir):
                stream_utils.createDir(base_local_dir + os.sep)
            f = open(shared_key_file, 'w+' )
            f.write(auth_key)
            f.close()
        except:
            logger.error('Unable to create the shared key file')
    else:
        auth_key = open(shared_key_file, 'r').read()

    return auth_key


