import os.path as op
import sys

bin_path = op.dirname(op.abspath(__file__))
if bin_path not in sys.path:
    sys.path.append(bin_path)

import shutil
import os

import splunk
import splunk.rest
import splunk.appserver.mrsparkle.lib.util as util

import splunk_app_stream.utils.stream_utils as stream_utils
import splunk_app_stream.utils.stream_kvstore_utils as kv_utils


logger = stream_utils.setup_logger('rest_kvstore_migrate')

# REST Handler class to migrate json files to KVStore. 

def perform_migration(local_dir, coll_name, sessionKey, id=None, file_ids=None):
    if not file_ids:
        file_ids = filter(lambda x: not x.startswith('.'), next(os.walk(local_dir))[2])
    logger.info('perform_migration: from folder %s to coll_name %s file_ids %s', local_dir, coll_name, file_ids)
    for file_id in file_ids:
        json_data = stream_utils.readAsJson(os.path.join(local_dir, file_id))
        if not id:
            json_data['_key'] = json_data['id']
        else:
            new_json_data = json_data
            if id == 'usertours':
                new_json_data = {}
                new_json_data['visited'] = json_data
            new_json_data['_key'] = id
            new_json_data['id'] = id
            json_data = new_json_data
        try:
            serverResponse, serverContent = kv_utils.kv_store_rest_request( coll_name, 'POST', sessionKey, False,
                                                                                        json_data)
            logger.info('perform_migration: migrating %s to coll_name %s response_status %s', file_id, coll_name, serverResponse['status'])
            if serverResponse == 500 or 'error' in serverContent:
                logger.error('perform_migration: migrating failed for %s to coll_name %s response_status %s error %s', file_id, coll_name, serverResponse['status'], serverContent['error'])
                return False
        except splunk.RESTException as e:
            if e.statusCode == 409:
                logger.info('perform_migration: %s to coll_name %s already exists', file_id, coll_name)
        except Exception:
            logger.exception('perform_migration: migrating failed for %s to coll_name %s', file_id, coll_name)
            return False
        
    return True


def migrate(sessionKey):
    stream_app = stream_utils.get_stream_app_name()
    local_streams_dir = os.path.join(util.get_apps_dir(), stream_app, 'local', 'streams')
    local_capture_addresses_dir = os.path.join(util.get_apps_dir(), stream_app, 'local', 'captureipaddresses')
    local_file_server_mount_points_dir = os.path.join(util.get_apps_dir(), stream_app, 'local', 'fileservermountpoints')
    local_stream_forwarder_groups_dir = os.path.join(util.get_apps_dir(), stream_app, 'local', 'streamforwardergroups')
    local_users_dir = os.path.join(util.get_apps_dir(), stream_app, 'local', 'users')
    local_dir =  os.path.join(util.get_apps_dir(), stream_app, 'local') 
    backup_dir = os.path.join(util.get_apps_dir(), stream_app, 'local', 'pre_kv_store_config')

     
    #migrate local/streams to kv store
    if os.path.exists(local_streams_dir) :
        logger.info('migrate: streams')
        if perform_migration(local_streams_dir, kv_utils.streams_kv_store_coll, sessionKey):
            #move the version file to the new location under local/.version
            if not os.path.exists(os.path.join(local_dir, '.version')):
                if os.path.exists(os.path.join(local_streams_dir, '.version')):
                    shutil.move(os.path.join(local_streams_dir, '.version'), local_dir)
            else:
                os.remove(os.path.join(local_streams_dir, '.version'))
            if not os.path.exists(os.path.join(backup_dir, 'streams')):
                shutil.move(local_streams_dir, os.path.join(backup_dir, 'streams'))    
        else:
            logger.error('migrate: migration failed for local streams folder')
    elif not os.path.exists(local_streams_dir):
        logger.info('migrate: no local streams folder to migrate')
    else:
        logger.info('migrate: local streams migration was already performed')

    #migrate local/captureipaddresses to kv store
    if os.path.exists(local_capture_addresses_dir):
        logger.info('migrate: captureipaddresses')
        if perform_migration(local_capture_addresses_dir, kv_utils.misc_kv_store_uri, sessionKey):
            if not os.path.exists(os.path.join(backup_dir, 'captureipaddresses')):
                shutil.move(local_capture_addresses_dir, os.path.join(backup_dir, 'captureipaddresses'))
        else:
            logger.error('migrate: migration failed for local captureipaddresses folder')
    elif not os.path.exists(local_capture_addresses_dir):
        logger.info('migrate: no local captureipaddresses folder to migrate')
    else:
        logger.info('migrate: local captureipaddresses migration was already performed')

    #migrate local/fileservermountpoints to kv store
    if os.path.exists(local_file_server_mount_points_dir):
        logger.info('migrate: fileservermountpoints')
        if perform_migration(local_file_server_mount_points_dir, kv_utils.file_server_mount_points_kv_store_coll, sessionKey):
            if not os.path.exists(os.path.join(backup_dir, 'fileservermountpoints')):
                shutil.move(local_file_server_mount_points_dir, os.path.join(backup_dir, 'fileservermountpoints'))
        else:
            logger.error('migrate: migration failed for local fileservermountpoints folder')
    else:
        logger.info('migrate: no local fileservermountpoints folder to migrate')

    #migrate local/streamforwardergroups to kv store
    if os.path.exists(local_stream_forwarder_groups_dir):
        logger.info('migrate: streamforwardergroups')
        if perform_migration(local_stream_forwarder_groups_dir, kv_utils.stream_forwarder_groups_kv_store_coll, sessionKey):
            if not os.path.exists(os.path.join(backup_dir, 'streamforwardergroups')):
                shutil.move(local_stream_forwarder_groups_dir, os.path.join(backup_dir, 'streamforwardergroups'))
        else:
            logger.error('migrate: migration failed for local streamforwardergroups folder')
    elif not os.path.exists(local_stream_forwarder_groups_dir):
        logger.info('migrate: no local streamforwardergroups folder to migrate')
    else:
        logger.info('migrate: local streamforwardergroups migration was already performed')

    #migrate local/users to kv store
    if os.path.exists(local_users_dir):
        logger.info('migrate: usertours')
        if perform_migration(local_users_dir, kv_utils.misc_kv_store_uri, sessionKey, 'usertours'):
            if not os.path.exists(os.path.join(backup_dir, 'users')):
                shutil.move(local_users_dir, os.path.join(backup_dir, 'users'))
        else:
            logger.error('migrate: migration failed for local users folder')
    elif not os.path.exists(local_users_dir):
        logger.info('migrate: no local users folder to migrate')
    else:
        logger.info('migrate: local users migration was already performed')


    #migrate apps meta to kv store
    if os.path.exists(os.path.join(local_dir, 'apps')): 
        logger.info('migrate: appsmeta')
        if perform_migration(local_dir, kv_utils.misc_kv_store_uri, sessionKey,  'appsmeta', ['apps']):
            if not os.path.exists(os.path.join(backup_dir, 'apps')):
                shutil.move(os.path.join(local_dir, 'apps'),  backup_dir) 
            else:
                os.remove(os.path.join(local_dir, 'apps'))
        else:
            logger.error('migrate: migration failed for local apps metadata')       
    elif not os.path.exists(os.path.join(local_dir, 'apps')):
        logger.info('migrate: no local apps metadata to migrate')
    else:
        logger.info('migrate: local apps metadata migration was already performed')


class KVStoreMigrate(splunk.rest.BaseRestHandler):

    def handle_POST(self):
        '''Return kvstore status''' 
        sessionKey = None
        output = {'success': True, 'status': 200}

        if 'systemAuth' in self.request and self.request['systemAuth']:
            sessionKey = self.request['systemAuth']
        else:
            sessionKey = self.sessionKey
        # check for auth key
        auth_key = None
        if 'systemAuth' in self.request:
            auth_key = stream_utils.extract_auth_key(self.request, self.args)
            auth_success  = stream_utils.validate_streamfwd_auth(auth_key)
            if not auth_success:
                self.response.status = 401
                output = {'success': False, 'error': 'Unauthorized', 'status': 401}
                return output

        use_kv_store = kv_utils.is_kv_store_supported_in_splunk()
        if sessionKey and use_kv_store:
            try:
                migrate(sessionKey)
            except Exception:
                logger.exception("failed to migrate")
        else:
            logger.info('Failed to migrate: sessionKey %s kv_store_supported %s', sessionKey, use_kv_store)
            output = {'success': False, 'status': 500, 'error': 'Failed to migrate'}                 
        return output
    handle_PUT = handle_POST
