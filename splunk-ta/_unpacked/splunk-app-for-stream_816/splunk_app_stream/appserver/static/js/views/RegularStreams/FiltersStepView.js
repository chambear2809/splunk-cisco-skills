define([
    "app-js/contrib/underscore",
    "app-js/contrib/jquery",
    "app-js/contrib/backbone",
    "app-components/stepwizard/BaseStepView",
    "swc-stream/index",
    "@splunk/ui-utils/i18n",
    "app-js/views/RegularStreams/SingleFilterEditorView",
    "contrib/text!app-js/templates/RegularStreams/FiltersStepTemplate.html",
    "contrib/text!app-js/templates/RegularStreams/FiltersStepTableTemplate.html",
    "css!app-js/templates/RegularStreams/FiltersStepTemplate.css"
],
    function(
        _,
        $,
        Backbone,
        BaseStepView,
        index,
        Inter,
        SingleFilterEditorView,
        FiltersStepTemplate,
        FiltersStepTableTemplate
        ) {
        /**
         * Filters Step View
         */

        const FlashMessagesCollection = index.FlashMessagesCollection;
        const FlashMessagesLegacyView = index.FlashMessagesLegacyView;
        const Popdown = index.Popdown;

        var FiltersStepView = BaseStepView.extend({
            tagName: 'div',
            events: {
                'keyup .filter-search-control'      : function(e) {this.renderTable()},
                'click a.clear'                     : 'clearSearchString',
                'click button.create-filter'        : 'createFilter',
                'click .match-all-comparisons-group': 'toggleMatchAll',
                'click .dropdown-menu .edit'        : 'editFilter',
                'click .dropdown-menu .delete'      : 'deleteFilter'
            },

            clearSearchString: function(e) {
                e.preventDefault();
                $(this.el).find('.filter-search-control input').val('');
                this.renderTable();
            },

            createFilter: function(e) {
                var createFilterView = new SingleFilterEditorView({
                    fields  : this.wizardData.newStream.get('fields'),
                    filters : this.wizardData.newStream.get('filters'),
                    app     : this.app
                }).show();

                $(e.target).blur();
                e.preventDefault();
            },

            toggleMatchAll: function(e) {
                this.wizardData.newStream.get('filters').matchAllComparisons = $(e.target).hasClass('match-all-enabled');
                if (! $(e.target).hasClass('active'))
                    $(e.target.parentElement).find('.btn').toggleClass('active');
            },

            editFilter: function(e) {
                var index = $(e.target).closest('tr').data('index');
                var filter = this.wizardData.newStream.get('filters').comparisons[index];

                var editFilterView = new SingleFilterEditorView({
                    fields  : this.wizardData.newStream.get('fields'),
                    filters : this.wizardData.newStream.get('filters'),
                    filter  : filter,
                    app     : this.app
                }).show();

                e.preventDefault();
            },

            deleteFilter: function(e) {
                var index = $(e.target).closest('tr').data('index');
                var comparisons = this.wizardData.newStream.get('filters').comparisons;

                // TODO: Add confirmation modal for deletion of filter
                comparisons.splice(index, 1);
                this.app.mediator.publish("event:filter-count-changed", comparisons.length);
                this.renderTable();
                e.preventDefault();
            },

            /**
             * Backbone initializer
             * @param {Object} options
             *        - {Object} wizardData: object containing data to be passed between steps of the wizard
             */
            initialize: function(options) {
                var self = this;

                BaseStepView.prototype.initialize.apply(this, arguments);

                this.text = Inter.gettext('Filters');
                this.label = this.text;
                this.nextLabel = "Next";
                this._validateArguments(options);
                this.wizardData = options.wizardData;
                this.app = options.app;
                this.filtersTableTemplate = _.template($(FiltersStepTableTemplate).html());
                this.flashMessages = new FlashMessagesCollection();
                this._flashMessagesLegacy = new FlashMessagesLegacyView({
                    collection: this.flashMessages
                });

                this.app.mediator.subscribe("event:filter-count-changed", function(numFilters) {
                    var status = numFilters == 1? '1 filter created' : numFilters + ' filters created';

                    $(self.el).find('.filter-count').text(status);
                    self.renderTable();
                });
            },

            /**
             * Ensure stream is passed as an argument and that it's of correct type
             * @private
             */
            _validateArguments: function(options) {
                if (! options.wizardData instanceof Object) {
                    throw new Error("Must provide 'wizardData' object");
                }
                // Can't check options.wizardData.newStream here since it doesn't exist when _validateArguments() is called.
                // See activate() below.
            },

            /**
             * Overrides BaseStepView.activate()
             */
            activate: function() {
                var self = this;

                // Throwing Errors here because these are programming errors, not user input errors.
                if (this.wizardData && this.wizardData.newStream) {
                    if (!(this.wizardData.newStream instanceof Backbone.Model)) {
                        throw new Error("Stream must be a valid model instance");
                    }
                } else {
                    throw new Error("Stream model must be provided");
                }

                self.fieldNamesByTerm = {};
                _.each(this.wizardData.newStream.get('fields'),
                       function(field) { self.fieldNamesByTerm[field.term] = field.name });

                this.render();
                return this;
            },

            /**
             * Save routine
             * @returns {jqXHR} result of calling stream.save()
             */
            save: function() {
                // Don't save yet...
                return $.Deferred().resolve();
            },

            _showError: function(text) {
                this.flashMessages.reset([{
                    key: "validationError", // What is this for?  See BasicInfoStepView._showError()
                    type: "error",
                    html: text
                }]);
            },

            /**
             * Validation method
             * @returns {$.Deferred}
             */
            validate: function() {
                var dfd = $.Deferred();

                dfd.resolve();
                return dfd;
            },

            /**
             * Backbone render method
             */
            render: function() {
                if (! this.wizardData.newStream)
                    return this;

                // Will only have a value if we've been to this page before.
                // TODO: Do we actually want to preserve the search after paging away?
                var searchString = $('.filter-search-control input').val();

                this.$el.html(_.template(FiltersStepTemplate, {
                    filters: this.wizardData.newStream.get('filters'),
                    stepTitle: this.label,
                    searchString: searchString
                }));

                this.renderTable();
                this.$el.prepend(this._flashMessagesLegacy.render().$el);
                return this;
            },

            renderTable: function() {
                var self = this;
                var searchString = $(this.el).find('.filter-search-control input').val();
                var output;

                output = self.filtersTableTemplate({
                    fieldNamesByTerm: this.fieldNamesByTerm,
                    comparisonTypes: this.app.comparisonTypes,
                    filters: this.wizardData.newStream.get('filters'),
                    stream: this.wizardData.newStream.toJSON(),
                    searchString: searchString
                });
                $(this.el).find('table.filter-list').replaceWith(output);

                $(".filter-edit").each(function(index, item) {
                    new Popdown({ el: $(item) });
                });

                // Disable sorting of Action column.
                var headers = { 4: { sorter: false } };

                // Initial sort happens in the call to sort() above.
                $('table.filter-list').tablesorter({
                    headers: headers,
                    textExtraction: function(node) { return node.innerHTML; }
                });
            }
        });
        return FiltersStepView;
    }
);
