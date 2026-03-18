define([
    "app-js/contrib/jquery",
    "app-js/components/loadLayout",
    "app-js/views/StreamsView",
    "app-js/contrib/mediator",
    "app-js/collections/Streams",
    "app-js/collections/ReferenceStreams",
    "app-js/models/Term",
    "app-js/collections/Vocabularies",
    "app-js/collections/ComparisonTypes",
    "app-js/collections/SplunkIndexes",
    "app-js/collections/Terms"
    ],
    function(
        $,
        LoadLayout,
        StreamsView,
        Mediator,
        Streams,
        ReferenceStreams,
        Term,
        Vocabularies,
        ComparisonTypes,
        SplunkIndexesCollection,
        Terms
        ) {

        var app = app || {};

        // instantiate a new Mediator
        app.mediator = new Mediator();

        app.streams          = new Streams();
        app.referenceStreams = new ReferenceStreams();
        app.vocabularies     = new Vocabularies();
        app.terms            = new Terms();
        app.comparisonTypes  = new ComparisonTypes(ComparisonTypes.comparisonTable);

        //initialize promises
        var termsFetchDone            = $.Deferred();
        var vocabsFetchDone           = $.Deferred();
        var splunkIndexesFetchDone    = $.Deferred();
        var referenceStreamsFetchDone = $.Deferred();

        /*======================================================
        =       Async Fetch Vocab, Indexes & Reference Streams =
        =======================================================*/

        /*==========  Fetch Terms  ==========*/

        app.terms.fetch({
            success: function (collection) {
                termsFetchDone.resolve();
            },
            error: function (model, response, options) {
                console.log('terms fetch failed.');
            }
        });

        /*==========  Fetch Vocabularies  ==========*/

        app.vocabularies.fetch({
            success: function (collection) {
                vocabsFetchDone.resolve();
            },
            error: function (mode, response) {
                console.log('vocabularies fetch failed.');
            }
        });

        /*==========  Fetch Indexes  ==========*/

        var splunkIndexes = new SplunkIndexesCollection();
        splunkIndexes.fetch({
            data: {count: 0},//default is 30, set to 0 for all
            success: function(data) {
                app.splunkIndexItems = splunkIndexes.filterParseMap(data.toJSON());
                splunkIndexesFetchDone.resolve();
            },
            error: function() {
                console.log("failure to retrieve splunk indexes");
            }
        })

        /*==========  Fetch Reference Streams  ==========*/

        app.referenceStreams.fetch({
            success: function() {
                referenceStreamsFetchDone.resolve();
            },
            error: function() {
                console.log("Error fetching Reference Streams collection from server");
            }
        });

        /*-----  End of Async Fetch Vocab, Indexes, Terms & Reference Streams  ------*/

        /*===============================
        =            Utility            =
        ===============================*/

        /*
        Automates the destruction and creation of views
        */

        function AppView() {

            this.showView = function(view) {
                //if view exists, remove it.
                if (this.currentView){
                    this.currentView.removeSelf();
                }
                this.currentView = view;
                return this.currentView.render();
            }
        };

        var appView = new AppView();

        $.when(termsFetchDone.promise(), vocabsFetchDone.promise(), splunkIndexesFetchDone.promise(), referenceStreamsFetchDone.promise())
            .done(function(version, tourFlag, easySetupFlag, streamfwdConfig, cloudInstanceFlag) {

            LoadLayout(function(layout) {
                var appContent = new StreamsView({
                    app : app,
                    appView : appView
                });
                layout.create()
                    .getContainerElement()
                    .appendChild(appContent.render().el);
            });
        });
    }
);
