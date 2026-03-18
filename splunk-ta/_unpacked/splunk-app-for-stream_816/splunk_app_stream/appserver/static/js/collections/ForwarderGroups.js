define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "app-js/models/ForwarderGroup",
    "swc-stream/index"
], function(
    $,
    _,
    Backbone,
    ForwarderGroup,
    index
    ) {
        const SplunkUtils = index.SplunkUtils;
    return Backbone.Collection.extend({
        model: ForwarderGroup,
        url: SplunkUtils.make_url([
            "custom",
            "splunk_app_stream",
            "streamforwardergroups"
        ].join('/')),
        comparator: "id"
    });
});