define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "app-js/models/EventType"
], function(
    $,
    _,
    Backbone,
    EventType
    ) {
    return Backbone.Collection.extend({
        model: EventType
    });
});