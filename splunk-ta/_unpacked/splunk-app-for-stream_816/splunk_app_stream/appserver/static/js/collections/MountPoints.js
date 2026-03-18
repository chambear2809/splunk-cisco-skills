define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "app-js/models/MountPoint",
    "swc-stream/index"
], function(
    $,
    _,
    Backbone,
    MountPoint,
    index
    ) {
    const SplunkUtils = index.SplunkUtils;
    return Backbone.Collection.extend({
        model: MountPoint,
        url: SplunkUtils.make_url([
            "custom",
            "splunk_app_stream",
            "fileservermountpoints"
        ].join('/')),
        comparator: "id"
    });
});
