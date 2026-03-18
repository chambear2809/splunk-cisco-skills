import json
import os
import shutil
import uuid

try:
    # py3
    from urllib.parse import quote as urllibquote
except ImportError:
    # py2
    from urllib import quote as urllibquote

import splunk
import splunk.appserver.mrsparkle.lib.util as util

import splunk_app_stream.utils.stream_kvstore_utils as kv_utils
import splunk_app_stream.utils.stream_utils as stream_utils


logger = stream_utils.setup_logger('fileservermountpoint')
DIR_NAME = 'fileservermountpoints'

#kv store
use_kv_store = kv_utils.is_kv_store_supported_in_splunk()
orig_use_kv_store = use_kv_store

# config files locations
default_dir = os.path.join(util.get_apps_dir(), 'splunk_app_stream', 'default', DIR_NAME)
local_dir = os.path.join(util.get_apps_dir(), 'splunk_app_stream', 'local', DIR_NAME)

# collections.conf contains [fileservermountpointsTEST]
test_suffix = 'TEST'

def hide_kv_store(kwargs):
    v = kwargs.get('hideKVStore')
    return v and (v[0] == 't' or v[0] == 'T')

def use_test_collection(kwargs):
    v = kwargs.get('useTestCollection')
    return v and (v[0] == 't' or v[0] == 'T')

# placeholder for possible future caching implementation
# TODO: Decide if caching mount points is worth doing.
def init_file_server_mount_points():
    pass

# validate file server mount point
def is_valid(json_data):
    return True

# This is needed because uuid.uuid3() doesn't work in the context of splunk; an error occurs when
# adding namespace.bytes + name, apparently because splunk sets the default encoding to 'utf8'
# (as can be seen by calling sys.getdefaultencoding()).
# I modified uuid.uuid3() here to make the concatenation of byte strings work.
# I verified its correctness by confirming that uuid3local(uuid.NAMESPACE_DNS, 'python.org')
# returns UUID('6fa459ea-ee8a-3ca4-894e-db77e160355e')
# which matches the python docs (https://docs.python.org/2/library/uuid.html)
# uuid3 (UUID version 3) is defined in RFC 412, section 4.1.3.
def uuid3local(namespace, name):
    """Generate a UUID from the MD5 hash of a namespace UUID and a name."""
    from hashlib import md5

    # The line in uuid3() in SPLUNK_HOME/Python-2.7/Lib/uuid.py that causes an error is:
    # hash = md5(namespace.bytes + name).digest()

    hash = md5(bytearray(namespace.bytes) + bytearray(name, "ascii")).digest()

    return uuid.UUID(bytes=hash[:16], version=3)


class FileServerMountPoint:

    @staticmethod
    def list(session_key=None, id='', **kwargs):
        logger.debug("FileServerMountPoint::list:id = %s", id)

        if use_kv_store and not hide_kv_store(kwargs):
            uri = kv_utils.file_server_mount_points_kv_store_coll
            if use_test_collection(kwargs):
                uri += test_suffix
            if id:
                # The 2nd param is needed so that '/' is also encoded.
                id = urllibquote(id, '')

                response = kv_utils.read_by_id_from_kv_store_coll(uri, id, session_key)
                logger.debug("FileServerMountPoint::list:response = %s", response)
                return response
            else:
                json_data = kv_utils.read_from_kv_store_coll(uri, session_key)
                return json_data
        else:
            if id:
                filename = str(uuid3local(uuid.NAMESPACE_URL, id))
                config_path = os.path.join(local_dir, filename)
                if not os.path.exists(config_path):
                    config_path = os.path.join(default_dir, filename)
                    if not os.path.exists(config_path):
                        return {'success': False, 'error': 'Could not find record with id = %s' % id, 'status': 404}

                logger.debug("FileServerMountPoint::list::config_path = %s", config_path)
                try:
                    f = open(config_path, 'r')
                    data = f.read()
                    json_data = json.loads(data)
                except Exception as e:
                    logger.exception("failed to load file server mount point config")
                    return {'success': False, 'error': e, 'status': 500}
                finally:
                    f.close()
                return json_data
            else:
                # Using a dict here so local files will override default ones.
                mount_point_dict = {}
                for config_dir in [default_dir, local_dir]:
                    if os.path.exists(config_dir):
                        for fname in os.listdir(config_dir):
                            config_path = os.path.join(config_dir, fname)
                            logger.debug("FileServerMountPoint::list::config_path = %s", config_path)
                            try:
                                f = open(config_path, 'r')
                                data = f.read()
                                record = json.loads(data)
                                if 'id' in record:
                                    mount_point_dict[record['id']] = record
                                else:
                                    raise Exception('%s does not contain id' % config_path)
                            except Exception as e:
                                logger.exception("failed to parse file server mount point config")
                                return {'success': False, 'error': e, 'status': 500}
                            finally:
                                f.close()
                return list(mount_point_dict.values())


    @staticmethod
    def create(json_data, session_key=None, **kwargs):
        if not 'id' in json_data:
            logger.error("Failed to create file server mount point because no id was provided.")
            raise Exception('Failed to create file server mount point because no id was provided.')
        id = json_data['id']

        if is_valid(json_data):
            if use_kv_store and not hide_kv_store(kwargs):
                uri = kv_utils.file_server_mount_points_kv_store_coll
                if use_test_collection(kwargs):
                    uri += test_suffix
                json_data['_key'] = json_data['id']
                try:
                    save_succeeded = kv_utils.save_to_kv_store(uri, None, json_data, session_key)
                    if save_succeeded:
                        return json_data
                    else:
                        logger.error("Failed to create file server mount point.")
                        # TODO: rewrite save_to_kv_store() to return the status
                        return {'success': False, 'error': 'Internal error, creating a file server mount point', 'status': 500}
                except Exception:
                    logger.exception("failed to create server mount point")
                    return {'success': False, 'error': 'Internal error, creating a file server mount point', 'status': 500}
            else:
                filename = str(uuid3local(uuid.NAMESPACE_URL, id))
                config_path = os.path.join(local_dir, filename)
                logger.debug("FileServerMountPoint::create:config_path = %s", config_path)
                if os.path.exists(config_path):
                    # returning 409 because that's what KV store does
                    return {'success': False, 'error': 'Record with specified id already exists.', 'status': 409}
                try:
                    stream_utils.createDir(local_dir + os.sep)
                    f = open(config_path, 'w')
                    f.write(json.dumps(json_data))
                    stream_utils.updateAppsMeta()
                except Exception:
                    logger.exception("failed to create file server mount point")
                    return {'success': False, 'error': 'Internal error, creating a file server mount point', 'status': 500}
                finally:
                    f.close()
            return json_data
        else:
            return {'success': False, 'error': "Invalid file server mount point specification", 'status': 500}


    @staticmethod
    def update(json_data, id='', session_key=None, **kwargs):
        if id == '' or id == None:
            logger.error("Failed to update file server mount point because the id was empty.")
            raise Exception('Failed to update file server mount point because the id was empty.')

        if id != json_data['id']:
            logger.error("Conflicting ids.")
            raise Exception('Conflicting ids.')

        if is_valid(json_data):
            if use_kv_store and not hide_kv_store(kwargs):
                uri = kv_utils.file_server_mount_points_kv_store_coll
                if use_test_collection(kwargs):
                    uri += test_suffix
                try:
                    # The 2nd param is needed so that '/' is also encoded.
                    id = urllibquote(id, '')

                    update_succeeded = kv_utils.save_to_kv_store(uri, id, json_data, session_key)
                    if update_succeeded:
                        return json_data
                    else:
                        logger.error("Failed to update file server mount point.")
                        return {'success': False, 'error': 'Internal error, updating a file server mount point', 'status': 500}
                except Exception:
                    logger.exception("failed to update file server mount point")
                    return {'success': False, 'error': 'Internal error, updating a file server mount point', 'status': 500}
            else:
                filename = str(uuid3local(uuid.NAMESPACE_URL, id))
                config_path = os.path.join(local_dir, filename)
                logger.debug("FileServerMountPoint::update:config_path = %s", config_path)
                try:
                    stream_utils.createDir(local_dir + os.sep)
                    f = open(config_path, 'w')
                    f.write(json.dumps(json_data))
                    stream_utils.updateAppsMeta()
                except Exception:
                    logger.exception("failed to create server mount point")
                    return {'success': False, 'error': 'Internal error, creating a file server mount point', 'status': 500}
                finally:
                    f.close()
            return json_data
        else:
            return {'success': False, 'error': "Invalid file server mount point specification", 'status': 500}


    @staticmethod
    def delete(id='', session_key=None, **kwargs):
        if use_kv_store and not hide_kv_store(kwargs):
            uri = kv_utils.file_server_mount_points_kv_store_coll
            if use_test_collection(kwargs):
                uri += test_suffix
            if id:
                # The 2nd param is needed so that '/' is also encoded.
                uri = uri + '/' + urllibquote(id, '')
            try:
                serverResponse, serverContent = kv_utils.kv_store_rest_request(uri, 'DELETE', session_key)
                logger.debug("FileServerMountPoint::delete:serverResponse = %s", serverResponse)
                if serverResponse['status'] == '200':
                    return {'success': True, 'status': 200}
                else:
                    return {'success': False, 'error': 'Delete failed', 'status': serverResponse['status']}
            except splunk.ResourceNotFound:
                return {'success': False, 'error': 'File server mount point not found', 'status': 404}
            except Exception:
                logger.exception("failed to delete file server mount point")
                return {'success': False, 'error': 'Internal error, deleting the file server mount point', 'status': 500}
        else:
            # We are intentionally not searching default_dir here, since we don't allow deleting
            # from there.  (See, e.g. delete_stream().)
            if id:
                filename = str(uuid3local(uuid.NAMESPACE_URL, id))
                config_path = os.path.join(local_dir, filename)
                logger.debug("FileServerMountPoint::delete:config_path = %s", config_path)
                if not os.path.exists(config_path):
                    return {'success': False, 'error': 'Could not find %s' % config_path, 'status': 404}
                try:
                    os.remove(config_path)
                except Exception as e:
                    logger.exception("failed to delete file server mount point")
                    return {'success': False, 'error': e, 'status': 500}
                return {'success': True, 'status': 200}
            else:
                if os.path.exists(local_dir):
                    try:
                        shutil.rmtree(local_dir)
                    except Exception as e:
                        logger.exception("failed to delete file server mount point")
                        return {'success': False, 'error': e, 'status': 500}
                return {'success': True, 'status': 200}
