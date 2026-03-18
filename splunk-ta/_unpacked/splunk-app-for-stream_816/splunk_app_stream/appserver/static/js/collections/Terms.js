define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "app-js/models/Term",
    "swc-stream/index"
], function(
    $,
    _,
    Backbone,
    Term,
    index
    ) {
    const SplunkUtils = index.SplunkUtils;

    return Backbone.Collection.extend({

        model: Term,

        url: SplunkUtils.make_url([
            "custom",
            "splunk_app_stream",
            "vocabularies"
        ].join('/')),

        //this URL returns XML instead of JSON
        fetch: function (options) {
            options = options || {};
            options.dataType = "xml";
            return Backbone.Collection.prototype.fetch.call(this, options);
        },

        parse: function (xml) {

            var termTypeInfo = this.constructor.termTypeInfo;
            var results = [];

            $.each($(xml).find("Term"), function(i, item) {

                var termId  = $(item).attr("id");
                var vocabId = termId.substring(0, termId.indexOf("."));
                var type    = $(item).find("Type").first().text();
                var comment = $(item).find("Comment").first().text();

                results.push({
                    id       : termId,
                    name     : termId.replace(vocabId + '.', ''),
                    type     : type,
                    category : termTypeInfo[type].category,
                    comment  : comment
                })
            });

            return results;
        }

    },{
        // From termTypes.json in Stream UI.
        // ^ no idea what this means.
        termTypeInfo: {
            'null'        : {description: 'undefined type', category: 'generic'},
            'object'      : {description: 'event type', category: 'generic'},
            'int8'        : {description: 'signed int (8-bit)', category: 'numeric'},
            'uint8'       : {description: 'positive int (8-bit)', category: 'numeric'},
            'int16'       : {description: 'signed int (16-bit)', category: 'numeric'},
            'uint16'      : {description: 'unsigned int (16-bit)', category: 'numeric'},
            'int32'       : {description: 'signed int (32-bit)', category: 'numeric'},
            'uint32'      : {description: 'unsigned int (32-bit)', category: 'numeric'},
            'int64'       : {description: 'signed int (64-bit)', category: 'numeric'},
            'uint64'      : {description: 'unsigned int (64-bit)', category: 'numeric'},
            'float'       : {description: 'small real number', category: 'numeric'},
            'double'      : {description: 'medium real number', category: 'numeric'},
            'longdouble'  : {description: 'large real number', category: 'numeric'},
            'shortstring' : {description: 'small string', category: 'string'},
            'string'      : {description: 'medium string', category: 'string'},
            'longstring'  : {description: 'large string', category: 'string'},
            'char'        : {description: 'fixed-length string', category: 'string'},
            'blob'        : {description: 'binary large object', category: 'string'},
            'zblob'       : {description: 'blob (stored compressed)', category: 'string'},
            'date'        : {description: 'specific date', category: 'date'},
            'time'        : {description: 'specific time', category: 'time'},
            'datetime'    : {description: 'specific time & date', category: 'date_time'}
        }
    });
});