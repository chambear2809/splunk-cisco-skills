define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "contrib/text!app-js/templates/ForwarderManagement/ForwarderTableRowTemplate.html",
    "app-js/views/ForwarderManagement/CreateNewForwarderGroupView",
    "app-js/views/ForwarderManagement/ModifyFwdGroupStreamsView",
    "app-js/views/ForwarderManagement/EditRuleView",
    "app-js/views/ConfirmView",
    "swc-stream/index"
], function(
    $,
    _,
    Backbone,
    ForwarderTableRowTemplate,
    CreateNewForwarderGroupView,
    ModifyFwdGroupStreamsView,
    EditRuleView,
    ConfirmView,
    index
    ) {
    const Popdown = index.Popdown;
    return Backbone.View.extend({

        tagName: 'tr',
        className: 'fwd-table-row',

        //this attribute unneeded, but useful for selenium testing.
        attributes: function () {
            return {
                'data-id': this.model.get('id')
            }
        },

        initialize: function(options){

            this.app                  = options.app;
            this.template             = _.template($(ForwarderTableRowTemplate).html());
            this.model                = options.model;
            this.streamsCollection    = options.streamsCollection;
            this.forwardersMasterList = options.forwardersMasterList;
            this.fwdGroupsCollection  = options.fwdGroupsCollection;
            this.matchedFwdGroups     = options.matchedFwdGroups || [];
            this.indexersModel        = options.indexersModel;

            var self = this;
            this.app.mediator.subscribe("search-filtered", function (searchString) {
                self._showHideBasedOnRegex(searchString);
            });

            this.listenTo(this.model, 'change', function () {
                self.render();
            })

        },

        //show/hide this row based on user input
        _showHideBasedOnRegex: function (searchString) {

            var self = this;
            var regex = new RegExp(searchString, "i");

            // show if regex matches any of these strings.
            var matchCases = _.flatten([
                self.model.get('id'),
                self.model.get('description'),
                self.matchedFwdGroups
            ]);

            var regexMatches = _.some(_.map(matchCases, function (str) {
                return regex.test(str);
            }));

            if (regexMatches) {
                self.$el.show();
                resetChevron();
            } else {
                self.$el.hide();
            }

            //reset Chevron b/c it isn't when user searches while expanded.
            function resetChevron() {
                var chevron = self.$el.find('span.more-info-toggle');
                chevron.removeClass("icon-chevron-down");
                chevron.addClass("icon-chevron-right");
            }

        },

        events: {

            'click .fwd-group-edit'           : 'editForwarderGroup',
            'click .fwd-group-edit-rule'      : 'editRule',
            'click .fwd-group-delete'         : 'deleteForwarderGroup',
            'click .more-info-td'             : 'toggleExtendedTable',
            'click .fwd-group-modify-streams' : 'modifyStreams'

        },

        editRule: function () {
            var editRuleView = new EditRuleView({
                forwardersMasterList : this.forwardersMasterList,
                fwdGroupModel        : this.model
            }).show();
        },

        modifyStreams: function () {
            var modifyFwdGroupStreamsView = new ModifyFwdGroupStreamsView({
                streamsCollection   : this.streamsCollection,
                fwdGroupsCollection : this.fwdGroupsCollection,
                fwdGroupModel       : this.model
            }).show();
        },

        editForwarderGroup: function (e) {
            e.preventDefault();
            var editFwdGroupView = new CreateNewForwarderGroupView({
                fwdGroupModel : this.model,
                indexersModel : this.indexersModel
            }).show();
        },

        deleteForwarderGroup: function (e) {

            e.preventDefault();
            var thisModel = this.model;
            var self = this;

            var confirmView = new ConfirmView({
                action  : "delete",
                model   : {text: this.model.get('id')},
                command : function() {

                    thisModel.destroy({
                        success: function (model, response) {console.log(model, " was succesfully destroyed"); },
                        error: function () {
                            alert("error: failed to delete");
                            location.reload();
                        }
                    })

                }
            }).show();

        },

        toggleExtendedTable: function (e) {

            var $target = $(e.target);

            //toggle second row visibility
            $target.closest('tr').next().toggle();

            //toggle chevron right/down
            var chevron = $target.find('span.more-info-toggle');
            chevron.toggleClass("icon-chevron-right");
            chevron.toggleClass("icon-chevron-down");

        },

        render: function(){

            var self = this;

            this.$el.html(self.template({
                model: this.model.toJSON()
            }));

            // WTF, this combined with not using toJSON above gives strange behavior
            // research core popdown usage.
            // setTimeout(function () {
                new Popdown({ el: this.$(".forwarder-group-action-popdown") });
            // }, 0);

            return self;
        },

        removeSelf: function () {
            this.unbind();
            this.$el.empty();
            this.undelegateEvents();
            return this;
        }

    });
});
