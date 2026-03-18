define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "contrib/text!app-js/templates/RegularStreams/SingleFilterEditorTemplate.html",
    "swc-stream/index"
], function(
    $,
    _,
    Backbone,
    SingleFilterEditorTemplate,
    index
    ) {

    const TextControl = index.TextControl;
    const SyntheticRadioControl = index.SyntheticRadioControl;
    const SyntheticSelectControl = index.SyntheticSelectControl;

    return Backbone.View.extend({

        className: 'modal',

        initialize: function(options) {
            this.options  = _.extend({}, this.options, options);
            this.template = _.template($(SingleFilterEditorTemplate).html());
            this.fields   = this.options.fields;
            this.filters  = this.options.filters;
            this.filter   = this.options.filter;
            this.name     = this.options.name;
            this.app      = this.options.app;
        },

        events: {
            'click .save'  : 'save',
            'click .cancel': 'cancel'
        },

        onFieldChanged: function(newTerm) {
            this.populateComparisonSelectControl(newTerm);
            this.comparisonSelectControl.setValue('is-defined');
        },

        populateComparisonSelectControl: function(newTerm) {
            var compItems = [];
            var newTermCategory = this.app.terms.get(newTerm).get('category');

            this.app.comparisonTypes.each(function(type) {
                var typeIsCompatibleWithNewTerm = type.get('categories').indexOf(newTermCategory) != -1;

                if (typeIsCompatibleWithNewTerm)
                    compItems.push({ label: type.get('description'), value: type.get('id') });
            });
            this.comparisonSelectControl.setItems(compItems);
        },

        onComparisonTypeChanged: function(comparisonType, oldComparisonType) {
            this.enableOrDisableValueInput(comparisonType);
        },

        enableOrDisableValueInput: function(comparisonType) {
            var arity = this.app.comparisonTypes.get(comparisonType).get('arity');

            if (arity == 1) {
                this.valueTextControl.disable();
                this.valueTextControl.clear();
            } else {
                this.valueTextControl.enable();
            }
        },

        show: function() {
            var self = this;

            this.$el.html(this.template({
                filter : self.filter,
                name   : this.name
            }));

            var fieldItems = _.map(this.fields, function(f) { return { label: f.name, value: f.term } });
            var selectedFieldTerm      = (self.filter && self.filter.term)           || fieldItems[0].value;
            var selectedComparisonType = (self.filter && self.filter.type)           || 'is-defined';
            var valueToCompare         = (self.filter && self.filter.value)          || '';
            var selectedMatchMode      = (self.filter && self.filter.matchAllValues) || false;

            // Note: We're including disabled fields, since they're currently allowed.
            // TODO: By sorting, we're intermixing enabled and disabled fields, but possibly we might
            // want to leave the enabled fields first, or indicate their status in some way.
            this.fieldSelectControl = new SyntheticSelectControl({
                toggleClassName: 'btn',
                menuWidth: 'narrow',
                items: _.sortBy(fieldItems, 'label')
            });
            this.fieldSelectControl.setValue(selectedFieldTerm);
            this.fieldSelectControl.parent = self;
            this.fieldSelectControl.on('change', self.onFieldChanged, self);
            $(self.el).find('.field-select').append(this.fieldSelectControl.render().el);

            this.comparisonSelectControl = new SyntheticSelectControl({
                toggleClassName: 'btn',
                menuWidth: 'narrow',
                items: []
            });
            this.populateComparisonSelectControl(selectedFieldTerm);
            this.comparisonSelectControl.setValue(selectedComparisonType);
            this.comparisonSelectControl.parent = self;
            this.comparisonSelectControl.on('change', self.onComparisonTypeChanged, self);
            $(self.el).find('.comparison-select').append(this.comparisonSelectControl.render().el);

            this.valueTextControl = new TextControl({
                //inputClassName: 'btn'
            });
            $(self.el).find('.value-to-compare-input').append(this.valueTextControl.render().el);
            this.enableOrDisableValueInput(selectedComparisonType);
            this.valueTextControl.setValue(valueToCompare);

            this.matchAllValuesToggle = new SyntheticRadioControl({
                //buttonClassName: 'btn-small',
                items: [
                    { label: "Any", value: false },
                    { label: "All", value: true }
                ]
            });
            $(self.el).find('.match-all-values').append(this.matchAllValuesToggle.render().el);
            this.matchAllValuesToggle.setValue(selectedMatchMode);

            this.$el.on('hide', function() {
                self.remove();
            });

            this.$el.modal('show');

        },

        save: function(e) {
            // If a filter was provided, update it, otherwise create a new one and add it.
            if (this.filter) {
                this.filter.term = this.fieldSelectControl.getValue();
                this.filter.type = this.comparisonSelectControl.getValue();
                this.filter.value = this.valueTextControl.getValue();
                this.filter.matchAllValues = this.matchAllValuesToggle.getValue();
            } else {
                this.filters.comparisons.push({
                    term: this.fieldSelectControl.getValue(),
                    type: this.comparisonSelectControl.getValue(),
                    value: this.valueTextControl.getValue(),
                    matchAllValues: this.matchAllValuesToggle.getValue()
                });
            }

            e.preventDefault();

            // TODO: Add validation?  E.g., for numeric terms, could check that the value is numeric, but
            // we don't currently do this in the Stream Config page.

            this.$el.modal('hide');
            this.remove();
            this.app.mediator.publish("event:filter-count-changed", this.filters.comparisons.length);
        },

        cancel: function() {
            this.remove();
        }

    });
});
