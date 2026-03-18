define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "contrib/text!app-js/templates/ForwarderManagement/ShowMoreInfoTemplate.html"
], function(
    $,
    _,
    Backbone,
    ShowMoreInfoTemplate
    ) {
    return Backbone.View.extend({

        className: 'modal',

        initialize: function(options){
            this.options            = _.extend({}, this.options, options);
            this.modalTitle         = this.options.modalTitle;
            this.additionalInfoList = this.options.additionalInfoList;
            this.parentName         = this.options.parentName
            this.template           = _.template($(ShowMoreInfoTemplate).html());
        },

        events:{
            'click #ok':'ok'
        },

        show: function(){

            this.$el.html(this.template({
                modalTitle         : this.modalTitle,
                additionalInfoList : this.additionalInfoList,
                parentName         : this.parentName
            }));

            this.$el.on('hide', function() {
                this.remove();
            }.bind(this));

            this.$el.modal('show');
            return this;

        },

        ok:function(){
            this.$el.modal('hide');
            this.remove();
            return false;
        }

    });
});