import sys
import os
import re
import xml.dom.minidom, xml.sax.saxutils
import subprocess
import platform
import codecs
import logging
import tempfile

from splunk.clilib import cli_common as cli

#Operating system constants
OS_LINUX_32   = 'linux_x86'
OS_LINUX_64   = 'linux_x86_64'
OS_WINDOWS_64 = 'windows_x86_64'
OS_MACOS_64   = 'darwin_x86_64'

SCHEME = """<scheme>
    <title>PCAP Files</title>
    <description>Upload pcap data for indexing.</description>
    <use_external_validation>true</use_external_validation>
    <streaming_mode>xml</streaming_mode>
    <endpoint>
        <args>
            <arg name="pcap_file">
                <title>PCAP File</title>
                <description>Select a pcap file to upload for indexing.</description>
                <required_on_create>true</required_on_create>
            </arg>
            <arg name="systemTime">
                <title>System Time</title>
                <description>If true, use the system clock time for each packet read.</description>
                <required_on_create>false</required_on_create>
                <validation>is_bool('systemTime')</validation>
            </arg>
            <arg name="repeat">
                <title>Repeat</title>
                <description>If true, continuously repeat pcap files until the stream forwarder is terminated.</description>
                <required_on_create>false</required_on_create>
                <validation>is_bool('repeat')</validation>
            </arg>
            <arg name="bitrate">
                <title>Bits Per Second</title>
                <description>Set the bitrate for how fast each pcap file is read. Defaults to 10 Mbps.</description>
                <required_on_create>false</required_on_create>
                <validation>is_pos_int('bitrate')</validation>
            </arg>
        </args>
    </endpoint>
</scheme>
"""

def setupLogger(logger=None, log_format='%(asctime)s %(levelname)s [upload_pcap] %(message)s', level=logging.INFO, log_name="upload_pcap.log", logger_name="upload_pcap"):
    if logger is None:
        logger = logging.getLogger(logger_name)
    logger.propagate = False
    logger.setLevel(level)
    file_handler = logging.handlers.RotatingFileHandler(os.path.join(os.environ['SPLUNK_HOME'], 'var', 'log', 'splunk', log_name), maxBytes=2500000, backupCount=5)
    formatter = logging.Formatter(log_format)
    file_handler.setFormatter(formatter)
    logger.handlers = []
    logger.addHandler(file_handler)
    logger.debug("init %s logger", logger_name)
    return logger

def get_config_value(root, key):
    return str(root.getElementsByTagName(key)[0].firstChild.data)

def get_pcap_filename(config):
    upload_parser = re.compile(r'^FieldStorage\(\'pcap_file\',\s\'(?P<filename>[^\']+)\',\s["\'](?P<filedata>.+)["\']\)$')
    filename = upload_parser.search(config['pcap_file']).group('filename')
    return filename

def get_pcap_data(config):
    upload_parser = re.compile(r'^FieldStorage\(\'pcap_file\',\s\'(?P<filename>[^\']+)\',\s["\'](?P<filedata>.+)["\']\)$')
    results = upload_parser.search(config['pcap_file']).group('filedata')
    utf8results = results.encode('utf-8')
    return utf8results.decode('unicode-escape')

def get_upload_status():
    f = open(ready_flag, 'r')
    status = int(f.read())
    f.close()
    return status

def set_upload_status(status):
    f = open(ready_flag, 'w')
    f.write(str(status))
    f.close()

def get_params(stanza):
    params_config = {}
    name = stanza.getAttribute("name")
    if name:
        logger.debug("XML: Found stanza %s", name)
        params_config["name"] = name
    params = stanza.getElementsByTagName("param")
    for param in params:
        param_name = param.getAttribute("name")
        logger.debug("XML: Found param '%s'",param_name)
        if param_name and param.firstChild and param.firstChild.nodeType == param.firstChild.TEXT_NODE:
            data = param.firstChild.data
            params_config[param_name] = data
            logger.debug("XML: '%s' -> '%s'", param_name, data if param_name != 'pcap_file' else get_pcap_filename(params_config))
    return params_config

def get_config():
    config = {}
    try:
        config_str = sys.stdin.read()
        doc = xml.dom.minidom.parseString(config_str)
        root = doc.documentElement

        server_host = get_config_value(root, "server_host")
        server_uri = get_config_value(root, "server_uri")
        session_key = get_config_value(root, "session_key")
        checkpoint_dir = get_config_value(root, "checkpoint_dir")

        if server_host:
            logger.debug("XML: Found server_host")
            config["server_host"] = server_host
        if server_uri:
            logger.debug("XML: Found server_uri")
            config["server_uri"] = server_uri
        if session_key:
            logger.debug("XML: Found session_key")
            config["session_key"] = session_key
        if checkpoint_dir:
            logger.debug("XML: Found checkpoint_dir")
            config["checkpoint_dir"] = checkpoint_dir

        conf_node = root.getElementsByTagName("configuration")[0]
        if conf_node:
            logger.debug("XML: Found configuration")
            stanza = conf_node.getElementsByTagName("stanza")[0]
            if stanza:
                config.update(get_params(stanza))

        if not config:
            logger.error("Invalid configuration received from Splunk.")
            raise Exception("Invalid configuration received from Splunk.")

    except Exception as e:
        logger.error(e)
        raise Exception("Error getting Splunk configuration via STDIN: %s" % str(e))

    return config

def get_arch():
    if platform.system() == 'Linux':
        if platform.architecture()[0] == '64bit':
            return OS_LINUX_64
        else:
            return OS_LINUX_32
    elif platform.system() == 'Windows':
        return OS_WINDOWS_64
    else:
        return OS_MACOS_64

def get_cmd():
    arch = get_arch()
    executable = 'streamfwd.exe' if arch == OS_WINDOWS_64 else 'streamfwd'
    return os.path.join(os.environ['SPLUNK_HOME'], 'etc', 'apps', 'Splunk_TA_stream', arch, 'bin', executable)

def get_args(config, validation_mode=False):
    args = []
    args.append(get_cmd())

    #avoid creating tempfile when doing validation checking
    if not validation_mode:
        prefix = 'tmp' if 'name' not in config.keys() else config['name'][14:] + '_'
        fd, filepath = tempfile.mkstemp(prefix=prefix, suffix='.pcap')
        f = codecs.open(filepath, 'w', 'latin-1')
        f.write(get_pcap_data(config))
        f.close()
    else:
        filepath = 'val_tmp'

    args.append('-r')
    args.append(filepath)

    if 'bitrate' in config.keys():
        args.append('-b')
        if config['bitrate']:
            args.append(config['bitrate'])
        else:
            args.append('1000000')
    if int(config['repeat']):
        args.append('--repeat')
    if int(config['systemTime']):
        args.append('--systime')
    args.append('--modinput')
    return args

def print_error(s):
    print("<error><message>" + xml.sax.saxutils.escape(s) + "</message></error>")

def get_validation_data():
    val_data = {}
    val_str = ''
    for line in sys.stdin:
        #if pcap data is too long, only store part of it to avoid memory errors
        if line[17:26] == 'pcap_file' and len(line) > 250:
            val_str += line[:200] + '\')</param>'
        else:
            val_str += line
    doc = xml.dom.minidom.parseString(val_str)
    root = doc.documentElement
    item_node = root.getElementsByTagName("item")[0]
    if item_node:
        name = item_node.getAttribute("name")
        params_node = item_node.getElementsByTagName("param")
        for param in params_node:
            name = param.getAttribute("name")
            if name and param.firstChild and param.firstChild.nodeType == param.firstChild.TEXT_NODE:
                val_data[name] = param.firstChild.data
    return val_data

def validPCAPFileName(fileName):
    if OS_WINDOWS_64 == get_arch():
        return re.match('^.+\.p?cap$', fileName)
    return re.match('^.+\.pcapng$|^.+\.p?cap$', fileName)


def validate_arguments():
    try:
        val_data = get_validation_data()
        if 'bitrate' in val_data.keys() and int(val_data['bitrate']) >= 1000000000:
            raise Exception("Bitrate must be a positive integer less than 10Gbps")
        args = get_args(val_data, True)
        if not os.path.isfile(args[0]):
            raise Exception("Stream Forwarder executable missing")
        if not validPCAPFileName(get_pcap_filename(val_data)):
            raise Exception("Invalid file type")
        set_upload_status(1)
    except Exception as e:
        print_error("Invalid configuration specified: %s" % str(e))
        sys.exit(1)

if __name__ == '__main__':
    ready_flag = os.path.join(os.environ['SPLUNK_HOME'], 'etc', 'apps', 'splunk_app_stream', 'local', 'upload_pcap_status')
    if len(sys.argv) > 1:
        if sys.argv[1] == "--scheme":
            print(SCHEME)
        elif sys.argv[1] == "--validate-arguments":
            validate_arguments()
        sys.exit(0)
    else:
        logger = setupLogger(level=logging.DEBUG)
        config = get_config()

        if int(config['repeat']) == 0 and get_upload_status() == 0:
            logger.debug('pcap_file: %s has already been uploaded' % get_pcap_filename(config))
            sys.exit(0)

        set_upload_status(0)
        args = get_args(config)

        # for windows
        args[0] = '"' + args[0] + '"'

        logger.debug('command: %s' % ' '.join(args))

        p = subprocess.Popen(' '.join(args), cwd=os.path.join(os.environ['SPLUNK_HOME'], 'etc', 'apps', 'Splunk_TA_stream'),
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)

        inputs_config = cli.getConfStanza('inputs', 'streamfwd://streamfwd')
        source = inputs_config.get('source')
        app_location = inputs_config.get('splunk_stream_app_location')

        logger.debug('source: %s' % source)
        logger.debug('splunk_stream_app_location: %s' % app_location)

        modinput_xml = '<input>' \
            '<server_host>'+config['server_host']+'</server_host>' \
            '<server_uri>'+config['server_uri']+'</server_uri>' \
            '<session_key>'+config['session_key']+'</session_key>' \
            '<checkpoint_dir>'+config['checkpoint_dir']+'</checkpoint_dir>' \
            '<configuration>' \
                '<stanza name="'+config['name']+'">' \
                    '<param name="disabled">false</param>' \
                    '<param name="host">'+config['host']+'</param>' \
                    '<param name="index">'+config['index']+'</param>' \
                    '<param name="source">'+source+'</param>' \
                    '<param name="passAuth">admin</param>' \
                    '<param name="splunk_stream_app_location">'+app_location+'</param>' \
                '</stanza>' \
            '</configuration>' \
        '</input>'
        
        try:
            p.stdin.write(modinput_xml)
        except:
            p.stdin.write(modinput_xml.encode('utf-8'))
        p.stdin.close()

        if int(config['repeat']):
            while True:
                data = p.stdout.read(1024)
                try:
                    sys.stdout.write(data)
                except:
                    sys.stdout.write(data.decode('utf-8'))
        else:
            data = p.stdout.read()
            try:
                sys.stdout.write(data)
            except:
                sys.stdout.write(data.decode('utf-8'))

