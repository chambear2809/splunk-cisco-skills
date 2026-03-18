define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "app-js/models/Field"
], function(
    $,
    _,
    Backbone,
    Field
    ) {
    return Backbone.Collection.extend({
        model: Field,

        //show enabled fields first.
        comparator: function (x,y) {

            var x = x.toJSON();
            var y = y.toJSON();

            //Sort: enabled/disabled -> aggType -> name
            if (x.enabled && ! y.enabled) return -1;
            if (! x.enabled && y.enabled) return 1;

            if (x.aggType === 'key' && y.aggType !== 'key') return -1;
            if (x.aggType !== 'key' && y.aggType === 'key') return 1;

            if (x.name < y.name) return -1;
            if (x.name > y.name) return 1;

            return 0;
        },

        adjustTo: function (type) {

            var self = this;

            if (type === 'agg_defaults') {
                setAggregationDefaults();
            } 
            else if (type === 'non_agg') {
                setAsValue();
            }
            else{}
            
            return this;

            function setAggregationDefaults () {

                var sensibleKeys = ["src_ip", "dest_ip", "dest_port", "src_port"];
                var sensibleSums = ["time_taken", "bytes_in", "bytes_out"];

                self.each(function (field) {
                    if (_.contains(sensibleKeys, field.get('name'))){
                        field.set('enabled', true);
                        field.set('aggType', 'key');
                    } else if (_.contains(sensibleSums, field.get('name'))){
                        field.set('enabled', true);
                        field.set('aggType', ['sum']);
                    } else {
                        field.set('enabled', false);
                        field.set('aggType', 'key');
                    }
                })

            }

            function setAsValue(collection) {
                self.each(function (field) {
                    field.set('aggType', 'value');
                })
            }
        }

    });
});
