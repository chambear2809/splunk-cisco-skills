define([
        "app-js/contrib/underscore",
        "app-js/contrib/jquery",
        "app-js/contrib/backbone",
        "app-js/contrib/mediator",
        "app-js/views/ForwarderManagement/ForwarderManagementView",
        "app-js/collections/ForwarderGroups",
        "app-js/collections/Streams",
        "app-js/models/Indexers",
        "app-js/models/StreamFwdAuth",
        "app-js/components/loadLayout"
    ],
    function(
        _,
        $,
        Backbone,
        Mediator,
        ForwarderManagementView,
        ForwarderGroups,
        Streams,
        Indexers,
        StreamFwdAuth,
        LoadLayout
        ) {

        var app      = app || {};
        var splunkd  = splunkd || {};
        app.mediator = new Mediator();

        /*========================================
        =            Fetch and Render            =
        ========================================*/

        var fwdGroupsFetched = $.Deferred();
        var fwdGroups        = new ForwarderGroups();
        var streamsFetched   = $.Deferred();
        var streams          = new Streams();
        var indexersFetched  = $.Deferred();
        var indexers         = new Indexers();
        var fwdAuthFetched   = $.Deferred();
        var fwdAuth          = new StreamFwdAuth();

        /*==============================================
        =            Fetch Forwarder Groups            =
        ==============================================*/

        fwdGroups.fetch({
            success: function (groupsCollection) {
                fwdGroupsFetched.resolve(groupsCollection);
            },
            error: function (e) {
                console.log("error fetching fwd groups");
            }
        })

        /*=====================================
        =            Fetch Streams            =
        =====================================*/

        streams.fetch({
            success: function (streamsCollection) {
                streamsFetched.resolve(streamsCollection);
            },
            error: function (e) {
                console.log("error fetching streams");
            }
        })

        /*======================================
        =            Fetch Indexers            =
        ======================================*/

        indexers.fetch({
            success: function (indexersModel) {
                indexersFetched.resolve(indexersModel);
            },
            error: function (e) {
                console.log("error fetching indexers");
                indexersFetched.resolve(undefined);
            }
        })

        /*===================================================
        =            Fetch Stream Forwarder Auth            =
        ===================================================*/

        fwdAuth.fetch({
            success: function (fwdAuthModel) {
                fwdAuthFetched.resolve(fwdAuthModel);
            },
            error: function (e) {
                console.log("error fetching stream forwarder auth");
            }
        })

        /*========================================
        =            When all Fetched            =
        ========================================*/

        $.when(fwdGroupsFetched.promise(), streamsFetched.promise(), indexersFetched.promise(), fwdAuthFetched.promise())
         .done(function(groupsCollection, streamsCollection, indexersModel, fwdAuthModel) {

            LoadLayout(function(layout) {
                var appContent = new ForwarderManagementView({
                    fwdGroupsCollection  : groupsCollection,
                    streamsCollection    : streamsCollection.returnPermanentStreams(),
                    indexersModel        : indexersModel,
                    fwdAuthModel         : fwdAuthModel,
                    app                  : app
                });
                layout.create()
                    .getContainerElement()
                    .appendChild(appContent.render().el);
            });
        });
});
