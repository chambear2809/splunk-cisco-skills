define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "contrib/text!app-js/templates/StreamConfig/FieldsTableRowTemplate.html",
    "app-js/views/StreamConfig/AggregationMethodsView",
    "app-js/views/StreamConfig/ContentExtractionView",
    "app-js/views/ConfirmView",
    'swc-stream/index'
], function(
    $,
    _,
    Backbone,
    FieldsTableRowTemplate,
    AggregationMethodsView,
    ContentExtractionView,
    ConfirmView,
    index
    ) {
    
    const Popdown = index.Popdown;
    return Backbone.View.extend({

        tagName: 'tr',

        initialize: function(options){

            this.options                = _.extend({}, this.options, options);
            this.app                    = this.options.app;
            this.fieldsTableRowTemplate = _.template($(FieldsTableRowTemplate).html());
            this.model                  = this.options.model;
            this.stringTerms            = this.options.stringTerms;
            this.streamModel            = this.options.streamModel;
            this.fieldsCollection       = this.options.fieldsCollection;
            this.idleFieldsCollection   = this.options.idleCollection;

            // row doesn't render b/c self-sorting feature require rendering to be done at the table level
            // this.listenTo(this.model, 'change', function () {
            //     this.render();
            // }.bind(this));

            this.listenTo(this.model, 'destroy', function () {
                this.remove();
            }.bind(this))

            this.app.mediator.subscribe("search-filtered", function (searchString) {
                this._showHideBasedOnRegex(searchString);
            }.bind(this));

        },

         _showHideBasedOnRegex: function (searchString) {

            var self = this;
            var regex = new RegExp(searchString, "i");

            // show if regex matches any of these strings.
            var matchCases = _.flatten([
                self.model.get('name'),
                self.model.get('desc'),
                self.model.get('term')
            ]);

            var regexMatches = _.some(_.map(matchCases, function (str) {
                return regex.test(str);
            }));

            if (regexMatches) {
                self.$el.show();
            } else {
                self.$el.hide();
            }

        },

        events: {
            'click .field-status'               : 'enableDisable',
            'click .agg-type .btn-toggle input' : 'aggTypeChange',
            'click .agg-methods'                : 'editAggregationMethods',
            'click .extract-field'              : 'createNewField',
            'click .edit-extracted-field'       : 'editExtractedField',
            'click .delete-extracted-field'     : 'deleteExtractedField',
        },

        enableDisable: function (e) {
            var fieldEnabled = $(e.currentTarget).is(':checked');
            if (this.model.get('aggregated') && !fieldEnabled) {
                this.model.set('aggType', 'key');
            }
            this.model.set('enabled', fieldEnabled);
        },

        aggTypeChange: function (e) {
            //if user clicks on key
            if ($(e.target).attr('class') === 'key') {
                this.model.set('aggType', 'key');

            //if previous type is key and user clicks on agg
            } else if (this.model.get('aggType') === 'key') {
                var field = this.model.toJSON();
                var category = this.app.terms.get(field.term).get('category');
                var aggType = category === 'numeric' ? ['sum'] : ['mode'];
                this.model.set('aggType', aggType);
            }
        },

        editAggregationMethods: function(e) {

            e.preventDefault();

            var aggregationMethodsView = new AggregationMethodsView({
                model  : this.model,
                field  : this.model.toJSON(),
                terms  : this.app.terms,
                parent : this
            }).show();
        },

        /*==========  Content Extraction  ==========*/

        createNewField: function(e) {

            e.preventDefault();

            var contentExtractionView = new ContentExtractionView({
                app              : this.app,
                model            : this.model,
                streamModel      : this.streamModel,
                originalTerm     : this.model.get('term'),
                stringTerms      : this.stringTerms,
                fieldsCollection : this.fieldsCollection,
                idleCollection   : this.idleFieldsCollection
            }).show();
        },

        editExtractedField: function(e) {

            e.preventDefault();
            var fieldName = this.model.get('name');

            var contentExtractionView = new ContentExtractionView({
                app              : this.app,
                model            : this.model,
                streamModel      : this.streamModel,
                originalTerm     : this.model.get('term'),
                stringTerms      : this.stringTerms,
                fieldName        : fieldName,
                fieldsCollection : this.fieldsCollection,
                idleCollection   : this.idleFieldsCollection
            }).show();
        },

        deleteExtractedField: function(e) {

            var self = this;
            e.preventDefault();

            var fieldName = this.model.get('name');
            var idleModel = this.idleFieldsCollection.findWhere({name: fieldName});

            var confirmView = new ConfirmView({
                model: {text: fieldName},
                action: "delete",
                command: function () {
                    //destroy model for both agg and non-agg field collections
                    self.model.destroy();
                    idleModel.destroy();
                }
            }).show();

        },

        render: function() {

            //backward compatibility for when pre 6.6 streamfwds send aggregated stream data
            if (this.model.get('aggType') === 'sum') {
                this.model.set('aggType', ['sum']);
            }

            this.$el.html(this.fieldsTableRowTemplate({
                field        : this.model.toJSON(),
                stringTerms  : this.stringTerms,
                terms        : this.app.terms,
                stream       : this.streamModel.toJSON()
            }));

            new Popdown({ el: this.$('.field-edit')});

            return this;
        },

        removeSelf: function () {
            // empty the contents of the container DOM element without taking it out of the DOM
            this.$el.empty();
            // clears all callbacks previously bound to the view with delegateEvents method
            // (I would expect stopListening to do the job but it doesn't)
            this.undelegateEvents();
            return this;
        }

    });
});
