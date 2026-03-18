define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "contrib/text!app-js/templates/EphemeralStreams/EphemeralStreamsTemplate.html",
    "contrib/text!app-js/templates/EphemeralStreams/EphemeralStreamsTableTemplate.html",
    "app-js/collections/Streams",
    'swc-stream/index',
    "app-js/contrib/jquery.tablesorter.min",
    "app-js/views/EphemeralStreams/DatepickerView",
    "app-js/contrib/moment",
    "app-js/contrib/moment-timezone-with-data"
], function(
    $,
    _,
    Backbone,
    EphemeralStreamsTemplate,
    EphemeralStreamsTableTemplate,
    Streams,
    index,
    Tablesorter,
    DatepickerView,
    moment,
    Moment
    ) {

    const Popdown = index.Popdown;
    return Backbone.View.extend({

        initialize: function(options){

            console.log('Ephemeral Streams List View created');

            this.options         = _.extend({}, this.options, options);
            this.app             = this.options.app;
            this.streamGroups    = this.options.streamGroups;
            this.template        = _.template($(EphemeralStreamsTemplate).html());
            this.collection      = this.options.collection,
            this.ephemCategory   = this.options.ephemCategory
            this.timezone        = this.options.timezone;
            this.selectedStreams = [];

        },

        events: {
            'click .more-info-td'            : 'toggleExtendedTable',
            'keyup #ephem-search'            : 'showMatchingStreams',
            'click a.clear'                  : 'resetSearch',
            'click .ephemeral-stream-select' : 'selectStreams',

            'click #enableGroup'  : 'enableGroup',
            'click #disableGroup' : 'disableGroup',
            'click #editEndTime'  : 'editEndTime',

            'click .ephemeral-streams-select-all' : 'bulkSelectStreams',
            'click #bulkEnableGroup'              : 'bulkEnableGroup',
            'click #bulkDisableGroup'             : 'bulkDisableGroup',
            'click #bulkDeleteGroup'              : 'bulkDeleteGroup'
        },

        editEndTime: function(e) {

            e.preventDefault();
            var groupId = $(e.target).closest('tr').data('id');

            var thisGroup = _.find(this.options.streamGroups, function(each) {
                return (each.name === groupId);
            })

            var datePickerView = new DatepickerView({
                app           : this.app,
                groupId       : groupId,
                startTime     : thisGroup.earliestTime,
                endTime       : thisGroup.latestTime,
                countdown     : thisGroup.timeRemaining,
                timezone      : this.timezone
            }).show();

        },

        triggerAddStreamDialogEvent: function() {
            this.app.mediator.publish("view:add-stream-dialog");
        },

        toggleExtendedTable: function(e){
            $(e.target).closest("tr").find('.stream-groups').toggle();

            var chevron = $(e.target).find('span.more-info-toggle');
            chevron.toggleClass("icon-chevron-right");
            chevron.toggleClass("icon-chevron-down");
        },

        selectStreams: function(e) {
            var name = $(e.target).closest('tr').data('id');
            if ($(e.target).is(":checked")) {
                this.selectedStreams.push(name);
            } else {
                var index = this.selectedStreams.indexOf(name);
                this.selectedStreams.splice(index, 1);
            }
            this._checkIfAllStreamsSelected();
        },

        bulkSelectStreams: function(e) {
            var self = this;
            if ($(e.target).is(":checked")) {
                $('.ephemeral-stream-select').each(function() {
                    if (!this.checked) {
                        this.checked = true;
                        var name = $(this).closest('tr').data('id');
                        self.selectedStreams.push(name);
                    }
                });
            } else {
                $('.ephemeral-stream-select').each(function() {
                    if (this.checked) {
                        this.checked = false;
                        var name = $(this).closest('tr').data('id');
                        var index = self.selectedStreams.indexOf(name);
                        self.selectedStreams.splice(index, 1);
                    }
                });
            }
        },

        getSelectedStreams: function() {
            var self = this;
            var streams = [];
            $('.ephemeral-stream-select:checked').each(function() {
                var groupId = $(this).closest('tr').data('id');
                var filteredStreams = self.collection.filter(function(each){
                    var isEphemeral = "expirationDate" in each.attributes;
                    var isInCategory = groupId === each.attributes.category;
                    return isEphemeral && isInCategory;
                });
                streams = streams.concat(filteredStreams);
            });
            return streams;
        },

        bulkEnableGroup: function(e){
            e.preventDefault();
            var streams = this.getSelectedStreams();
            if (streams.length > 0) {
                this.app.mediator.publish("view:bulk-enable-streams-dialog", {
                    streams: streams,
                    location: Backbone.history.fragment
                });
            } else {
                this.app.mediator.publish("view:info-dialog", "No selection made!", "Please select a stream");
            }
        },

        bulkDisableGroup: function(e){
            e.preventDefault();
            var streams = this.getSelectedStreams();
            if (streams.length > 0) {
                this.app.mediator.publish("view:bulk-disable-streams-dialog", {
                    streams: streams,
                    location: Backbone.history.fragment
                });
            } else {
                this.app.mediator.publish("view:info-dialog", "No selection made!", "Please select a stream");
            }
        },

        bulkDeleteGroup: function(e){
            e.preventDefault();
            var streams = this.getSelectedStreams();
            if (streams.length > 0) {
                this.app.mediator.publish("view:bulk-delete-streams-dialog", {
                    streams: streams,
                    location: Backbone.history.fragment
                });
            } else {
                this.app.mediator.publish("view:info-dialog", "No selection made!", "Please select a stream");
            }
        },

        enableGroup: function(e){

            var self = this;
            e.preventDefault();
            var groupId = $(e.target).closest('tr').data('id');

            var filteredStreams = self.collection.filter(function(each){
                var isEphemeral = "expirationDate" in each.attributes;
                var isInCategory = groupId === each.attributes.category;
                return isEphemeral && isInCategory;
            })

            this.app.mediator.publish("view:bulk-enable-streams-dialog", {
                streams: filteredStreams,
                location: Backbone.history.fragment
            });

        },

        disableGroup: function(e){

            var self = this;
            e.preventDefault();
            var groupId = $(e.target).closest('tr').data('id');

            var filteredStreams = self.collection.filter(function(each){
                var isEphemeral = "expirationDate" in each.attributes;
                var isInCategory = groupId === each.attributes.category;
                return isEphemeral && isInCategory;
            })

            this.app.mediator.publish("view:bulk-disable-streams-dialog", {
                streams: filteredStreams,
                location: Backbone.history.fragment
            });

        },

        resetSearch: function(e) {
            e.preventDefault();
            $(this.el).find('.stream-search input').val('');
            this.render();
        },

        showMatchingStreams: function(e) {
            e.preventDefault();
            this.renderTable();
        },

        render: function(){
            var self = this;
            var searchString = $(this.el).find('.stream-search input').val();

            var output = self.template({
                searchString: searchString
            });

            this.$el.empty();
            self.$el.append(output);

            self.renderTable();

            /*==========  Popdown  ==========*/
            this.bulkEditPopdown = new Popdown({
                el: this.$('.ephemeral-bulk-edit')
            });
            $(".ephemeral-stream-edit").each(function(index, item) {
                new Popdown({ el: $(item) })
            });
            /*==========  Tablesorter  ==========*/
            $.tablesorter.addParser({
                   // set a unique id
                   id: 'countdown',
                   is: function(s) {
                       // return false so this parser is not auto detected
                       return false;
                   },
                   format: function(s) {
                       var numbers = s.split(" ");
                       var days    = parseInt( numbers[0].slice(0,numbers[0].length-1) );
                       var hours   = parseInt( numbers[1].slice(0,numbers[1].length-1) );
                       var minutes = parseInt( numbers[2].slice(0,numbers[2].length-1) );
                       return days * 24 * 60 + hours * 60 + minutes;
                   },
                   // set type, either numeric or text
                   type: 'numeric'
            });
            $("#ephemeral-streams-table").tablesorter({
                headers:{
                    0: { sorter: false },
                    1: { sorter: false },
                    7: { sorter: "countdown"},
                    9: { sorter: false }
                }
            });

            return self;
        },

        renderTable: function(){

            var self = this;

            var tableTemplate  = _.template($(EphemeralStreamsTableTemplate).html());
            var searchString = $(this.el).find('#ephem-search').val();

            var formattedGroups = jQuery.extend(true, [], self.streamGroups);

            _.each(formattedGroups, function(each){
                each.earliestTime = formatTime(each.earliestTime, self.timezone);
                each.latestTime = formatTime(each.latestTime, self.timezone);
            });

            var output = tableTemplate({
                streamGroups: formattedGroups,
                searchString: searchString
            });

            $("#ephemeral-streams-table").empty();
            $("#ephemeral-streams-table").append(output);

            $('.ephemeral-stream-select').each(function() {
                var name = $(this).closest('tr').data('id');
                if (_.contains(self.selectedStreams, name)) {
                    this.checked = true;
                }
            });

            function formatTime(utcTime, timezone){
                Moment.locale(_i18n_locale.locale_name);
                if (timezone)
                    return Moment(utcTime).tz(timezone).format("LLL");
                else
                    return Moment(utcTime).format("LLL");
            }

            this._checkIfAllStreamsSelected();
        },

        _checkIfAllStreamsSelected: function() {
            //Check if all visible streams are selected
            var visibleStreams = $('.ephemeral-stream-select:visible');
            var allChecked = _.every(visibleStreams, function(s) { return s.checked; });
            $('.ephemeral-streams-select-all').prop('checked', allChecked && visibleStreams.length);
        },

        removeSelf: function () {
            console.log("Removing StreamListView");
            // empty the contents of the container DOM element without taking it out of the DOM

            this.unbind();

            this.$el.empty();
            // clears all callbacks previously bound to the view with delegateEvents method
            // (I would expect stopListening to do the job but it doesn't)
            this.undelegateEvents();


            return this;
        }

    });
});
