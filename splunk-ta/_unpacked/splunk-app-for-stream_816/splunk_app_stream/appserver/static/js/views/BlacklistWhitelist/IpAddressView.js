define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone"
], function ($, _, Backbone) {
    return Backbone.View.extend({
        className: 'list-item',
        template: _.template('<span><%- value %></span> <span class="destroy">x</span>'),
        events: {
            'click': 'onItemClick',
            'click .destroy': 'onDestroyClick'
        },

        render: function() {
            this.$el.html(this.template(this.model.toJSON()));
        },

        onItemClick: function () {
            this.trigger('click');
        },

        onDestroyClick: function () {
            this.trigger('destroy');
        }

    });
});