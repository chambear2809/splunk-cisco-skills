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
            "fileservermountpoints"
        ].join('/')),

        idAttribute: '_key',

        validate: function(attrs, options) {
            // TODO: possbily some validation could be done, but it's not obvious what it should be.
        }
    });
});
