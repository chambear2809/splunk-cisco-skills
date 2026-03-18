import os
import sys
import re

import cherrypy
import splunk.appserver.mrsparkle.controllers as controllers
from splunk.appserver.mrsparkle.lib.decorators import expose_page
from splunk.appserver.mrsparkle.lib.decorators import set_cache_level
from splunk.appserver.mrsparkle.lib.routes import route
from splunk.appserver.mrsparkle.lib.util import make_splunkhome_path

# STREAM-3375: if splunk_app_stream bin path is not present in the sys.path,
# then add it to sys.path to ensure python modules are loaded
bin_path = make_splunkhome_path(['etc', 'apps', 'splunk_app_stream', 'bin'])
if bin_path not in sys.path:
    sys.path.append(bin_path)

import splunk_app_stream.utils.stream_utils as stream_utils
import splunk_app_stream.models.file_server_mount_point

logger = stream_utils.setup_logger('pcaps')

year_regex = re.compile("^[1-9][0-9]{3}$")
month_regex = re.compile("(^[0][1-9]$)|(^[1][0-2]$)")
day_regex= re.compile("(^[0][1-9]$)|(^[1][0-9]$)|(^[2][0-9]$)|(^[3][0-1]$)")
flow_id_regex = re.compile("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
file_name_regex  = re.compile("^[0-9a-fA-F]{32}$")

# Controller class for retrieving pcap files

class Pcaps(controllers.BaseController):
    ''' Pcaps Controller '''
    # make sure the params are in expected format
    def valid_capture_bucket_date(self,capture_bucket_date):
        try:
            if not capture_bucket_date or len(capture_bucket_date) != 8:
                return False
            year=capture_bucket_date[0:4]
            month=capture_bucket_date[4:6]
            day=capture_bucket_date[6:8]
            return None != year_regex.match(year) and None != month_regex.match(month) and None != day_regex.match(day)
        except:
            return False
            
    def valid_flow_id(self,flow_id):
        try:
            if not flow_id or len(flow_id) != 36:
                return False
            return None != flow_id_regex.match(flow_id)
        except:
            return False
            
    
    def validate_arguments(self,capture_bucket_date,flow_id):
        return self.valid_capture_bucket_date(capture_bucket_date) and self.valid_flow_id(flow_id)

    def handle_error(self, capture_bucket_date, flow_id, orig_kwargs, err_text, overrides={}):
        '''Display error message when PCAP download fails'''

        logger.error("Pcaps.handle_error: capture_bucket_date = %s, flow_id = %s, kwargs = %s",
                     capture_bucket_date, flow_id, orig_kwargs)
        if 'log_msg' in overrides:
            logger.error("Pcaps.handle_error: %s", overrides['log_msg'])
        else:
            logger.error("Pcaps.handle_error: %s", err_text)

        page_args = {
            'namespace': 'search',
            'text': err_text,
            'banner_msg': '<p class="error">Unable to download PCAP file</p>'
        }
        page_args.update(overrides)

        return self.render_template('/splunk_app_stream:/templates/pcap_download_error.html', page_args)


    def handle_mount_point_not_configured(self, capture_bucket_date, flow_id, orig_kwargs, file_server_id):
        '''Display error message when PCAP download fails because mount point is not configured'''

        # Display a message for the user which includes a link to the mount point configuration page.
        err_text = "The PCAP file you requested from file server " + file_server_id \
        + " can't be downloaded because Splunk Stream doesn't know the mount point for that server. " \
        + "If you know it, " \
        + '<a href="/app/splunk_app_stream/mount_points?file_server=' + file_server_id + '">' \
        + "edit the corresponding entry in Splunk Stream's list of file server mount points</a> " \
        + "and then try downloading the file again."

        page_args = {
            'banner_msg': '<p class="error">Unable to download PCAP file: mount point not specified</p>',
            'log_msg': 'No mount point configured for file server %s' % file_server_id
        }

        return self.handle_error(capture_bucket_date, flow_id, orig_kwargs, err_text, page_args)


    @route('/:capture_bucket_date/:flow_id', methods=['GET'])
    @expose_page(must_login=True, methods=['GET'])
    @set_cache_level('never')
    def get_file(self, capture_bucket_date='', flow_id='', **kwargs):
        '''Return pcap file'''

        logger.debug("Pcaps.get_file: capture_bucket_date = %s, flow_id = %s, kwargs = %s",
                     capture_bucket_date, flow_id, kwargs)

        if not capture_bucket_date:
            return self.handle_error(capture_bucket_date, flow_id, kwargs, 'Error: missing capture_bucket_date')
        if not flow_id:
            return self.handle_error(capture_bucket_date, flow_id, kwargs, 'Error: missing flow_id')
        if 'file_server_id' in kwargs:
            file_server_id = kwargs['file_server_id']
        else:
            return self.handle_error(capture_bucket_date, flow_id, kwargs, 'Error: missing file_server_id')

        if not self.validate_arguments(capture_bucket_date,flow_id):
            return self.handle_error(capture_bucket_date, flow_id, kwargs, 'Error: Invalid arguments')

        session_key = cherrypy.session.get('sessionKey')
        result = splunk_app_stream.models.file_server_mount_point.FileServerMountPoint.list(session_key, file_server_id)
        logger.debug("Pcaps.get_file: result = %s", result)

        if 'mount_point' in result:
            mount_point = result['mount_point']
        else:
            # Create an entry for the file server without a mount point, for the convenience of the user.
            # (It's possible that such an entry already exists, in which case no harm is done.)
            splunk_app_stream.models.file_server_mount_point.FileServerMountPoint.create({'id': file_server_id}, session_key)

            return self.handle_mount_point_not_configured(capture_bucket_date, flow_id, kwargs, file_server_id)

        # folder hierarchy: for example flow_id e5af8646-9a4f-4f3f-9705-879f299a7d0e will create \e5\af\8646-9a4f-4f3f-9705-879f299a7d0e as folder hierarchy under capture bucket folder
        pcapFile = os.path.join(mount_point, capture_bucket_date, flow_id[:2], flow_id[2:4], flow_id[4:], 'capture.pcap')
        logger.info("Pcaps.get_file: pcapFile = %s", pcapFile)
        content_disp = 'inline; filename="capture_' + flow_id + '.pcap"'
        logger.debug("Pcaps.get_file: content_disp = %s", content_disp)

        try:
            f = open(pcapFile, 'rb')
            try:
                content = f.read()
            except Exception as e:
                err_text = 'Error reading %s.<br>Error from read(): %s' % (pcapFile, str(e))
                return self.handle_error(capture_bucket_date, flow_id, kwargs, err_text)
            finally:
                f.close()
        except Exception as e:
            # check to see if the mount point itself is accessible
            if not os.path.exists(mount_point):
                log_msg = 'The configured mount point (%s) for file server %s does not exist.' % (mount_point, file_server_id)
                page_args = {'log_msg': log_msg}
                err_text = log_msg + '<br>You can <a href="/app/splunk_app_stream/mount_points?file_server=' + file_server_id + '">' \
                + "edit the configured value</a> if it is incorrect."
                return self.handle_error(capture_bucket_date, flow_id, kwargs, err_text, page_args)

            err_text = 'Error opening %s.<br>Error from open(): %s' % (pcapFile, str(e))
            return self.handle_error(capture_bucket_date, flow_id, kwargs, err_text)

        cherrypy.response.headers['Content-Type'] = 'application/octet-stream'
        cherrypy.response.headers['Content-Disposition'] = content_disp
        return content
