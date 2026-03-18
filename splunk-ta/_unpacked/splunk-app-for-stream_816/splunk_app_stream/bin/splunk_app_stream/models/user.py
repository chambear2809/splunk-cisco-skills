import os

import splunk.appserver.mrsparkle.lib.util as util

import splunk_app_stream.utils.stream_utils as stream_utils
import splunk_app_stream.utils.stream_kvstore_utils as kv_utils
from splunk_app_stream.models.ping import Ping


logger = stream_utils.setup_logger('user')

users_dir = os.path.join(util.get_apps_dir(), 'splunk_app_stream', 'local', 'users')
tour_users = set()
easy_setup_users = set()

# Last updated time used to refresh cache
dateLastUpdated = 0

#kv store
user_tours_kv_store_uri = '/servicesNS/nobody/splunk_app_stream/storage/collections/data/users/all/tour'
user_tours_kv_store_with_session_key_uri = kv_utils.misc_kv_store_uri + '/usertours'
user_easy_setup_kv_store_uri = '/servicesNS/nobody/splunk_app_stream/storage/collections/data/users/all/easysetup'
user_easy_setup_kv_store_with_session_key_uri = kv_utils.misc_kv_store_uri + '/easysetup'
use_kv_store = kv_utils.is_kv_store_supported_in_splunk()
if not use_kv_store:
    stream_utils.createDir(users_dir + os.sep)

def init_users(session_key=None):
    global tour_users, easy_setup_users, dateLastUpdated
    try:
        pingData = Ping.ping(session_key)
        if pingData['dateLastUpdated'] > dateLastUpdated:
            logger.info("cachedateLastUpdated::%d appsDateLastUpdated::%d", dateLastUpdated, pingData['dateLastUpdated'])
            dateLastUpdated = pingData['dateLastUpdated']
            if not use_kv_store:
                tour_users_list = stream_utils.readAsJson(os.path.join(users_dir, 'tour_users'))
                if tour_users_list != 'NotFound':
                    tour_users = set(tour_users_list)
                easy_setup_users_list = stream_utils.readAsJson(os.path.join(users_dir, 'easy_setup_users'))
                if easy_setup_users_list != 'NotFound':
                    easy_setup_users = set(easy_setup_users_list)
            else:
                uri = user_tours_kv_store_uri
                if session_key:
                    uri = user_tours_kv_store_with_session_key_uri
                json_data = kv_utils.read_from_kv_store_coll(uri, session_key)
                if 'visited' in json_data:
                    tour_users = set(json_data['visited'])

                uri = user_easy_setup_kv_store_uri
                if session_key:
                    uri = user_easy_setup_kv_store_with_session_key_uri
                json_data = kv_utils.read_from_kv_store_coll(uri, session_key)
                if 'visited' in json_data:
                    easy_setup_users = set(json_data['visited'])
            
    except Exception:
        # Exception happens as appsMeta file is in the process of getting written to.
        # Do Nothing and return existing cache.
        logger.exception("failed init users")

def update(user_flag, session_key):
    if use_kv_store:
        kv_utils.update_kv_store_apps_meta(session_key)
        flag_id = ''
        users = set()
        if user_flag == 'tour':
            flag_id = 'usertours'
            users = tour_users
        else:
            flag_id = 'easysetup'
            users = easy_setup_users

        json_data = {}
        json_data['id'] = flag_id
        json_data['_key'] = flag_id
        json_data['visited'] = list(users)

        if not kv_utils.save_to_kv_store(kv_utils.misc_kv_store_uri, flag_id, json_data, session_key):
            kv_utils.save_to_kv_store(kv_utils.misc_kv_store_uri, None, json_data, session_key)
    else:
        if user_flag == 'tour':
            stream_utils.writeAsJson(os.path.join(users_dir, 'tour_users'), list(tour_users))
        else:
            stream_utils.writeAsJson(os.path.join(users_dir, 'easy_setup_users'), list(easy_setup_users))

    
class User:

    @staticmethod
    def get_user_flag(user_name, user_flag, session_key=None):
        '''Return tour visited for the username'''
        init_users(session_key)
        users = set()
        if user_flag == 'tour':
            users = tour_users
        else:
            users = easy_setup_users

        if user_name == 'all':
            return {'visited': list(users)}
        if user_name in users:
            return {'visited': True}
        else:
            return {'visited': False}
        
        
    @staticmethod
    def set_user_flag(user_name, user_flag, user_flag_visited, session_key=None):
        '''Update tour visited for the username '''
        global tour_users, easy_setup_users
        init_users(session_key)
        if user_flag == 'tour':
            users = tour_users
        else:
            users = easy_setup_users
        if user_name:
            if user_name in users:
                if user_flag_visited:
                    return {'visited': True}
                else:
                    users.remove(user_name)                    
                    update(user_flag, session_key)
                    return {'visited': False}
            else:
                if user_flag_visited:
                    users.add(user_name)                   
                    update(user_flag, session_key)
                    return {'visited': True}
                else:
                    return {'visited': False}
        else:
            return {'success': False, 'error': str("Bad Request, username required"), 'status': 400}
