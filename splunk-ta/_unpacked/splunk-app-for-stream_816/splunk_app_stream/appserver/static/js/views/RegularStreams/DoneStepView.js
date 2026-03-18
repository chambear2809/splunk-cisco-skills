define([
    "app-js/contrib/underscore",
    "app-js/contrib/jquery",
    "app-js/contrib/backbone",
    "app-components/stepwizard/BaseStepView",
    "swc-stream/index"
],
    function(
        _,
        $,
        Backbone,
        BaseStepView,
        index
    ) {
        /**
         * Done Step View
         */
        const FlashMessagesCollection = index.FlashMessagesCollection;
        const FlashMessagesLegacyView = index.FlashMessagesLegacyView;

        var DoneStepView = BaseStepView.extend({
            initialize: function(options) {
                BaseStepView.prototype.initialize.apply(this, arguments);
                this.text = "Done";
                this.label = this.text;
                this.saveLabel = "Done";
                this.showPreviousButton = false;
                this.wizardData = options.wizardData;
                this.valid = false;
                this.flashMessages = new FlashMessagesCollection();
                this._flashMessagesLegacy = new FlashMessagesLegacyView({
                    collection: this.flashMessages
                });
            },
            activate: function() {
                var html =
                    '<div class="step-subheading">Done' +
                        '<div class="step-subsubheading"><span class="name">' + this.wizardData.newStream.escape('id') + ' </span> has been successfully created</div>' +
                    '</div>';

                this.$el.html(html);
                if (this.wizardData.failedGroupId) {
                    this.$el.prepend(this._flashMessagesLegacy.render().$el);
                    this._showError(
                        "Warning: Couldn't add stream " +
                        this.wizardData.newStream.escape('id') +
                        ' to forwarder group ' +
                        this.wizardData.failedGroupId +
                        '.');
                }

                return this;
            },
            render: function() {
                return this;
            },
            _showError: function(text) {
                this.flashMessages.reset([{
                    type: "warning",
                    html: text
                }]);
            },
            validate: function(step) {
                return $.Deferred().resolve();
            },
            save: function() {
                return $.Deferred().resolve();
            }
        });

        return DoneStepView;
    }
);
