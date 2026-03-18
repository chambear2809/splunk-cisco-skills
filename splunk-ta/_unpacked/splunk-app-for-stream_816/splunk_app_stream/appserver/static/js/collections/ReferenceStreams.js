define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "app-js/models/Stream",
    "swc-stream/index"
], function(
    $,
    _,
    Backbone,
    Stream,
    index
    ) {
    const SplunkUtils = index.SplunkUtils;
    return Backbone.Collection.extend({
        model: Stream,
        url: SplunkUtils.make_url([
            "custom",
            "splunk_app_stream",
            "streams?type=reference_streams"
        ].join('/')),
        comparator: "id"
    });
});
