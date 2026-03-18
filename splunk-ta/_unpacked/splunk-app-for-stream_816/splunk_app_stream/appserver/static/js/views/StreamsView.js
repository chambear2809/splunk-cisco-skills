define([
        "app-js/contrib/underscore",
        "app-js/contrib/jquery",
        "app-js/contrib/backbone",
        "app-js/views/RegularStreams/StreamsListView",
        "app-js/views/StreamConfig/StreamView",
        "app-js/views/RegularStreams/AddStreamView",
        "app-js/views/EphemeralStreams/EphemeralStreamsView",
        "app-js/views/RegularStreams/AddStreamWizardView",
        "app-js/views/ConfirmView",
        "app-js/views/InfoView",
        "app-js/collections/EventTypes",
        "app-js/models/Vocabulary",
        "app-js/contrib/serialize-object",
        "contrib/text!app-js/templates/StreamsTemplate.html",
        "swc-stream/index"
    ],
    function(
        _,
        $,
        Backbone,
        StreamsListView,
        StreamView,
        AddStreamView,
        EphemeralStreamsView,
        AddStreamWizardView,
        ConfirmView,
        InfoView,
        EventTypes,
        Vocabulary,
        SerializeObject,
        StreamsTemplate,
        index
        ){
        const SplunkUtils = index.SplunkUtils;
        const Popdown = index.Popdown;
        return Backbone.View.extend({

        events: {
            'click #createMetadataStream' : 'showMetadataStreamWizard',
            'click #createPacketStream'   : 'showPacketStreamWizard'
        },

        initialize: function(options){
            this.options = _.extend({}, this.options, options);
            this.template = _.template($(StreamsTemplate).html());
            this.app = this.options.app;
            this.appView = this.options.appView;

            var self = this;

            ConfigRouter = Backbone.Router.extend({
                routes: {
                    "metadata": "showMetadataStreams",
                    "streamConfig/:streamId": "showStreamDetails",
                    "packet": "showPacketStreams",
                    "ephemeral": "showEphemeralStreams",
                    "newMetadataStreamWizard": "showNewMetadataStreamWizard",
                    "newPacketStreamWizard": "showNewPacketStreamWizard",
                    "streamTour" : "showStreamTour",
                    "*notFound" : "showMetadataStreams"
                },

                initialize: function(options){
                    this.appView = options.appView;
                },

                showStreamTour: function () {
                    //Allows manual tour initialization at following url:
                    //http://localhost:8000/en-US/app/splunk_app_stream/streams?tour=stream-tour:enterprise#permanent
                    window.location.href = "?tour=stream-tour:enterprise";
                },

                /*==========  Metadata Streams  ==========*/

                showMetadataStreams: function(options){
                    self.app.mediator.publish("switch-layout", "app-main-layout");

                    self.$("#permanent-tab").addClass('is-selected');
                    self.$("#packet-tab").removeClass('is-selected');
                    self.$("#ephemeral-tab").removeClass('is-selected');
                    self.$("#createStream").removeAttr("disabled");

                    var selfRouter = this;
                    var that = this;

                    self.app.streams.fetch({
                        success: function(streams) {

                            var streamsListView = new StreamsListView({
                                collection   : streams.returnMetadataStreams(),
                                el           : '#config',
                                app          : self.app,
                                router       : selfRouter,
                                isPacket     : false
                            });

                            that.appView.showView(streamsListView);
                            selfRouter.navigate("metadata" , {trigger:false})

                        },
                        error: function() {
                            console.log("Error fetching Streams collection from server");
                        }
                    });
                },

                //shows the configuration for an individual stream
                showStreamDetails: function(streamId) {

                    var that = this;

                    self.app.mediator.publish("switch-layout", "app-secondary-layout");

                    //right column (CONFIGURATIONS)
                    var stream = new self.app.streams.model({id: streamId});

                    var termsDict = {};
                    //extract the terms as a map {term: category-type}
                    // types: string, date_time, numeric, generic
                    _.each(self.app.terms.models, function(each) {
                        termsDict[each.get('id')] = each.get('category');
                    })

                    stream.fetch({
                        success: function() {
                            var streamView = new StreamView({
                                model         : stream,
                                el            : '#individual-config',
                                app           : self.app,
                                termsDict     : termsDict
                            });
                            that.appView.showView(streamView);
                        },
                        error: function() {
                            console.log("Error fetching Stream model from server");
                        }
                    });

                },

                /*==========  Packet Streams  ==========*/

                showPacketStreams: function(options){
                    self.app.mediator.publish("switch-layout", "app-main-layout");

                    self.$("#packet-tab").addClass('is-selected');
                    self.$("#permanent-tab").removeClass('is-selected');
                    self.$("#ephemeral-tab").removeClass('is-selected');
                    self.$("#createStream").removeAttr("disabled");

                    var selfRouter = this;
                    var that = this;

                    self.app.streams.fetch({
                        success: function(streams) {

                            var streamsListView = new StreamsListView({
                                collection   : streams.returnPacketStreams(),
                                el           : '#config',
                                app          : self.app,
                                router       : selfRouter,
                                isPacket     : true
                            });

                            that.appView.showView(streamsListView);
                            self.$('#app-main-layout').hide().show(0);
                            selfRouter.navigate("packet" , {trigger:false})

                        },
                        error: function() {
                            console.log("Error fetching Streams collection from server");
                        }
                    });
                },

                /*==========  Ephemeral Streams  ==========*/

                showEphemeralStreams: function(categoryItem){
                    self.$("#ephemeral-tab").addClass('is-selected');
                    self.$("#packet-tab").removeClass('is-selected');
                    self.$("#permanent-tab").removeClass('is-selected');
                    self.$("#createStream").removeAttr("disabled");

                    var dest = 'all';//default
                    if (categoryItem) { dest = categoryItem; }

                    var selfRouter = this;
                    var that = this;
                    self.app.streams.fetch({
                        success: function(streams) {

                            var ephemeralStreamsPromise = streams.returnGroupedEphemeralStreamsPromise();
                            ephemeralStreamsPromise.done(function (results) {

                                var ephemeralStreamsView = new EphemeralStreamsView({
                                    streamGroups : results.ephemeralStreamGroups,
                                    el           : '#config',
                                    app          : self.app,
                                    collection   : streams,
                                    timezone     : results.timezone
                                });

                                that.appView.showView(ephemeralStreamsView);
                                self.$('#app-main-layout').hide().show(0);
                                selfRouter.navigate("ephemeral" , {trigger:false})

                            });

                        },
                        error: function() {
                            console.log("Error fetching Streams collection from server");
                        }
                    });
                },

                /*==========  New Stream Wizard  ==========*/

                // This is only called when the app is loaded via /newStreamWizard, i.e. when the app
                // is starting in the wizard.
                showNewMetadataStreamWizard: function () {
                    self.app.mediator.publish("switch-layout", "new-stream-wizard-layout");

                    var streamsFetchDone = $.Deferred();

                    // app.streams has not yet been fetched, so do it.
                    self.app.streams.fetch({
                        success: function() {
                            streamsFetchDone.resolve();
                        },
                        error: function() {
                            console.log("Error fetching Streams collection from server");
                        }
                    });

                    $.when(streamsFetchDone.promise()).done(function() {
                        var addStreamWizardView = new AddStreamWizardView({
                            el         : '#new-stream-wizard-layout',
                            streamType : 'metadata',
                            app        : self.app
                        });

                        addStreamWizardView.show();
                    });
                },

                showNewPacketStreamWizard: function () {
                    self.app.mediator.publish("switch-layout", "new-stream-wizard-layout");

                    var streamsFetchDone = $.Deferred();

                    // app.streams has not yet been fetched, so do it.
                    self.app.streams.fetch({
                        success: function() {
                            streamsFetchDone.resolve();
                        },
                        error: function() {
                            console.log("Error fetching Streams collection from server");
                        }
                    });

                    $.when(streamsFetchDone.promise()).done(function() {
                        var addStreamWizardView = new AddStreamWizardView({
                            el         : '#new-stream-wizard-layout',
                            streamType : 'packet',
                            app        : self.app
                        });

                        addStreamWizardView.show();
                    });
                }

            });

            /*-----  End of Router  ------*/


            /*=============================================
            =           Initialize App                    =
            =============================================*/

            var router = new ConfigRouter({appView: this.appView});
            //attach router to app
            this.app.router = router;

            /*=====================================
            =            Subscriptions            =
            =====================================*/

            this.app.mediator.subscribe("view:streams", function(){
                self.app.router.navigate("metadata", {trigger: true});
            });

            this.app.mediator.subscribe("view:add-stream-dialog", function(stream, userHasChanges){
                var addStreamView = new AddStreamView({
                    app: self.app,
                    stream: stream,
                    userHasChanges: userHasChanges
                }).show();
            });

            this.app.mediator.subscribe("event:new-stream-added", function(stream){
                self.app.streams.add(stream);
                //go to the newly created stream
                var urlFragment = "streamConfig/" + stream.id;
                self.app.router.navigate(urlFragment, {trigger:true});
            });

            this.app.mediator.subscribe("switch-layout", function(layoutId) {
                self.$('.mutually-exclusive-layout').each(function() {
                    if (this.id === layoutId) {
                        $(this).show();
                    }
                    else {
                        $(this).hide();
                    }
                });
            });

            /*==========  Bulk Actions  ==========*/

            var showModifyMultipleStreamsDialog = function (streams, action, location) {

                var confirmView = new ConfirmView({
                    action: action,
                    model: {streams: _(streams).map(function(eachModel){ return eachModel.toJSON(); })},
                    command: function () {

                        var defArray = [];

                        streams.forEach(function(stream) {
                            var promise;
                            if (action === "delete"){
                                promise = stream.deleteStream();
                            } else {
                                promise = stream.setStreamMode(action)
                            }
                            defArray.push(promise);
                        });

                        //show all failures
                        $.when.apply($, defArray).done(function(){
                            var results = Array.prototype.slice.call(arguments);

                            var errors = _.chain(results)
                                          .where({success: false})
                                          .map(function (each) {
                                              return each.value.responseJSON.error;
                                          })
                                          .value();

                            if (errors.length > 0) {
                                var errorMsg = "<p>" + errors.join("</p><p>") + "</p>";
                                var infoView = new InfoView({
                                    title: "Following changes failed:",
                                    message: errorMsg
                                }).show();
                            }

                            //force a reload to sync client & server models
                            //quite slow b/c the fetch is slow
                            router.navigate("", {trigger: false});
                            router.navigate(location, {trigger:true});
                        });
                    }
                }).show();
            };

            //disable
            this.app.mediator.subscribe("view:bulk-disable-streams-dialog", function(options){
                showModifyMultipleStreamsDialog(options.streams, 'disable', options.location);
            });

            // enable
            this.app.mediator.subscribe("view:bulk-enable-streams-dialog", function(options){
                showModifyMultipleStreamsDialog(options.streams, 'enable', options.location);
            });

            // delete
            this.app.mediator.subscribe("view:bulk-delete-streams-dialog", function(options){
                showModifyMultipleStreamsDialog(options.streams, 'delete', options.location);
            });

            // estimate
            this.app.mediator.subscribe("view:bulk-stats-only-streams-dialog", function(options){
                showModifyMultipleStreamsDialog(options.streams, 'estimate', options.location);
            });

            this.app.mediator.subscribe("view:info-dialog", function(title, message){
                var infoView = new InfoView({
                    title: title,
                    message: message
                }).show();
            });

            /*==========  Listen for stream changes and update # of streams tab  ==========*/

            this.app.streams.on("add remove", function (result) {
                var collection = result.collection;
                var numTotal = collection.length;
                var ephemeralStreams = collection.filter(function(eachModel){
                    return eachModel.has("expirationDate");
                });

                metadataStreams = collection.filter(function(eachModel){
                    return !eachModel.has("expirationDate") &&
                    (!eachModel.has("isPacketStream") || eachModel.attributes.isPacketStream === false);
                });

                packetStreams = collection.filter(function(eachModel){
                    return eachModel.attributes.isPacketStream === true;
                });

                self.$("#permanent-tab span").html(metadataStreams.length);
                self.$("#ephemeral-tab span").html(ephemeralStreams.length);
                self.$("#packet-tab span").html(packetStreams.length);
            })
        },

        openStreamWizard: function (streamType) {
            var self = this;
            this.app.mediator.publish("switch-layout", "new-stream-wizard-layout");

            var latestStreamsFetchDone = $.Deferred();

            // always do a fresh fetch here, since the list of streams can change any time (unlike the reference streams)
            this.app.streams.fetch({
                success: function() {
                    latestStreamsFetchDone.resolve();
                },
                error: function() {
                    console.log("Error fetching Streams collection from server");
                }
            });

            $.when(latestStreamsFetchDone.promise()).done(function() {
                var addStreamWizardView = new AddStreamWizardView({
                    el         : '#new-stream-wizard-layout',
                    streamType : streamType,
                    app        : self.app
                });

                // Update the URL.
                if (streamType === 'metadata') {
                    self.app.router.navigate("newMetadataStreamWizard");
                } else {
                    self.app.router.navigate("newPacketStreamWizard");
                }

                addStreamWizardView.show();
            });
        },

        showMetadataStreamWizard: function() {
            this.openStreamWizard('metadata');
        },

        showPacketStreamWizard: function() {
            this.openStreamWizard('packet');
        },

        render: function () {

            var self = this;
            this.$el.html(this.template({}));

            Backbone.history.start();

            var originalLoadUrl = Backbone.history.loadUrl;

            Backbone.history.loadUrl = function () {
                if (self.app.pageIsDirty) {
                    var fragment = Backbone.history.fragment;
                    var dialog = confirm(self.app.exitMessage);
                    if (dialog){
                        self.app.pageIsDirty = false;
                        originalLoadUrl.apply(this,arguments);
                    } else {
                        window.location.hash = '#' + fragment;
                        return false;
                    }
                } else {
                    originalLoadUrl.apply(this,arguments);
                }
            }

            //Any time any page in the app is dirty, a confirmation will be displayed.
            $(window).on('beforeunload', function(){
                if (self.app.pageIsDirty){
                    return self.app.exitMessage;
                }
            });

            $("title").text("Configure Streams");

            new Popdown({ el: self.$(".stream-create") });

            /*==========  Browser resizing  ==========*/

            $(window).resize(function() {
                var height = $(window).height() * 0.7;
                self.$("#main-streams-page .right-column").css("height", height);
                self.$("#main-streams-page .left-column").css("height", height);
            });

            return this;
        }

    });
});
