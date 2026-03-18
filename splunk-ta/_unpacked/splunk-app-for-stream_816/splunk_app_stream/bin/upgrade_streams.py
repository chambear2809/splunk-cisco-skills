import os
import copy
import json
import shutil
from collections import OrderedDict

import splunk.appserver.mrsparkle.lib.util as util

import splunk_app_stream.utils.stream_utils as stream_utils
import splunk_app_stream.utils.stream_kvstore_utils as kv_utils

# Determine stream app name (or folder...)
stream_app = stream_utils.get_stream_app_name()

currentDir = os.path.dirname(__file__)
base_default_streams_dir = os.path.join(util.get_apps_dir(), stream_app, 'default', "streams")
base_local_streams_dir = os.path.join(util.get_apps_dir(), stream_app, 'local', "streams")
base_local_dir = os.path.join(util.get_apps_dir(), stream_app, 'local')
version_file = os.path.join(util.get_apps_dir(), stream_app, 'local', '.version')


# map containing a list of splunk_app_stream version to new streams that were added in this version
# for any new version add an entry into the map using the version as the key and a list of new streams added as the value
# for e.g., version_to_new_streams_map['6.4.1'] = ['new_stream1', 'new_stream2']
# if there are no new streams, no need to add that version
version_to_new_streams_map = OrderedDict()
version_to_new_streams_map['6.4.0'] = [
    "Splunk_DNSClientErrors",
    "Splunk_DNSClientQueryTypes",
    "Splunk_DNSIntegrity",
    "Splunk_DNSRequestResponse",
    "Splunk_DNSServerErrors",
    "Splunk_DNSServerQuery",
    "Splunk_DNSServerResponse",
    "Splunk_HTTPClient",
    "Splunk_HTTPResponseTime",
    "Splunk_HTTPStatus",
    "Splunk_HTTPURI",
    "Splunk_MySql",
    "Splunk_Postgres",
    "Splunk_SSLActivity",
    "Splunk_Tds",
    "Splunk_Tns"
    ]
version_to_new_streams_map['6.6.0'] = [
    "rtp",
    "icmp",
    "ip"
    ]

version_to_new_streams_map['6.7.0'] = [
    "arp",
    "netflow",
    "sflow",
    "Splunk_IP",
    "Splunk_Tcp",
    "Splunk_Udp"
]

version_to_new_streams_map['7.1.0'] = [
    "rtcp",
    "igmp"
]

version_to_new_streams_map['7.1.1'] = [
    "Splunk_IP"
]

version_to_new_streams_map['8.0.0'] = [
    "modbus"
]

# map containing a list of splunk_app_stream version to new content extraction fields that were added in this version
# for any new version add an entry into the map using the version as the key and a list of new content extractions fields added as the value
# for e.g., version_to_new_content_extraction_fields_map['6.4.1'] = ['new_content_extraction_field1', 'new_content_extraction_field2']
# if there are no new streams, no need to add that version
version_to_new_content_extraction_fields_map = OrderedDict()
version_to_new_content_extraction_fields_map['6.7.0'] = [
    'src_content_md5_hash',
    'dest_content_md5_hash',
    'attach_content_md5_hash',
    'attach_content_decoded_md5_hash'
    ]


#new streams to be added to defaultgroup
new_default_group_streams = []

# list of deprecated fields that can be deleted from the streams
schema_deprecated_fields = ['locked']

# Initialize the first such logger.
logger = stream_utils.setup_logger('upgrade_streams')

#keys that can change in reference streams
override_user_stream_keys_values = ['category', 'sourcetype', 'protocolName', 'name']
override_user_field_keys_values = ['aggType', 'desc', 'name', 'isList']

#add the oob stream filter to delete, map key should be oob stream id and the value
#is a list of filter comparisons that need to be deleted for e.g.:
#filters_to_delete_from_oob_stream = {"Splunk_SSLActivity": [{
          #"matchAllValues": False,
          #"term": "flow.ssl-cert-subject",
          #"type": "is-defined",
          #"value": ""
        #}]
#}
filters_to_delete_from_oob_stream = {}

oob_stream_default_disabled_fields = [
    'flow_id', 'protocol_stack', 'result_column_count', 'result_row_count',
    'sql_error_code', 'bind_variable_value', 'txt_vals', 'vxlan_id', 'vlan_tags'
]


default_stream_ids = []
if os.path.exists(base_default_streams_dir):
    default_stream_ids = filter(lambda x: not x.startswith('.'), next(os.walk(base_default_streams_dir))[2])

def get_new_streams(old_version, new_version):
    new_streams = []
    logger.debug("New version %s Old version %s", new_version, old_version)
    skip_upgrade = True
    try:
        nv = int (new_version.replace('.', ''))
        ov = int (old_version.replace('.', ''))
        # skip if new_version is less than or equal to the old version
        if nv > ov:
            # get the new streams to be copied from default to local for the versions between old version and the new version of the app
            # include the new version streams also
            # uses version_to_new_streams_map to get the new streams added in a version
            skip_upgrade = False
            for k in version_to_new_streams_map:
                v = int (k.replace('.', ''))
                if v > ov and v <= nv:
                    new_streams = new_streams + version_to_new_streams_map[k]
    except Exception:
        logger.exception("failed to get new streams")

    return new_streams, skip_upgrade

# copy from default to local for base streams
def copy_default_to_local_streams(use_kv_store, coll_name=None, session_key=None):
    global new_default_group_streams
    updated = False

    # get the new version of the app which has been installed
    new_version = stream_utils.getAppVersion()
    old_version = None
    if os.path.exists(base_local_dir):
        logger.info('copy_default_to_local_streams:: base local folder present')
        # get the existing version as old version
        old_version_json = stream_utils.readAsJson(version_file)
        if old_version_json == 'NotFound':
            # read again from the path that was used in old versions
            old_version_json = stream_utils.readAsJson(os.path.join(base_local_streams_dir, '.version'))
        local_stream_ids = []
        if use_kv_store:
            local_streams = kv_utils.read_from_kv_store_coll(coll_name, session_key, True)
            local_stream_ids = [s['id'] for s in local_streams]
        else:
            if (os.path.exists(base_local_streams_dir)):
                local_stream_ids = filter(lambda x: not x.startswith('.'), next(os.walk(base_local_streams_dir))[2])
        if old_version_json != 'NotFound':
            # version file found, it is an upgrade from old version in version file to the new version of the app
            old_version = old_version_json['version']
            new_streams_to_copy, skip_upgrade = get_new_streams(old_version, new_version)
            logger.info("old_version:%s new_version:%s", old_version, new_version)
            if skip_upgrade:
                logger.debug("Upgrade skipped because the new version is not greater than the old version")
                return (updated, old_version, new_version)
            if not new_streams_to_copy:
                updated = True
            new_default_group_streams = new_streams_to_copy
            for s_id in new_streams_to_copy:
                if s_id not in local_stream_ids:
                    logger.info("copying the new stream %s not in local streams", s_id)
                else:
                    logger.info("updating stream %s which is already present in local streams", s_id)
                    #existing stream must be deleted before adding updated stream for kvstore
                    if use_kv_store:
                        serverResponse, serverContent = kv_utils.kv_store_rest_request(coll_name + '/' + s_id, 'DELETE', session_key)
                try:
                    if use_kv_store:
                        stream_json = stream_utils.readAsJson(os.path.join(base_default_streams_dir, s_id))
                        stream_json['_key'] = stream_json['id']
                        serverResponse, serverContent = kv_utils.kv_store_rest_request( coll_name, 'POST', session_key, False,
                                                                                stream_json)
                    else:
                        shutil.copy2(os.path.join(base_default_streams_dir, s_id), base_local_streams_dir)
                    updated = True
                except:
                    logger.exception("Error copying the file %s", os.path.join(base_default_streams_dir, s_id))
        else:
            # no version file found, copy the default streams that are not in the local streams
            logger.info('no old version found')
            for k in version_to_new_streams_map:
                new_default_group_streams = new_default_group_streams + version_to_new_streams_map[k]

            # local streams are already existing in the data store but for some reason version file is not present
            if local_stream_ids:
                updated = True
            if not use_kv_store:
                stream_utils.createDir(base_local_streams_dir + os.sep)

            for s_id in default_stream_ids:
                if s_id not in local_stream_ids:
                    logger.info("copying the new stream %s not in local streams", s_id)
                    try:
                        if use_kv_store:
                            stream_json = stream_utils.readAsJson(os.path.join(base_default_streams_dir, s_id))
                            stream_json['_key'] = stream_json['id']
                            serverResponse, serverContent = kv_utils.kv_store_rest_request( coll_name, 'POST', session_key, False,
                                                                                    stream_json)
                        else:
                            shutil.copy2(os.path.join(base_default_streams_dir, s_id), base_local_streams_dir)
                        updated = True
                    except:
                        logger.exception("Error copying the file %s", os.path.join(base_default_streams_dir, s_id))
    else:
        # no local streams folder found, treat it as a prestine install and copy all the default streams to local
        # get the existing version as old version
        logger.info('base local foler not found, pristine installation')
        old_version_json = stream_utils.readAsJson(version_file)
        if old_version_json == 'NotFound':
            # read again from the path that was used in old versions
            old_version_json = stream_utils.readAsJson(os.path.join(base_local_streams_dir, '.version'))
        if old_version_json != 'NotFound':
            old_version = old_version_json['version']
            new_streams_to_copy, skip_upgrade = get_new_streams(old_version, new_version)
            logger.info("old_version:%s new_version:%s", old_version, new_version)
            if skip_upgrade:
                logger.debug("new version is already installed, skipping the installation")
                return (updated, old_version, new_version)

        for k in version_to_new_streams_map:
            new_default_group_streams = new_default_group_streams + version_to_new_streams_map[k]
        if not use_kv_store:
            logger.info('creating base local streams folder')
            stream_utils.createDir(base_local_streams_dir + os.sep)
        else:
            local_streams = kv_utils.read_from_kv_store_coll(coll_name, session_key, True)
            local_stream_ids = [s['id'] for s in local_streams]
        for s_id in default_stream_ids:
            try:
                if use_kv_store:
                    if s_id not in local_stream_ids:
                        logger.info("copying the new stream %s not in local streams", s_id)
                        stream_json = stream_utils.readAsJson(os.path.join(base_default_streams_dir, s_id))
                        stream_json['_key'] = stream_json['id']
                        serverResponse, serverContent = kv_utils.kv_store_rest_request( coll_name, 'POST', session_key, False,
                                                                                stream_json)
                else:
                    shutil.copy2(os.path.join(base_default_streams_dir, s_id), base_local_streams_dir)
                updated = True
            except:
                logger.exception("Error copying the file %s", os.path.join(base_default_streams_dir, s_id))
    if updated:
        new_version_json = {}
        new_version_json['version'] = new_version
        # save it to file
        try:
            f = open( version_file, 'w+' )
            f.write(json.dumps(new_version_json, sort_keys=True, indent=2))
            f.close()
        except:
            logger.error('Unable to create the version file')
    else:
        logger.error('Install or update  to version %s failed ', new_version)

    logger.info("old_version:%s new_version:%s", old_version, new_version)
    return (updated, old_version, new_version)


def modified_streams_exist(use_kv_store, coll_name=None, session_key=None):
    local_stream_ids = []
    if use_kv_store:
        local_streams = kv_utils.read_from_kv_store_coll(coll_name, session_key, True)
        local_stream_ids = [s['id'] for s in local_streams]
    else:
        local_stream_ids = stream_utils.get_stream_ids(base_local_streams_dir)
    return local_stream_ids and len(local_stream_ids)

def update_field_changes(default_stream, local_stream, local_stream_fields_by_term, oob_stream):
    stream_modified = False

    if oob_stream:
        oob_stream_fields = oob_stream['fields']

    for df in default_stream['fields']:
        if df['term'] in local_stream_fields_by_term and 'transformation' not in df:
            local_fields = local_stream_fields_by_term[df['term']]
            for lf in local_fields:
                #add all new attributes for each field in default field
                for key in df:
                    if key not in lf:
                        logger.info('default stream field key %s is not in local stream, so adding to stream:: %s', key, local_stream['id'])
                        lf[key] = df[key]
                        stream_modified = True
                #remove the attributes not present in default field
                lf_copy = copy.deepcopy(lf)
                for key in lf_copy:
                    if key not in df:
                        #don't delete the transformation key and isList key for extracted fields
                        if not(key == 'transformation' or (key == 'isList' and 'transformation' in lf_copy)):
                            del lf[key]
                            logger.info('local stream field attibute %s is not present in default stream, so removing in stream:: %s', key, local_stream['id'])
                            stream_modified = True
                for k in override_user_field_keys_values:
                    if k == 'aggType':
                        if 'aggregated' in local_stream and local_stream['aggregated']:
                            if lf[k] == 'value':
                                lf[k] = 'key'
                                stream_modified = True
                                logger.info('Wrong aggtype for Aggregate stream %s, changed to "key" instead of "value"', local_stream['id'])

                            if lf[k] == 'sum':
                                if 'topSortBy' in local_stream['extras']:
                                    top_sort_by = local_stream['extras']['topSortBy']
                                    if top_sort_by == lf['name']:
                                        local_stream['extras']['topSortBy'] = "sum(" + top_sort_by + ")"
                                lf[k] = ['sum']
                                # update the value of aggType from oob stream, if found in the oob stream
                                if oob_stream:
                                    for oobf in oob_stream_fields:
                                        if oobf['name'] == lf['name']:
                                            lf[k] = oobf[k]
                                stream_modified = True
                                logger.info('Aggtype changed to list for Aggregate stream %s, changed to "[sum]" instead of "sum"', local_stream['id'])

                    else:
                        if 'transformation' not in lf and k in lf and k in df and lf[k] != df[k]:
                            logger.info('default stream field key %s is changed from %s to %s, so updating in stream:: %s', k, lf[k], df[k], local_stream['id'])
                            lf[k] = df[k]
                            stream_modified = True

    return stream_modified

def update_filters(oob_stream, local_stream):
    #update "the filters"
    stream_modified = False
    if 'filters' in oob_stream and 'comparisons' in oob_stream['filters']:
        comps = oob_stream['filters']['comparisons']
        if comps:
            add_new_comps = []
            for comp in comps:
                found = False
                for local_comp in local_stream['filters']['comparisons']:
                    if set(comp.items()) == set(local_comp.items()):
                        found = True
                if not found:
                    add_new_comps.append(comp)

            if add_new_comps:
                local_comps = local_stream['filters']['comparisons']
                logger.info("Added new filter %s to stream %s", add_new_comps, local_stream['id'])
                local_comps.extend(add_new_comps)
                stream_modified = True

        #delete the filters present in filters_to_delete_from_oob_stream
        if filters_to_delete_from_oob_stream:
            if oob_stream['id'] in filters_to_delete_from_oob_stream:
                comps = filters_to_delete_from_oob_stream[oob_stream['id']]
                if comps:
                    delete_comps_index = []
                    for comp in comps:
                        for i, local_comp in enumerate(local_stream['filters']['comparisons']):
                            if set(comp.items()) == set(local_comp.items()):
                                logger.info("Deleteing filter %s to stream %s", comp, local_stream['id'])
                                del local_stream['filters']['comparisons'][i]
                                stream_modified = True

    return stream_modified


def update_streams(use_kv_store, old_version, new_version, coll_name=None, session_key=None):
    local_stream_ids = []
    local_streams_map = {}
    nv = int (new_version.replace('.', ''))
    ov = 0
    if old_version:
        ov = int (old_version.replace('.', ''))

    if use_kv_store:
        local_streams = kv_utils.read_from_kv_store_coll(coll_name, session_key, True)
        for s in local_streams:
            local_streams_map[s['id']] = s
            local_stream_ids.append(s['id'])
    else:
        local_stream_ids = stream_utils.get_stream_ids(base_local_streams_dir)

    for stream_id in local_stream_ids:

        stream_modified = False

        try:
            local_stream = None
            if use_kv_store:
                local_stream = local_streams_map[stream_id]
            else:
                stream_path = os.path.join(base_local_streams_dir, stream_id)
                local_stream = stream_utils.readAsJson(stream_path)

            if local_stream != "NotFound":
                event_type = local_stream['extras']['eventType']

                # Get the original stream definition based on the event Id
                default_stream_id = event_type.split('.')[0]
                # for "flow" default_stream_id use the suffix to decide if its "tcp" or "udp"
                # event_type = "flow.tcp-event" or "flow.udp-event"
                if default_stream_id == "flow":
                    new_default_stream_id = (event_type.split('.')[1]).split('-')[0]
                    default_stream_id = new_default_stream_id
                default_stream_path = os.path.join(base_default_streams_dir, default_stream_id)
                default_stream = stream_utils.readAsJson(default_stream_path)
                # also read the corresponding OOB stream if the local_stream_id is found in the default stream folder
                oob_stream = None
                if stream_id != default_stream_id and stream_id in default_stream_ids:
                    oob_stream = stream_utils.readAsJson(os.path.join(base_default_streams_dir, stream_id))

                if default_stream != "NotFound":

                    default_stream_terms = frozenset([x['term'] if 'transformation' not in x else None for x in default_stream['fields']])
                    default_content_extract_stream_fields = ([x if 'transformation' in x else None for x in default_stream['fields']])
                    local_content_extract_stream_fields = ([x if 'transformation' in x else None for x in local_stream['fields']])

                    # Add any new content extraction fields found in the default stream definition and check the version_to_new_content_extraction_fields_map
                    if default_content_extract_stream_fields:
                        for orig_field in default_content_extract_stream_fields:
                            if orig_field:
                                found = False
                                for local_field in local_content_extract_stream_fields:
                                    if local_field and local_field['name'] == orig_field['name']:
                                        found = True
                                        break
                                if not found:
                                    for k in version_to_new_content_extraction_fields_map:
                                        v = int (k.replace('.', ''))
                                        if v > ov and v <= nv:
                                            if orig_field['name'] in version_to_new_content_extraction_fields_map[k]:
                                                local_stream['fields'].append(orig_field)
                                                logger.info("Added field(%s) to Stream %s", orig_field['name'], local_stream['id'])
                                                stream_modified = True

                    # Add any other key that was added to default stream and not present in local stream
                    for key in default_stream:
                        if key not in local_stream:
                            local_stream[key] = default_stream[key]
                            logger.info("Added field(%s) to Stream %s", key, local_stream['id'])
                            stream_modified = True

                    # Add any key that has been added for this OOB stream
                    if oob_stream:
                        for key in oob_stream:
                            if key not in local_stream:
                                local_stream[key] = oob_stream[key]
                                logger.info("Added field(%s) to Stream %s", key, local_stream['id'])
                                stream_modified = True
                        #update "the filters"
                        if update_filters(oob_stream, local_stream):
                            stream_modified = True

                    # Delete any deprecated field that is obsolete from local stream
                    for f in schema_deprecated_fields:
                        try:
                            if local_stream[f]:
                                del local_stream[f]
                                logger.info("Deleted the deprecated field %s from stream %s", f, local_stream['id'])
                                stream_modified = True
                        except:
                            pass

                    # detect any changes for the existing keys listed in override_user_stream_keys_values and override_user_field_keys_values
                    # for each key in override_user_stream_keys_values, check if it is changed in the default reference stream
                    for k in override_user_stream_keys_values:
                        if k in default_stream:
                            if oob_stream and k == 'name' and oob_stream[k] != local_stream[k]:
                                logger.info('oob stream key %s is changed from %s to %s, so updating in stream:: %s', k, local_stream[k], oob_stream[k], local_stream['id'])
                                local_stream[k] = oob_stream[k]
                                stream_modified = True
                            elif 'expirationDate' not in local_stream and k != 'name' and default_stream[k] != local_stream[k]:
                                logger.info('default stream key %s is changed from %s to %s, so updating in stream:: %s', k, local_stream[k], default_stream[k], local_stream['id'])
                                local_stream[k] = default_stream[k]
                                stream_modified = True

                    # for each key in override_user_field_keys_values, check if it is changed in the default reference stream
                    local_stream_fields_by_term = {}
                    for f in local_stream['fields']:
                        if not f['term'] in local_stream_fields_by_term:
                            local_stream_fields_by_term[f['term']] = list()
                        local_stream_fields_by_term[f['term']].append(f)

                    if default_stream_terms:
                        #update terms
                        if oob_stream:
                            if update_field_changes(default_stream, local_stream, local_stream_fields_by_term, oob_stream):
                                stream_modified = True
                        else:
                            if update_field_changes(default_stream, local_stream, local_stream_fields_by_term, None):
                                stream_modified = True


                    #isReferenceStream in a local stream created based of a reference stream should be false
                    if oob_stream or stream_id not in default_stream_ids:
                        if 'isReferenceStream' in local_stream:
                            if local_stream['isReferenceStream']:
                                local_stream['isReferenceStream'] = False
                                logger.info('isReferenceStream value changed to False in stream:: %s', local_stream['id'])
                                stream_modified = True
                        else:
                            local_stream['isReferenceStream'] = False
                            logger.info('isReferenceStream not found, value set to False in stream:: %s', local_stream['id'])
                            stream_modified = True

                else:
                    logger.error("Stream definition for %s not found", default_stream_id)

                if stream_modified:
                    logger.info("Updated definition found for Stream %s ....upgrading on disk", stream_id)
                    if use_kv_store:
                        local_stream['_key'] = local_stream['id']
                        serverResponse, serverContent = kv_utils.kv_store_rest_request(coll_name + '/' + local_stream['id'],
                                                                                'PUT', session_key, False, local_stream)
                    else:
                        stream_utils.writeAsJson(stream_path, local_stream)

            else:
                logger.error("Stream path %s for local stream %s not valid", stream_path, stream_id)

        except Exception:
            logger.exception("failed to handle stream")

def get_default_group_streams():
    return new_default_group_streams
