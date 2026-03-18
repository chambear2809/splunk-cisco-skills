define([
    "app-js/contrib/underscore",
    "app-js/contrib/jquery",
    "app-js/contrib/backbone",
    "app-components/stepwizard/BaseStepView",
    "swc-stream/index",
    "@splunk/ui-utils/i18n",
    "app-js/models/Extras",
    "app-js/views/StreamConfig/AggregationMethodsView",
    "contrib/text!app-js/templates/RegularStreams/FieldsStepTemplate.html",
    "contrib/text!app-js/templates/RegularStreams/FieldsStepTableTemplate.html",
    "css!app-js/templates/RegularStreams/FieldsStepTemplate.css"
],
    function(
        _,
        $,
        Backbone,
        BaseStepView,
        index,
        Inter,
        Extras,
        AggregationMethodsView,
        template,
        FieldsTableTemplate
        ) {
        /**
         * Fields Step View
         */
        const utils = index.utils;
        const sharedmodels = index.sharedmodels;
        const route = index.route;
        const ControlGroup = index.ControlGroup;
        const TextControl = index.TextControl;
        const Popdown = index.Popdown;
        const FlashMessagesCollection = index.FlashMessagesCollection;
        const FlashMessagesLegacyView = index.FlashMessagesLegacyView;
        
        var FieldsStepView = BaseStepView.extend({
            tagName: 'div',
            events: {
                'keyup .field-search-control'       : 'handleSearchStringChange',
                'click a.clear'                     : 'handleSearchStringClear',
                'click .field-status'               : 'handleEnabledStatusChange',
                'click .agg-type .btn-toggle input' : 'handleAggTypeChange',
                'click .agg-methods'                : 'handleAggregationSettings'
            },
            handleSearchStringChange: function(e) {
                e.preventDefault();
                this.renderTable();
            },
            handleSearchStringClear: function(e) {
                e.preventDefault();
                $(this.el).find('.field-search input').val('');
                this.renderTable();
            },
            handleEnabledStatusChange: function(e) {
                var fieldName = $(e.target).closest('tr').data('name');
                var field = _.find(this.wizardData.newStream.get('fields'),
                                    function(field) { return field.name == fieldName; });

                field.enabled = $(e.target).is(':checked');
                if (this.wizardData.newStream.get('aggregated') && !field.enabled) {
                    field.aggType = 'key';
                }
                this.renderTable();
            },
            handleAggTypeChange: function(e) {
                var fieldName = $(e.target).closest('tr').data('name');
                var field = _.find(this.wizardData.newStream.get('fields'),
                                   function(field) { return field.name == fieldName; });

                if ($(e.target).hasClass('agg')) {
                    var category = this.terms.get(field.term).get('category');
                    field.aggType = category === 'numeric' ? ['sum'] : ['mode'];
                } else {
                    field.aggType = 'key';
                }

                this.renderTable();
            },
            handleAggregationSettings: function(e) {
                e.preventDefault();

                var fieldName = $(e.target).closest('tr').data('name');
                var field = _.find(this.wizardData.newStream.get('fields'),
                                   function(field) { return field.name == fieldName; });

                var aggregationMethodsView = new AggregationMethodsView({
                    model  : undefined,
                    field  : field,
                    terms  : this.terms,
                    parent : this
                }).show();
            },
            /**
             * Backbone initializer
             * @param {Object} options
             *        - {Object} wizardData: object containing data to be passed between steps of the wizard
             */
            initialize: function(options) {
                BaseStepView.prototype.initialize.apply(this, arguments);

                this.text = Inter.gettext('Fields');
                this.label = this.text;
                this.nextLabel = "Next";

                this._validateArguments(options);
                this.wizardData = options.wizardData;
                this.terms = options.terms;
                this.fieldsTableTemplate = _.template($(FieldsTableTemplate).html());
                this.flashMessages = new FlashMessagesCollection();
                this._flashMessagesLegacy = new FlashMessagesLegacyView({
                    collection: this.flashMessages
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
                // Throwing Errors here because these are programming errors, not user input errors.
                if (this.wizardData && this.wizardData.newStream) {
                    if (!(this.wizardData.newStream instanceof Backbone.Model)) {
                        throw new Error("Stream must be a valid model instance");
                    }
                } else {
                    throw new Error("Stream model must be provided");
                }

                if (this.wizardData.newStream.get('aggregated')) {
                    if (this.prevActivationAggStatus == 'aggregated') {
                        // We've reached this wizard step before, and the last time we were here,
                        // we also had aggregation on, so don't update the fields.
                    } else {
                       this._generateDefaultAggFields(this.wizardData.newStream);
                    }
                    this.prevActivationAggStatus = 'aggregated';
                } else {
                    if (this.prevActivationAggStatus == 'aggregated') {
                        var originalFieldsCopy = $.extend(true, [], this.wizardData.referenceStream.get('fields'));
                        this.wizardData.newStream.set('fields', originalFieldsCopy);
                    } else {
                        // We've reached this wizard step before, and the last time we were here,
                        // we also had aggregation off, so don't update the fields.
                    }
                    this.prevActivationAggStatus = 'notAggregated';
                }

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

                // TODO: Should it be an error if nothing is enabled?  Probably not.
                dfd.resolve();

                return dfd;
            },

            //Takes a model and sets sensible defaults for aggregation.
            //Disable everthing else.
            _generateDefaultAggFields: function (model) {
                var sensibleKeys = ["src_ip", "dest_ip", "dest_port", "src_port"];
                var sensibleSums = ["time_taken", "bytes_in", "bytes_out"];

                _.each(model.get('fields'), function(field)  {
                    if (_.contains(sensibleKeys, field.name)){
                        field.enabled = true;
                        field.aggType = 'key';
                    } else if (_.contains(sensibleSums, field.name)){
                        field.enabled = true;
                        field.aggType = ['sum'];
                    } else {
                        field.enabled = false;
                        field.aggType = 'key';
                    }
                });
            },

            /**
             * Backbone render method
             */
            render: function() {
                if (! this.wizardData.newStream)
                    return this;

                // Will only have a value if we've been to this page before.
                // TODO: Do we actually want to preserve the search after paging away?
                var searchString = $('.field-search input').val();

                this.$el.html(_.template(template, {
                    stepTitle: this.label,
                    searchString: searchString
                }));

                this.renderTable();
                this.$el.prepend(this._flashMessagesLegacy.render().$el);
                return this;
            },

            renderTable: function() {
                var self = this;
                var isAggregated = this.wizardData.newStream.get('aggregated');
                var searchString = $(this.el).find('.field-search input').val();
                var output;

                this.wizardData.newStream.get('fields').sort(function(x, y) {
                    if (x.enabled && !y.enabled) return -1;
                    if (!x.enabled && y.enabled) return 1;

                    if (x.aggType === 'key' && y.aggType !== 'key') return -1;
                    if (x.aggType !== 'key' && y.aggType === 'key') return 1;

                    if (x.name < y.name) return -1;
                    if (x.name > y.name) return 1;
                    return 0;
                });

                var termsDict = {};
                //extract the terms as a map {term: category-type}
                // types: string, date_time, numeric, generic
                _.each(this.terms.models, function(each) {
                    termsDict[each.get('id')] = each.get('category');
                })
                _.each(termsDict, function(value, key) {
                    if (value !== "string")
                        delete termsDict[key];
                });

                output = self.fieldsTableTemplate({
                    stream: this.wizardData.newStream.toJSON(),
                    isAggregated: isAggregated,
                    terms: this.terms,
                    searchString: searchString,
                    stringTerms: termsDict
                });
                $(this.el).find('table.field-list').replaceWith(output);

                // Initial sort happens in the call to sort() above.
                $('table.field-list').tablesorter({
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
            }
        });
        return FieldsStepView;
    }
);
