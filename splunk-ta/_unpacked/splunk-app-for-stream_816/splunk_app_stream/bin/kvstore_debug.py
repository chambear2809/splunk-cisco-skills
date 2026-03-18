'''
This file contains the implementation of the script used to debug the Stream KVStore.

This is a self-contained tool for gathering troubleshooting data related to the
KVStore implementation of Splunk App for Stream. It provides organized information
for debugging purposes.

The script can be run via the Splunk command line interface via the following command
from the Splunk Home directory:

	- bin/splunk cmd python etc/apps/splunk_app_stream/bin/kvstore_debug.py [options]

Running the script produces a compressed .tar.gz archive in the Splunk Home directory:

	- splunk-app-stream-(hostname)-(date).tar.gz

Extracting the archive produces the following information:

	- JSONs present in KV Store
	- JSONs present in pre-kv backup directory
	- Parsed XML configs of KV Store
	- Relevant .conf files
	- Directory/File structure of Stream App
	- Stream Log Files
	- Splunk and Stream version info

Options available to this script can be viewed via the -h option:

	--owner=[owner]    (set owner of kvstore data)
	--local            (toggle to only output kvstre data in local config structure)
'''
from xml.dom import minidom
import datetime
import getpass
import json
import logging
import optparse
import os
import posixpath
import re
import signal
import socket
import sys
import tarfile
import tempfile

import splunk.auth
import splunk.rest
from splunk.appserver.mrsparkle.lib import util

try:
	SPLUNK_HOME = os.environ['SPLUNK_HOME']
except:
	SPLUNK_HOME = os.path.abspath(os.path.join(util.get_apps_dir(), '..', '..'))

SPLUNK_VERSION_FILE = os.path.join(SPLUNK_HOME, 'etc', 'splunk.version')
LOG_DIR             = os.path.join(SPLUNK_HOME, 'var', 'log', 'splunk')
STREAM_DIR          = os.path.join(util.get_apps_dir(), 'splunk_app_stream')
PRE_KV_STORE_DIR    = os.path.join(STREAM_DIR, 'local', 'pre_kv_store_config')
STREAM_VERSION_FILE = os.path.join(STREAM_DIR, 'default', 'app.conf')

collections = ('streams', 'streamforwardergroups', 'miscellaneous')
conf_files  = ('collections',)
logs        = ('splunk_app_stream', 'streamfwd')

logger = logging.getLogger('stream_kvstore_debug')

#global vars: (Tarfile) tar, (str) tar_name, (str) base_kvstore_path, str session_key, (bool) local


#########
# SETUP #
#########


def setup_logger():
	logger.setLevel(logging.INFO)
	ch = logging.StreamHandler(sys.stdout)
	ch.setLevel(logging.INFO)
	formatter = logging.Formatter('%(message)s')
	ch.setFormatter(formatter)
	logger.addHandler(ch)

#Setup args into global vars to make information available to rest of script
def setup_args():
	global base_kvstore_path
	global session_key
	global local
	splunkd_url = 'https://localhost:8089'
	(options, args) = parse_args()
	owner = options.owner
	local = options.local
	base_kvstore_path = get_kvstore_path(splunkd_url, owner)
	session_key = get_auth(splunkd_url)
	logger.info('Running with options: %s' % options)

#Further options for script can be added here
def parse_args():
	run_command = '$SPLUNK_HOME/bin/splunk cmd python $SPLUNK_HOME/etc/apps/splunk_app_stream/bin/kvstore_debug.py [options]'
	parser = optparse.OptionParser(usage=run_command, description='Debug KV store config for Splunk App for Stream')
	parser.add_option('--owner', metavar='owner', type=str, default='nobody', help='owner of data in kvstore (default: nobody)')
	parser.add_option('--local', action='store_true', default=False, help='only output kvstore jsons in local configuration format')
	return parser.parse_args()


def get_username(msg):
	#To run correct command to capture user input based on python version 2 or 3
    if (sys.version_info > (3, 0)):
        return input(msg)
    else:
        return raw_input(msg)


#Ask user for credentials and retrieve session key
def get_auth(url):
	pass_retries = 3
	auth_user = get_username('Splunk username: ')
	try:
		for i in range(pass_retries):
			auth_pass = getpass.getpass('Splunk password: ')
			try:
				sessionKey = splunk.auth.getSessionKey(auth_user, auth_pass, url)
				return sessionKey
			except:
				if i+1 == pass_retries:
					logger.error('Failed to log in.')
					sys.exit(0)
				else:
					logger.warning('Invalid credentials. Try again.')
	except Exception as e:
		logger.error(e)
		sys.exit(0)

def get_kvstore_path(url, owner):
	app_context = 'splunk_app_stream'
	return posixpath.join(url, 'servicesNS', owner, app_context, 'storage', 'collections')

def signal_handler(signal, frame):
	logger.info('\nKilled via Signal Interrupt.')
	sys.exit(0)


###########
# KVSTORE #
###########


#Returns content if success, else returns None
def kvstore_get(extension):
	try:
		kvstore_path = posixpath.join(base_kvstore_path, extension)
		response, content = splunk.rest.simpleRequest(kvstore_path, method='GET', sessionKey=session_key, timeout=splunk.rest.SPLUNKD_CONNECTION_TIMEOUT)
		if response.status == 200:
			return content
		logger.error('Failed GET request w/ HTTP Error Code: %d' % response.status)
	except Exception as e:
		logger.error(e)
	return None


###############
# TAR ARCHIVE #
###############

def create_tar_archive():
	global tar
	create_tar_name()
	tar_path = os.path.join(SPLUNK_HOME, '%s.tar.gz' % tar_name)
	tar = tarfile.open(name=tar_path, mode='w:gz')
	create_tar_dir()

def create_tar_name():
	global tar_name
	cur_datetime = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
	tar_name = 'splunk-app-stream-%s-%s' % (get_splunkinstance_name(), cur_datetime)
	logger.info('Selected archive name of: %s' % tar_name)

def get_splunkinstance_name():
	return socket.gethostname()

#Creates the main directory with same name as tar archive
def create_tar_dir():
	tar_dir = tarfile.TarInfo(tar_name)
	tar_dir.type = tarfile.DIRTYPE
	tar_dir.mode = int('0755', 8)
	tar.addfile(tar_dir)

#Copy over a file into archive
def add_file_to_archive(file_path, file_name):
	dest_name = os.path.join(tar_name, file_name)
	tar.add(file_path, arcname=dest_name)

#Write messages directly to archive
def write_msg_to_archive(name, msg):
	f = TemporaryFile()
	f.write(msg)
	f.add_to_archive(name)

#Creates a temporary file to write to before adding to archive
class TemporaryFile(object):

	def __init__(self):
		self.fd, self.path = tempfile.mkstemp()
		self.file = open(self.path, 'w')

	def write(self, msg):
		try:		
			self.file.write(str(msg))
		except:
			pass

	#Adds file to archive and cleans tempfile
	def add_to_archive(self, name):
		try:
			self.file.close()
			add_file_to_archive(self.path, name)
		finally:
			if not self.file.closed:
				self.file.close()
			os.close(self.fd)
			os.remove(self.path)


##################
# ADD TO ARCHIVE #
##################


#Add all requested files into tar archive
def add_files_to_archive():
	logger.info('Starting Splunk App for Stream KVStore Debug Process...')
	add_kvstore_jsons_to_archive()
	#Skip adding other info if --local option is toggled to true
	if not local:
		add_kvstore_configs_to_archive()
		add_backup_streams_to_archive()
		add_conf_to_archive()
		add_logs_to_archive()
		add_app_structure_to_archive()
		add_app_info_to_archive()
	logger.info('Cleaning up...')

#Directory name of kvstore jsons is dependent on --local option status
def add_kvstore_jsons_to_archive():
	dir_name = 'local' if local else 'kvstore_jsons'
	for collection in ('streams', 'streamforwardergroups'):
		logger.info('Getting KVStore JSON for %s' % collection)
		split_and_add_collection(collection, dir_name)
	logger.info('Getting KVStore JSON for miscellaneous')
	add_misc_collections(dir_name)

def add_misc_collections(dir_name):
	content = kvstore_get(posixpath.join('data', 'miscellaneous'))
	if content:
		ip_dir = os.path.join(dir_name, 'captureipaddresses')
		users_dir = os.path.join(dir_name, 'users')
		for j in json.loads(content):
			if j['_key'] in ('blacklist', 'whitelist'):
				j['id'] = j['_key']
				file_dest = os.path.join(ip_dir, j['id'])
				j = prettify_json(j)
				write_msg_to_archive(file_dest, j)
			elif j['_key'] == 'usertours':
				users = []
				for field in j:
					if type(j[field]) == list:
						users = prettify_json(j[field])
						break
				file_dest = os.path.join(users_dir, 'tour_users')
				write_msg_to_archive(file_dest, str(users))
			elif j['_key'] == 'appsmeta':
				if 'id' in j:
					j.pop('id')
				j = prettify_json(j)
				file_dest = os.path.join(dir_name, 'apps')
				write_msg_to_archive(file_dest, j)

#Skips the main kvstore config to avoid redundancy
def add_kvstore_configs_to_archive():
	for col in collections:
		logger.info('Getting %s config...' % col)
		config_path = posixpath.join('config', col)
		content = kvstore_get(config_path)
		if content:
			try:
				file_dest = os.path.join('configs', '%s_config.txt' % col)
				write_config_xml(file_dest, content)
			except:
				logger.error('Failed parsing of %s config xml' % col)

#Add pre-kvstore streams
def add_backup_streams_to_archive():
	local_dir = os.path.join(STREAM_DIR, 'local')
	pre_kv_dirname = 'pre_kv_store_config'
	if pre_kv_dirname in os.listdir(local_dir):
		logger.info('Getting Pre-KVStore config...')
		pre_kv_dir = os.path.join(local_dir, pre_kv_dirname)
		backup_files = get_all_file_names(pre_kv_dir)
		dir_name = 'backup_jsons'
		for f in backup_files:
			file_dest = os.path.join(dir_name, os.path.relpath(f, pre_kv_dir))
			add_file_to_archive(f, file_dest)

def add_conf_to_archive():
	for conf in conf_files:
		try:
			logger.info('Getting %s configuration file...' % conf)
			file_path = os.path.join(STREAM_DIR, 'default', '%s.conf' % conf)
			add_file_to_archive(file_path, '%s.conf' % conf)
		except:
			logger.error('%s.conf does not exist.' % conf)

def add_logs_to_archive():
	for l in logs:
		log_path = os.path.join(LOG_DIR, '%s.log' % l)
		try:
			logger.info('Getting %s log...' % l)
			file_dest = os.path.join('logs', '%s.log' % l)
			add_file_to_archive(log_path, file_dest)
		except:
			logger.error('Log %s does not exist.' % log_path)

#Add directory and file layout of app
def add_app_structure_to_archive():
	logger.info('Getting stream app directory structure...')
	f = TemporaryFile()
	all_files = get_all_file_names(STREAM_DIR)
	f.write('\n'.join(all_files))
	f.add_to_archive('stream_app_structure.txt')

#Add Splunk and stream version info
def add_app_info_to_archive():
	f = TemporaryFile()
	logger.info('Getting Splunk version info...')
	f.write('****** Splunk Version Info ******\n\n')
	copy_file(SPLUNK_VERSION_FILE, f)
	logger.info('Getting stream version info...')
	f.write('\n\n****** Stream Version Info ******\n\n')
	f.write(get_stream_version())
	f.add_to_archive('version.txt')


####################
# HELPER FUNCTIONS #
####################


def prettify_json(j):
	fields_to_remove = [field for field in j if field[0] == '_']
	for field in fields_to_remove:
		j.pop(field)
	return json.dumps(j, indent=4, sort_keys=True)

def write_config_xml(file_name, content):
	f = TemporaryFile()
	content = minidom.parseString(content)
	title = content.getElementsByTagName('title')[1].firstChild.nodeValue
	f.write('****** %s config ******\n\n' % title)

	#Writes the xml data to file in clean indented hierarchical format
	def write_nested_keys(key_nodes, indent=0):
		indent_level = ' ' * 4 * indent
		for node in key_nodes:
			if len(node.childNodes) == 1:
				key = node.getAttribute('name')
				value = node.firstChild.nodeValue
				f.write('%s%s = %s\n' % (indent_level, key, value))
			elif len(node.childNodes) > 1:
				child = node.childNodes[1]
				if child.tagName == 's:dict':
					f.write('%s%s\n' % (indent_level, node.getAttribute('name')))
					write_nested_keys(child.childNodes, indent+1)
				elif child.tagName == 's:list':
					if len(child.childNodes) > 2:
						get_value = lambda x: str(x.firstChild.nodeValue)
						rlist = map(get_value, child.childNodes[1:-1])
						f.write('%s%s = %s\n' % (indent_level, node.getAttribute('name'), rlist))
					else:
						f.write('%s%s = []\n' % (indent_level, node.getAttribute('name')))

	outer_keys = lambda x: x.parentNode.parentNode.tagName == 'content'
	key_nodes = filter(outer_keys, content.getElementsByTagName('s:key'))
	write_nested_keys(key_nodes)
	f.add_to_archive(file_name)

#Split collection into multiple json files to match local storage
def split_and_add_collection(name, dir_name):
	content = kvstore_get(posixpath.join('data', name))
	if content:
		for j in json.loads(content):
			j['id'] = j['_key']
			file_dest = os.path.join(dir_name, name, j['id'])
			j = prettify_json(j)
			write_msg_to_archive(file_dest, j)

#Retrieve all nested files within a directory
def get_all_file_names(dir_path):
	files, dirs = [], []
	try:
		for f in os.listdir(dir_path):
			f = os.path.join(dir_path, f)
			if os.path.isfile(f):
				files.append(f)
			elif os.path.isdir(f):
				dirs.append(f)
	except:
		logger.error('Directory %s does not exist.' % dir_path)
	for d in dirs:
		files += get_all_file_names(d)
	return files

#Does not overwrite existing data in outfile
def copy_file(infile, outfile):
	try:
		with open(infile, 'r') as version_file:
			for line in version_file:
				outfile.write(line)
	except:
		logger.error('File %s does not exist' % infile)

def get_stream_version():
	try:
		f = open(STREAM_VERSION_FILE, 'r')
		for line in f:
			match = re.match('^\s*version\s*=.*$', line)
			if match:
				return match.group(0)
	except:
		logger.error('File %s does not exist' % STREAM_VERSION_FILE)
	finally:
		f.close()
	return 'Could not find version number'


########
# MAIN #
########


if __name__ == '__main__':
	signal.signal(signal.SIGINT, signal_handler)
	setup_logger()
	setup_args()
	try:
		create_tar_archive()
		add_files_to_archive()
	finally:
		tar.close()
		logger.info('Stream KV Store Debug File created: %s.tar.gz' % os.path.join(SPLUNK_HOME, tar_name))
