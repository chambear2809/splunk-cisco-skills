define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "swc-stream/index"
], function(
    $,
    _,
    Backbone,
    index
    ) {
    const SplunkUtils = index.SplunkUtils;
    return Backbone.Model.extend({

        urlRoot: SplunkUtils.make_url([
            "custom",
            "splunk_app_stream",
            "local_streamfwd_proxy"
        ].join('/')),

        initialize: function () {

        },

        defaults: {},

    });
});