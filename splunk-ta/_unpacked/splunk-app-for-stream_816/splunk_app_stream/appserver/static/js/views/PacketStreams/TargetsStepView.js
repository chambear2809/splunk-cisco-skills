define([
    "app-js/contrib/underscore",
    "app-js/contrib/jquery",
    "app-js/contrib/backbone",
    "app-components/stepwizard/BaseStepView",
    "swc-stream/index",
    "@splunk/ui-utils/i18n",
    "app-js/views/PacketStreams/SingleTargetEditorView",
    "contrib/text!app-js/templates/PacketStreams/TargetsStepTemplate.html",
    "contrib/text!app-js/templates/PacketStreams/TargetsStepTableTemplate.html",
    "css!app-js/templates/PacketStreams/TargetsStepTemplate.css"
],
    function(
        _,
        $,
        Backbone,
        BaseStepView,
        index,
        Inter,
        SingleTargetEditorView,
        TargetsStepTemplate,
        TargetsStepTableTemplate
        ) {
        /**
         * Targets Step View
         */
        const utils = index.utils;
        const sharedmodels = index.sharedmodels;
        const route = index.route;
        const FlashMessagesCollection = index.FlashMessagesCollection;
        const FlashMessagesLegacyView = index.FlashMessagesLegacyView;
        const Popdown = index.Popdown;

        var TargetsStepView = BaseStepView.extend({
            tagName: 'div',
            events: {
                'keyup .target-search-control'      : function(e) {this.renderTable()},
                'click a.clear'                     : 'clearSearchString',
                'click button.create-target'        : 'createTarget',
                'click .match-all-comparisons-group': 'toggleMatchAll',
                'click .dropdown-menu .edit'        : 'editTarget',
                'click .dropdown-menu .delete'      : 'deleteTarget'
            },

            clearSearchString: function(e) {
                e.preventDefault();
                $(this.el).find('.target-search-control input').val('');
                this.renderTable();
            },

            createTarget: function(e) {
                var createTargetView = new SingleTargetEditorView({
                    fields  : this.wizardData.newStream.get('fields'),
                    targets : this.wizardData.newStream.get('filters'),
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

            editTarget: function(e) {
                var index = $(e.target).closest('tr').data('index');
                var target = this.wizardData.newStream.get('filters').comparisons[index];

                var editTargetView = new SingleTargetEditorView({
                    fields  : this.wizardData.newStream.get('fields'),
                    targets : this.wizardData.newStream.get('filters'),
                    target  : target,
                    app     : this.app
                }).show();

                e.preventDefault();
            },

            deleteTarget: function(e) {
                var index = $(e.target).closest('tr').data('index');
                var comparisons = this.wizardData.newStream.get('filters').comparisons;

                // TODO: Add confirmation modal for deletion of target
                comparisons.splice(index, 1);
                this.app.mediator.publish("event:target-count-changed", comparisons.length);
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

                this.text = Inter.gettext('Targets');
                this.label = this.text;
                this.nextLabel = "Next";
                this._validateArguments(options);
                this.wizardData = options.wizardData;
                this.app = options.app;
                this.curProtocol = undefined;
                this.targetsTableTemplate = _.template($(TargetsStepTableTemplate).html());
                this.flashMessages = new FlashMessagesCollection();
                this._flashMessagesLegacy = new FlashMessagesLegacyView({
                    collection: this.flashMessages
                });

                this.app.mediator.subscribe("event:target-count-changed", function(numTargets) {
                    var status = numTargets == 1? '1 target created' : numTargets + ' targets created';

                    $(self.el).find('.target-count').text(status);
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

                // Will reset targets back to defaults if user goes back one step and changes the stream's protocol
                // Default IPs are known reserved IP addresses specifically set aside for documentation and example purposes
                if (this.curProtocol !== this.wizardData.newStream.get('protocolName')) {
                    this.curProtocol = this.wizardData.newStream.get('protocolName');
                    var fields = this.wizardData.newStream.get('fields');
                    var filters = this.wizardData.newStream.get('filters');
                    filters.comparisons = [
                        {
                            "matchAllValues": false,
                            "term": _.findWhere(fields, {name: "src_ip"}).term,
                            "value": "192.0.2.0",
                            "type": "exact-match-primary"
                        },
                        {
                            "matchAllValues": false,
                            "term": _.findWhere(fields, {name: "dest_ip"}).term,
                            "value": "203.0.113.0",
                            "type": "exact-match-primary"
                        }
                    ];
                    this.wizardData.newStream.set('filters', filters);
                    this.app.mediator.publish("event:target-count-changed", this.wizardData.newStream.get('filters').comparisons.length);
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
                    key: "validationError",
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

                if (this.wizardData.newStream.get('filters').comparisons.length === 0) {
                    dfd.reject();
                    this._showError("Target criteria must be set for this packet stream");
                } else {
                    dfd.resolve();
                    this.flashMessages.reset();
                }
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
                var searchString = $('.target-search-control input').val();

                this.$el.html(_.template(TargetsStepTemplate, {
                    targets: this.wizardData.newStream.get('filters'),
                    stepTitle: "Targets",
                    searchString: searchString
                }));

                this.renderTable();
                this.$el.prepend(this._flashMessagesLegacy.render().$el);
                this.renderFlag = true;
                return this;
            },

            renderTable: function() {
                var self = this;
                var searchString = $(this.el).find('.target-search-control input').val();
                var output;

                output = self.targetsTableTemplate({
                    fieldNamesByTerm: this.fieldNamesByTerm,
                    comparisonTypes: this.app.comparisonTypes,
                    targets: this.wizardData.newStream.get('filters'),
                    stream: this.wizardData.newStream.toJSON(),
                    searchString: searchString
                });
                $(this.el).find('table.target-list').replaceWith(output);

                $(".target-edit").each(function(index, item) {
                    new Popdown({ el: $(item) });
                });

                // Disable sorting of Action column.
                var headers = { 4: { sorter: false } };

                // Initial sort happens in the call to sort() above.
                $('table.target-list').tablesorter({
                    headers: headers,
                    textExtraction: function(node) { return node.innerHTML; }
                });
            }
        });
        return TargetsStepView;
    }
);
