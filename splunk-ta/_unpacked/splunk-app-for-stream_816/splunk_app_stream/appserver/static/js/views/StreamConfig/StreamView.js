define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "contrib/text!app-js/templates/StreamConfig/StreamConfigTemplate.html",
    "app-js/views/ConfirmView",
    "app-js/views/StreamConfig/FieldsTableView",
    "app-js/views/StreamConfig/FiltersTableView",
    "app-js/views/StreamConfig/ExpirationConfigView",
    "app-js/views/SaveView",
    "app-js/collections/Fields",
    "app-js/collections/Comparisons",
    "app-js/models/Field",
    "app-js/models/Extras",
    "app-js/models/Field",
    "app-js/models/Filters",
    "swc-stream/index"
], function(
    $,
    _,
    Backbone,
    StreamConfigTemplate,
    ConfirmView,
    FieldsTableView,
    FiltersTableView,
    ExpirationConfigView,
    SaveView,
    Fields,
    Comparisons,
    Field,
    Extras,
    Field,
    Filters,
    index
    ) {
    
    const SyntheticSelectControl = index.SyntheticSelectControl;
    return Backbone.View.extend({

        initialize: function(options){
            console.log('Stream View created');

            this.options              = _.extend({}, this.options, options);
            this.app                  = this.options.app;
            this.streamConfigTemplate = _.template($(StreamConfigTemplate).html());
            this.termsDict            = this.options.termsDict;

            //create models and collections used by this view.
            //===========================================================
            //stream model
            this.model = this.options.model;
            this.extras = this._createExtrasModel();

            //set default values for aggregation customization
            //-----------------------------------------------------------
            this.timeInterval = this.model.get('aggregated') ? this.model.get('extras').interval : this.extras.defaults.interval;

            //keep track of 2 collections of fields, one for aggregated, one for non-aggregated
            //-----------------------------------------------------------
            var fields = this.model.get('fields');
            if (this.model.get('aggregated')) {
                //if aggregated, set non-agg fields to be the same but w/o agg 'key/sum' fields.
                this.userAggFieldsCollection = (new Fields(fields)).adjustTo('default');
                this.userFieldsCollection = (new Fields(fields)).adjustTo('non_agg');
            } else {
                //if not aggregated, set agg fields to a default.
                this.userAggFieldsCollection = (new Fields(fields)).adjustTo('agg_defaults');
                this.userFieldsCollection = (new Fields(fields)).adjustTo('default');
            }

            //set default values for topX customization
            //-----------------------------------------------------------
            this.topXEnabled = !!this.model.get('extras').topLimit;
            this.topLimit    = this.topXEnabled ? this.model.get('extras').topLimit  : this.extras.defaults.topLimit;
            this.topSortBy   = this.topXEnabled ? this.model.get('extras').topSortBy : this.extras.defaults.topSortBy;

            //Create filters model
            //-----------------------------------------------------------
            this.filters = new Filters();
            this.filters.set('comparisons', new Comparisons(this.model.get('filters').comparisons));
            this.filters.set('matchAllComparisons', this.model.get('filters').matchAllComparisons);

            //other values
            //-----------------------------------------------------------
            this.stringTerms      = this._generateStringTerms(this.termsDict);
            this.topFieldsOptions = this._generateTopFieldsOptions();

            //stateModel to track which tab to show.
            //-----------------------------------------------------------
            this.configPageStateModel = new Backbone.Model({
                //can be either fields, filters, or expiration
                showTab: 'fields',
            });

            //===========================================================

            var self = this;

            //listen for changes to show 'has changes' message.
            //===========================================================
            var listenForChanges = [this.model, this.extras, this.filters, this.userAggFieldsCollection, this.userFieldsCollection];

            for (var i = 0; i < listenForChanges.length; i++) {
                this.listenTo(listenForChanges[i], 'add remove change', function () {
                    self._setHasChanges();
                });
            };

            //listeners for the live count in tabs feature.
            //===========================================================
            this.listenTo(this.userFieldsCollection, 'add change remove', function (model) {
                if (!this.model.get('aggregated')) {
                    $("#enabled-fields-count").html(this.userFieldsCollection.filter(function (field) {
                        return field.get('enabled');
                    }).length);
                }
            }.bind(this));

            this.listenTo(this.userAggFieldsCollection, 'add change remove', function () {
                if (this.model.get('aggregated')) {
                    $("#enabled-fields-count").html(this.userAggFieldsCollection.filter(function (field) {
                        return field.get('enabled');
                    }).length);
                }
            }.bind(this));

            this.listenTo(this.filters, 'add change remove', function () {
                $("#filters-count").html(this.filters.get('comparisons').length);
            }.bind(this))

            //catch 'extras' validation errors and show error messages
            //===========================================================
            this.listenTo(this.extras, 'invalid', function (model, errors) {
                self._showErrors(errors);
            });

            //updates options for Top Fields dropdown whenever agg fields changes
            //===========================================================
            this.listenTo(this.userAggFieldsCollection, 'add change remove', _.debounce(function () {
                self._recheckTopFieldsOptions();
            },100));

        },

        /*============================================
        =            Data Helper Functions           =
        ============================================*/

        // Extras model used for validation and model syncing
        // Sync with streams model prior to saving.
        // Create a new one by copying but w/o defaults
        _createExtrasModel: function () {
            var extras = new Extras();
            extras.clear();
            extras.set(this.model.get('extras'));
            return extras;
        },

        //used to determine which fields content-extraction is allowed on.
        _generateStringTerms: function (terms) {
            var results = $.extend({},terms);
            _.each(results, function(value,key) {
                if (value !== "string")
                    delete results[key];
            });
            return results;
        },

        //Builds the list of options for the criterion which Top Fields uses.
        _generateTopFieldsOptions: function() {
            var terms = this.app.terms;
            var options = ['count'];

            this.userAggFieldsCollection.each(function(field) {
                if (_.isArray(field.get('aggType')) && field.get('enabled')) {
                    if (terms.get(field.get('term')).get('category') === 'numeric') {
                        _.each(field.get('aggType'), function(fn) {
                            if (fn != 'values')
                                options.push(fn + '(' + field.get('name') + ')')
                        });
                    }
                }
            });

            return options;
        },

        //Called any time the drop-down of Top Fields options needs to be changed.
        //Will also set topSortBy to 'count' if the original value becomes invalid.
        _recheckTopFieldsOptions: function() {
            this.topFieldsOptions = this._generateTopFieldsOptions();

            var currentTopSortByTermValid = _(this.topFieldsOptions).contains(this.extras.get('topSortBy'));
            //make sure to set only if field exists, else backend validation will fail.
            var topSortByIsSet = !!this.extras.get('topSortBy');
            if (topSortByIsSet && !currentTopSortByTermValid){
                this.extras.set("topSortBy", "count");
            }

            //set items in the format SyntheticSelectControl expects.
            this.topSortBySelection.setItems(this.topFieldsOptions.map(function(term) {
                return {
                    label: term,
                    value: term
                }
            }));

            this.render();
        },

        /*==============================
        =            Events            =
        ==============================*/

        events: {

            //upper right controls
            'click #save'   : 'updateStream',
            'click #delete' : 'deleteStream',
            'click #clone'  : 'cloneStream',

            //enable/disable/stats-only
            'click #stream-enabled'    : 'onStreamEnable',
            'click #stream-disabled'   : 'onStreamDisable',
            'click #stream-stats-only' : 'onStreamStatsOnly',

            //aggregation
            'click #aggregation-on'  : 'onAggregationEnable',
            'click #aggregation-off' : 'onAggregationDisable',
            'keyup .time-interval'   : 'onTimeIntervalChange',

            //topX
            'click #topx-on'       : 'onTopXEnable',
            'click #topx-off'      : 'onTopXDisable',
            'keyup #topLimitInput' : 'onTopLimitChange',

            //table tabs
            'click #fields-tab'     : 'onFieldsTab',
            'click #filters-tab'    : 'onFiltersTab',
            'click #expiration-tab' : 'onExpirationTab'

        },

        /*=============================================
        =            Table Header Controls            =
        =============================================*/

        /*==========  Enable/Disable/Estimate  ==========*/

        onStreamEnable: function(e) {
            $("#stream-enabled").addClass('active');
            $("#stream-disabled").removeClass('active');
            $("#stream-stats-only").removeClass('active');
            this.model.set('enabled', true);
            this.model.set('statsOnly', false);
        },

        onStreamDisable: function(e) {
            $("#stream-enabled").removeClass('active');
            $("#stream-disabled").addClass('active');
            $("#stream-stats-only").removeClass('active');
            this.model.set('enabled', false);
            this.model.set('statsOnly', false);
        },

        onStreamStatsOnly: function(e) {
            $("#stream-enabled").removeClass('active');
            $("#stream-disabled").removeClass('active');
            $("#stream-stats-only").addClass('active');
            this.model.set('enabled', true);
            this.model.set('statsOnly', true);
        },

        /*==========  Aggregation  ==========*/

        onAggregationEnable: function(e) {
            if (!this.model.get('aggregated')) {
                this.extras.set('interval', this.timeInterval);
                this.model.set('aggregated', true);
                this.model.set('streamType', 'agg_event');
                this.render();
            }
        },

        onAggregationDisable: function(e) {
            if (this.model.get('aggregated')) {
                this.timeInterval = this.extras.get('interval');
                this.extras.unset('interval');
                this.model.set('aggregated', false);
                this.model.set('streamType', 'event');
                this.render();
            }
        },

        onTimeIntervalChange: function(e) {
            var $aggInterval = $('.time-interval');
            $aggInterval.removeClass("error");
            this.extras.set('interval', Number($aggInterval.val()) || "NaN");
        },

        /*==========  Top X  ==========*/

        onTopXEnable: function(e) {
            if (!this.topXEnabled) {
                this.extras.set('topLimit', this.topLimit);
                this.extras.set('topSortBy', this.topSortBy);
                this.topXEnabled = true;
                this.render();
            }
        },

        onTopXDisable: function(e) {
            if (this.topXEnabled) {
                this.topLimit = this.extras.get('topLimit');
                this.topSortBy = this.extras.get('topSortBy');
                this.extras.unset("topLimit");
                this.extras.unset("topSortBy");
                this.topXEnabled = false;
                this.render();
            }
        },

        onTopLimitChange: function(e) {
            var $topLimit = $('#topLimitInput');
            $topLimit.removeClass("error");
            var topLimit = Number($topLimit.val()) || "NaN";
            if (topLimit) {
                this.extras.set('topLimit', topLimit);
            } else {
                this.extras.unset('topLimit');
            }
        },

        /*==========  Table Tabs  ==========*/

        onFieldsTab: function (e) {
            e.preventDefault();
            this.configPageStateModel.set('showTab', 'fields');
            this.render();
        },

        onFiltersTab: function (e) {
            e.preventDefault();
            this.configPageStateModel.set('showTab', 'filters');
            this.render();
        },

        onExpirationTab: function (e) {
            e.preventDefault();
            this.configPageStateModel.set('showTab', 'expiration');
            this.render();
        },

        /*==========  Utility  ==========*/

        _setHasChanges: function() {
            var self = this;
            //only set this once
            if (!this.app.pageIsDirty){
                this.app.pageIsDirty = true;
                this.app.exitMessage = "Are you sure you want to leave this page? You will lose all unsaved changes.";
            }
            this._showHasChanges();
        },

        _showHasChanges: function () {
            if (this.app.pageIsDirty){
                $("#has-changes").show();
                $("#save").removeAttr('disabled');
            }
        },

        _showErrors: function(errors) {

            var alertMessage = "";
            for (var i = 0; i < errors.length; i++) {
                alertMessage += "\n\u2022" + errors[i].message;
                if (errors[i].name === "interval") {
                    $('.time-interval').addClass('error');
                }
                if (errors[i].name === "topLimit"){
                    $('#topLimitInput').addClass('error');
                }
            };
            alert(alertMessage);

        },

        cloneStream: function(e) {

            e.preventDefault();
            var stream = this.model;
            var fieldsCollection = this.model.get('aggregated') ? this.userAggFieldsCollection : this.userFieldsCollection;

            if (this.app.pageIsDirty) {
                stream.set('extras', this.extras.toJSON());
                stream.set('fields', fieldsCollection.toJSON());
                stream.set('filters', this.filters.toJSON());
            }

            this.app.mediator.publish("view:add-stream-dialog", stream, this.app.pageIsDirty);
        },

        render: function() {

            var self = this;
            var fieldsCollection = this.model.get('aggregated') ? this.userAggFieldsCollection : this.userFieldsCollection;

            var streamType = 'metadata';
            var filtersName = 'filters';
            if (this.model.get('isPacketStream')) {
                streamType = 'packet';
                filtersName = 'targets';
            } else if (this.model.get('expirationDate')) {
                streamType = 'ephemeral';
            }

            this.$el.empty();

            /*==========  Append Basic Controls  ==========*/
            /*================================================================================*/

            var output = this.streamConfigTemplate({
                stream                : this.model.toJSON(),
                streamType            : streamType,
                streamExtras          : this.extras.toJSON(),
                fieldsCollection      : fieldsCollection,
                comparisonsCollection : this.filters.get('comparisons'),
                configPageStateModel  : this.configPageStateModel.toJSON(),
                filtersName           : filtersName,
                pageIsDirty           : this.app.pageIsDirty
            });
            this.$el.append(output);

            /*==========  Append Index Selection View  ==========*/
            /*================================================================================*/

            if (this.indexSelection) { this.indexSelection.remove(); }

            this.indexSelection = new SyntheticSelectControl({
                toggleClassName : 'btn',
                menuWidth       : 'narrow',
                model           : this.model,
                modelAttribute  : "index",
                items           : this.app.splunkIndexItems
            });
            this.$("#indexSelectionWrapper").append(this.indexSelection.render().$el);

            /*==========  Append topSortBy Selection View  ==========*/
            /*================================================================================*/

            if (this.topSortBySelection) { this.topSortBySelection.remove(); }

            var topFieldsOptions = _(this.topFieldsOptions).map(function(terms){ return {label:terms, value:terms}; });
            this.topSortBySelection = new SyntheticSelectControl({
                toggleClassName : 'btn topSortBySelection',
                menuWidth       : 'narrow',
                model           : this.extras,
                modelAttribute  : 'topSortBy',
                items           : topFieldsOptions
            });
            this.$("#topx-controls").append(this.topSortBySelection.render().$el);

            if (!this.extras.get('topLimit')) {
                this.topSortBySelection.disable();
            }

            /*==========  Append Fields Table View   ==========*/
            /*================================================================================*/

            if (this.fieldsTableView) { this.fieldsTableView.remove() };

            //Retrieve the fields collection (agg/non-agg) that is currently not being rendered
            var idleFieldsCollection = this.model.get('aggregated') ? this.userFieldsCollection : this.userAggFieldsCollection;

            this.fieldsTableView =  new FieldsTableView({
                collection     : fieldsCollection,
                idleCollection : idleFieldsCollection,
                app            : this.app,
                stringTerms    : this.stringTerms,
                streamModel    : this.model
            });
            this.$('#fields-view').append(this.fieldsTableView.render().$el)

            /*==========  Append Filters Table View   ==========*/
            /*================================================================================*/

            if (this.filtersTableView) { this.filtersTableView.remove() };

            this.filtersTableView =  new FiltersTableView({
                app                  : this.app,
                streamModel          : this.model,
                filtersModel         : this.filters,
                fieldsCollection     : fieldsCollection,
                configPageStateModel : this.configPageStateModel
            });
            this.$('#filters-view').append(this.filtersTableView.render().$el)

            /*==========  Append Expiration Conifg View   ==========*/
            /*================================================================================*/

            if (this.model.get('isPacketStream')) {
                if (this.expirationConfigView) { this.expirationConfigView.remove() };

                this.expirationConfigView =  new ExpirationConfigView({
                    app                  : this.app,
                    streamModel          : this.model
                });
                this.$('#expiration-view').append(this.expirationConfigView.render().$el)
            }

            return this;
        },

        /*==========================================
        =            Model Manipulation            =
        ==========================================*/

        deleteStream: function(e) {
            var self = this;
            e.preventDefault();
            var id = self.model.get('id');

            var confirmView = new ConfirmView({
                model: {text: self.model.get('id') + ":" + self.model.get('name')},
                action: "delete",
                command: function() {
                    self.model.destroy({
                        success: function(e){
                            self.app.router.navigate("metadata",{trigger:true});
                        },
                        error: function(e){
                            console.log("Error deleting stream");
                            alert("Error deleting stream");
                        }
                    });
                }
            }).show();
        },

        //remove the fields that have to do with aggregation
        //Under extras: interval, topLimit, topSortBy
        //Otherwise backend validation fails.
        _removeAggregatedFields: function (args) {
            this.extras.unset("interval");
            this.extras.unset("topLimit");
            this.extras.unset("topSortBy");
            this.topXEnabled = false;
        },

        validatePacketStream: function () {
            var bytes = this.model.get("maxBytesCaptured");
            var flows = this.model.get("maxFlowsCaptured");
            var packets = this.model.get("maxPacketsCaptured");
            var absTime = this.model.get("absoluteLatestTime");
            var elaTime = this.model.get("maxElapsedTime");

            if (bytes !== undefined && !bytes.toString().match(/^[1-9]\d*$/)) {
                return "Expiration by bytes captured must be a postive integer";
            }
            if (flows !== undefined && !flows.toString().match(/^[1-9]\d*$/)) {
                return "Expiration by flows captured must be a postive integer";
            }
            if (packets !== undefined && !packets.toString().match(/^[1-9]\d*$/)) {
                return "Expiration by packets captured must be a postive integer";
            }
            if (elaTime !== undefined && !elaTime.toString().match(/^[1-9]\d*$/)) {
                return "Expiration by elapsed time must be a postive integer";
            }
            if (absTime !== undefined && !absTime.toString().match(/^[1-9]\d*$/)) {
                return "Expiration by absolute time must be a valid datetime";
            }
            if (absTime !== undefined && absTime <= (new Date()).getTime() / 1000) {
                return "Expiration by absolute time must be set to a future datetime";
            }
            if (!bytes && !flows && !packets && !absTime && !elaTime) {
                return "At least one expiration condition must be set";
            }
            if (this.model.get('filters').comparisons.length === 0) {
                return "At least one target must be set";
            }
            return;
        },

        updateStream: _.debounce(function(e) {

            e.preventDefault();
            var self = this;
            var stream = this.model;
            var fieldsCollection = this.model.get('aggregated') ? this.userAggFieldsCollection : this.userFieldsCollection;

            //remove these fields to pass backend validation
            //---------------------------------------------
            if (!this.model.get('aggregated')) {
                this._removeAggregatedFields();
            }

            //sync stream model with extras model
            //---------------------------------------------
            this.model.set('extras', this.extras.toJSON());

            //sync fields collection to main stream model
            //---------------------------------------------
            this.model.set('fields', fieldsCollection.toJSON());

            //sync filters model to main stream model
            //---------------------------------------------
            this.model.set('filters', this.filters.toJSON());

            if (this.model.get('isPacketStream')) {
                var errorMsg = this.validatePacketStream();
                if (!!errorMsg) {
                    alert(errorMsg);
                    return;
                }
                if (this.model.get('enabled')) {
                    var epochTime = parseInt((new Date).getTime() / 1000);
                    this.model.set('latestEnableTime', epochTime);
                }
            }

            //Update stream model only if 'extras' model is valid.
            if (this.extras.isValid()) {

                var saveView = new SaveView();
                saveView.show();

                stream.save(null, {
                    success: function(e){
                        //set false as changes have been saved
                        self.app.pageIsDirty = false;
                        self.render();
                        saveView.showSaved("Successfully Saved! ✓");
                    },
                    error: function(model, response){
                        console.log("Error saving stream", model, response, arguments);
                        saveView.showSaved("Error saving stream: " + response.responseJSON.error);
                    }
                });
                return false;

            } else {
                console.log("'Extras' model validation failed.");
            }
        },200),

        removeSelf: function () {
            console.log("Removing StreamView");
            this.$el.empty();
            this.undelegateEvents();
            return this;
        }

    });
});
