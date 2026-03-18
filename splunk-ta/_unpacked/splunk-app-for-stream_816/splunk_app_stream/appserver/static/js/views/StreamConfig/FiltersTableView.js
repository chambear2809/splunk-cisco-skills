define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "contrib/text!app-js/templates/StreamConfig/FiltersTableTemplate.html",
    "app-js/views/RegularStreams/SingleFilterEditorView",
    "app-js/views/StreamConfig/FiltersTableRowView",
    "app-js/collections/Comparisons",
    "app-js/contrib/jquery.tablesorter.min"
], function(
    $,
    _,
    Backbone,
    FiltersTableTemplate,
    SingleFilterEditorView,
    FiltersTableRowView,
    Comparisons,
    TableSorter
    ) {
    return Backbone.View.extend({

        initialize: function(options){

            this.options               = _.extend({}, this.options, options);
            this.app                   = this.options.app;
            this.filtersTableTemplate  = _.template($(FiltersTableTemplate).html());

            this.streamModel  = this.options.streamModel;
            this.filtersModel = this.options.filtersModel

            //return an array representation of fields since that is required by SingleFilterEditorView
            this.filtersJSON = {
                comparisons: this.filtersModel.get('comparisons').toJSON(),
                matchAllComparisons: this.filtersModel.get('matchAllComparisons')
            };

            this.app.mediator.subscribe("event:filter-count-changed", function(numFilters) {

                //sync comparisonsJSON which has been updated by SingleFilterEditorView
                //to the filters model, then re-render
                this.filtersModel.set('comparisons', new Comparisons(this.filtersJSON.comparisons));
                this.render();

            }.bind(this));

        },

        events: {
            'click #create-new-filter'                 : 'createNewFilter',
            'click #match-all-aggregation-btns button' : 'onMatchAllChange',
            'keyup .search-control input'              : 'filterTable',
            'click a.clear'                            : 'resetSearch'
        },

        onMatchAllChange: function (e) {
            var matchAll = $(e.currentTarget).attr("value") === "all";
            this.$('#match-all-aggregation-btns button').each(function () {
                $(this).removeClass('active');
            });
            $(e.currentTarget).addClass('active');
            this.filtersModel.set('matchAllComparisons',matchAll);
        },

        filterTable: function () {
            var searchString = this.$('.search-control input').val();
            this.app.mediator.publish("search-filtered", searchString);
        },

        resetSearch: function(e) {
            this.$('.search-control input').val('');
            this.app.mediator.publish("search-filtered", '');
        },

        createNewFilter: function () {
            var createFilterView = new SingleFilterEditorView({
                //for the dropdown to select from, pass in all non-extracted fields.
                fields: _.filter(this.streamModel.get('fields'),function (field) {
                    return !field.transformation;
                }),
                filters: this.filtersJSON,
                name: this.streamModel.get('isPacketStream') ? 'Target' : 'Filter',
                app: this.app
            }).show();
        },

        render: function() {

            var self = this;

            //Create the table template
            this.$el.html(this.filtersTableTemplate({
                stream : this.streamModel.toJSON(),
                name   : this.streamModel.get('isPacketStream') ? 'target' : 'filter'
            }));

            var nonExtractedFields = _.filter(self.streamModel.get('fields'),function (field) {
                                        return !field.transformation;
                                    });

            //bind and append the rows
            this.filtersModel.get('comparisons').each(function (comparison) {
                var tableRow = new FiltersTableRowView({
                    model       : comparison,
                    app         : self.app,
                    streamModel : self.streamModel,
                    fields      : nonExtractedFields,
                    //pass down so child views can adjust.
                    filtersJSON : self.filtersJSON
                }).render().$el.appendTo(self.$('#filter-rows'));
            })

            this.$("#filters").tablesorter({
                headers:{
                    4: { sorter:false }
                }
            });

            return this;

        }

    });
});
