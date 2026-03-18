define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "contrib/text!app-js/templates/ForwarderManagement/ForwarderTableInfoRowTemplate.html",
    "app-js/views/ForwarderManagement/ShowMoreInfoView"
], function(
    $,
    _,
    Backbone,
    ForwarderTableInfoRowTemplate,
    ShowMoreInfoView
    ) {
    return Backbone.View.extend({

        tagName: 'tr',
        className: 'detailed-info-tr',

        initialize: function (options) {

            this.options  = _.extend({}, this.options, options);
            this.app      = this.options.app;
            this.template = _.template($(ForwarderTableInfoRowTemplate).html());
            this.model    = this.options.model;
            this.indexers = this.options.indexersModel;

            this.streams          = this.model.get('streams').sort(this._lexiComparator);
            this.matchedFwdGroups = this.options.matchedFwdGroups.sort(this._lexiComparator);

            if (this.indexers) {
                this.endpointUrls     = this.model.get('hec').urls || this.indexers.get('collectors');
            }

            var self = this;
            this.app.mediator.subscribe("search-filtered", function (searchString) {
                //make sure all secondary rows are hidden when user searches.
                self.$el.hide();
            });

            this.listenTo(this.model, 'change', function () {
                self.render();
            })

        },

        events: {
            "click span.show-more.stream-models"      : "showMoreStreams",
            "click span.show-more.matched-fwd-groups" : "showMoreMatchedFwdGroups",
            "click span.show-more.http-endpoint-urls" : "showMoreEndpointUrls"
        },

        showMoreStreams: function () {
            var showMoreInfoView = new ShowMoreInfoView({
                modalTitle         : "Streams",
                parentName         : this.model.get('id'),
                additionalInfoList : this.streams
            }).show();
        },

        showMoreMatchedFwdGroups: function () {
            var showMoreInfoView = new ShowMoreInfoView({
                modalTitle         : "Matched Forwarder Groups",
                parentName         : this.model.get('id'),
                additionalInfoList : this.matchedFwdGroups
            }).show();
        },

        showMoreEndpointUrls: function () {
            var showMoreInfoView = new ShowMoreInfoView({
                modalTitle         : "Endpoint Urls",
                parentName         : this.model.get('id'),
                additionalInfoList : this.endpointUrls
            }).show();
        },

        _lexiComparator: function (a,b) {
            //lowercase lexicographical sort
            var a_lower = a.toLowerCase();
            var b_lower = b.toLowerCase();
            if (a_lower < b_lower) { return -1; }
            if (a_lower > b_lower) { return 1; }
            return 0;
        },

        render: function () {
            this.$el.html(this.template({
                streams          : this.streams,
                matchedFwdGroups : this.matchedFwdGroups,
                endpointUrls     : this.endpointUrls
            }));
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
