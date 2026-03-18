define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "app-js/models/IpAddressList",
    "swc-stream/index"
], function(
    $,
    _,
    Backbone,
    IpAddressList,
    index
    ) {
    const SplunkUtils = index.SplunkUtils;
    return Backbone.Collection.extend({
        model: IpAddressList,
        url: SplunkUtils.make_url([
            "custom",
            "splunk_app_stream",
            "captureipaddresses"
        ].join('/'))
    });
});
