define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "contrib/text!app-js/templates/StreamConfig/AggregationMethodsTemplate.html",
    "app-js/models/Field"
], function(
    $,
    _,
    Backbone,
    AggregationMethodsTemplate,
    Field
    ) {
    return Backbone.View.extend({

        className: 'modal',

        initialize: function (options) {

            this.options  = _.extend({}, this.options, options);
            this.template = _.template($(AggregationMethodsTemplate).html());
            this.model    = this.options.model;
            this.field    = this.options.field;
            this.terms    = this.options.terms;
            this.parent   = this.options.parent;

            //a list of aggregation methods
            this.aggType  = this.options.field.aggType.slice(0);
        },

        events: {
            'click .agg-checkbox' : 'toggleAggType',
            'click .save'         : 'save',
            'click .cancel'       : 'cancel'
        },

        toggleAggType: function (e) {
            //the aggregation method clicked on
            var aggMethod = $(e.target)[0].id;

            if ($(e.target).is(':checked')) {
                this.aggType.push(aggMethod);
            } else {
                var index = this.aggType.indexOf(aggMethod);
                this.aggType.splice(index, 1);
            }
        },

        cancel: function () {
            this.remove();
        },

        show: function () {
            var isNumeric = this.terms.get(this.field.term).get('category') === 'numeric';

            this.$el.html(this.template({
                field     : this.field,
                isNumeric : isNumeric
            }));

            this.$el.on('hide', function() {
                this.remove();
            }.bind(this));

            this.$el.modal('show');
            return this;

        },

        save: function (e) {
            e.preventDefault();

            if (this.aggType.length === 0) {
                alert('Please select at least one aggregation method');
            } else {
                if ($(this.parent.el).hasClass('step-wizard-step')) {
                    //saving from create new stream wizard fields step
                    this.field.aggType = this.aggType;
                    this.parent.renderTable();
                } else {
                    //saving from config streams page
                    this.model.set('aggType', this.aggType);
                }
                this.$el.modal('hide');
                this.remove();
            }
        }

    });
});
