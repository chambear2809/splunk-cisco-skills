define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "swc-stream/index",
    "contrib/text!app-js/templates/AnalyticsOverviewTemplate.html",
    "app-js/views/InitialSetupView",
    "app-js/views/ProductTourView",
    "app-js/models/LocalStreamFwdProxy",
    ],
    function(
        $,
        _,
        Backbone,
        index,
        AnalyticsOverviewTemplate,
        InitialSetupView,
        ProductTourView,
        LocalStreamFwdProxy
        ) {

        const mvc = index.mvc;
        const utils = index.utils;
        const TokenUtils = index.TokenUtils;
        const DashboardController = index.DashboardController;
        const Dashboard = index.Dashboard;
        const ChartElement =index.ChartElement;
        const TableElement = index.TableElement;
        const SingleElement = index.SingleElement;
        const TimeRangeInput = index.TimeRangeInput;
        const FormUtils = index.FormUtils;
        const SearchManager = index.SearchManager;
        const PostProcessManager = index.PostProcessManager;
        const UrlTokenModel = index.UrlTokenModel;

        return Backbone.View.extend({

        initialize: function(options){
            this.options = _.extend({}, this.options, options);
            this.template = _.template($(AnalyticsOverviewTemplate).html());
            this.tourSupported = this.options.tourSupported;
            this.tourFlag = this.options.tourFlag;
            this.easySetupFlag = this.options.easySetupFlag;
            this.streamfwdConfig = this.options.streamfwdConfig;
            this.cloudInstanceFlag = this.options.cloudInstanceFlag;
        },

        render: function () {

            this.$el.html(this.template({}));

            var pageLoading = true;

            //
            // TOKENS
            //

            // Create token namespaces
            var urlTokenModel = new UrlTokenModel();
            mvc.Components.registerInstance('url', urlTokenModel);
            var defaultTokenModel = mvc.Components.getInstance('default', {create: true});
            var submittedTokenModel = mvc.Components.getInstance('submitted', {create: true});

            urlTokenModel.on('url:navigate', function() {
                defaultTokenModel.set(urlTokenModel.toJSON());
                if (!_.isEmpty(urlTokenModel.toJSON()) && !_.all(urlTokenModel.toJSON(), _.isUndefined)) {
                    submitTokens();
                } else {
                    submittedTokenModel.clear();
                }
            });

            // Initialize tokens
            defaultTokenModel.set(urlTokenModel.toJSON());

            function submitTokens() {
                // Copy the contents of the defaultTokenModel to the submittedTokenModel and urlTokenModel
                FormUtils.submitForm({ replaceState: pageLoading });
            }

            function setToken(name, value) {
                defaultTokenModel.set(name, value);
                submittedTokenModel.set(name, value);
            }

            function unsetToken(name) {
                defaultTokenModel.unset(name);
                submittedTokenModel.unset(name);
            }

            //
            // DASHBOARD EDITOR
            //

            new Dashboard({
                id: 'dashboard',
                el: this.$('.dashboard-body'),
                showTitle: false,
                editable: false
            }, {tokens: true}).render();

            /*=====================================
            =            App Analytics            =
            =====================================*/

            /**
            *
            * Top Applications by Volume (Bytes)
            *
            **/

            var topApps = new SearchManager({
                "id": "topApps",
                "earliest_time": "$earliest$",
                "status_buckets": 0,
                "search": "index=* source=\"stream:Splunk_Tcp\" OR source=\"stream:Splunk_Udp\" | stats sum(sum(bytes)) as Bytes by app | search Bytes > 0 | sort - Bytes | head 20 | rename app AS \"Application\" | table Application, Bytes",
                "sample_ratio": null,
                "latest_time": "$latest$",
                "cancelOnUnload": true,
                "app": utils.getCurrentApp(),
                "auto_cancel": 90,
                "preview": true,
                "runWhenTimeIsUndefined": false
            }, {tokens: true, tokenNamespace: "submitted"});

            var topAppsChart = new ChartElement({
                "id": "topAppsChart",
                "charting.chart": "pie",
                "resizable": true,
                "charting.chart.sliceCollapsingThreshold": "0",
                "managerid": "topApps",
                "el": this.$('#element1_1')
            }, {tokens: true, tokenNamespace: "submitted"}).render();

            /**
            *
            * Flow Visualization
            *
            **/

            var flowViz = new SearchManager({
                "id": "flowViz",
                "earliest_time": "$earliest$",
                "latest_time": "$latest$",
                "sample_ratio": null,
                "cancelOnUnload": true,
                "status_buckets": 0,
                "search": "index=* source=stream:Splunk_IP | rex field=src_ip \"(?<src1>.*)\\.(?<src2>.*)\\.(?<src3>.*)\\.(?<src4>.*)\" | where src1 NOT null | rex field=dest_ip \"(?<dest1>.*)\\.(?<dest2>.*)\\.(?<dest3>.*)\\.(?<dest4>.*)\" | where dest1 NOT null | eval source_ip=round(src1+exact(src2*.001), 3) | eval destination_ip=round(dest1+exact(dest2*.001), 3) | eventstats sum(sum(bytes)) as bytes by source_ip, destination_ip | stats latest(source_ip), latest(destination_ip), sum(count) by bytes | rename latest(source_ip) as \"Source IP\", latest(destination_ip) as \"Destination IP\", sum(count) as \"Flows\", bytes as \"Bytes\", sourcetype as \"Sourcetype\"",
                "app": utils.getCurrentApp(),
                "auto_cancel": 90,
                "preview": true,
                "runWhenTimeIsUndefined": false
            }, {tokens: true, tokenNamespace: "submitted"});


            var flowVizChart = new ChartElement({
                "id": "flowVizChart",
                "charting.gridLinesX.showMajorLines": "true",
                "charting.chart.showDataLabels": "none",
                "charting.axisLabelsX.majorLabelStyle.rotation": "-45",
                "charting.axisTitleY.text": "Destination IP",
                "charting.chart.bubbleSizeBy": "area",
                "charting.layout.splitSeries.allowIndependentYRanges": "0",
                "charting.axisX.maximumNumber": "255",
                "charting.axisY.maximumNumber": "255",
                "charting.chart.style": "shiny",
                "charting.chart": "bubble",
                "charting.axisTitleY2.visibility": "visible",
                "resizable": true,
                "charting.chart.stackMode": "default",
                "charting.axisY2.enabled": "0",
                "charting.chart.bubbleMaximumSize": "50",
                "charting.drilldown": "none",
                "charting.axisTitleX.text": "Source IP",
                "charting.axisTitleY.visibility": "visible",
                "charting.chart.nullValueMode": "gaps",
                "charting.data.count": "0",
                "charting.axisY2.scale": "inherit",
                "charting.foregroundColor": "white",
                "charting.chart.sliceCollapsingThreshold": "0.01",
                "charting.axisX.scale": "linear",
                "charting.axisY.scale": "linear",
                "charting.gridLinesY.showMajorLines": "true",
                "charting.layout.splitSeries": "0",
                "charting.axisX.minimumNumber": "0",
                "charting.legend.placement": "none",
                "charting.axisY.minimumNumber": "0",
                "charting.axisTitleX.visibility": "visible",
                "charting.axisLabelsX.majorLabelStyle.overflowMode": "ellipsisNone",
                "charting.legend.labelStyle.overflowMode": "ellipsisMiddle",
                "charting.chart.bubbleMinimumSize": "5",
                "managerid": "flowViz",
                "el": this.$('#element1_2')
            }, {tokens: true, tokenNamespace: "submitted"}).render();

            /*=====================================
            =            Web Analytics            =
            =====================================*/

            /**
            *
            * Domain Table
            *
            **/

            var domainTableSM = new SearchManager({
                "id": "domainTableSM",
                "status_buckets": 0,
                "earliest_time": "$earliest$",
                "latest_time": "$latest$",
                "search": 'index=* source="stream:Splunk_HTTPURI" site!=""' +
                          ' | rename sum(bytes_in) as bytes_in, sum(bytes_out) as bytes_out' +
                          ' | stats sum(count) as "Event Count" ' +
                          '   sum(bytes_in) as "Bytes In" ' +
                          '   sparkline(sum(bytes_in)) as "Bytes In Over Time" ' +
                          '   sum(bytes_out) as "Bytes Out" ' +
                          '   sparkline(sum(bytes_out)) as "Bytes Out Over Time"  by site ' +
                          ' | rename site as Domain' +
                          ' | sort by "Event Count" desc ' +
                          ' | head 28 ' +
                          ' | table Domain, "Bytes In Over Time", "Bytes Out Over Time", "Event Count"',
                "cancelOnUnload": true,
                "app": utils.getCurrentApp(),
                "auto_cancel": 90,
                "preview": true,
                "runWhenTimeIsUndefined": false
            }, {tokens: true, tokenNamespace: "submitted"});

            var domainTable = new TableElement({
                "id": "element2",
                "count": 7,
                "managerid": "domainTableSM",
                "showPager": true,
                "el": this.$('#element2_1')
            }, {tokens: true, tokenNamespace: "submitted"}).render();

            /**
            *
            * Client Errors
            *
            **/
            var httpErrors = new SearchManager({
                "id": "httpErrors",
                "status_buckets": 0,
                "earliest_time": "$earliest$",
                "latest_time": "$latest$",
                "search": 'index=* source="stream:Splunk_HTTPURI" (status = "4*" OR status = "5*") | fields status, count',
                "cancelOnUnload": true,
                "app": utils.getCurrentApp(),
                "auto_cancel": 90,
                "preview": true,
                "runWhenTimeIsUndefined": false
            }, {tokens: true, tokenNamespace: "submitted"});

            var clientErrors = new PostProcessManager({
               "id": "clientErrors",
               "managerid": "httpErrors",
               "status_buckets": 0,
               "earliest_time": "$earliest$",
               "latest_time": "$latest$",
               "search": '| search status = "4*" | stats sum(count) by status',
               "auto_cancel": 90,
               "preview": true,
               }, {tokens: true, tokenNamespace: "submitted"});


            var clientErrorsChart = new ChartElement({
                "id": "clientErrorsChart",
                "charting.chart": "pie",
                "charting.chart.sliceCollapsingThreshold": "0",
                "resizable": true,
                "managerid": "clientErrors",
                "el": this.$('#element2_2')
            }, {tokens: true, tokenNamespace: "submitted"}).render();

            /**
            *
            * Server Errors
            *
            **/

            var serverErrors = new PostProcessManager({
                "id": "serverErrors",
                "managerid": "httpErrors",
                "status_buckets": 0,
                "earliest_time": "$earliest$",
                "latest_time": "$latest$",
                "search": '| search status = "5*" | stats sum(count) by status',
                "auto_cancel": 90,
                "preview": true,
            }, {tokens: true, tokenNamespace: "submitted"});

            var serverErrorsChart = new ChartElement({
                "id": "serverErrorsChart",
                "charting.chart": "pie",
                "charting.chart.sliceCollapsingThreshold": "0",
                "resizable": true,
                "managerid": "serverErrors",
                "el": this.$('#element2_3')
            }, {tokens: true, tokenNamespace: "submitted"}).render();

            /*================================
            =            Database            =
            ================================*/

            /**
            *
            * Response Times
            *
            **/

            var responseTimesSM = new SearchManager({
                                "id": "responseTimesSM",
                                "status_buckets": 0,
                                "earliest_time": "$earliest$",
                                "latest_time": "$latest$",
                                "search": 'index=* eventtype=stream_agg_databases ' +
                                ' | rename sum(time_taken) as time_taken | stats sparkline(max(time_taken)) as "Response Time (μs)" by sourcetype',
                                "cancelOnUnload": true,
                                "app": utils.getCurrentApp(),
                                "auto_cancel": 90,
                                "preview": true,
                                "runWhenTimeIsUndefined": false
                                }, {tokens: true, tokenNamespace: "submitted"});


            var responseTimesTable = new TableElement({
                                    "id": "responseTimesTable",
                                    "count": 10,
                                    "managerid": "responseTimesSM",
                                    "el": this.$('#element3_1')
                                }, {tokens: true, tokenNamespace: "submitted"}).render();

            /**
            *
            * Avg Response Times
            *
            **/
            var responseTimesSM = new SearchManager({
                                    "id": "avgResponseTimesSM",
                                    "status_buckets": 0,
                                    "earliest_time": "$earliest$",
                                    "latest_time": "$latest$",
                                    "search": 'index=* eventtype=stream_agg_databases  ' +
                                    ' | rename sum(time_taken) as time_taken | stats sparkline(avg(time_taken)) as "Response Time (μs)" by sourcetype',
                                    "cancelOnUnload": true,
                                    "app": utils.getCurrentApp(),
                                    "auto_cancel": 90,
                                    "preview": true,
                                    "runWhenTimeIsUndefined": false
                                    }, {tokens: true, tokenNamespace: "submitted"});

            var avgResponseTimeTable = new TableElement({
                                        "id": "avgResponseTimeTable",
                                        "count": 10,
                                        "managerid": "avgResponseTimesSM",
                                        "el": this.$('#element3_2')
                                    }, {tokens: true, tokenNamespace: "submitted"}).render();

            /*===========================
            =            DNS            =
            ===========================*/

            /**
            *
            * DNS Activity
            *
            **/

            var dnsActivitySM = new SearchManager({
                                "id": "dnsActivitySM",
                                "status_buckets": 0,
                                "earliest_time": "$earliest$",
                                "latest_time": "$latest$",
                                "search": 'index=* source="stream:Splunk_DNSServerQuery" | timechart sum(count) as "DNS Queries"' ,
                                "cancelOnUnload": true,
                                "app": utils.getCurrentApp(),
                                "auto_cancel": 90,
                                "preview": true,
                                "runWhenTimeIsUndefined": false
                            }, {tokens: true, tokenNamespace: "submitted"});

            var dnsActivityChart = new ChartElement({
                "id": "dnsActivityChart",
                "charting.chart": "area",
                "resizable": true,
                "managerid": "dnsActivitySM",
                "el": this.$('#element4_1')
            }, {tokens: true, tokenNamespace: "submitted"}).render();

            /**
            *
            * DNS Error Count over Time
            *
            **/

            var dnsErrorCounts = new SearchManager({
               "id": "dnsErrors",
               "status_buckets": 0,
               "earliest_time": "$earliest$",
               "latest_time": "$latest$",
               "search": 'index=* source=stream:Splunk_DNSServerErrors | fields _time, count',
               "cancelOnUnload": true,
               "app": utils.getCurrentApp(),
               "auto_cancel": 90,
               "preview": true,
               "runWhenTimeIsUndefined": false
               }, {tokens: true, tokenNamespace: "submitted"});

            var dnsErrorChart = new PostProcessManager({
               "id": "dnsSumErrors",
               "managerid": "dnsErrors",
               "status_buckets": 0,
               "earliest_time": "$earliest$",
               "latest_time": "$latest$",
               "search": '| timechart sum(count) as "Error Counts" ',
               "auto_cancel": 90,
               "preview": true
               }, {tokens: true, tokenNamespace: "submitted"});

            var dnsErrorCountChart = new ChartElement({
              "id": "dnsErrorCountChart",
              "charting.chart": "area",
              "resizable": true,
              "managerid": "dnsSumErrors",
              "el": this.$('#element4_2')
              }, {tokens: true, tokenNamespace: "submitted"}).render();

            /**
             *
             * DNS Total Error Count
             *
             **/

            var dnsTotalErrorSM = new PostProcessManager({
                 "id": "dnsTotalErrorSM",
                 "managerid": "dnsErrors",
                 "status_buckets": 0,
                 "earliest_time": "$earliest$",
                 "latest_time": "$latest$",
                 "search": '| stats sum(count)',
                 "auto_cancel": 90,
                 "preview": true,
                 }, {tokens: true, tokenNamespace: "submitted"});

            var dnsTotalErrorChart = new SingleElement({
               "id": "dnsTotalErrorChart",
               "field": "count",
               "managerid": "dnsTotalErrorSM",
               "el": this.$('#element4_3')
               }, {tokens: true, tokenNamespace: "submitted"}).render();


            /*=====================================
            =             SSL Activity            =
            =====================================*/

            /**
            *
            * SSL Activity by Domain
            *
            **/

            var sslActivitySM = new SearchManager({
                "id": "sslActivitySM",
                "status_buckets": 0,
                "earliest_time": "$earliest$",
                "latest_time": "$latest$",
                "search": 'index=* source=stream:Splunk_SSLActivity ssl_subject_common_name!=NULL | stats sum(count) as Count by ssl_subject_common_name | search Count > 0 | head 999',
                "cancelOnUnload": true,
                "app": utils.getCurrentApp(),
                "auto_cancel": 90,
                "preview": true,
                "runWhenTimeIsUndefined": false
            }, {tokens: true, tokenNamespace: "submitted"});

            var sslActivityChart = new ChartElement({
                "id": "sslActivityChart",
                "charting.chart": "pie",
                "charting.chart.sliceCollapsingThreshold": "0",
                "resizable": true,
                "managerid": "sslActivitySM",
                "el": this.$('#element5_1')
            }, {tokens: true, tokenNamespace: "submitted"}).render();

            /**
            *
            * SSL Certificate Expiry
            *
            **/
             var certificateExpirySM = new SearchManager({
                "id": "certificateExpirySM",
                "status_buckets": 0,
                "earliest_time": "$earliest$",
                "latest_time": "$latest$",
                "search": 'index=* source=stream:Splunk_SSLActivity' +
                          ' | eval ssl_end_time=strptime(ssl_validity_end, "%b %d %H:%M:%S %Y")' +
                          ' | dedup ssl_subject_common_name, ssl_end_time' +
                          ' | sort 10 ssl_end_time' +
                          ' | convert ctime(ssl_end_time) as certificate_expiry_time' +
                          ' | table ssl_subject_common_name, certificate_expiry_time',
                "cancelOnUnload": true,
                "app": utils.getCurrentApp(),
                "auto_cancel": 90,
                "preview": true,
                "runWhenTimeIsUndefined": false
            }, {tokens: true, tokenNamespace: "submitted"});

            var certificateExpiryTable = new TableElement({
                "id": "certificateExpiryTable",
                "managerid": "certificateExpirySM",
                "showPager": false,
                "el": this.$('#element5_2')
            }, {tokens: true, tokenNamespace: "submitted"}).render();

           /*===================================
           =            Form Inputs            =
           ===================================*/

            var timepicker = new TimeRangeInput({
                "id": "timepicker",
                "searchWhenChanged": true,
                "default": {"latest_time": "now", "earliest_time": "-24h@h"},
                "earliest_time": "$earliest$",
                "latest_time": "$latest$",
                "el": this.$('#timepicker')
            }, {tokens: true}).render();

            timepicker.on("change", function(newValue) {
                FormUtils.handleValueChange(timepicker);
            });

            //on splunk 6.1 it renders as display:none for no #$!$& reason.
            //use parent b/c directly selecting .fieldset element reveals other things.
            this.$("#timepicker").parent().css('display', 'block');

            /*============================================
            =            Width Specifications            =
            ============================================*/

            //widths must be specified in JS as they are
            //overwritten to be equally spaced at render time.

            //App Analytics
            this.$("#panel1_1").css('width', '50%');
            this.$("#panel1_2").css('width', '50%');

            //Web Analytics
            this.$("#panel2_1").css('width', '50%');
            this.$("#panel2_2").css('width', '25%');
            this.$("#panel2_3").css('width', '25%');

            //Database
            this.$("#panel3_1").css('width', '50%');
            this.$("#panel3_2").css('width', '50%');

            //DNS
            this.$("#panel4_1").css('width', '50%');
            this.$("#panel4_2").css('width', '25%');
            this.$("#panel4_3").css('width', '25%');

            //SSL Analytics
            this.$("#panel5_1").css('width', '50%');
            this.$("#panel5_2").css('width', '50%');

            //===============================================================

            // Initialize time tokens to default
            if (!defaultTokenModel.has('earliest') && !defaultTokenModel.has('latest')) {
                defaultTokenModel.set({ earliest: '0', latest: '' });
            }

            submitTokens();

            //
            // DASHBOARD READY
            //

            DashboardController.ready();
            pageLoading = false;
            this.$(".dashboard-body").show();

            if (!this.tourFlag.get('visited')) {
                if (this.tourSupported) {

                    var productTour = new ProductTourView({
                        tourFlag          : this.tourFlag,
                        easySetupFlag     : this.easySetupFlag,
                        cloudInstanceFlag : this.cloudInstanceFlag
                    }).show();

                } else {
                    console.log("tour not supported.");
                }
            }

            var streamFwdStatus = new LocalStreamFwdProxy();
            var currentThis = this;
            
            streamFwdStatus.fetch({
                success: function () {
                    console.log("Stream TA found");
                    if (!currentThis.easySetupFlag.get('visited')) {
                        currentThis.$('#overview-dashboard').hide();
        
                        var setupView = new InitialSetupView({
                            easySetupFlag   : currentThis.easySetupFlag,
                            tourSupported   : currentThis.tourSupported,
                            tourFlag        : currentThis.tourFlag,
                            streamfwdConfig : currentThis.streamfwdConfig
                        });
        
                        setupView.render().$el.appendTo(currentThis.$('#setup'));
                    }
                },
                error: function () {
                    console.log("Stream TA not found");
                }
            });
            return this;
        }

    });
});
