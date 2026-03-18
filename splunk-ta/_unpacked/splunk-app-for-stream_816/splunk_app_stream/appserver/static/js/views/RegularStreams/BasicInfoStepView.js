define([
    "app-js/contrib/underscore",
    "app-js/contrib/jquery",
    "app-js/contrib/backbone",
    "app-components/stepwizard/BaseStepView",
    "app-js/views/RegularStreams/BasicInfoControlsView",
    "app-js/collections/Streams",
    "app-js/collections/ReferenceStreams",
    "swc-stream/index",
    "@splunk/ui-utils/i18n",
    "contrib/text!app-js/templates/RegularStreams/BasicInfoStepTemplate.html",
    "css!app-js/templates/RegularStreams/BasicInfoStepTemplate.css"
],
    function(
        _,
        $,
        Backbone,
        BaseStepView,
        ControlsView,
        Streams,
        ReferenceStreams,
        index,
        Inter,
        template
    ) {
        /**
         * Basic Info Step View
         *
         * Renders the controls and inputs for populating fields of a new Stream.
         */
        const utils = index.utils;
        const sharedmodels = index.sharedmodels;
        const route = index.route;
        const FlashMessagesCollection = index.FlashMessagesCollection;
        const FlashMessagesLegacyView = index.FlashMessagesLegacyView;

        var BasicInfoStepView = BaseStepView.extend({
            tagName: 'div',
            events: {
            },
            /**
             * Backbone initializer
             * @param {Object} options
             *        - {Object} wizardData: object containing data to be passed between steps of the wizard
             *        - {Object} streams: Collection of type Streams
             */
            initialize: function(options) {
                BaseStepView.prototype.initialize.apply(this, arguments);

                this.text = Inter.gettext('Basic Info');
                this.label = this.text;
                this.nextLabel = "Next";
                this.showPreviousButton = false;

                this._validateArguments(options);
                this.wizardData = options.wizardData;
                this.streams = options.streams;
                this.referenceStreams = options.referenceStreams;
                this.flashMessages = new FlashMessagesCollection();
                this._initSubviews();
            },
            /**
             * Ensure stream is passed as an argument and that it's of correct type
             * @private
             */
            _validateArguments: function(options) {
                if (! options.wizardData instanceof Object) {
                    throw new Error("Must provide 'wizardData' object");
                }
                if (options && options.streams) {
                    if (!(options.streams instanceof Streams)) {
                        throw new Error("streams must be a valid Streams instance");
                    }
                } else {
                    throw new Error("Streams collection must be provided");
                }
                if (options && options.referenceStreams) {
                    if (!(options.referenceStreams instanceof ReferenceStreams)) {
                        throw new Error("referenceStreams must be a valid ReferenceStreams instance");
                    }
                } else {
                    throw new Error("ReferenceStreams collection must be provided");
                }
            },
            /**
             * Save routine
             * @returns {jqXHR} result of calling stream.save()
             */
            save: function() {
                var referenceStream = this.referenceStreams.get(this.basicInfoModel.get('referenceStreamId'));
                var selectedProtocol = referenceStream.get('protocolName');

                this.wizardData.referenceStream = referenceStream.clone();

                if (! this.wizardData.newStream || this.wizardData.newStream.get('protocolName') != selectedProtocol) {
                    // newStream has not yet been created, or it has, but with a different reference
                    // stream, so (re)create it.  In the latter case, changes may have been made on other wizard pages
                    // and these will be lost, but we need to start over because those changes may be incompatible
                    // with the new protocol.
                    this.wizardData.newStream = referenceStream.clone();
                    this.wizardData.newStream.set('enabled', false);
                    this.wizardData.newStream.set('isReferenceStream', false);
                    this.wizardData.newStream.set('index', null);
                }

                this.wizardData.newStream.set('id', this.basicInfoModel.get('id'));
                this.wizardData.newStream.set('name', this.basicInfoModel.get('description'));

                // Don't save yet...
                return $.Deferred().resolve();
            },
            /**
             * Initialize child views
             * @private
             */
            _initSubviews: function() {
                this._flashMessagesLegacy = new FlashMessagesLegacyView({
                    collection: this.flashMessages
                });

                this.basicInfoModel = new Backbone.Model();
                this.controlsView = new ControlsView({
                    model: this.basicInfoModel,
                    referenceStreams: this.referenceStreams,
                    usedStreamIds: _.pluck(this.streams.models, 'id').map(function(s) { return s.toLowerCase(); })
                });
            },

            _showError: function(text) {
                this.flashMessages.reset([{
// FIXME!
// See https://confluence.splunk.com/display/PROD/Backbone+Validation
// See search_mrsparkle\exposed\js\models\shared\FlashMessage.js
// I don't know if this should be "basicinfoerror", "validationError", or whether it has any effect at all.
                    ///key: "basicinfoerror",
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
            /**
             * Backbone render method
             */
            render: function() {
                this.$el.html(_.template(template, {
                    stepTitle: this.label
                }));
                this.$el.prepend(this._flashMessagesLegacy.render().$el);
                this.controlsView.setElement(this.$(".basicinfo-basic-controls")).render();
                return this;
            }
        });
        return BasicInfoStepView;
    }
);
