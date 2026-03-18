define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "contrib/text!app-js/templates/SaveDialog.html"
], function(
    $,
    _,
    Backbone,
    SaveDialogTemplate
    ) {
    return Backbone.View.extend({

        className: 'modal',

        initialize: function(options){
            this.options = _.extend({}, this.options, options);
            this.template = _.template($(SaveDialogTemplate).html());
        },

        events:{
            'click #done':'done'
        },

        show: function(){
            this.$el.html(this.template());
            this.$el.modal({ backdrop: 'static' });

            this.$el.on('hide', function() {
                this.remove();
            })

            this.$el.modal('show');
        },

        showSaved: function (msg) {
            $('.modal-title').html("Saved");
            $('#done').css({opacity:1});
            $("#save-message").html(msg);
        },

        done:function(e){
            e.preventDefault();
            this.$el.modal('hide');
            this.remove();
        }

    });
});