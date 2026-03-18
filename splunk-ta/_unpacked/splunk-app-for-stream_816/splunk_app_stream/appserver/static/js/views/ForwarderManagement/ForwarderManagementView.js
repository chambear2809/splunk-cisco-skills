define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "swc-stream/index",
    "contrib/text!app-js/templates/ForwarderManagement/ForwarderManagementTemplate.html",
    "app-js/views/ForwarderManagement/CreateNewForwarderGroupView",
    "app-js/models/ForwarderGroup",
    "app-js/views/ForwarderManagement/ForwarderTableRowView",
    "app-js/views/ForwarderManagement/ForwarderTableInfoRowView",
    "app-js/views/ForwarderManagement/FwdManagementWizardView",
    "app-js/views/ForwarderManagement/InstallStreamForwardersView",
    "app-js/views/ForwarderManagement/SetupStreamForwarderAuthView"
], function(
    $,
    _,
    Backbone,
    index,
    ForwarderManagementTemplate,
    CreateNewForwarderGroupView,
    ForwarderGroup,
    ForwarderTableRowView,
    ForwarderTableInfoRowView,
    FwdManagementWizardView,
    InstallStreamForwardersView,
    SetupStreamForwarderAuthView
    ) {

    const SearchManager = index.SearchManager;
    const mvc = index.mvc;
    const utils = index.utils;

    return Backbone.View.extend({

        initialize: function (options) {

            this.options              = _.extend({}, this.options, options);
            this.app                  = this.options.app;
            this.template             = _.template($(ForwarderManagementTemplate).html());
            this.collection           = this.options.fwdGroupsCollection;
            this.streamsCollection    = this.options.streamsCollection;
            this.indexersModel        = this.options.indexersModel;
            this.streamfwdAuth        = this.options.fwdAuthModel;

            this.matchedFwdGroupsFetched = $.Deferred();

            this.collection.on('change add remove', this.render.bind(this));

            var wizardPartialModel = new ForwarderGroup({});
            var self = this;

            var fwdGroupSearch = new SearchManager({
                id            : "fwdGroupSearch",
                // what time range is best?
                earliest_time : "-15m",
                app           : utils.getCurrentApp(),
                latest_time   : "now",
                max_time      : 4,
                auto_cancel   : 8,
                search        : 'index=_internal sourcetype="stream:stats" | spath Output=fwdGroups path=senders{}.streamForwarderGroups{} | spath Output=fwdId path=senders{}.streamForwarderId | table fwdGroups, fwdId, timestamp'
            });

            fwdGroupSearch.on("search:done", function(state, job) {

                /*==========  If data is found  ==========*/
                if (state.content.resultCount > 0){

                    job.results({count:0}, function(error, data){

                        var results = {
                            fields : data.fields,
                            rows   : data.rows
                        }

                        //key: forwarder-id, value: latestTime
                        var forwardersMasterDict = {};
                        //key: forwarder-group, value: [array of matched forwarder IDs]
                        var fwdGroupsDict = {};

                        for (var i = 0; i < results.rows.length; i++) {

                            var eachRow       = results.rows[i];
                            var matchedGroups = _.flatten([eachRow[0]]);
                            var fwdId         = eachRow[1];
                            var fwdTime       = eachRow[2];
                            var fwdRegistered = fwdId in forwardersMasterDict;

                            if (!fwdRegistered) {
                                /*==========  Update Fwd Groups ==========*/
                                _.each(matchedGroups, function (value, key) {
                                    fwdGroupsDict[value] = fwdGroupsDict[value] || [];
                                    fwdGroupsDict[value].push(fwdId);
                                })
                                /*==========  Update Forwarders  ==========*/
                                forwardersMasterDict[fwdId] = fwdTime;
                            }
                        }

                        var formattedForwardersList = _.map(_.pairs(forwardersMasterDict), function (each) {
                            return {id: each[0], latestTime: each[1]};
                        })

                        self.matchedFwdGroupsFetched.resolve({
                            fwdGroupsDict        : fwdGroupsDict,
                            forwardersMasterList : formattedForwardersList
                        });

                    });
                }

                /*==========  If no data is found  ==========*/
                else{
                    self.matchedFwdGroupsFetched.resolve({
                        fwdGroupsDict        : {},
                        forwardersMasterList : []
                    });
                }

            });

        },

        events: {
            "keyup #fwd-group-search-input"     : "filterTable",
            'click a.clear'                     : "resetSearch",
            'click #create-new-forwarder-group' : "createNewForwarderGroup",
            'click #install-stream-forwarders'  : "installStreamForwarders",
            'click #setup-streamfwd-auth'       : "setupStreamForwarderAuth"
        },

        createNewForwarderGroup: function () {

            var wizard = new FwdManagementWizardView({
                forwardersMasterList : this.forwardersMasterList,
                matchedFwdGroups     : this.matchedFwdGroups,
                fwdGroupsCollection  : this.collection,
                streamsCollection    : this.streamsCollection,
                indexersModel        : this.indexersModel
            });
            wizard.start();
        },

        installStreamForwarders: function () {
            var installStreamForwarders = new InstallStreamForwardersView({
                streamfwdAuth: this.streamfwdAuth
            }).show();
        },

        setupStreamForwarderAuth: function () {
            var setupStreamForwaderAuth = new SetupStreamForwarderAuthView({
                streamfwdAuth: this.streamfwdAuth
            }).show();
        },

        resetSearch: function (e) {
            e.preventDefault();
            $(this.el).find('.stream-search input').val('');
            this.render();
        },

        filterTable: function () {
            var searchString = $('#fwd-group-search-input').val();
            this.app.mediator.publish("search-filtered", searchString);
        },

        render: function () {

            var self = this;

            $.when(this.matchedFwdGroupsFetched.promise())
             .done(function(matchedFwdGroupsObj) {

                self.matchedFwdGroups = matchedFwdGroupsObj.fwdGroupsDict;
                self.forwardersMasterList = matchedFwdGroupsObj.forwardersMasterList;

                var output = self.template({
                    fwdGroupCount: self.collection.length
                });

                self.$el.empty();
                self.$el.append(output);

                var tableBody = self.$("#forwarder-management-table");

                //append the table rows
                self.collection.each(function (eachModel) {

                    var newRow = new ForwarderTableRowView({
                        model                : eachModel,
                        streamsCollection    : self.streamsCollection,
                        app                  : self.app,
                        forwardersMasterList : self.forwardersMasterList,
                        matchedFwdGroups     : self.matchedFwdGroups[eachModel.get('id')] || [],
                        fwdGroupsCollection  : self.collection,
                        indexersModel        : self.indexersModel
                    }).render().$el.appendTo(tableBody);

                    var newInfoRow = new ForwarderTableInfoRowView({
                        model            : eachModel,
                        matchedFwdGroups : self.matchedFwdGroups[eachModel.get('id')] || [],
                        app              : self.app,
                        indexersModel    : self.indexersModel
                    }).render().$el.appendTo(tableBody);

                });

                $("#forwarder-management-table").tablesorter({
                    cssChildRow: 'detailed-info-tr',
                    headers:{
                        //info toggle chevrons
                        0: { sorter:false },
                        //actions
                        7: { sorter:false }
                    }
                });
            });

            return this;
        },


        removeSelf: function () {
            this.unbind();
            this.$el.empty();
            this.undelegateEvents();
            return this;
        }

    });
});
