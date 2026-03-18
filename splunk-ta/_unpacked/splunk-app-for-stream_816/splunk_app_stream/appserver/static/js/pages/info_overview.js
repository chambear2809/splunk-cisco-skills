define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "swc-stream/index",
    "app-js/models/TourFlag",
    "app-js/models/EasySetupFlag",
    "app-js/models/LocalStreamFwdProxy",
    "app-js/models/CloudInstanceFlag",
    "app-js/components/loadLayout",
    "app-js/views/AnalyticsOverviewView"
    ],
    function(
        $,
        _,
        index,
        TourFlag,
        EasySetupFlag,
        LocalStreamFwdProxy,
        CloudInstanceFlag,
        LoadLayout,
        AnalyticsOverviewView
        ) {

        /*=====================================
        =            Initial Setup            =
        ======================================*/
        const ServerInfo = index.ServerInfo;
        var versionInfoPromise = new $.Deferred();
        var tourFlagPromise = new $.Deferred();
        var easySetupPromise = new $.Deferred();
        var streamfwdConfigPromise = new $.Deferred();
        var cloudInstanceFlagPromise = new $.Deferred();
        

        var serverInfo = new ServerInfo();
        var tourFlag = new TourFlag();
        var easySetupFlag = new EasySetupFlag();
        var streamFwdStatus = new LocalStreamFwdProxy();
        var cloudInstanceFlag = new CloudInstanceFlag();

        serverInfo.fetch({
            success: function (info) {
                versionInfoPromise.resolve(serverInfo.entry.content.get('version'));
            },
            error: function () { console.log("unable to get server info"); }
        });

        tourFlag.fetch({
            success: function (flag) {
                //set 'false' to test tour when easysetup flag is true.
                //flag.set('visited', false);

                //go to the start function inside InitialSetupView.js
                //to test tour when easysetup flag is false.
                tourFlagPromise.resolve(flag);
            },
            error: function (err) { console.log("tour flag failed to fetch"); }
        });

        easySetupFlag.fetch({
            success: function (flag) {
                //set 'false' to test easysetup page.
                //flag.set('visited', false);
                easySetupPromise.resolve(flag);
            },
            error: function (err) { console.log("easy setup flag failed to fetch"); }
        });

        streamFwdStatus.fetch({
            success: function (results) {
                streamfwdConfigPromise.resolve({disabled: results.attributes['disabled'], host: results.attributes['host']});
            },
            error: function (err) {
                console.log("failed to fetch local streamfwd TA status");
                streamfwdConfigPromise.resolve({disabled:true, host:"",success:false});
            }
        });

        cloudInstanceFlag.fetch({
            success: function (flag) {
                //set 'true' to test cloud instance behavior
                //flag.set('is_cloud_instance', true)
                cloudInstanceFlagPromise.resolve(flag);
            },
            error: function (err) { console.log("cloud instance flag failed to fetch"); }
        });


         $.when(versionInfoPromise.promise(), tourFlagPromise.promise(), easySetupPromise.promise(), streamfwdConfigPromise.promise(), cloudInstanceFlagPromise.promise())
            .done(function(version, tourFlag, easySetupFlag, streamfwdConfig, cloudInstanceFlag) {

            var versionNum = parseFloat(version.substr(0,3));
            //tour is supported on 6.3+
            var tourSupported = versionNum >= 6.3;
            LoadLayout(function(layout) {
                var appContent = new AnalyticsOverviewView({
                    tourSupported     : tourSupported,
                    tourFlag          : tourFlag,
                    easySetupFlag     : easySetupFlag,
                    streamfwdConfig   : streamfwdConfig,
                    cloudInstanceFlag : cloudInstanceFlag
                });
                layout.create()
                    .getContainerElement()
                    .appendChild(appContent.render().el);
            });

        });
    }
);
