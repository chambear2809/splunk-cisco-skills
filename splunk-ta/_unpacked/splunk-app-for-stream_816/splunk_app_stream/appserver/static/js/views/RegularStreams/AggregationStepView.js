define([
    "app-js/contrib/underscore",
    "app-js/contrib/jquery",
    "app-js/contrib/backbone",
    "app-components/stepwizard/BaseStepView",
    "swc-stream/index",
    "@splunk/ui-utils/i18n",
    "app-js/models/Extras",
    "contrib/text!app-js/templates/RegularStreams/AggregationStepTemplate.html",
    "css!app-js/templates/RegularStreams/AggregationStepTemplate.css"
],
    function(
        _,
        $,
        Backbone,
        BaseStepView,
        index,
        Inter,
        Extras,
        template
    ) {
        /**
         * Aggregation Step View
         */
        const TextControl = index.TextControl;
        const ControlGroup = index.ControlGroup;
        const utils = index.utils;
        const sharedmodels = index.sharedmodels;
        const route = index.route;
        const FlashMessagesLegacyView = index.FlashMessagesLegacyView;
        const FlashMessagesCollection = index.FlashMessagesCollection;
        var AggregationStepView = BaseStepView.extend({
            tagName: 'div',
            events: {
                'click .aggregation-off': function(e) {
                    this.wizardData.newStream.set('aggregated', false);
                    this.wizardData.newStream.set('streamType', 'event');
                    this.render();
                },
                'click .aggregation-on': function(e) {
                    this.wizardData.newStream.set('aggregated', true);
                    this.wizardData.newStream.set('streamType', 'agg_event');
                    this.render();
                },
                'change .time-interval': function(e) {
                    this.wizardData.newStream.get('extras')['interval'] = Number($('input.time-interval').val()) || "NaN";
                },
                'click .expansion-trigger': function(e) {
                    this.expanded = !this.expanded;
                    $(e.target).closest('.expandable').toggleClass('expanded');
                }
            },
            /**
             * Backbone initializer
             * @param {Object} options
             *        - {Object} wizardData: object containing data to be passed between steps of the wizard
             */
            initialize: function(options) {
                BaseStepView.prototype.initialize.apply(this, arguments);

                this.text = Inter.gettext('Aggregation');
                this.label = this.text;
                this.nextLabel = "Next";

                this._validateArguments(options);
                this.wizardData = options.wizardData;
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
                    if (!this.wizardData.newStream.get('extras')['interval']) {
                        if (this.wizardData.newStream.get('aggregated')) {
                            throw new Error("An aggregated Stream must have a time interval");
                        } else {
                            // Set the time interval to the default value, in case the user chooses aggregation.
                            var defaultExtras = new Extras();
                            this.wizardData.newStream.get('extras')['interval'] = defaultExtras.get('interval');
                        }
                    }
                } else {
                    throw new Error("Stream model must be provided");
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
                var extras = new Extras();
                //clear the defaults so they don't impact back-end validation.
                extras.clear();
                extras.set(this.wizardData.newStream.get('extras'));

                if (extras.isValid()) {
                    dfd.resolve();

                    //Resync stream model and extras model. (e.g. extras.unset above)
                    this.wizardData.newStream.set('extras', extras.attributes);

                    this.flashMessages.reset();
                    $('input.time-interval').closest('.control-group').removeClass('error');
                } else {
                    dfd.reject();
                    //there will only be 1 error.
                    this._showError(extras.validationError[0].message);
                    $('input.time-interval').closest('.control-group').addClass('error');
                }
                return dfd;
            },
            /**
             * Backbone render method
             */
            render: function() {
                var isAggregated = false;
                var timeInterval = '';

                if (this.wizardData.newStream) {
                    isAggregated = this.wizardData.newStream.get('aggregated');
                    timeInterval = isAggregated ? this.wizardData.newStream.get('extras').interval : '';
                }

                this.$el.html(_.template(template, {
                    stepTitle: this.label,
                    isAggregated: isAggregated,
                    timeInterval: timeInterval,
                    expanded: this.expanded
                }));

                this.$el.prepend(this._flashMessagesLegacy.render().$el);
                return this;
            }
        });
        return AggregationStepView;
    }
);
