define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "contrib/text!app-js/templates/ForwarderManagement/CreateNewForwarderGroupTemplate.html",
    "app-js/views/ForwarderManagement/EditRuleView",
    "app-js/models/ForwarderGroup"
], function(
    $,
    _,
    Backbone,
    CreateNewForwarderGroupTemplate,
    EditRuleView,
    ForwarderGroup
    ) {
    return Backbone.View.extend({

        //bootstrap modal styling
        className: 'modal',

        initialize: function(options) {

            this.template      = _.template($(CreateNewForwarderGroupTemplate).html());
            this.fwdGroupModel = options.fwdGroupModel;
            this.indexersModel = options.indexersModel;

            //wizard options
            this.fwdGroupsCollection = options.fwdGroupsCollection;
            this.wizardController    = options.wizardController;
            this.isWizard            = !!(options.wizardController);

            //get url endpoints found via hec autodiscovery
            this.autoconfigUrls = '';
            if (this.indexersModel && this.indexersModel.get('collectors'))
                this.autoconfigUrls = this.indexersModel.get('collectors').join(',\n');

            //get user set hec indexer endpoint urls stored in kvstore
            this.manualUrls = '';
            if (this.indexersModel && this.fwdGroupModel.get('hec') 
                && this.fwdGroupModel.get('hec').urls) {
                this.manualUrls = this.fwdGroupModel.get('hec').urls.join(',\n');
            }

            //listen for errors
            this.listenTo(this.fwdGroupModel, 'invalid', function (model, errors) {
                this.alertErrors(errors)
            }.bind(this));
        },

        alertErrors: function(errorsArray) {
            var alertMessage = "";
            for (var i = 0; i < errorsArray.length; i++) {
                alertMessage += "\n\u2022 " + errorsArray[i];
            };
            alert(alertMessage);
        },

        events: {
            'click .yes'    : 'yes',
            'click .next'   : 'next',
            'click .back'   : 'back',
            'click .cancel' : 'cancel',

            'click #include-ephemeral-toggle' : 'toggleEphemeral',
            'click #hec-autoConfig-toggle'    : 'toggleAutoConfig'
        },

        _showEndpointUrls: function() {
            var urlTextbox = $("#hec-endpoint-urls");

            if (this.indexersModel) {
                if ($("#hec-autoConfig-on").hasClass('active')) {
                    this.manualUrls = $("#hec-endpoint-urls")[0].value;
                    urlTextbox.prop('disabled', true);
                    urlTextbox.attr('placeholder', '');
                    urlTextbox[0].value = this.autoconfigUrls;
                } else {
                    urlTextbox.prop('disabled', false);
                    urlTextbox.attr('placeholder', 'required');
                    urlTextbox[0].value = this.manualUrls;
                }
            }
        },

        toggleEphemeral: function(e) {
            var btnGroup = e.target.parentElement;

            if (! $(e.target).hasClass('active'))
                $(btnGroup).find('.btn').toggleClass('active');
        },

        toggleAutoConfig: function(e) {
            if (! $(e.target).hasClass('active')) {
                $("#hec-autoConfig-on").toggleClass('active');
                $("#hec-autoConfig-off").toggleClass('active');
                this._showEndpointUrls();
            }
        },

        cancel: function() {
            this.remove();
        },

        show: function() {

            var fwdGroupModel = this.fwdGroupModel.toJSON();

            if (!fwdGroupModel.hec || !fwdGroupModel.hec.urls) {
                fwdGroupModel.hec = {autoConfig: true, urls: []};
            }

            this.$el.html(this.template({
               fwdGroupModel : fwdGroupModel,
               isWizard      : this.isWizard,
               hecSupported  : this.indexersModel
            }));

            this.$el.on('hide', function() {
                this.remove();
            }.bind(this))

            this.$el.modal('show');
            this._showEndpointUrls();

            return this;
        },

        next: function() {

            var fwdGroupName        = $("#fwd-group-name").val();
            var includeEphemeral    = $("#include-ephemeral").is(".active");
            var fwdGroupDescription = $("#fwd-group-description").val();
            var autoConfigEnabled   = true;
            var endpointUrls = '';

            if (this.indexersModel) {
                autoConfigEnabled   = $("#hec-autoConfig-on").is(".active");

                endpointUrls = $("#hec-endpoint-urls").val().split(",");
                endpointUrls = _.compact(_.map(endpointUrls, function(x) {return x.trim();}));
            }

            var hec = {
                autoConfig : autoConfigEnabled,
                urls       : endpointUrls
            };

            var partialModel = {
                id                      : fwdGroupName,
                description             : fwdGroupDescription,
                includeEphemeralStreams : includeEphemeral,
                hec                     : hec
            };

            //check errors for this page
            var errors      = this.fwdGroupModel.validateBasic(partialModel);
            var isDuplicate = !!this.fwdGroupsCollection.get(fwdGroupName);
            if (isDuplicate) {
                errors.push("Duplicate name is not allowed.");
            }

            if (errors.length > 0) {
                this.alertErrors(errors);
            } else {
                this.$el.modal('hide');
                this.wizardController.stepTwo(partialModel);
            }

        },

        yes: function(e) {

            /* Save Edits */

            var self = this;

            var fwdGroupDescription = $("#fwd-group-description").val();
            var includeEphemeral    = $("#include-ephemeral").is(".active");

            var autoConfigEnabled   = this.indexersModel ? $("#hec-autoConfig-on").is(".active") : true;

            var hec = {autoConfig: autoConfigEnabled};

            if (!autoConfigEnabled) {
                var endpointUrls = $("#hec-endpoint-urls").val().split(",");
                hec.urls = _.compact(_.map(endpointUrls, function(x) {return x.trim();}));
            }

            this.fwdGroupModel.save({
                description             : fwdGroupDescription,
                includeEphemeralStreams : includeEphemeral,
                hec                     : hec
            },
            {
                success: function (model, response) {
                    console.log("model updated", response);
                    self.$el.modal('hide');
                    self.remove();
                },
                error: function (model, response) {
                    console.log("error editing group: ", response);
                    alert(response.responseJSON.error);
                }
            });

        }

    });
})
