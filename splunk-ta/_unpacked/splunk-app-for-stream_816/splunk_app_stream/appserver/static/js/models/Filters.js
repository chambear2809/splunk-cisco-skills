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

            //model consists of a collection of Comparisons
            //and an additional 'matchAllComparisons' field
            //==============================================
            
            // comparisons: 
            // ---Collection of Comparisons
            // [
            // "matchAllValues": true, 
            // "term": "dns.reply-code", 
            // "type": "regex", 
            // "value": "^(?!NoError).\\S"
            // ]
            // "matchAllComparisons": false
            // 
            
        },
        validate: function(attrs, options) {
            // ???
        }
    });
});
