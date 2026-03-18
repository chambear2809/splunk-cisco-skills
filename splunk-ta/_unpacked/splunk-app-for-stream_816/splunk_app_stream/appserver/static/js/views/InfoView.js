define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "contrib/text!app-js/templates/InfoDialog.html"
], function(
    $,
    _,
    Backbone,
    InfoDialogTemplate
    ) {
    return Backbone.View.extend({

        className: 'modal',

        initialize: function(options){
            this.options = _.extend({}, this.options, options);
            this.command = this.options.command;
            this.template = _.template($(InfoDialogTemplate).html());
        },

        events:{
            'click .ok':'ok'
        },

        ok:function(){
            this.$el.modal('hide');
            this.remove();
        },

        show: function(){
            this.$el.html(this.template({
                "title": this.options.title, 
                "message": this.options.message
            }));

            this.$el.on('hide', function() {
                this.remove();
            }.bind(this));

            this.$el.modal('show');
        }

    });
});