define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "contrib/text!app-js/templates/StreamConfig/FieldsTableTemplate.html",
    "app-js/views/StreamConfig/FieldsTableRowView",
    "app-js/views/StreamConfig/ContentExtractionView",
    "app-js/contrib/jquery.tablesorter.min"
], function(
    $,
    _,
    Backbone,
    FieldsTableTemplate,
    FieldsTableRowView,
    ContentExtractionView,
    TableSorter
    ) {
    return Backbone.View.extend({

        initialize: function(options){

            this.options             = _.extend({}, this.options, options);
            this.app                 = this.options.app;
            this.fieldsTableTemplate = _.template($(FieldsTableTemplate).html());
            this.collection          = this.options.collection;
            this.idleCollection      = this.options.idleCollection;
            this.stringTerms         = this.options.stringTerms;
            this.streamModel         = this.options.streamModel;

            this.listenTo(this.collection, 'add change', _.debounce(function () {
                console.log('fields collection was modified, updating entire table');
                // TODO: solve the mystery of why collection.sort() here has no effect.
                this.render();
            }.bind(this),100));

        },

        events: {
            'keyup .search-control input' : 'filterTable',
            'click a.clear'               : 'resetSearch',
            'click #extract-new-field'    : 'extractNewField'
        },

        filterTable: function () {
            var searchString = this.$('.search-control input').val();
            this.app.mediator.publish("search-filtered", searchString);
        },

        resetSearch: function(e) {
            this.$('.search-control input').val('');
            this.app.mediator.publish("search-filtered", '');
        },

        extractNewField: function (e) {
            e.preventDefault();

            var contentExtractionView = new ContentExtractionView({
                app              : this.app,
                streamModel      : this.streamModel,
                stringTerms      : this.stringTerms,
                fieldsCollection : this.collection,
                idleCollection   : this.idleCollection
            }).show();
        },

        render: function() {

            var self = this;

            //keeps enabled fields at the top.
            this.collection.sort();

            this.$el.html(this.fieldsTableTemplate({
                stream: this.streamModel.toJSON()
            }));

            this.collection.each(function (fieldModel) {

                var fieldRow = new FieldsTableRowView({
                    model            : fieldModel,
                    app              : self.app,
                    stringTerms      : self.stringTerms,
                    streamModel      : self.streamModel,
                    fieldsCollection : self.collection,
                    idleCollection   : self.idleCollection
                })

                self.$('#field-rows').append(fieldRow.render().$el);

            })

             this.$("#fields").tablesorter({
                headers:{
                    5: { sorter:false }
                },
                textExtraction: function(node) {
                    if ($(node).hasClass('enabled')) {
                        // The exact strings don't matter, but the first should come lexicographically
                        // first, so that ascending order puts enabled fields first.
                        return $(node).find('.field-status').prop('checked') ? 'checked' : 'unchecked';
                    } else if ($(node).hasClass('agg-type')) {
                        //if field is disabled, send to bottom
                        if ($(node).find('.key').prop('disabled')) return '';
                        return $(node).find('.key').prop('checked') ? 'key' : 'value_agg';
                    } else {
                        return node.innerHTML;
                    }
                }
            });

            return this;

        }

    });
});
