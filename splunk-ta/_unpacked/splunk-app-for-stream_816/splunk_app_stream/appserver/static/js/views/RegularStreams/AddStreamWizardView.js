define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "swc-stream/index",
    "app-js/models/Stream",
    "app-js/models/Extras",
    "app-components/stepwizard/BaseStepView",
    "app-components/stepwizard/StepWizardView",
    "app-js/views/RegularStreams/BasicInfoStepView",
    "app-js/views/RegularStreams/AggregationStepView",
    "app-js/views/RegularStreams/FieldsStepView",
    "app-js/views/RegularStreams/FiltersStepView",
    "app-js/views/RegularStreams/SettingsStepView",
    "app-js/views/RegularStreams/GroupsStepView",
    "app-js/views/RegularStreams/DoneStepView",
    "app-js/views/PacketStreams/TargetsStepView",
    "app-js/views/PacketStreams/ExpirationStepView",
    "contrib/text!app-js/templates/RegularStreams/AddStreamWizardTemplate.html"
], function(
    $,
    _,
    Backbone,
    index,
    Stream,
    Extras,
    BaseStepView,
    StepWizardView,
    BasicInfoStepView,
    AggregationStepView,
    FieldsStepView,
    FiltersStepView,
    SettingsStepView,
    GroupsStepView,
    DoneStepView,
    TargetsStepView,
    ExpirationStepView,
    AddStreamWizardTemplate
    ) {
    const SplunkUtils = index.SplunkUtils;
    return Backbone.View.extend({

        initialize: function(options) {
            this.options = _.extend({}, this.options, options);
            this.command = this.options.command;
            this.streamType = this.options.streamType;
            this.template = _.template($(AddStreamWizardTemplate).html());
            this.app = this.options.app;
            this.callingView = this.options.callingView;

            this.app.pageIsDirty = true;
            this.app.exitMessage = "Are you sure you want to exit the wizard?";
        },

        show: function(){
            var self = this;

            this.$el.empty();
            this.$el.append(this.template());

            this.wizardData = {};
            var basicInfoStepView   = new BasicInfoStepView({ wizardData: this.wizardData, streams: this.app.streams,
                                                              referenceStreams: this.app.referenceStreams }).render();
            var fieldsStepView      = new FieldsStepView({ wizardData: this.wizardData, terms: this.app.terms }).render();
            var settingsStepView    = new SettingsStepView({ wizardData: this.wizardData, app: this.app, streamType: this.streamType}).render();
            var groupsStepView      = new GroupsStepView({ wizardData: this.wizardData, onSave: this.save.bind(this) }).render();
            var doneStepView        = new DoneStepView({ wizardData: this.wizardData }).render();

            if (this.streamType === 'metadata') {
                var aggregationStepView = new AggregationStepView({ wizardData: this.wizardData }).render();
                var filtersStepView = new FiltersStepView({ wizardData: this.wizardData, app: this.app }).render();
                var steps = [
                    basicInfoStepView,
                    aggregationStepView,
                    fieldsStepView,
                    filtersStepView,
                    settingsStepView,
                    groupsStepView,
                    doneStepView
                ];
                var label = "New Metadata Stream";
            } else {
                var targetsStepView = new TargetsStepView({ wizardData: this.wizardData, app: this.app }).render();
                var expirationStepView = new ExpirationStepView({ wizardData: this.wizardData, app: this.app }).render();
                var steps = [
                    basicInfoStepView,
                    targetsStepView,
                    expirationStepView,
                    fieldsStepView,
                    settingsStepView,
                    groupsStepView,
                    doneStepView
                ];
                var label = "New Packet Stream";
            }

            var wizView = new StepWizardView({
                el: $(".wizard-head"),
                stepContainer: $(".wizard-body"),
                operatingMode: "wizard",
                label: label,
                showExitButton: true,
                steps: steps
            }).render();

            wizView.$('.exit-button').html('Cancel');
            wizView.on('exit', this.onWizardExit, this);

            this.app.mediator.publish("switch-layout", "new-stream-wizard-layout");
        },

        save: function(errorCallback) {
            var promise = $.Deferred();
            var self = this;
            var newStream = this.wizardData.newStream;
            var queryString = 'addToDefaultGroup=' + _(_.pluck(this.wizardData.selectedGroups, 'id')).contains('defaultgroup');

            if (this.streamType === 'packet') {
                newStream.set('isPacketStream', true);
                if (Boolean(newStream.get('enabled'))) {
                    var epochTime = parseInt((new Date).getTime() / 1000);
                    newStream.set('latestEnableTime', epochTime);
                }
            }

            if (newStream.isValid(true)) {
                newStream.save(null, {
                    type: 'post',
                    url: SplunkUtils.make_url([
                        "custom",
                        "splunk_app_stream",
                        "streams?" + queryString
                    ].join('/')),
                    success: function(e) {
                        self.app.pageIsDirty = false;
                        // Add stream to any selected forwarder groups other than defaultgroup.
                        var dfds = _.chain(self.wizardData.selectedGroups)
                                    .filter(function(group) { return group.get('id') != 'defaultgroup' })
                                    .map(function(group) {
                                        var dfd = $.Deferred();

                                        group.get('streams').push(newStream.get('id'));
                                        group.save(null, {
                                            success: function() {
                                                dfd.resolve();
                                            },
                                            error: function(model) {
                                                dfd.reject(model.get('id'))
                                            }
                                        });

                                        return dfd;
                                    })
                                    .value();

                        // Wait until all requests succeed or one fails.  In either case, go on to the final wizard page, but
                        // in the latter case, save the group id of the (first) failed request so a warning can be displayed.
                        $.when.apply($, dfds)
                              .done(function() {
                                  promise.resolve();
                              })
                              .fail(function(id) {
                                  self.wizardData.failedGroupId = id;
                                  promise.resolve();
                              })

                        // Don't publish "event:new-stream-added" yet, or you'll go right to the new
                        // stream page instead of the final wizard page.
                        self.streamCreated = true;
                        self.$('.exit-button').hide();
                    },
                    error: function(obj, err) {
                        errorCallback(err.responseJSON.error);
                        console.log("Error saving stream: ", err.responseJSON.error);
                        promise.reject();
                    }
                });
            }
            else {
                this.$('.alert-error').fadeIn();
                promise.reject();
            }
            return promise;
        },

        onWizardExit: function() {
            this.app.pageIsDirty = false;
            if (this.streamCreated){
                this.app.mediator.publish("event:new-stream-added", this.wizardData.newStream);
            }
            else{
                // this.app.mediator.publish("switch-layout", "app-main-layout");
                //cannot just hide b/c refreshing within the wizard rehydrates only
                //the wizard so when hide/show is done nothing is shown.
                this.app.router.navigate("permanent", {trigger: true})
            }
            this.removeSelf();
        },

        removeSelf: function() {
            // empty the contents of the container DOM element without taking it out of the DOM
            this.$el.empty();

            // clears all callbacks previously bound to the view with delegateEvents method
            this.undelegateEvents();

            return this;
        }

    });
});
