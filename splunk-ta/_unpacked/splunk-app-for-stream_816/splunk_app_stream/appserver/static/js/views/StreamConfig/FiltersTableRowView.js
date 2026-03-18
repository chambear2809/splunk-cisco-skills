define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "contrib/text!app-js/templates/StreamConfig/FiltersTableRowTemplate.html",
    "app-js/views/ConfirmView",
    'app-js/views/RegularStreams/SingleFilterEditorView',
    "app-js/views/ConfirmView",
    'swc-stream/index'
], function(
    $,
    _,
    Backbone,
    FiltersTableRowTemplate,
    ConfirmView,
    SingleFilterEditorView,
    ConfirmView,
    index
    ) {

    const Popdown = index.Popdown;
    return Backbone.View.extend({

        tagName: 'tr',

        initialize: function(options){

            this.options                 = _.extend({}, this.options, options);
            this.app                     = this.options.app;
            this.filtersTableRowTemplate = _.template($(FiltersTableRowTemplate).html());
            this.model                   = this.options.model;
            this.filtersJSON             = this.options.filtersJSON;
            this.fields                  = this.options.fields;
            this.streamModel             = this.options.streamModel;

            //filter must be a reference to inside filters
            this.filter = _.findWhere(this.filtersJSON.comparisons, {
                //no unique ID to find by....
                matchAllValues : this.model.get('matchAllValues'),
                term           : this.model.get('term'),
                type           : this.model.get('type'),
                value          : this.model.get('value'),
            });

            //TODO: if term is not needed, backend should just store name instead of term.
            this.fieldName = _.findWhere(this.streamModel.get('fields'), {term : this.filter.term}).name;

            this.typeName = this.app.comparisonTypes.get(this.model.get('type')).get('description');

            this.app.mediator.subscribe("search-filtered", function (searchString) {
                this._showHideBasedOnRegex(searchString);
            }.bind(this));

        },

         _showHideBasedOnRegex: function (searchString) {

            var self = this;
            var regex = new RegExp(searchString, "i");

            // show if regex matches any of these strings.
            var matchCases = _.flatten([
                self.fieldName,
                self.typeName,
                self.model.get('value')
            ]);

            var regexMatches = _.some(_.map(matchCases, function (str) {
                return regex.test(str);
            }));

            if (regexMatches) {
                self.$el.show();
            } else {
                self.$el.hide();
            }

        },

        events: {
            'click .filter-edit .edit'   : 'editFilter',
            'click .filter-edit .delete' : 'deleteFilter'
        },

        editFilter: function () {
            var createFilterView = new SingleFilterEditorView({
                fields  : this.fields,
                filters : this.filtersJSON,
                filter  : this.filter,
                name    : this.streamModel.get('isPacketStream') ? 'Target' : 'Filter',
                app     : this.app
            }).show();
        },

        deleteFilter: function (e) {
            var self = this;
            e.preventDefault();

            var filterIndex = _.indexOf(this.filtersJSON.comparisons, this.filter);

            var confirmView = new ConfirmView({
                model: {text: this.fieldName + " " + this.typeName + " " + this.filter.value},
                action: "delete",
                command: function () {
                    self.filtersJSON.comparisons.splice(filterIndex, 1);
                    self.app.mediator.publish('event:filter-count-changed', self.filtersJSON.comparisons.length);
                }
            }).show();
        },

        render: function() {

            this.$el.html(this.filtersTableRowTemplate({
                comparisonName  : this.fieldName,
                comparison      : this.model.toJSON(),
                comparisonTypes : this.app.comparisonTypes
            }));

            new Popdown({ el: this.$('.filter-edit')});

            return this;
        }

    });
});
