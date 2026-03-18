
import copy
import json
import os
import re
import threading
import time

from datetime import datetime as dt
from collections import OrderedDict

import splunk
import splunk.rest
import splunk.appserver.mrsparkle.lib.util as util
import splunk.appserver.mrsparkle.lib.apps as apps

import jsonschema

import splunk_app_stream.utils.stream_utils as stream_utils
import splunk_app_stream.utils.stream_kvstore_utils as kv_utils

logger = stream_utils.setup_logger('stream')

import splunk_app_stream.models.stream_forwarder_group as stream_fwd_grp

from splunk_app_stream.models.vocabulary import Vocabulary
from splunk_app_stream.models.ping import Ping

stream_schema_path = os.path.join(util.get_apps_dir(), 'splunk_app_stream', 'default', "stream_schema")
stream_schema = None
lock  = threading.Lock()

try:
    schema_data = open( stream_schema_path, 'rb' ).read()
    stream_schema = dict(json.loads(schema_data.decode("utf-8")))
except Exception as e:
    logger.exception(e)
    logger.error("Error reading Stream schema file")
    raise

stream_errors = ['StreamNotFound','InvalidStreamDefinition', 'IdMismatch']

base_default_streams_dir = os.path.join(util.get_apps_dir(), 'splunk_app_stream', 'default', "streams")
base_local_streams_dir = os.path.join(util.get_apps_dir(), 'splunk_app_stream', 'local', "streams")

# flag to wait for upgrade to finish
run_once = True

# Last updated time used to refresh cache
dateLastUpdated = 0

# used to ensure that stream expirations are checked at most once per second
timeLastExpirationCheck = 0

# used to cache the results for a given stream forwarder
stream_forwarder_results_cache = {}

# App Name -> App Location cache
app_locations_map = {}

# Stream Id -> App Location Cache
stream_app_location_map = {}

# Map of all the streams in all the apps keyed by app_id
app_streams = {}

# Stream definitions bundled with splunk_app_stream
base_streams = []
base_stream_ids = []
base_streams_map = {}

#reference streams
reference_streams = []

#kv store
use_kv_store = kv_utils.is_kv_store_supported_in_splunk()

# flag to update app date last updated time if a stream file is modified out of band
update_app_last_date_time = False

# Get list of apps installed
apps = apps.local_apps.items()
for app in apps:
    app_name = app[0]
    app_location = app[1]['full_path']
    app_locations_map[app_name] = app_location

# Vocabulary terms variable
vocab_terms = {}
vocab_terms = kv_utils.get_vocab_terms()

def update_vocab_terms():
    global vocab_terms, lock
    try:
        lock.acquire()
        vocab_terms = kv_utils.get_vocab_terms()    
    except Exception as exce:
        logger.info("Failed to fetch vocabularies from kvstore: %s"% exce)
    finally:
        lock.release()
  

#update cache if dateLastUpdated is different between cached value and the persisted value
def update_streams_cache(session_key=None):
    global dateLastUpdated
    global stream_forwarder_results_cache
    queried_all_streams = set()
    try:
        appsMeta = Ping.ping(session_key)
        if appsMeta['dateLastUpdated'] > dateLastUpdated:
            logger.debug("cachedateLastUpdated:: %d" % dateLastUpdated)
            logger.debug("appsDateLastUpdated:: %d" % appsMeta['dateLastUpdated'])
            queried_all_streams = init_streams_collection(session_key)
            dateLastUpdated = appsMeta['dateLastUpdated']
            stream_forwarder_results_cache = {}
    except Exception:
        # Exception happens as appsMeta file is in the process of getting written to.
        # Do Nothing and return existing cache.
        logger.exception("failed to update streams cache")
    return queried_all_streams

def update_date_last_updated(new_ts):
    global dateLastUpdated
    dateLastUpdated = new_ts

def delete_from_streams_collection_with_lock(stream_id):
    global app_streams, stream_app_location_map, dateLastUpdated, stream_forwarder_results_cache

    if stream_id in stream_app_location_map:
        del stream_app_location_map[stream_id]
    
    #make sure 'splunk_app_stream' values are populated before removing items
    #during initialization, app_streams may not yet be updated
    if 'splunk_app_stream' in app_streams:
        base_streams = app_streams['splunk_app_stream']
        for i, s in enumerate(base_streams):
            if s['id'] == stream_id:
                del base_streams[i]
                break
    update_valid_streams()
    dateLastUpdated = int(round(time.time() * 1000))
    stream_forwarder_results_cache = {}

def delete_from_streams_collection(stream_id):
    with lock:
        delete_from_streams_collection_with_lock(stream_id)
 
def update_streams_collection(stream_json):
    global app_streams, stream_app_location_map, dateLastUpdated, base_stream_ids, lock, stream_forwarder_results_cache
    lock.acquire()
    try:
        stream_app_location_map[stream_json['id']] = app_locations_map['splunk_app_stream']
        base_streams = app_streams['splunk_app_stream']
        stream_found = False
        for i, s in enumerate(base_streams):
            if s['id'] == stream_json['id']:
                base_streams[i] = stream_json
                stream_found = True
        if not stream_found:
            base_streams.append(stream_json)
            base_stream_ids.append(stream_json['id'])
        dateLastUpdated = int(round(time.time() * 1000))
        stream_forwarder_results_cache = {}
    finally:
        lock.release()

def update_valid_streams(stream_id=None):
    valid_streams = set()  
    for app_id in app_streams:
        streams = app_streams[app_id]
        for stream in streams:
            if not 'expirationDate' in stream:
                valid_streams.add(stream['id'])
    if stream_id:
        valid_streams.add(stream_id)
    stream_fwd_grp.set_valid_streams(valid_streams)    
    return valid_streams

def init_date_last_updated():
    global dateLastUpdated
    pingData = Ping.ping()
    dateLastUpdated = pingData['dateLastUpdated']

def init_streams_collection(session_key=None):
    # FIXME, this is not something good
    import upgrade_streams

    global app_streams, stream_app_location_map, base_streams, base_stream_ids, base_streams_map, run_once, reference_streams,lock
    queried_all_streams = set()
    if run_once:
        if use_kv_store:
            # Need the session key to proxy via splunk REST controller else KV store wont be initialized
            if session_key:
                (updated, old_version, new_version) = upgrade_streams.copy_default_to_local_streams(use_kv_store, kv_utils.streams_kv_store_coll, session_key)
                if upgrade_streams.modified_streams_exist(use_kv_store, kv_utils.streams_kv_store_coll, session_key):
                    upgrade_streams.update_streams(use_kv_store, old_version, new_version, kv_utils.streams_kv_store_coll, session_key)
        else:
            (updated, old_version, new_version) = upgrade_streams.copy_default_to_local_streams(use_kv_store)
            if upgrade_streams.modified_streams_exist(use_kv_store):
                upgrade_streams.update_streams(use_kv_store, old_version, new_version)
        # Fetch the list of reference streams defined by splunk_app_stream
        reference_streams = read_reference_streams()
    lock.acquire()
    try:
        # Fetch the list of streams defined by splunk_app_stream
        if use_kv_store:
            base_streams = read_streams_from_kv_store(session_key)
        else:
            base_streams = read_streams(app_locations_map['splunk_app_stream'], "splunk_app_stream")

        base_stream_ids = []
        base_streams_map = {}
        for base_stream in base_streams:
            base_stream_ids.append(base_stream['id'])
            base_streams_map[base_stream['id']] = base_stream
            stream_app_location_map[base_stream['id']] = app_locations_map['splunk_app_stream']

        for app in apps:
            app_name = app[0]
            app_location = app[1]['full_path']

            if app_name != "splunk_app_stream":
                streams = read_streams(app_location, app_name)

                result_streams = []

                if len(streams) != 0:
                    for stream in streams:
                        # If a stream with the same id as splunk_app_stream base streams is found in external app, then log an error and continue
                        if stream['id'] in base_stream_ids:
                            logger.error("Stream with id %s exists in splunk_app_stream. External app %s should not contain stream with same id and will be ignored." % (stream['id'], app_name))
                        else:
                            # Prepend the stream id with the app field if specified or app_name if not
                            # Only for the external apps
                            if 'app' in stream:
                                stream['id'] = stream['app'] + '_' + stream['id']
                            else:
                                stream['id'] = app_name + '_' + stream['id']

                            #Cache the app_location for the Stream
                            stream_app_location_map[stream['id']] = app_location
                            result_streams.append(stream)

                    app_streams[app_name] = result_streams
                    logger.info("Streams for App %s are %d" % (app_name, len(result_streams)))

        app_streams["splunk_app_stream"] = base_streams    
        queried_all_streams = update_valid_streams()
        if run_once:
            stream_fwd_grp.create_default_group(session_key)
            stream_fwd_grp.update_default_group(upgrade_streams.get_default_group_streams(), session_key)
        run_once = False
    finally:
        lock.release()
    return queried_all_streams

# only splunk_app_stream base streams and ephemeral streams are stored in kv_store
def read_streams_from_kv_store(session_key):
    tmp_streams = []
    local_streams = kv_utils.read_from_kv_store_coll(kv_utils.streams_kv_store_coll, session_key, True)

    if 'error' in local_streams:
        logger.error('read_streams_from_kv_store: Error getting streams from stream kv store collection, reason %s', local_streams['error'])
        return tmp_streams

    for stream in local_streams:
        stream_expired = False        
        if 'expirationDate' in stream:
            # expirationDate is expected in seconds since epoch time
            if dt.fromtimestamp(stream['expirationDate']) < dt.now():
                logger.info("Stream %s expired...deleting it", stream['_key'])
                delete_stream(stream['_key'], session_key, with_lock_held=True)
                stream_expired = True

        if not stream_expired:
            tmp_streams.append(stream)
    return tmp_streams

def save_stream_to_kv_store(stream_id, json_data, session_key):
    return kv_utils.save_to_kv_store(kv_utils.streams_kv_store_coll, stream_id, json_data, session_key)

# This function will update the netflow_utils when any stream is deleted

def stream_delete_netflow_utils_support(stream_id, session_key):

    try:
        temp = []
        netflow_ipfix_coll_info = kv_utils.read_from_kv_store_coll(kv_utils.netflow_ipfix_apps_info_kv_store_coll, session_key)

        # Support for maintaining DELETED STREAMS for IPFIX apps
        for i in netflow_ipfix_coll_info:

            if i["_key"] == "netflow_ipfix_apps_info":
                main_data = i["data"]

        for i in netflow_ipfix_coll_info:

            if len(netflow_ipfix_coll_info) == 2:
                if i["_key"] == "DELETED_STREAMS":
                    existing_deteled_streams = i["data"]
                    for j in main_data:
                        if stream_id in j['streams']:

                            j['streams'].remove(stream_id)

                            if stream_id not in existing_deteled_streams:
                                existing_deteled_streams.append(stream_id)
                                json_data = {'_key': 'DELETED_STREAMS', 'data': existing_deteled_streams}
                                kv_utils.save_to_kv_store(kv_utils.netflow_ipfix_apps_info_kv_store_coll, "DELETED_STREAMS", json_data, session_key)
                        
                        temp.append(j)

                    json_data = {'_key':'netflow_ipfix_apps_info', 'data': temp}
                    kv_utils.save_to_kv_store(kv_utils.netflow_ipfix_apps_info_kv_store_coll, "netflow_ipfix_apps_info", json_data, session_key)

            elif len(netflow_ipfix_coll_info) == 1:

                for j in main_data:

                    if stream_id in j['streams']:

                        j['streams'].remove(stream_id)

                        json_data = {'_key': 'DELETED_STREAMS', 'data': [stream_id]}
                        kv_utils.save_to_kv_store(kv_utils.netflow_ipfix_apps_info_kv_store_coll, None, json_data, session_key)
                    
                    temp.append(j)

                json_data = {'_key':'netflow_ipfix_apps_info', 'data': temp}
                kv_utils.save_to_kv_store(kv_utils.netflow_ipfix_apps_info_kv_store_coll, "netflow_ipfix_apps_info", json_data, session_key)
    
    except Exception as e:
        logger.error(e)


# Delete is only allowed for all streams which are stored
# under local/streams in the stream app.
def delete_stream(stream_id, session_key=None, with_lock_held=False, from_netflow_script=False):
    #sanitize stream id to prevent directory traversal attack
    global base_streams_map
    stream_id = os.path.basename(stream_id)
    delete_succeeded = False
    error_msg = 'Stream not found'

    if use_kv_store:
        try:

            if from_netflow_script == False:
                stream_delete_netflow_utils_support(stream_id, session_key)      

            serverResponse, serverContent = kv_utils.kv_store_rest_request(kv_utils.streams_kv_store_coll + '/' + stream_id,
                                                                'DELETE', session_key)

            kv_utils.update_kv_store_apps_meta(session_key)
            delete_succeeded = True
            if with_lock_held:
                delete_from_streams_collection_with_lock(stream_id)
            else:
                delete_from_streams_collection(stream_id)

        except splunk.RESTException as re:
            logger.error("REST Exception Caught when invoking REST API :: %s", re)
    else:
        try:
            stream_path = os.path.join(base_local_streams_dir, stream_id)
            json_data = read_stream_as_json(stream_id, base_local_streams_dir)

            if json_data != "StreamNotFound":           
                try:
                    os.remove(stream_path)
                    stream_utils.updateAppsMeta()
                    delete_succeeded = True
                    if with_lock_held:
                        delete_from_streams_collection_with_lock(stream_id)
                    else:
                        delete_from_streams_collection(stream_id)
                except OSError:
                    error_msg = "OSError while deleting the file"
                    pass
        except:
            pass

    return delete_succeeded, error_msg


def read_stream_as_json(stream_id, streams_dir):

    global update_app_last_date_time, run_once, dateLastUpdated
    # sanitize stream id to prevent directory traversal attack
    stream_id = os.path.basename(stream_id)

    stream_path = os.path.join(streams_dir, stream_id)
    try:
        f = open( stream_path, 'r' )
        try:            
            # check if the json file is modified out of band
            if run_once and not update_app_last_date_time and 'local' in stream_path:
                if stream_utils.is_file_modified(stream_path, dateLastUpdated):
                    logger.info("file %s has been modified out of band so updating app last updated time", stream_path)
                    stream_utils.updateAppsMeta()
                    update_app_last_date_time = True

            data = f.read()
            stream_json = json.loads(data, object_pairs_hook=OrderedDict)
            is_valid_stream, stream_validation_messages = stream_utils.is_valid_stream_definition_new(stream_json,vocab_terms)
            if is_valid_stream:
                if stream_json['id'] == stream_id:
                    return stream_json
                else:
                    logger.error("Stream Id mismatch -- Id does not match file name at :: %s", stream_path)
                    return 'IdMismatch'
            else:
                return 'InvalidStreamDefinition'
        except:
            return 'StreamNotFound'
        finally:
            f.close()
    except Exception:
        logger.exception("IOerror, unable to read file")

def write_json_to_stream(stream_id, json_data):
    # sanitize stream id to prevent directory traversal attack
    stream_id = os.path.basename(stream_id)

    stream_path = os.path.join(base_local_streams_dir, stream_id)
    logger.debug("write_json_to_stream:: %s", stream_path)
    stream_utils.createDir(base_local_streams_dir + os.sep)
    try:
        f = open( stream_path, 'w' )
        try:
            f.write(json.dumps(json_data, sort_keys=True, indent=2))
            stream_utils.updateAppsMeta()
            return True
        except:
            logger.error("Error opening %s" % stream_path)
            return False
        finally:
            f.close()
    except Exception:
        logger.exception("IOerror, unable to read file")

def update_field(json_data, req_json_data, field):
    try:
        json_data[field] = req_json_data[field]
    except:
        pass

def update_list_field(json_data, req_json_data_dict, field, itemIndex):
    try:
        json_data["fields"][itemIndex][field] = req_json_data_dict[field]
    except:
        pass

def get_stream_dirs_for_app(app_location):
    default_streams_dir = os.path.join(app_location, 'default', "streams")
    local_streams_dir = os.path.join(app_location, 'local', "streams")
    return default_streams_dir, local_streams_dir

def get_stream_ids_for_app(app_location):
    default_stream_ids = []
    local_stream_ids = []

    default_streams_dir, local_streams_dir = get_stream_dirs_for_app(app_location)

    logger.debug("DefaultDir %s, LocalDir %s", default_streams_dir, local_streams_dir)

    if os.path.exists(default_streams_dir):
        default_stream_ids = filter(lambda x: not x.startswith('.'), next(os.walk(default_streams_dir))[2])

    if os.path.exists(local_streams_dir):
        local_stream_ids = filter(lambda x: not x.startswith('.'), next(os.walk(local_streams_dir))[2])

    return default_stream_ids, local_stream_ids

def read_reference_streams():
    default_streams_dir, local_streams_dir = get_stream_dirs_for_app(app_locations_map['splunk_app_stream'])
    (default_stream_ids, local_stream_ids) = get_stream_ids_for_app(app_locations_map['splunk_app_stream'])
    streams_json_list = []
    for id in default_stream_ids:
        json_data = read_stream_as_json(id, default_streams_dir)
        try:
            if json_data['isReferenceStream']:
                streams_json_list.append(json_data)
        except:
            pass
    return streams_json_list

def read_streams(app_location, app_name):
    default_streams_dir, local_streams_dir = get_stream_dirs_for_app(app_location)
    (default_stream_ids, local_stream_ids) = get_stream_ids_for_app(app_location)

    streams_json_list = []
    stream_modified = False
    #for splunk_app_stream streams (base and ephemeral streams) read from the local streams folder only
    if app_name == 'splunk_app_stream':
        for id in local_stream_ids:
            json_data = read_stream_as_json(id, local_streams_dir)
            stream_expired = False
            if not json_data in stream_errors:                    
                if 'expirationDate' in json_data:
                    #expirationDate is expected in seconds since epoch time
                    if dt.fromtimestamp(json_data['expirationDate']) < dt.now():
                        logger.info("Stream %s expired...deleting it", id)
                        #Only delete if app is stream..else ignore!
                        if app_name == "splunk_app_stream":
                            delete_stream(id, with_lock_held=True)
                        stream_expired = True

                if not stream_expired:
                    streams_json_list.append(json_data)
    else:
        for id in default_stream_ids:
            if id in local_stream_ids:
                json_data = read_stream_as_json(id, local_streams_dir)
            else:
                json_data = read_stream_as_json(id, default_streams_dir)

            if not json_data in stream_errors:
                streams_json_list.append(json_data)

        for id in local_stream_ids:
            logger.debug("local stream %s", id)
            if id not in default_stream_ids:
                json_data = read_stream_as_json(id, local_streams_dir)
                if not json_data in stream_errors:
                    streams_json_list.append(json_data)

    return streams_json_list

def get_stream_by_id(id, session_key):
    found_stream = None

    if id not in stream_app_location_map:
        init_streams_collection(session_key)

    if id in stream_app_location_map:
        app_location = stream_app_location_map[id]
        app_id = app_location.split(os.sep)[-1]
        logger.debug("app_location %s, app_id %s", app_location, app_id)

        if app_id in app_streams:
            streams = app_streams[app_id]
            for stream in streams:
                if stream['id'] == id:
                    found_stream = stream
                    break
    return found_stream

#validate aggregate streams settings
#aggType must either be 'key', 'value', or a list of valid aggTypes
def validate_aggregation_config(stream_json):
    fields = stream_json['fields']
    valid_agg_types = {'dc', 'max', 'mean', 'median', 'min', 'mode', 'stdev', 'stdevp', 'sum', 'sumsq', 'values', 'var', 'varp'}
    valid = True
    error_msg = ''
    for field in fields:
        agg_type = field['aggType']
        if not (agg_type in ('key', 'value') or set(agg_type).issubset(valid_agg_types)):
            valid = False
#            error_msg = "Invalid aggregation type for field %s for stream with id %s" % (field['name'], stream_json['id'])
#             This function gets called after the ID gets validated so at this point it's only letters, numbers, underscores, so it's fine to log it
            error_msg = "Invalid aggregation type for field for stream with id %s" % stream_json['id']
            return (valid, error_msg)
        if len(agg_type) == 0:
            valid = False
#            error_msg = "No aggregation type set for field %s for stream with id %s" % (field['name'], stream_json['id'])
            error_msg = "No aggregation type set for field for stream with id %s" % stream_json['id']
            return (valid, error_msg)
    return (valid, error_msg)

#validate aggregate streams for topX configuration
#topLimit and topSortBy are optional fields
#for topX feature both the fields need to be present for topX configuration
#topSortBy field has to be of a supported numeric agg_type or "count" field
#logging IDs here is fine since this function is called after stream_json['id'] is validated
def validate_topx_config(stream_json):
    is_aggregated = False
    if 'aggregated' in stream_json:
        is_aggregated = stream_json['aggregated']
    extras = stream_json['extras']
    valid = True
    error_msg = ''
    if is_aggregated:
        if 'topLimit' not in extras and 'topSortBy' not in extras:
            return (valid, error_msg)
        elif 'topLimit' not in extras:
            valid = False
            error_msg = "Missing topLimit for stream with id " + stream_json['id']
        elif 'topSortBy' not in extras:
            valid = False
            error_msg = "Missing topSortBy for stream with id " + stream_json['id']
        else:
            if extras['topLimit'] <= 0:
                valid = False
                error_msg = "topLimit value should be greater than 0 for stream with id " + stream_json['id']
                return (valid, error_msg)
            topSortBy = extras['topSortBy']
            if topSortBy != "count":
                split_index = topSortBy.index('(')
                agg_type = topSortBy[:split_index]
                topSortBy = topSortBy[split_index+1:-1]
                fields = stream_json['fields']
                valid = False
                error_msg = "topSortBy should be either a 'count' field or a numeric aggregation type field for stream with id " + stream_json['id']
                for field in fields:
                    if field['name'] == topSortBy:
                        numeric_agg_types = ['dc', 'max', 'mean', 'median', 'min', 'mode', 'stdev', 'stdevp', 'sum', 'sumsq', 'var', 'varp']
                        # logger.debug("agg_type is %s for topSortBy field %s for stream %s", agg_type, topSortBy, stream_json['id'])
                        # Since we don't know what topSortBy might be, let's not log it, just in case
                        logger.debug("checking agg_type for a topSortBy field for stream %s", stream_json['id'])
                        if agg_type in numeric_agg_types and agg_type in field['aggType'] and field['enabled']:
                            valid = True
                            error_msg = ""
                        else:
                            if agg_type not in numeric_agg_types or agg_type not in field['aggType']:
                                error_msg = "topSortBy should be an enabled numeric aggregation type field for stream with id " + stream_json['id']
                            else:
                                error_msg = "topSortBy should be enabled for stream with id " + stream_json['id']
            else:
                # topSortBy is count; can log it
                logger.debug("topSortBy field %s for stream %s", topSortBy, stream_json['id'])
    else:
        if'topSortBy' in extras or 'topLimit' in extras:
            valid = False
            error_msg = "top configuration cannot be configured for non aggregated stream with id " + stream_json['id']
    
    return (valid, error_msg)

def is_valid_stream_definition(stream_json, new_vocab_terms=None):
    global vocab_terms
    validator = jsonschema.Draft4Validator(stream_schema)
    error_messages = []
    valid_stream_id_regex = '^\w+$'
    if not re.compile(valid_stream_id_regex).match(stream_json['id']):
#        error_msg = "Invalid Stream definition for stream with id %s --  only letters, digits and underscores ('_') allowed for Id" % stream_json['id']
        error_msg = "Invalid Stream definition for stream --  only letters, digits and underscores ('_') allowed for Id"
        logger.error(error_msg)
        error_messages.append(error_msg) 
        return False, error_messages

    if not validator.is_valid(stream_json):
        for error in sorted(validator.iter_errors(stream_json), key=str):
            error_msg = "Invalid Stream definition for stream with id %s -- Validation Error %s" % (stream_json['id'], error.message)
            logger.error(error_msg)
            error_messages.append(error_msg)
        return False, error_messages
    else:
        (valid_agg_config, error_msg) = validate_aggregation_config(stream_json)
        if not valid_agg_config:
            logger.error(error_msg)
            error_messages.append(error_msg)
            return False, error_messages

        (valid_topx_config, error_msg) = validate_topx_config(stream_json)
        if not valid_topx_config:
            logger.error(error_msg)
            error_messages.append(error_msg)
            return False, error_messages

        fields = stream_json['fields']
        invalid_terms = []
        invalid_regexes = []
        field_names = []

        if new_vocab_terms:
            vocab_terms = new_vocab_terms

        for field in fields:
            field_names.append(field['name'])
            if not field['term'] in vocab_terms:
                invalid_terms.append(field['term'])

            if 'transformation' in field and field['transformation']['type'] == 'regex':
                # check for validity of regex
                regex = field['transformation']['value']
                try:
                    re.compile(regex)
                except Exception:
                    logger.exception("transformation regex is invalid")
                    invalid_regexes.append(field)

        duplicate_field_names = find_duplicates_in_list(field_names)
        invalid_dates = not date_field_check(stream_json)

        if invalid_terms or invalid_regexes or duplicate_field_names or invalid_dates:
            # Don't log anything that hasn't already been validated
            if invalid_terms:
#                error_msg = "Invalid Stream definition for stream with id %s -- " \
#                            "Following terms do not have matching vocabulary entries :: %s" \
#                            %(stream_json['id'], ', '.join([str(x) for x in invalid_terms]))
                error_msg = "Invalid Stream definition for stream with id %s -- " \
                            "Terms do not have matching vocabulary entries" % stream_json['id']
                error_messages.append(error_msg)

            if invalid_regexes:
#                error_msg = "Invalid Stream definition for stream with id %s -- " \
#                             "Extraction rules with invalid regexes were found :: %s" % \
#                             (stream_json['id'], ', '.join([x['transformation']['value'] for x in invalid_regexes]))
                error_msg = "Invalid Stream definition for stream with id %s -- " \
                            "Extraction rules with invalid regexes were found" % stream_json['id']
                error_messages.append(error_msg)

            if duplicate_field_names:
#                error_msg = "Invalid Stream definition for stream with id %s -- " \
#                             "Following field names are duplicated :: %s" % \
#                             (stream_json['id'], ', '.join([str(x) for x in duplicate_field_names]))
                error_msg = "Invalid Stream definition for stream with id %s -- " \
                            "Field names are duplicated" % stream_json['id']
                error_messages.append(error_msg)

            if invalid_dates:
                error_msg = "Invalid Stream definition for stream with id %s -- " \
                             "Expiration Date cannot be earlier than the Create Date" % \
                             stream_json['id']
                error_messages.append(error_msg)

            for msg in error_messages:
                logger.error(msg)

            return False, error_messages
        else:
            return True, None

def find_duplicates_in_list(list):
    return set([x for x in list if list.count(x) > 1])

def date_field_check(stream_json):
    if 'createDate' in stream_json and 'expirationDate' in stream_json:
        return stream_json['expirationDate'] > stream_json['createDate']
    else:
        return True

def get_filtered_streams(streams, stream_forwarder_group_streams, includeEphemeralStreams):
    result = []
    for s in streams:
        if s['id'] in stream_forwarder_group_streams or (includeEphemeralStreams and 'expirationDate' in s):
            result.append(s)
    return result

def transform_stream(stream):
    remove = False   
    transform = False 
    # check if aggregate stream
    if 'aggregated' in stream and stream['aggregated']:
        if 'topSortBy' in stream['extras']:                            
            top_sort_by = stream['extras']['topSortBy']
            m = re.search(r"\((.*)\)", top_sort_by)
            if m:
                stream['extras']['topSortBy'] = m.group(1)
                transform = True
        
        for f in stream['fields']:            
            if f['aggType'] != 'key':
                if ['sum'] == f['aggType']:
                    f['aggType'] = 'sum'
                    transform = True                   
                else:
                    remove = True
                    logger.info("stream %s contains new aggragete functions, so not included in the response for backward compatibility", stream['id'])
                    return remove
    if transform:
        logger.info("stream %s contains new aggragete functions, so transformed to older schema version for backward compatibility", stream['id'])
    return remove

def get_backward_compatible_streams(streams):
    backward_compatible_streams = []
    for s in streams:
        remove = transform_stream(s)
        if not remove:
            backward_compatible_streams.append(s)
    return backward_compatible_streams

def is_transform_required(user_agent):
    if not user_agent:
        return True
    else:
        m = re.search(r"(^StreamForwarder/)(.*)", user_agent, re.IGNORECASE)
        if m:
            version = m.group(2)
            # if the version is less than 6.6
            if int(version.replace('.', '')) < 66:
                return True
            else:
                return False
        else:
            return False

class Stream:

    @staticmethod
    def list(session_key, id='', **kwargs):
        """Return list of saved streams"""
        global timeLastExpirationCheck
        global stream_forwarder_results_cache
        try:
            #sanitize stream id to prevent directory traversal attack
            id = os.path.basename(id)

            # get user agent
            user_agent = kwargs.get('user_agent', '')
            logger.debug("user_agent in the header is %s", user_agent)

            # get the repository parameter, if true then return all the streams (local) from the repository
            repository = kwargs.get('repository', '')
            stream_type = kwargs.get('type', '')
            if stream_type == 'reference_streams':
                return reference_streams

            #update cache if timestamp is different
            update_streams_cache(session_key)

            #Check cache for expired streams and delete
            base_streams = app_streams['splunk_app_stream']
            currentTimeSeconds = int(time.time())
            if (timeLastExpirationCheck != currentTimeSeconds):
                for base_stream in base_streams:
                    if 'expirationDate' in base_stream:
                        #expirationDate is expected in seconds since epoch time
                        if dt.fromtimestamp(base_stream['expirationDate']) < dt.now():
                            logger.info("Stream %s expired...deleting it", id)
                            delete_stream(base_stream['id'])
                            stream_forwarder_results_cache = {}
                timeLastExpirationCheck = currentTimeSeconds

            includeEphemeralStreams = False
            stream_forwarder_group_streams = set()
            stream_forwarder_group_ids = []
            stream_forwarder_id = kwargs.get('streamForwarderId', '_default')
            
            # if repository and id param are not part of the request, then return the streams from the matched
            # stream forwarder group. If streamForwarderId is empty, then return the 'defatultgroup' streams only. If
            # the matched group has 'includeDefaultGroupStreams' as true, then include the default group streams (union of
            # defaultgroup and matche group streams), otherwise return the matched group streams.
            if not repository and not id:
                # check if we can just use cache and exit now
                result = stream_forwarder_results_cache.get(stream_forwarder_id, {})
                if result:
                    if is_transform_required(user_agent):
                        new_result = copy.deepcopy(result)
                        new_result = get_backward_compatible_streams(new_result)
                        return new_result
                    return result

                # get matching stream forwarder groups
                stream_forwarder_id_param_supplied = 'streamForwarderId' in kwargs
                stream_forwarder_id_empty_default = stream_forwarder_id
                if (not stream_forwarder_id_param_supplied):
                    stream_forwarder_id_empty_default = ""
                stream_forwarder_groups = stream_fwd_grp.StreamForwarderGroup.match(stream_forwarder_id_empty_default, session_key)
                for g in stream_forwarder_groups:
                    stream_forwarder_group_streams = stream_forwarder_group_streams | set(g['streams'])
                    includeEphemeralStreams = includeEphemeralStreams | g['includeEphemeralStreams']
                    stream_forwarder_group_ids.append(g['id'])
                stream_forwarder_group_streams  = list(stream_forwarder_group_streams)

                logger.info("includeEphemeralStreams is set to %s", includeEphemeralStreams)

            #If no id is specified, list all streams
            if not id:
                #Check if there is a valid groupby criteria
                if 'groupby' in kwargs and (kwargs['groupby'] == 'app'):
                    result = []
                    for app_id in app_streams:
                        streams = app_streams[app_id]
                        if not repository:
                            streams = get_filtered_streams(streams, stream_forwarder_group_streams, includeEphemeralStreams)
                        if streams:
                            if is_transform_required(user_agent):
                                new_streams = copy.deepcopy(streams)
                                new_streams = get_backward_compatible_streams(new_streams)
                                result.append({"app_id": app_id, "streams": new_streams})
                            else:
                                result.append({"app_id": app_id, "streams": streams})
                    if not repository:
                        result.append({"enabled": False, "stream_forwarder_groups": stream_forwarder_group_ids})
                        stream_forwarder_results_cache[stream_forwarder_id] = result
                    return result
                else:
                    # Return a flattened list of streams
                    return_streams = []
                    for app_id in app_streams:
                        streams = app_streams[app_id]
                        if not repository:
                            streams = get_filtered_streams(streams, stream_forwarder_group_streams, includeEphemeralStreams)
                        if streams:
                            return_streams += streams

                    # Append the stream_forwarder_groups element only if the stream_forwarder_id is present
                    if not repository:
                        if stream_forwarder_id_param_supplied:
                            return_streams.append({"enabled": False, "stream_forwarder_groups": stream_forwarder_group_ids})
                        stream_forwarder_results_cache[stream_forwarder_id] = return_streams

                    if is_transform_required(user_agent):
                        new_return_streams = copy.deepcopy(return_streams)
                        new_return_streams = get_backward_compatible_streams(new_return_streams)
                        return new_return_streams
                    return return_streams
            else:
                id = os.path.basename(id)
                found_stream = get_stream_by_id(id, session_key)
                if found_stream:
                    if is_transform_required(user_agent):
                        new_found_stream = copy.deepcopy(found_stream)
                        remove = transform_stream(new_found_stream)
                        if not remove:
                            return new_found_stream
                        else:
                            return {'success': False, 'error': str("Stream with specified id not found"), 'status': 404}
                    return found_stream
                else:
                    return {'success': False, 'error': str("Stream with specified id not found"), 'status': 404}
        except Exception:
            logger.exception("failed to list streams")
            return {'success': False, 'error': 'Internal error, retrieving the stream', 'status': 500}

    @staticmethod
    def save(json_data, session_key, id='', action='', user=None, **kwargs):
        #sanitize stream id to prevent directory traversal attack
        try:
            id = os.path.basename(id)

            # Only allow splunk_app_stream streams with the name 'Stream' or ephemeral streams to be modified
            if 'app' in json_data and json_data['app'] != 'Stream' and  'expirationDate' not in json_data:
#                logger.error("External non ephemeral stream cannot be created or modified with id %s" % json_data['id'])
                logger.error("External non ephemeral stream cannot be created or modified")
                
                return {'success': False, 'error': str("External non ephemeral stream cannot be created or modified"), 'status': 400}

            """Update posted stream """
            found_stream = get_stream_by_id(id, session_key)
            if action in ['enable','disable', 'statsOnly']:
                if found_stream:
                    if action == 'statsOnly':
                        found_stream['enabled'] = True
                        found_stream['statsOnly'] = True
                    else:
                        found_stream['enabled'] = action == 'enable'
                        found_stream['statsOnly'] = False

                    if user:
                        found_stream['modifiedBy'] = user
                    if use_kv_store:
                        found_stream['_key'] = found_stream['id']
                        wrote_stream = save_stream_to_kv_store(id, found_stream, session_key)
                    else:
                        wrote_stream = write_json_to_stream(id, found_stream)
                    if not wrote_stream:
                        logger.error("Failed to update stream %s", id)
                        raise Exception('Failed to update stream')
                    #Update app_streams cache
                    streams = app_streams['splunk_app_stream']
                    update_streams_collection(found_stream)
                    #for stream in streams:
                        #if stream['id'] == id:
                            #streams.remove(stream)
                    #streams.append(found_stream)
                    return found_stream
                else:
                    return {'success': False, 'error': str("Stream with specified id not found"), 'status': 404}
        except Exception:
            logger.exception("failed to save stream")
            return {'success': False, 'error': 'Internal error, saving stream', 'status': 500}

        # read POST or PUT data of type application/json
        try:
            if not id:
                id = json_data['id']
#                logger.info("stream id from json_data: %s", id)
                # Haven't validated the id yet, so let's not log it
                logger.info("stream id from json_data")

                if id.lower() in (stream_id.lower() for stream_id in base_stream_ids):
                    return {'success': False, 'error': str("Stream with the same id already exists"), 'status': 400}
                else:
                    stream_json = json_data

                    if user:
                        stream_json['createdBy'] = user
            else:
                if found_stream and found_stream['id'] == json_data['id']:
                    stream_json = json_data
                    logger.debug("stream id passed as arg: %s", id)

                    if user:
                        stream_json['modifiedBy'] = user
                else:
                    return {'success': False, 'error': str("Stream with specified id not found"), 'status': 404}

        except Exception:
            logger.exception("failed to save stream")
            return {'success': False, 'error': 'Internal error, updating the stream', 'status': 500}

        # Stream-1836, to preserve backward compatibility for ES.
        if 'createDate' in stream_json:
            if type(stream_json['createDate']) is not int:
                try:
                    stream_json['createDate'] = int(stream_json['createDate'])
                except Exception as e:
                    pass

        # Stream-2989 For backward compatibility, if aggType is 'sum', update to ['sum']
        # Also update topSortBy to include the aggType i.e. sum(bytes) instead of bytes
        if 'aggregated' in stream_json and stream_json['aggregated']:
            for field in stream_json['fields']:
                if field['aggType'] == 'sum':
                    field['aggType'] = ['sum']

        if 'topSortBy' in stream_json['extras']:
            topSortBy = stream_json['extras']['topSortBy']
            if topSortBy != 'count' and '(' not in topSortBy and ')' not in topSortBy:
                stream_json['extras']['topSortBy'] = 'sum(' + topSortBy + ')'

        is_valid_stream, stream_validation_messages = stream_utils.is_valid_stream_definition_new(stream_json)
        # Only print ID if it's validated
        if is_valid_stream:
            logger.info("Stream with Id %s is valid", stream_json['id'])
        else:
            logger.info("Stream is invalid")

#        logger.info("Stream with Id %s is %s", stream_json['id'], is_valid_stream)
        try:
            if is_valid_stream:
                if use_kv_store:
                    stream_json['_key'] = stream_json['id']
                    if found_stream:
                        wrote_stream = save_stream_to_kv_store(id, stream_json, session_key)
                    else:
                        wrote_stream = save_stream_to_kv_store('', stream_json, session_key)
                else:
                    wrote_stream = write_json_to_stream(id, stream_json)
                if not wrote_stream:
                    logger.error("Failed to update stream %s", id)
                    raise Exception('Failed to update stream')

                logger.info('after writing the stream with id %s', id)
               
                #Update app_streams cache
                #streams = app_streams['splunk_app_stream']
                #for stream in streams:
                    #if stream['id'] == id:
                        #streams.remove(stream)

                #streams.append(stream_json)
                #stream_app_location_map[id] = app_locations_map['splunk_app_stream']

                update_valid_streams(stream_json['id'])
                # all new streams are added to defaultgroup by default for backward compatibility
                include_in_defaultgroup = kwargs.get('addToDefaultGroup', 'true')
                logger.debug('include in default group %s', include_in_defaultgroup)
                if not found_stream:
                    default_group_json = stream_fwd_grp.StreamForwarderGroup.list(session_key, 'defaultgroup')
                    if include_in_defaultgroup == 'true':
                        logger.debug(default_group_json['streams'])
                        default_group_json['streams'].append(id)
                    else:
                        # if a stream with the same id existed in the past, the id might still be in defaultgroup
                        if id in default_group_json['streams']:
                            logger.info('removing %s from default group', id)
                            default_group_json['streams'].remove(id)
                    stream_fwd_grp.StreamForwarderGroup.save(default_group_json, 'defaultgroup', user, session_key)
                update_streams_collection(stream_json)
                return stream_json
            else:
                return {'success': False, 'error': ", ".join(x for x in stream_validation_messages), 'status': 500}
        except Exception:
            logger.exception("failed to save stream")
            return {'success': False, 'error': 'Internal error, saving stream', 'status': 500}

    @staticmethod
    def delete(session_key, id='', from_netflow_script=False):
        """delete posted stream """
        #sanitize stream id to prevent directory traversal attack
        id = os.path.basename(id)

        try:
            if not id:
                return {'success': False, 'error': str("Invalid Request Data"), 'status': 400}
            else:
                status, error_msg = delete_stream(id, session_key, False, from_netflow_script)
                if status:
                    return {'success': True, 'deleted': str(id)}
                else:
                    return {'success': False, 'error': str(error_msg), 'status': 400}
        except Exception:
            logger.exception("failed to delete stream")
            return {'success': False, 'error': 'Internal error, deleting the stream', 'status': 500}
