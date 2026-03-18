define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "contrib/text!app-js/templates/ConfirmDialog.html"
], function(
    $,
    _,
    Backbone,
    ConfirmDialogTemplate
    ) {
    return Backbone.View.extend({

        className: 'modal',

        initialize: function(options){
            this.options = _.extend({}, this.options, options);
            this.command = this.options.command;
            this.template = _.template($(ConfirmDialogTemplate).html());
        },

        events:{
            'click .yes':'yes'
        },

        show: function(){
            this.$el.html(this.template({
                "model"   : this.model,
                "action"  : this.options.action,
                "warning" : this.options.warning || ""
            }));

            this.$el.on('hide', function() {
                this.remove();
            }.bind(this));

            this.$el.modal('show');
            return this;
        },

        yes:function(e){
            e.preventDefault();
            this.command();
            this.$el.modal('hide');
            this.remove();
        }

    });
});