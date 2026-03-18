import glob
import os.path
import sys

import cherrypy
from cherrypy.lib.static import serve_file

import splunk.appserver.mrsparkle.controllers as controllers
import splunk.appserver.mrsparkle.lib.util as util
from splunk.appserver.mrsparkle.lib.decorators import expose_page
from splunk.appserver.mrsparkle.lib.decorators import set_cache_level
from splunk.appserver.mrsparkle.lib.routes import route


# STREAM-3375: if splunk_app_stream bin path is not present in the sys.path,
# then add it to sys.path to ensure python modules are loaded
bin_path = util.make_splunkhome_path(['etc', 'apps', 'splunk_app_stream', 'bin'])
if bin_path not in sys.path:
    sys.path.append(bin_path)

import splunk_app_stream.utils.stream_utils as stream_utils


logger = stream_utils.setup_logger('streamfwdinstall')

#download file directory
download_dir = os.path.join(util.get_apps_dir(), 'splunk_app_stream', 'install')

# absolute file path to linux 64 bit streamfwd tarball
streamfwd_package_linux64 = None

# Controller class to compile and serve a shell script that downloads and installs streamfwd binary
class InstallStreamfwd(controllers.BaseController):
    ''' InstallStreamfwd Controller '''

    def serve_install_script_file_linux64(self):
        """prepares and serves the install script file for 64 bit linux platform"""
        global streamfwd_package_linux64

        # resolve the package file name if necessary
        if streamfwd_package_linux64 is None:
            streamfwd_package_linux64 = self.resolve_package_file_linux64()
        # read the script template in memory
        with open(os.path.join(download_dir, 'install_streamfwd_linux64.tmpl'), 'r') as script_file:
            install_script_linux64=script_file.read().replace('[[APP_VERSION]]', stream_utils.getAppVersion()).replace('[[PACKAGE_FILE_NAME]]', os.path.basename(streamfwd_package_linux64))

        cherrypy.response.headers['Content-Type'] = "text/x-shellscript"
        cherrypy.response.headers['Content-Disposition']='attachment; filename="install_streamfwd.sh"'

        #STREAM-3156- cherrypy.request.base is not set to the correct protocol. Instead, check if ssl is enabled for splunk web
        configs = util.splunk_to_cherry_cfg('web','settings')
        isHTTPS = 0
        new_base = cherrypy.request.base
        try:
           isHTTPS = configs['enableSplunkWebSSL']
        except KeyError:
           pass
        if (isHTTPS and 'https' not in cherrypy.request.base):
           new_base = cherrypy.request.base.replace('http','https')
        return install_script_linux64.replace('[[URL_BASE]]', new_base)

    def resolve_package_file_linux64(self):
        """resolves streamfwd package file for 64 bit linux platform"""
        package_files = glob.glob(download_dir + os.sep + 'splunkstreamfwd-' 
            + stream_utils.getAppVersion() + '-*.linux64.tar.bz2')
        return package_files[0]

    def download_linux64(self):
        """serves streamfwd binary package for 64 bit linux platform"""
        global streamfwd_package_linux64
        if streamfwd_package_linux64 is None:
            streamfwd_package_linux64 = self.resolve_package_file_linux64()
            logger.debug("streamfwd_package_linux64=%s", streamfwd_package_linux64)

        return serve_file(streamfwd_package_linux64, "application/x-download", "attachment")

    @route('/:what', methods=['GET'])
    @expose_page(must_login=True, methods=['GET'])
    @set_cache_level('never')
    def download(self, what='', **params):
        """Serves either the install script file or platform-specific install package;"""
        """Current version only supports linux 64 bit platform"""
        try:
            if not what or what=='':
                return self.serve_install_script_file_linux64()
            elif what == 'linux64':
                return self.download_linux64()
            else:
                cherrypy.response.status = 400
                return ""
        except Exception:
            logger.exception("failed to download installation package")
            cherrypy.response.status = 500
            return ""

