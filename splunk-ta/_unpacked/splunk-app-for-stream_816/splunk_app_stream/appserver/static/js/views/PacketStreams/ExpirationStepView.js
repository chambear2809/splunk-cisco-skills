define([
    "app-js/contrib/underscore",
    "app-js/contrib/jquery",
    "app-js/contrib/backbone",
    "app-components/stepwizard/BaseStepView",
    "app-js/views/PacketStreams/ExpirationControlsView",
    "swc-stream/index",
    "@splunk/ui-utils/i18n",
    "contrib/text!app-js/templates/PacketStreams/ExpirationStepTemplate.html",
    "css!app-js/templates/PacketStreams/ExpirationStepTemplate.css"
],
    function(
        _,
        $,
        Backbone,
        BaseStepView,
        ControlsView,
        index,
        Inter,
        template
    ) {
        const utils = index.utils;
        const sharedmodels = index.sharedmodels;
        const route = index.route;
        const FlashMessagesLegacyView = index.FlashMessagesLegacyView;
        const FlashMessagesCollection = index.FlashMessagesCollection;
        const Popdown = index.Popdown;

        var ExpirationStepView = BaseStepView.extend({
            tagName: 'div',
            events: {},

            initialize: function(options) {
                BaseStepView.prototype.initialize.apply(this, arguments);

                this.text = Inter.gettext('Expiration');
                this.label = this.text;
                this.nextLabel = "Next";

                this._validateArguments(options);
                this.wizardData = options.wizardData;
                this.app = options.app;
                this.flashMessages = new FlashMessagesCollection();
                this._initSubviews();
            },

            _validateArguments: function(options) {
                if (! options.wizardData instanceof Object) {
                    throw new Error("Must provide 'wizardData' object");
                }
            },

            save: function() {
                //Save Total Bytes Captured
                if (this.expirationModel.get("maxBytesCaptured")) {
                    this.wizardData.newStream.set('maxBytesCaptured', parseInt(this.expirationModel.get('maxBytesCaptured')));
                } else {
                    this.wizardData.newStream.unset('maxBytesCaptured');
                }

                //Save Total Packets Captured
                if (this.expirationModel.get("maxPacketsCaptured")) {
                    this.wizardData.newStream.set('maxPacketsCaptured', parseInt(this.expirationModel.get('maxPacketsCaptured')));
                } else {
                    this.wizardData.newStream.unset('maxPacketsCaptured');
                }

                //Save Total Flows Captured
                if (this.expirationModel.get("maxFlowsCaptured")) {
                    this.wizardData.newStream.set('maxFlowsCaptured', parseInt(this.expirationModel.get('maxFlowsCaptured')));
                } else {
                    this.wizardData.newStream.unset('maxFlowsCaptured');
                }

                //Save Elapsed Time
                if (this.expirationModel.get("maxElapsedTime") && this.expirationModel.get("maxElapsedTimeUnits")) {
                    var conversionToSeconds = { seconds: 1, minutes: 60, hours: 3600, days: 86400 };
                    var secondsMultiplier = conversionToSeconds[this.expirationModel.get("maxElapsedTimeUnits")];
                    this.wizardData.newStream.set('maxElapsedTime', parseInt(this.expirationModel.get('maxElapsedTime')) * secondsMultiplier);
                } else {
                    this.wizardData.newStream.unset('maxElapsedTime');
                }

                //Save Absolute Time
                if (this.expirationModel.get("absoluteDate") && this.expirationModel.get("absoluteTime")) {
                    var date = this.expirationModel.get("absoluteDate");
                    var time = this.expirationModel.get("absoluteTime").split(':');
                    var unixTime = new Date(date.get('year'), date.get('month'), date.get('day'), parseInt(time[0]), parseInt(time[1]), parseInt(time[2]));
                    unixTime = Math.floor(unixTime.getTime() / 1000);
                    this.wizardData.newStream.set('absoluteLatestTime', unixTime);
                } else {
                    this.wizardData.newStream.unset("absoluteLatestTime");
                }

                // Don't save yet...
                return $.Deferred().resolve();
            },

            _initSubviews: function() {
                this._flashMessagesLegacy = new FlashMessagesLegacyView({
                    collection: this.flashMessages
                });

                this.expirationModel = new Backbone.Model();
                this.controlsView = new ControlsView({
                    model: this.expirationModel,
                    app: this.app
                });
            },

            _showError: function(text) {
                this.flashMessages.reset([{
                    key: "validationError",
                    type: "error",
                    html: text
                }]);
            },

            validate: function() {
                var dfd = $.Deferred();
                var validationError = this.controlsView.validate();

                if (validationError) {
                    dfd.reject();
                    this._showError(validationError);
                } else {
                    dfd.resolve();
                    this.flashMessages.reset();
                }
                return dfd;
            },

            render: function() {
                var self = this;
                this.$el.html(_.template(template, {
                    stepTitle: "Expiration"
                }));
                this.$el.prepend(this._flashMessagesLegacy.render().$el);
                this.controlsView.setElement(this.$(".expiration-edit-controls")).render();
                return this;
            }
        });
        return ExpirationStepView;
    }
);
