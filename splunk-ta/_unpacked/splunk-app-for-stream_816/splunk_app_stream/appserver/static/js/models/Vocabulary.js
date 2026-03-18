define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "app-js/models/Term"
], function(
    $,
    _,
    Backbone,
    Term
    ) {
    return Backbone.Model.extend({
        defaults: {
            id: "",
            comment : "",
            name : '',
            terms : []
        }
    });
});
