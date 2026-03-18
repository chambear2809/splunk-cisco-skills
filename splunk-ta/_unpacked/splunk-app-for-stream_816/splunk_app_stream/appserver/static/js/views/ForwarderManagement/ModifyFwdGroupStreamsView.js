define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "contrib/text!app-js/templates/ForwarderManagement/ModifyFwdGroupStreamsTemplate.html",
    "app-js/collections/ForwarderGroups",
    "app-js/contrib/jquery.tablesorter.min"

], function(
    $,
    _,
    Backbone,
    ModifyFwdGroupStreamsTemplate,
    ForwarderGroups,
    Tablesorter

    ) {
    return Backbone.View.extend({

        className: 'modal xxl-modal',

        initialize: function(options){
            this.template            = _.template($(ModifyFwdGroupStreamsTemplate).html());
            this.streamsCollection   = options.streamsCollection;
            this.fwdGroupModel       = options.fwdGroupModel;
            this.fwdGroupsCollection = options.fwdGroupsCollection;

            //wizard options
            this.wizardController    = options.wizardController;
            this.isWizard            = !!(options.wizardController);

            this.fwdGroupAppendedStreams = this.createAppendedStreams();
        },

        events: {
            'click .finish'                              : 'finish',
            'click .save'                                : 'save',
            'click .back'                                : 'back',
            'click #modify-fwd-streams-search a.clear'   : "resetSearch",
            'click .cancel'                              : 'cancel',
            'click .stream-select'                       : 'adjustSelectedCount',
            'click #all-selected-toggle'                 : 'toggleSelected',
            'keyup #modify-fwd-streams-input'            : 'filterTable',
            'click #modify-fwd-streams-table .check-all' : 'checkAll'
        },

        adjustSelectedCount: function () {
            var numSelected = this.getSelectedStreams().length;
            $("#selected-count").html(numSelected);
        },

        toggleSelected: function (e) {
            var btnGroup = e.target.parentElement;

            if (! $(e.target).hasClass('active'))
                $(btnGroup).find('.btn').toggleClass('active');

            if ($(e.target).val() === "selected") {
                //hide non-selected
                $('.stream-select:not(:checked)').parents(".mod-fwd-group-stream").hide();
            } else {
                //show all
                $('.stream-select').parents(".mod-fwd-group-stream").show();
            }
        },

        //create streams with additional field "fwdGroupsPresentIn"
        //possible to delegate this to backend if necessary.
        createAppendedStreams: function () {

            var self            = this;
            var fwdGroupStreams = this.fwdGroupModel.get('streams');
            var appendedStreams = this.streamsCollection.sortByContains(fwdGroupStreams);

            _.each(appendedStreams, function (eachStreamObj) {
                var fwdGroupsPresentIn = _.chain(self.fwdGroupsCollection.toJSON())
                                            .filter(function (eachGroup) {
                                                return _.contains(eachGroup.streams, eachStreamObj.id);
                                            })
                                            .map(function (eachGroup) {
                                                return eachGroup.id;
                                            }).value();
                eachStreamObj.fwdGroupsPresentIn = fwdGroupsPresentIn;
            });
            return appendedStreams;
        },

        resetSearch: function () {
            $('#modify-fwd-streams-input').val('');
            this.filterTable();
        },

        filterTable: function (e) {

            var searchString = $('#modify-fwd-streams-input').val();
            var regex        = new RegExp(searchString, "i");

            for (var i = 0; i < this.fwdGroupAppendedStreams.length; i++) {

                var streamId           = this.fwdGroupAppendedStreams[i].id;
                var desc               = this.fwdGroupAppendedStreams[i].name;
                var fwdGroupsPresentIn = this.fwdGroupAppendedStreams[i].fwdGroupsPresentIn;
                var selector           = "tr.mod-fwd-group-stream[data-id='" + streamId + "']";
                var attributesToTest   = _.flatten([streamId, desc, fwdGroupsPresentIn]);

                var inAttributes =  _.some(attributesToTest, function (eachAttr) {
                                        return regex.test(eachAttr);
                                    })

                if (inAttributes) {
                    $(selector).show();
                } else {
                    $(selector).hide();
                }

            };

        },

        checkAll: function (e) {
            if ($(e.target).is(":checked")) {
                $('.stream-select:visible').each(function() {
                    this.checked = true;
                });
            } else {
                $('.stream-select:visible').each(function() {
                    this.checked = false;
                });
            }
            this.adjustSelectedCount();
        },

        getSelectedStreams: function () {
            var self    = this;
            var streams = [];

            $('.stream-select:checked').each(function() {
                var streamId = $(this).closest('tr').data('id');
                var stream   = self.streamsCollection.get(streamId);
                streams.push(stream);
            });

            return streams;
        },

        cancel: function() {
            this.remove();
        },

        show: function(){

            this.$el.html(this.template({
                streams         : this.fwdGroupAppendedStreams,
                fwdGroup        : this.fwdGroupModel.toJSON(),
                fwdGroupStreams : this.fwdGroupModel.get('streams') || [],
                isWizard        : this.isWizard
            }));

            this.$el.on('hide', function() {
                this.remove();
            }.bind(this))

            $("#modify-fwd-streams-table").tablesorter({
                headers: {
                    0: {sorter: false}
                }
            });

            this.$el.modal('show');
            return this;

        },

        back: function () {

            var selectedStreamModels = this.getSelectedStreams();
            var selectedStreams      = _.map(selectedStreamModels, function (eachModel) {
                return eachModel.get('id');
            })

            this.$el.modal('hide');
            this.wizardController.stepTwo({
                streams: selectedStreams
            });

        },

        finish: function () {

            var self                 = this;
            var selectedStreamModels = this.getSelectedStreams();
            var selectedStreams      = _.map(selectedStreamModels, function (eachModel) {
                return eachModel.get('id');
            })

            this.fwdGroupModel.save({streams: selectedStreams},
            {
                success: function (model, resp) {
                    self.$el.modal('hide');
                    // trigger collection listener
                    self.fwdGroupsCollection.add(self.fwdGroupModel);
                    console.log("saved: ", model, resp);
                },
                error: function (model, resp) {
                    console.log("failed to save: ", model, resp);
                }
            });
        },

        save: function(e) {

            var self = this;
            var selectedStreamModels = this.getSelectedStreams();
            var selectedStreams = _.map(selectedStreamModels, function (eachModel) {
                return eachModel.get('id');
            })

            this.fwdGroupModel.save({streams: selectedStreams}, {
                success: function (model, resp) {
                    self.$el.modal('hide');
                    self.remove();
                },
                error: function (model, resp) {
                    alert("error saving streams, please redo.", resp);
                }
            })

        }

    });
});