define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "swc-stream/index",
    "contrib/text!app-js/templates/ForwarderManagement/InstallStreamForwardersTemplate.html",
    "app-js/models/HttpEventCollector",
    "app-js/models/CloudInstanceFlag"
], function(
    $,
    _,
    Backbone,
    index,
    InstallStreamForwardersTemplate,
    HttpEventCollector,
    CloudInstanceFlag
    ) {
    
    const SharedModels = index.SharedModels;
    return Backbone.View.extend({

        className: 'modal',

        initialize: function (options) {

            this.options        = _.extend({}, this.options, options);
            this.app            = this.options.app;
            this.template       = _.template($(InstallStreamForwardersTemplate).html());
            this.hec            = new HttpEventCollector();
            this.hecFetched     = $.Deferred();
            this.streamfwdAuth  = this.options.streamfwdAuth;
                                
            this.cloudInstanceInfo = new CloudInstanceFlag();
            this.cloudInfoFetched  = $.Deferred();

            var self = this;

            this.hec.fetch({
                success: function (hec) {
                    self.hecFetched.resolve(hec);
                },
                error: function(e) {
                    self.hecFetched.resolve(undefined);
                }
            });
            
            this.cloudInstanceInfo.fetch({
                 success: function(info){
                    self.cloudInfoFetched.resolve(info)
                 },
                 error: function(e) {
                    self.cloudInfoFetched.resolve(undefined);
                 }
                 });
        },

        events: {
            'click .redetect' : 'redetectTokenConfig'
        },

        redetectTokenConfig: function () {

            var self = this;

            $('#hec-token-configuration-blocks .inner-block').hide();
            $('#hec-token-loading').show();

            this.hec.fetch({
                success: function (hec) {
                    self._processTokenConfig(hec);
                },
                error: function (e) {
                    self._processTokenConfig();
                }
            });
        },

        _processTokenConfig: function (hec) {

            var self = this;

            if (hec) {
                var streamfwdtoken = _.findWhere(hec.get('tokens'), {name: 'http://streamfwd'});
                var instanceType = SharedModels.get('serverInfo').entry.content.get('instance_type');
                $('#hec-token-loading').hide();

                if (streamfwdtoken === undefined) {
                    $('#hec-token-undefined').show();
                } else if (hec.get('disabled')) {
                    if(instanceType && (instanceType == "cloud")) {
                        if(streamfwdtoken.disabled) {
                            $('#hec-token-disabled').show();
                        } else {
                            $('#hec-global-cloud-disabled').show();
                        }
                    } else {
                        $('#hec-global-disabled').show();
                    }
                } else if (streamfwdtoken.disabled) {
                    $('#hec-token-disabled').show();
                } else {
                    $('#hec-token-enabled').show();
                }

                if(streamfwdtoken && !self._checkValidHostname(streamfwdtoken.host)) {
                    $('#host-error-message').show();
                }

                $('#hec-token-debugging').show();
            } else {
                console.log("error fetching http event collector info");
                $('#hec-token-loading').hide();
                $('#hec-config-command').hide();
                $('#hec-unsupported').show();
                $('#hec-token-debugging .external').hide();
                $('#hec-token-debugging').show();
            }
        },

        _checkValidHostname: function (hostname) {
            return !!hostname.match(/^(([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])\.)*([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9\-]*[A-Za-z0-9])$/);
        },

        show: function () {

            var self = this;

            $.when(this.hecFetched.promise(), this.cloudInfoFetched.promise()).done(function(hec, cloudInstanceInfo) {

                var shcRoles = ['shc_captain', 'shc_deployer', 'shc_member'];
                var serverRoles = SharedModels.get('serverInfo').entry.content.get('server_roles');
                var instanceType = SharedModels.get('serverInfo').entry.content.get('instance_type');
                // STREAM-3545 Change HEC help link for SHC setups
                var isShcSetup = _.intersection(shcRoles, serverRoles).length > 0;

                var hostname = SharedModels.get('serverInfo').entry.content.get('host_fqdn');
                var port = window.location.port;
                if (instanceType && (instanceType == "cloud")) {
                    var gotCloudInfo = !!cloudInstanceInfo;
                    if (gotCloudInfo) {
                        var serverFQDN = cloudInstanceInfo.get('serverFQDN')
                        if (serverFQDN && (serverFQDN.length > 0)) {
                            hostname = serverFQDN;
                        }
                    }
                }

                var curlUrl = window.location.protocol + '//' + hostname;
                if (port.length > 0) curlUrl += ':' + port;
                curlUrl += '/en-us/custom/splunk_app_stream/install_streamfwd';

                var authEnabled = !!self.streamfwdAuth.get('enabled');
                var authToken   = self.streamfwdAuth.get('authKey');

                var hecSupported = !!hec;
                var hecHostname  = '';

                if (hecSupported) {
                    var streamfwdToken = _.findWhere(hec.get('tokens'), {name: 'http://streamfwd'});
                    if (streamfwdToken) {
                        hecHostname = streamfwdToken.host;
                    }
                }

                self.$el.html(self.template({
                    hecSupported : hecSupported,
                    hecHostname  : hecHostname,
                    curlUrl      : curlUrl,
                    authEnabled  : authEnabled,
                    authToken    : authToken,
                    isShcSetup   : isShcSetup
                }));

                self.$el.on('hide', function() {
                    self.remove();
                });

                self.$el.modal('show');

                self._processTokenConfig(hec);
            });

            return this;
        }

    });
});
