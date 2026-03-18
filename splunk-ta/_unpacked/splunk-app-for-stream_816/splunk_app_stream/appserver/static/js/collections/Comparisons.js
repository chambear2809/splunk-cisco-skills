define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "app-js/models/Comparison"
], function(
    $,
    _,
    Backbone,
    Comparison
    ) {

    return Backbone.Collection.extend({
        model: Comparison,
    });
});