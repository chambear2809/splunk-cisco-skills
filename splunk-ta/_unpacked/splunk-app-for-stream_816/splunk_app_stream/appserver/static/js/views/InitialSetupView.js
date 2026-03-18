define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "swc-stream/index",
    "contrib/text!app-js/templates/InitialSetupTemplate.html",
    "app-js/models/HttpEventCollector",
    "app-js/models/LocalStreamFwdProxy",
    "app-js/views/ProductTourView"
], function(
    $,
    _,
    Backbone,
    index,
    InitialSetupTemplate,
    HttpEventCollector,
    LocalStreamFwdProxy,
    ProductTourView
    ) {
    
    const SearchManager = index.SearchManager;
    const SharedModels = index.SharedModels;

    return Backbone.View.extend({

        initialize: function(options){

            this.options = _.extend({}, this.options, options);
            this.initialSetupTemplate = _.template($(InitialSetupTemplate).html());
            this.easySetupFlag = this.options.easySetupFlag;
            this.tourFlag = this.options.tourFlag;
            this.tourSupported = this.options.tourSupported;
            this.streamfwdConfig = this.options.streamfwdConfig;
            this.streamfwdStats = null;
            this.searchRetryCount = 0;
            this.hec = new HttpEventCollector();
            this.hecFetched = $.Deferred();

            var that = this;

            this.hec.fetch({
                success: function (hec) {
                    that.hecFetched.resolve(hec);
                },
                error: function(e) {
                    that.hecFetched.resolve(undefined);
                }
            });

            this.streamfwdStatsSearch = new SearchManager({
                id             : "streamfwdStatsSearch",
                earliest_time  : "-5m",
                latest_time    : "now",
                max_time       : 4,
                auto_cancel    : 8,
                autostart      : false,
                search         : 'index=_internal sourcetype="stream:stats" host=' + this.streamfwdConfig.host +
                                 '| fields "sniffer.lastErrorCode", "senders{}.lastErrorCode", "senders{}.lastErrorMsg", "sniffer.running", "senders{}.running", _time' +
                                 '| head 1 | table _time, "sniffer.lastErrorCode", "senders{}.lastErrorCode", "sniffer.running", "senders{}.lastErrorMsg", "senders{}.running"'
            });

            this.streamfwdStatsSearch.on("search:done", function(state, job) {
                if ($('#permissions-checkbox').is(':checked')) {
                    $('#permissions-loading').hide();
                    /*==========  If data is found  ==========*/
                    if (state.content.resultCount > 0){
                        job.results({count:0}, function(error, data){

                            var streamfwd_stats = {};
                            var results = {
                                fields : data.fields,
                                rows   : data.rows
                            }

                            if (results.rows.length > 0) {
                                var r = results.rows[0];
                                streamfwd_stats.timestamp = r[0];

                                if (that.streamfwdStats != null && that.streamfwdStats.timestamp == streamfwd_stats.timestamp) {
                                    // this is the same stats event as before, re-run the search
                                    if (that.searchRetryCount < 10) {
                                        $('#permissions-loading').show();
                                        that.searchRetryCount ++;
                                        setTimeout(function() {that.streamfwdStatsSearch.startSearch();}, 3000*that.searchRetryCount);
                                    } else {
                                        console.log("streamfwd stats event search retry limit reached");
                                        $('#permissions-error').show();
                                        that.searchRetryCount = 0;
                                    }
                                } else {
                                    that.searchRetryCount = 0;

                                    // a new stats event obtained, analyze
                                    streamfwd_stats.lastSnifferError = parseInt(r[1] || "0");
                                    streamfwd_stats.lastSenderError = parseInt(r[2] || "0");
                                    streamfwd_stats.snifferRunning = r[3] == "true";
                                    streamfwd_stats.lastSenderErrorMsg = r[4];
                                    streamfwd_stats.senderRunning = r[5] == "true";

                                    that.updateStats(streamfwd_stats);
                                }
                            } else {
                                $('#permissions-error').show();
                            }
                        });
                    }
                    /*==========  If no data is found  ==========*/
                    else{
                        $('#permissions-error').show();
                    }
                }
            });

        },

        events: {
            'click #permissions-checkbox'               : 'togglePermissionsBlock',
            'click #collection-checkbox'                : 'toggleCollectionBlock',
            'click #permissions-inner-blocks .redetect' : 'recheckPermissions',
            'click #hec-token-debugging .redetect'      : 'redetectTokenConfig',
            'click #start'                              : 'start'
        },

        updateStats: function (streamfwd_stats) {
            this.streamfwdStats = streamfwd_stats;

            if (streamfwd_stats.lastSenderError === 0 && streamfwd_stats.lastSnifferError === 0) {
                $('#permissions-success').show();
            } else {
                if (streamfwd_stats.lastSnifferError !== 0) {
                    $('#permissions-capture-error').show();
                } else if (streamfwd_stats.lastSenderError !== 0) {
                    $('#permissions-sender-error').show();
                    if (streamfwd_stats.lastSenderErrorMsg && streamfwd_stats.lastSenderErrorMsg.length) {
                        $('#sender-error-message').text(streamfwd_stats.lastSenderErrorMsg);
                    } else {
                        $('#sender-error-message').text("");
                    }
                }
            }
        },

        togglePermissionsBlock: function () {
            var checked = $('#permissions-checkbox').is(':checked');
            var streamFwdStatus = new LocalStreamFwdProxy();
            var that = this;

            $('#permissions-checkbox').prop('disabled', true);
            $('#permissions-inner-blocks .inner-block').hide();
            $('#permissions-loading').show();

            // save the model with the "disabled" attribute specified to
            // trigger the config change
            streamFwdStatus.save("disabled", checked ? "0" : "1", {
                success: function (model, response, options) {
                    $('#permissions-checkbox').prop('disabled', false);

                    if (checked) {
                        that._checkPermissions();
                    } else {
                        $('#permissions-loading').hide();
                    }
                },
                error: function (model, response, options) {
                    console.log("failed to disable/enable local streamfwd TA ")
                    $('#permissions-checkbox').prop('disabled', false);
                    $('#permissions-loading').hide();
                    $('#permissions-error').show();
                }
            });

        },

        recheckPermissions: function () {
            $('#permissions-inner-blocks .inner-block').hide();
            $('#permissions-loading').show();
            var streamFwdStatus = new LocalStreamFwdProxy();
            var that = this;
            // save the new model to reload the TA
             streamFwdStatus.save({
                success: function (model, response, options) {
                        that._checkPermissions();
                },
                error: function (model, response, options) {
                    console.log("failed to reload local streamfwd TA ")
                    $('#permissions-checkbox').prop('disabled', false);
                    $('#permissions-loading').hide();
                    $('#permissions-error').show();
                }
            });

            this._checkPermissions();
        },

        toggleCollectionBlock: function () {
            $('#collection-inner-block').toggle();
            if ($('#collection-checkbox').is(':checked')) {
                this.redetectTokenConfig();
            }
        },

        redetectTokenConfig: function () {

            var that = this;

            $('.configuration-block').hide();
            $('#hec-token-debugging').hide();
            $('#hec-token-loading').show();

            this.hec.fetch({
                success: function (hec) {

                    var streamfwdtoken = _.findWhere(hec.get('tokens'), {name: 'http://streamfwd'});
                    $('#hec-token-loading').hide();

                    if (streamfwdtoken === undefined) {
                        $('#hec-token-undefined').show();
                    } else if (hec.get('disabled')) {
                        $('#hec-global-disabled').show();
                    } else if (streamfwdtoken.disabled) {
                        $('#hec-token-disabled').show();
                    } else {
                        $('#hec-token-enabled').show();
                    }

                    if(streamfwdtoken && !that._checkValidHostname(streamfwdtoken.host)) {
                        $('#hec-host-error-message').show();
                    }

                    $('#hec-token-debugging').show();
                    $('#hec-config-command').show();
                },
                error: function (e) {
                    console.log("error fetching http event collector info");
                    $('#hec-token-loading').hide();
                    $('#hec-config-command').hide();
                    $('#hec-unsupported').show();
                    $('#hec-token-debugging .external').hide();
                    $('#hec-token-debugging').show();
                }
            });
        },

        _checkPermissions: function () {
            // wait for streamfwd to send a new stats event and re-run the search
            var that = this;
            this.searchRetryCount = 0; // reset the retry count
            setTimeout(function () {
                that.streamfwdStatsSearch.startSearch();
            }, 1000);
        },

        _checkValidHostname: function (hostname) {
            return !!hostname.match(/^(([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])\.)*([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9\-]*[A-Za-z0-9])$/);
        },

        start: function () {

            this.easySetupFlag.set('visited', true);
            this.easySetupFlag.save();

            $('.app-bar').show();
            $('.footer').show();
            $('#overview-dashboard').show();
            $('#setup').hide();

            //for testing purposes
            //resets both flags to false when easysetup is completed
            //this.easySetupFlag.set('visited', false);
            //this.easySetupFlag.save();
            //this.tourFlag.set('visited', false);
            //this.tourFlag.save();
        },

        render: function() {

            var that = this;

            var shcRoles = ['shc_captain', 'shc_deployer', 'shc_member'];
            var serverRoles = SharedModels.get('serverInfo').entry.content.get('server_roles');

            // STREAM-3545 Change HEC help link for SHC setups
            var isShcSetup = _.intersection(shcRoles, serverRoles).length > 0;

            var hostname = SharedModels.get('serverInfo').entry.content.get('host_fqdn');
            var port = window.location.port;

            var curlUrl = window.location.protocol + '//' + hostname;
            if (port.length > 0) curlUrl += ':' + port;
            curlUrl += '/en-us/custom/splunk_app_stream/install_streamfwd';

            $.when(this.hecFetched.promise()).done(function(hec) {
                var hecHostname  = '';

                if (hec) {
                    var streamfwdToken = _.findWhere(hec.get('tokens'), {name: 'http://streamfwd'});
                    if (streamfwdToken) {
                        hecHostname = streamfwdToken.host;
                    }
                }

                that.$el.html(that.initialSetupTemplate({
                    streamfwd_disabled : that.streamfwdConfig.disabled,
                    hecHostname        : hecHostname,
                    curlUrl            : curlUrl,
                    isShcSetup         : isShcSetup
                }));

                if (that.streamfwdConfig.disabled === false) {
                    that.streamfwdStatsSearch.startSearch();
                }
            });

            return this;
        }

    });
});
