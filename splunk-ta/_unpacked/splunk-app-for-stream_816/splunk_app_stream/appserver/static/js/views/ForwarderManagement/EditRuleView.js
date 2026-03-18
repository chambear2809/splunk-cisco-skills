define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "contrib/text!app-js/templates/ForwarderManagement/EditRuleTemplate.html",
    "app-js/models/ForwarderGroup",
    "app-js/views/ForwarderManagement/ModifyFwdGroupStreamsView",
    "app-js/views/ForwarderManagement/CreateNewForwarderGroupView",
    "app-js/contrib/moment"
], function(
    $,
    _,
    Backbone,
    EditRuleTemplate,
    ForwarderGroup,
    ModifyFwdGroupStreamsView,
    CreateNewForwarderGroupView,
    moment
    ) {
    return Backbone.View.extend({

        className: 'modal xl-modal',

        initialize: function(options){

            this.template      = _.template($(EditRuleTemplate).html());
            this.fwdGroupModel = options.fwdGroupModel;

            //variables for wizard instance
            this.forwardersMasterList = options.forwardersMasterList;
            this.wizardController     = options.wizardController;
            this.isWizard             = !!(options.wizardController);
            this.fwdGroupsCollection  = options.fwdGroupsCollection;

            //map timezone into human readable time diff
            _.each(this.forwardersMasterList, function (val, key, obj) {
                obj[key].latestTime = moment(val.latestTime).fromNow();
            })

            this.listenTo(this.fwdGroupModel, 'invalid', function (model, error) {
                //only expecting 1 error.
                alert("\n\u2022 " + error[0]);
            });

        },

        events: {
            'click .save'                 : 'save',
            'click .back'                 : 'back',
            'click .next'                 : 'next',
            'click .cancel'               : 'cancel',
            'keyup #fwd-group-rule-input' : 'filterTable'
        },

        filterTable: _.debounce(function () {

            var searchString = $("#fwd-group-rule-input").val();
            var regex;
            try {
                regex = new RegExp(searchString, "i");
            } catch(e) {
                regex = null;
            }

            var numMatched = 0;
            for (var i = 0; i < this.forwardersMasterList.length; i++) {

                var fwdId     = this.forwardersMasterList[i].id;
                //jQuery not used for optimization purposes.
                var selector = document.getElementById("fwd-info-" + fwdId);

                //css used over show/hide for optimization
                if (!regex) {
                    selector.style.display = 'none';
                    continue;
                }

                //(if regex matches something AND match is exactly the same as fwdId) OR if searchString is blank
                if ((fwdId.match(regex) && fwdId.match(regex)[0] === fwdId) || searchString === "") {
                    selector.style.display = 'table-row';
                    numMatched++;
                } else {
                    selector.style.display = 'none';
                }
            }

            if (numMatched === 0) {
                $("#num-matched-fwds").html("No matches found.");
            }
            else if(searchString === "") {
                $("#num-matched-fwds").html("Please enter a rule.");
            } else {
                $("#num-matched-fwds").html( numMatched + " matched forwarders");
            }

        }, 200),

        cancel: function() {
            //also triggers through data-dismiss property on button element
            this.remove();
        },

        show: function(){

            this.$el.html(this.template({
                forwardersMasterList : this.forwardersMasterList,
                isWizard             : this.isWizard,
                fwdGroupModel        : this.fwdGroupModel.toJSON()
            }));

            this.$el.on('hide', function() {
                this.remove();
            }.bind(this))

            this.$el.modal('show');
            this.filterTable();

            return this;
        },

        back: function () {
            var userRegex = $("#fwd-group-rule-input").val();
            this.$el.modal('hide');
            this.wizardController.stepOne({
                rule: userRegex
            })
        },

        next: function () {

            var userRegex = $("#fwd-group-rule-input").val();
            var errors    = this.fwdGroupModel.validateRegex(userRegex,true);

            var isDuplicateRule = !!(this.fwdGroupsCollection.find(function (eachModel) {
                return (eachModel.get("rule") === userRegex);
            }));

            if (isDuplicateRule && userRegex) {
                errors.push("Duplicate rule already exists.");
            }

            if (errors.length > 0){
                this.alertErrors(errors);
            } else {
                this.$el.modal('hide');
                this.wizardController.stepThree({
                    rule: userRegex
                })

            }
        },

        save: function(e) {

            var userRegex = $("#fwd-group-rule-input").val();
            var self = this;

            this.fwdGroupModel.save({rule: userRegex}, {
                success: function () {
                    self.$el.modal('hide');
                },
                error: function (model, resp) {
                    alert("\n\u2022 " + resp.responseJSON.error);
                }
            });

        },

        alertErrors: function (errorsArray) {
            var alertMessage = "";
            for (var i = 0; i < errorsArray.length; i++) {
                alertMessage += "\n\u2022 " + errorsArray[i];
            };
            alert(alertMessage);
        }

    });
});
