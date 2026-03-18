define(
    [
        "app-js/models/SplunkIndex",
        "swc-stream/index",
        "app-js/contrib/underscore",
    ],
    function(IndexModel, index,_) {
        const SplunkDsBaseCollection = index.SplunkDsBaseCollection;
        return SplunkDsBaseCollection.extend({

            url: "data/indexes",
            model: IndexModel,
            initialize: function() {
                SplunkDsBaseCollection.prototype.initialize.apply(this, arguments);
            },

            //filters raw data and transform it into format usable by front-end components.
            //e.g.[{label: 'abc', value; 'abc'}]
            //pertinent part of input format is array of objects like: {
            //  entry{
            //      0: {
            //          //last piece is the index.
            //          id: "https://localhost:8000/servicesNS/nobody/system/data/indexes/_introspection"
            //      }
            //      ...
            //  }
            //  ...
            //}
            filterParseMap: function (array) {

                var results = [];

                var results = _.chain(array)
                             .map(function (each) {
                                 var delimitedString = each.entry[0].id.split("/");
                                 var indexName = delimitedString[delimitedString.length - 1];
                                 return {
                                    label: indexName,
                                    value: indexName
                                 }
                             })
                             .filter(function (each) {
                                 //private indexes start with '_', ignore
                                 return each.value[0] !== "_";
                             })
                             .value();

                //add a default value.
                results.unshift({label: 'default', value: null});

                return results;

            }
        });
    }
);