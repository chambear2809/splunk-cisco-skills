define([
    
    "app-js/contrib/underscore",
    "app-js/contrib/jquery",
    "app-js/contrib/backbone",
    "app-components/stepwizard/BaseStepView",
    "swc-stream/index",
    "@splunk/ui-utils/i18n",
    "contrib/text!app-js/templates/RegularStreams/SettingsStepTemplate.html",
    "css!app-js/templates/RegularStreams/SettingsStepTemplate.css"
],
    function(
        _,
        $,
        Backbone,
        BaseStepView,
        index,
        Inter,
        template
    ) {
        /**
         * Settings Step View
         */
        const utils = index.utils;
        const sharedmodels = index.sharedmodels;
        const route = index.route;
        const FlashMessagesCollection = index.FlashMessagesCollection;
        const FlashMessagesLegacyView = index.FlashMessagesLegacyView;
        const SyntheticRadioControl = index.SyntheticRadioControl;
        const SyntheticSelectControl = index.SyntheticSelectControl;

        var SettingsStepView = BaseStepView.extend({
            tagName: 'div',
            events: {
            },
            /**
             * Backbone initializer
             * @param {Object} options
             *        - {Object} wizardData: object containing data to be passed between steps of the wizard
             */
            initialize: function(options) {
                BaseStepView.prototype.initialize.apply(this, arguments);

                this.text = Inter.gettext('Settings');
                this.label = this.text;
                this.nextLabel = "Next";

                this._validateArguments(options);
                this.wizardData = options.wizardData;
                this.streamType = options.streamType
                this.app = options.app;
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

                this.render();
                return this;
            },
            /**
             * Save routine
             * @returns {jqXHR} result of calling stream.save()
             */
            save: function(stepBack) {
                var selectedStatus = this.statusRadioControl.getValue();
                var selectedIndex = this.indexSelectControl.getValue();

                this.wizardData.newStream.set('enabled', selectedStatus == 'enabled' || selectedStatus == 'statsOnly');
                this.wizardData.newStream.set('statsOnly', selectedStatus == 'statsOnly');
                this.wizardData.newStream.set('index', selectedIndex);

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

                var isEnabled = this.wizardData.newStream.get('enabled');
                var isStatsOnly = this.wizardData.newStream.get('statsOnly');
                var selectedStatus = isEnabled? (isStatsOnly? 'statsOnly' : 'enabled') : 'disabled';
                var selectedIndex = this.wizardData.newStream.get('index');

                this.$el.html(_.template(template, {
                    stepTitle: this.label,
                    streamType: this.streamType
                }));

                this.indexSelectControl = new SyntheticSelectControl({
                    toggleClassName: 'btn',
                    menuWidth: 'narrow',
                    items: this.app.splunkIndexItems
                });
                this.indexSelectControl.setValue(selectedIndex);
                $(this.el).find('.index-select').append(this.indexSelectControl.render().el);

                if (this.streamType === 'metadata') {
                    this.statusRadioControl = new SyntheticRadioControl({
                        items: [
                            { label: 'Enabled', value: 'enabled' },
                            { label: 'Disabled', value: 'disabled' },
                            { label: 'Estimate', value: 'statsOnly' }
                        ]
                    });
                } else {
                    this.statusRadioControl = new SyntheticRadioControl({
                        items: [
                            { label: 'Enabled', value: 'enabled' },
                            { label: 'Disabled', value: 'disabled' }
                        ]
                    });
                }
                $(this.el).find('.status-control').append(this.statusRadioControl.render().el);
                this.statusRadioControl.setValue(selectedStatus);

                this.$el.prepend(this._flashMessagesLegacy.render().$el);
                return this;
            }
        });
        return SettingsStepView;
    }
);
