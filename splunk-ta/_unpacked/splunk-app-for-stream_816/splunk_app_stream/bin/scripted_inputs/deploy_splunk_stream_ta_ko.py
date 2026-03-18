import json
import logging.handlers
import os
import re
import sys
import time

from distutils.version import LooseVersion
import distutils.dir_util as dir_util

import splunk
import splunk.entity
import splunk.appserver.mrsparkle.lib.util as app_util
from splunk.clilib import cli_common as cli

SPLUNK_HOME = os.environ.get('SPLUNK_HOME')
STREAM_TA_KO_INSTALLER_FILENAME = os.path.join(SPLUNK_HOME,'var','log','splunk','stream_ta_ko_installer.log')
STREAM_PATH = 'en-us/custom/splunk_app_stream/'


logger = logging.getLogger('stream_ta_ko_installer')
logger.setLevel(logging.DEBUG)
handler = logging.handlers.RotatingFileHandler(STREAM_TA_KO_INSTALLER_FILENAME, maxBytes=1024000, backupCount=5)
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
handler.setLevel(logging.DEBUG)
logger.addHandler(handler)


APP_NAME = 'splunk_app_stream'
APPS_DIR = app_util.get_apps_dir()
(ETC_DIR, APPS_STEM) = os.path.split(APPS_DIR)
INSTALL_DIR = os.path.join(APPS_DIR, APP_NAME, 'install')
DEPENDENCY_TA = 'Splunk_TA_stream'
STREAMFWD_URI = 'servicesNS/nobody/Splunk_TA_stream/data/inputs/streamfwd/streamfwd/'
STREAM_APP_RELOAD = '/servicesNS/nobody/system/apps/local/splunk_app_stream/_reload'


def entryExitDecorator(func):
    def decorated(*args):
        logger.info("Splunk App for Stream Dependency Manager: Checking for updates...")
        try:
            returnVal = func(*args)
        except Exception as error:
            logger.error("Splunk App for Stream Dependency Manager: Caught exception in %s" % func.__name__)
            logger.exception(error)
        logger.info("Splunk App for Stream Dependency Manager: Exiting...")
        return returnVal
    return decorated

#creates inputs.conf
#param appdir - location of Stream TA
#param location - update param location of Stream App
#param disabled - flag to indicate whether Stream TA is to be enabled or disabled
def createInputs(appdir, location, disabled):
    logger.info("Splunk App for Stream Dependency Manager: createInputs...")

    localdir = os.path.join(appdir, 'local')
    if not os.path.exists(localdir):
        os.makedirs(localdir)
    inputs_file = os.path.join(localdir, 'inputs.conf')
    if not os.path.exists(inputs_file):
        try:
            fo = open(inputs_file, 'w')
            try:
                fo.write( "[streamfwd://streamfwd]\n")
                fo.write( "splunk_stream_app_location = %s\n" % location)
                fo.write( "stream_forwarder_id = %s\n" % "")
                fo.write( "disabled = %d\n" % disabled)
                logger.info("Splunk App for Stream Dependency Manager: created config file (disabled=%d): %s" % (disabled, inputs_file))
            finally:
                fo.close()
        except Exception as ex:
            logger.error("Splunk App for Stream Dependency Manager: IOerror, unable to create inputs.conf")
            logger.exception(ex)

    
def getEntity(appName,sessionToken):
    return splunk.entity.getEntities('/apps/local', search=appName, sessionKey=sessionToken)

def getSplunkURIConfig(sessionToken):
    serverEntity = splunk.entity.getEntity('server/settings', 'settings', sessionKey=sessionToken)
    splunkProtocol = 'http'
    splunkHost = 'localhost'
    splunkPort = '8000'
    if serverEntity:
        splunkProtocol = ("https" if int(serverEntity['enableSplunkWebSSL'])==1 else "http")
        splunkHost = serverEntity['host']
        splunkPort = serverEntity['httpport']
    
    return splunkProtocol,splunkHost,splunkPort
    
def getSplunkRootEndPoint(sessionToken):
    splunkRootEndPoint = None
    webEntity = splunk.entity.getEntity('configs/conf-web', 'settings', sessionKey=sessionToken)
    if (webEntity and 'root_endpoint' in webEntity):
        splunkRootEndPoint = webEntity['root_endpoint']
        logger.info("Splunk App for Stream Dependency Manager: Got root_endpoint value as %s " % splunkRootEndPoint)
        if not splunkRootEndPoint.startswith('/'):
            splunkRootEndPoint = "/" + splunkRootEndPoint
        if not splunkRootEndPoint.endswith('/'):
            splunkRootEndPoint += '/'
    return splunkRootEndPoint

def reloadStreamApp(sessionToken):
    logger.info("Splunk App for Stream Dependency Manager: reloadStreamApp...")
    serverResponse, serverContent = splunk.rest.simpleRequest(
          app_util.make_url_internal(STREAM_APP_RELOAD),
          sessionToken,
          postargs=None,
          method='GET',
          raiseAllErrors=True,
          proxyMode=False,
          rawResult=None,
          jsonargs=None,
          timeout=splunk.rest.SPLUNKD_CONNECTION_TIMEOUT)
          
def modifyUploadPcapModinput(enable,sessionToken):
    def modify_mod_input(enable):
        reload = False
        specfile_dir = os.path.join(os.environ['SPLUNK_HOME'], 'etc', 'apps', APP_NAME,'README')
        disabled_spec_file = os.path.join(specfile_dir, 'inputs.conf.spec.disabled')
        spec_file = os.path.join(specfile_dir, 'inputs.conf.spec')
        if enable:
            if not os.path.exists(spec_file):
                os.rename(disabled_spec_file,spec_file)
                reload = True
        else:
            if not os.path.exists(disabled_spec_file):
                os.rename(spec_file,disabled_spec_file)
                reload = True
            if  os.path.exists(spec_file):
                os.remove(spec_file)
                reload = True
        return reload
            
    return modify_mod_input(enable)

def enablePCAPUpload(sessionToken):
    return modifyUploadPcapModinput(True,sessionToken)
    
def disablePCAPUpload(sessionToken):
    return modifyUploadPcapModinput(False,sessionToken)
    
#returns true if Stream TA is disabled else return false
#param sessionKey - indicates session in use
#param location - update param location of Stream App
#param disabled - flag to indicate whether Stream TA is to be enabled or disabled
def isStreamTADisabled(sessionKey):
    logger.info("Splunk App for Stream Dependency Manager: isStreamTADisabled...")

    disabled = True
    serverResponse, serverContent = splunk.rest.simpleRequest(
                app_util.make_url_internal(STREAMFWD_URI + '?output_mode=json'),
                sessionKey,
                postargs=None,
                method='GET',
                raiseAllErrors=True,
                proxyMode=False,
                rawResult=None,
                jsonargs=None,
                timeout=splunk.rest.SPLUNKD_CONNECTION_TIMEOUT
            )
    status = serverResponse['status']
    logger.info('Splunk App for Stream Dependency Manager: status of streamfwd disabled state GET request %s ' % status)
    if status == '200':
        disabled_state =  json.loads(serverContent)['entry'][0]['content']['disabled']
        logger.info("Splunk App for Stream Dependency Manager: streamfwd disabled state %s " % disabled_state)
        if not(disabled_state):
            disabled = False
    return disabled

#configures Stream TA
#param sessionKey - indicates session in use
def configureStreamTA(sessionKey):
    logger.info("Splunk App for Stream Dependency Manager: configureStreamTA...")
    serverProto, serverHost, serverPort = getSplunkURIConfig(sessionKey)
    endPoint = getSplunkRootEndPoint(sessionKey)
    rootEndPoint = (endPoint if (endPoint) else '/')
    
    streamTALocation = os.path.join(APPS_DIR, DEPENDENCY_TA)
    appLocation = ( "%s://%s:%s%s%s" % (serverProto, 'localhost',serverPort, rootEndPoint, STREAM_PATH))
    createInputs(streamTALocation, appLocation, 0)
    
#returns true if Stream TA is already configured else false
def isStreamTAConfigured():
    logger.info("Splunk App for Stream Dependency Manager: isStreamTAConfigured..")
    streamTALocation = os.path.join(APPS_DIR, DEPENDENCY_TA)
    streamTAlocalDir = os.path.join(streamTALocation, 'local')
    inputsConf = os.path.join(streamTAlocalDir, 'inputs.conf')
    return os.path.exists(streamTAlocalDir) and os.path.exists(inputsConf)

#Returns true if Stream TA binaries are present else false
def isStreamTABinaryAvailable():
    logger.info("Splunk App for Stream Dependency Manager: isStreamTABinaryAvailable..")
    import platform
    OS_LINUX_32   = 'linux_x86'
    OS_LINUX_64   = 'linux_x86_64'
    OS_WINDOWS_64 = 'windows_x86_64'
    OS_MACOS_64   = 'darwin_x86_64'

    def get_os_arch():
        if platform.system() == 'Linux':
            if platform.architecture()[0] == '64bit':
                return OS_LINUX_64
            else:
                return OS_LINUX_32
        elif platform.system() == 'Windows':
            return OS_WINDOWS_64
        else:
            return OS_MACOS_64

    def get_stream_ta_binary():
        arch = get_os_arch()
        executable = 'streamfwd.exe' if arch == OS_WINDOWS_64 else 'streamfwd'
        return os.path.join(os.environ['SPLUNK_HOME'], 'etc', 'apps', 'Splunk_TA_stream', arch, 'bin', executable)

    if os.path.exists(get_stream_ta_binary()):
        return True
    return False


@entryExitDecorator
def main():
    reload = False
    sessionToken = sys.stdin.readlines()[0].strip()
    if isStreamTABinaryAvailable():
        if isStreamTAConfigured():
            logger.info("Splunk App for Stream Dependency Manager: Stream TA is already configured")
        else:
            configureStreamTA(sessionToken)
        reload = disablePCAPUpload(sessionToken)
    else:
        logger.info("Splunk App for Stream Dependency Manager: Disabling PCAP Upload modinput since Stream TA binaries are not available...")
        reload = disablePCAPUpload(sessionToken)
    if reload:
        reloadStreamApp(sessionToken)
    
if __name__ == '__main__':
    main()


