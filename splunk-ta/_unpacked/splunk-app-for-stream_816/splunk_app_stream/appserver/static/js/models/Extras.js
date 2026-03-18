define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone"
], function(
    $,
    _,
    Backbone
    ) {
    return Backbone.Model.extend({
        defaults: {
            eventType: "http.event",
            interval: 60,
            topLimit: 100,
            topSortBy: "count"
        },

        validate: function(attrs, options) {

            var errors = [];

            if (!attrs.eventType){
                errors.push({name: 'eventType', message: 'eventType is required'});
            }

            if (attrs.interval && !isPositiveInteger(attrs.interval.toString())) {
                errors.push({name: 'interval', message: 'Aggregation interval must be a positive integer'});
            }

            if (attrs.topLimit && !isPositiveInteger(attrs.topLimit.toString())) {
                errors.push({name: 'topLimit', message: 'Top fields limit must be a positive integer'});
            }

            return errors.length > 0 ? errors : false;

            function isPositiveInteger(str) {
                return str.match(/^[1-9]\d*$/);
            }

        }

    });
});
