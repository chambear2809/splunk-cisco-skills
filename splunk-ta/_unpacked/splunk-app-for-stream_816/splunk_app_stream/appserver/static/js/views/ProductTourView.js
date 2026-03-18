define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "contrib/text!app-js/templates/ProductTourDialog.html"
], function(
    $,
    _,
    Backbone,
    ProductDialogTemplate
    ) {
    return Backbone.View.extend({

        className: 'modal',

        initialize: function (options) {
            this.options  = _.extend({}, this.options, options);
            this.template = _.template($(ProductDialogTemplate).html());

            this.tourFlag          = this.options.tourFlag;
            this.easySetupFlag     = this.options.easySetupFlag;
            this.cloudInstanceFlag = this.options.cloudInstanceFlag;
        },

        events: {
            'click #cloud-agreement-checkbox' : 'toggleCloudAgreement',
            'click #btnYes'                   : 'yes',
            'click #btnSkip'                  : 'skip'
        },

        show: function () {

            var isCloudInstance = this.cloudInstanceFlag.get('is_cloud_instance');
            var cloud=false;
            if (isCloudInstance.toLowerCase()=="true") {
                cloud=true;
            }
            this.$el.html(this.template({
                isCloudInstance: cloud
            }));

            this.$el.on('hide', function() {
                this.remove();
            }.bind(this));

            this.$el.modal({
              backdrop: 'static',
              keyboard: false
            });

            return this;

        },

        toggleCloudAgreement: function (e) {
            var isChecked = $(e.target).is(':checked');
            $('#btnYes').prop('disabled', !isChecked);
            $('#btnSkip').prop('disabled', !isChecked);
        },

        skip: function (e) {
            e.preventDefault();
            this.$el.modal('hide');
            this.tourFlag.set('visited', true);
            this.tourFlag.save();
            this.remove();
        },

        yes: function (e) {
            e.preventDefault();
            this.$el.modal('hide');

            this.tourFlag.set('visited', true);
            this.tourFlag.save();

            if (this.easySetupFlag.get("visited")) {
                var urlParts = window.location.href.split("/");
                urlParts.pop();
                window.location.href = urlParts.join("/") + "/streams?tour=stream-tour:enterprise";
            } else {
                window.location.href = "?tour=stream-tour:enterprise";
            }

            this.remove();
        }

    });
});
