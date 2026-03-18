define([
    "app-js/contrib/underscore",
    "app-js/contrib/jquery",
    "app-js/contrib/backbone",
    "app-js/collections/ForwarderGroups",
    "app-components/stepwizard/BaseStepView",
    "swc-stream/index",
    "contrib/text!app-js/templates/RegularStreams/GroupsStepTemplate.html",
    "css!app-js/templates/RegularStreams/GroupsStepTemplate.css"
],
    function(
        _,
        $,
        Backbone,
        ForwarderGroups,
        BaseStepView,
        index,
        template
    ) {
        const FlashMessagesCollection = index.FlashMessagesCollection;
        const FlashMessagesLegacyView = index.FlashMessagesLegacyView;

        var GroupsStepView = BaseStepView.extend({
            initialize: function(options) {
                BaseStepView.prototype.initialize.apply(this, arguments);
                this.text = "Groups";
                this.label = this.text;
                this.nextLabel = "Create Stream";
                this.wizardData = options.wizardData;
                this.onSave = options.onSave;
                this.valid = false;
                this.flashMessages = new FlashMessagesCollection();
                this._flashMessagesLegacy = new FlashMessagesLegacyView({
                    collection: this.flashMessages
                });
            },
            activate: function() {
                this.flashMessages.reset();
                return this;
            },
            render: function() {
                var self = this;
                var fwdGroupsFetched = $.Deferred();

                this.fwdGroups = new ForwarderGroups();
                this.fwdGroups.fetch({
                    success: function() {
                        fwdGroupsFetched.resolve();
                    },
                    error: function(e) {
                        console.log("error fetching fwd groups")
                    }
                });
                fwdGroupsFetched.done(function() {
                    // If this is the first time for this page for this stream, initialize selectedGroups.
                    if (! self.wizardData.selectedGroups)
                        self.wizardData.selectedGroups = [self.fwdGroups.get('defaultgroup')];

                    self.$el.html(_.template(template, {
                        stepTitle: self.label,
                        availableGroups: self.fwdGroups,
                        selectedGroupIds: _.pluck(self.wizardData.selectedGroups, 'id')
                    }));

                    self.$el.prepend(self._flashMessagesLegacy.render().$el);
                });

                return this;
            },
            _showError: function(text) {
                this.flashMessages.reset([{
                    key: "validationError", // What is this for?  See BasicInfoStepView._showError()
                    type: "error",
                    html: text
                }]);
            },
            validate: function(step) {
                return $.Deferred().resolve();
            },
            save: function(stepBack) {
                var fwdGroups = this.fwdGroups;

                this.wizardData.selectedGroups = $('.controls input:checked').map(function() { return fwdGroups.get($(this).data('id')); });

                return stepBack? $.Deferred().resolve() : this.onSave(this._showError.bind(this));
            }
        });

        return GroupsStepView;
    }
);
