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
        initialize: function() {
          // example fields
          
          // "aggType": "key", 
          // "desc": "Server IP Address", 
          // "enabled": true, 
          // "name": "dest_ip", 
          // "term": "flow.s-ip"
        }
    });
});