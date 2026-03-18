define([
        "app-js/contrib/underscore",
        "app-js/contrib/jquery",
        "app-js/contrib/backbone",
        "swc-stream/index"
    ],
    function(
        _,
        $,
        Backbone,
        index
        ) {

        const ServerInfo = index.ServerInfo;

        /*================================================
        =            Conditional Product Tour            =
        ================================================*/

        var versionInfoPromise = new $.Deferred();
        var serverInfo = new ServerInfo();

        serverInfo.fetch({
            success: function (info) {
                versionInfoPromise.resolve(serverInfo.entry.content.get('version'));
            },
            error: function () {console.log("unable to get server info"); }
        })

        versionInfoPromise.done(function (version) {

            var versionNum = parseFloat(version.substr(0,3));
            //tour is supported on 6.3+
            var tourSupported = versionNum >= 6.3;

            var fullUrl = window.location.href;
            var urlParts = fullUrl.split("/");
            //pop the 'product_tour' part.
            urlParts.pop();
            var newUrl;

            if (tourSupported) {
                newUrl = urlParts.join("/") + "/streams?tour=stream-tour:enterprise";
                window.location.href = newUrl;
            } else {
                alert("Tour only supported on Splunk 6.3+");
                window.history.back();
            }

        });

        /*=====  End of Conditional Product Tour  ======*/

    });
