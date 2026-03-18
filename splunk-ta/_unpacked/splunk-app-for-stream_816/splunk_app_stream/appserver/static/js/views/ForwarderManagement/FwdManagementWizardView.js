define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "app-js/models/ForwarderGroup",
    "app-js/views/ForwarderManagement/EditRuleView",
    "app-js/views/ForwarderManagement/ModifyFwdGroupStreamsView",
    "app-js/views/ForwarderManagement/CreateNewForwarderGroupView"
], function(
    $,
    _,
    Backbone,
    ForwarderGroup,
    EditRuleView,
    ModifyFwdGroupStreamsView,
    CreateNewForwarderGroupView
    ) {
    return Backbone.View.extend({

        initialize: function(options){

            this.forwardersMasterList = options.forwardersMasterList;
            this.fwdGroupsCollection  = options.fwdGroupsCollection;
            this.indexersModel        = options.indexersModel;
            this.streamsCollection    = options.streamsCollection;

            this.wizardPartialModel = new ForwarderGroup();

        },

        start: function () {
            this.stepOne();
        },

        /*===========================================
        =            Wizard Flow Control            =
        ===========================================*/
        // Step 1: Basic Information
        // Step 2: Regex Rule
        // Step 3: Selection of streams

        // Step 1: Basic Information
        stepOne: function (newPartialObj) {

            var extendedPartial = _.extend(this.wizardPartialModel.toJSON(), newPartialObj);
            this.wizardPartialModel.set(extendedPartial);

            var createNewForwarderGroup = new CreateNewForwarderGroupView({
                fwdGroupModel       : this.wizardPartialModel,
                fwdGroupsCollection : this.fwdGroupsCollection,
                indexersModel       : this.indexersModel,
                wizardController    : this
            })
            createNewForwarderGroup.show();
        },

        // Step 2: Regex Rule
        stepTwo: function (newPartialObj) {

            var extendedPartial = _.extend(this.wizardPartialModel.toJSON(), newPartialObj);
            this.wizardPartialModel.set(extendedPartial);

            var editRuleView = new EditRuleView({
                fwdGroupModel        : this.wizardPartialModel,
                forwardersMasterList : this.forwardersMasterList,
                fwdGroupsCollection  : this.fwdGroupsCollection,
                wizardController     : this
            }).show();
        },

        // Step 3: Selection of Streams
        stepThree: function (newPartialObj) {

            var extendedPartial = _.extend(this.wizardPartialModel.toJSON(), newPartialObj);
            this.wizardPartialModel.set(extendedPartial);

            var modifyFwdGroupStreamsView = new ModifyFwdGroupStreamsView({
                fwdGroupModel       : this.wizardPartialModel,
                streamsCollection   : this.streamsCollection,
                fwdGroupsCollection : this.fwdGroupsCollection,
                wizardController    : this
            }).show();
        },

        /*-----  End of Wizard Flow Control  ------*/

    });
});
