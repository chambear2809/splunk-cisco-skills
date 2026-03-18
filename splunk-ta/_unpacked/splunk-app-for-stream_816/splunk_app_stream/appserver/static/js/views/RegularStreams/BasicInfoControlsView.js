define([
    "app-js/contrib/underscore",
    "app-js/contrib/jquery",
    "app-js/contrib/backbone",
    "swc-stream/index",
    "@splunk/ui-utils/i18n"
    ],
    function(
        _,
        $,
        Backbone,
        index,
        Inter
    ) {
        /**
         * View responsible for rendering basic stream info controls.
         */
        const ControlGroup = index.ControlGroup;
        var ControlsView = Backbone.View.extend({
            /**
             * Backbone initializer
             * @param {Object} options
             *        - {Model} model: storage for basic stream info controls
             *        - {ReferenceStreams} referenceStreams: reference streams Collection
             *        - {Array} usedStreamIds: for checking for duplicate id's
             */
            initialize: function(options) {
                this.referenceStreams = options.referenceStreams;
                this.usedStreamIds = options.usedStreamIds;
                this._initControls();
            },
            /**
             * Initializes control groups and sets them to populate the stream model.
             * @private
             */
            _initControls: function() {
                var basicInfoModel = this.model;
                this.controls = {};

                // referenceStreamItems looks like:
                //[
                //    { value: "amqp", label: "AMQP" },
                //    { value: "dhcp", label: "DHCP" },
                //    { value: "diameter", label: "Diameter" },
                //    ...
                //]
                // where value = a reference stream ID
                // and label = the corresponding protocol name.

                var referenceStreamItems = this.referenceStreams.map(function(model) {
                    return {
                        value: model.get('id'),
                        label: model.get('protocolName')
                    }
                });

                basicInfoModel.set("referenceStreamId", "http");
                this.controls.protocol = new ControlGroup({
                    controlType: 'SyntheticSelect',
                    controlOptions: {
                        model: basicInfoModel,
                        modelAttribute: 'referenceStreamId',
                        className: 'protocol',
                        toggleClassName: 'btn',
                        items: referenceStreamItems
                    },
                    label: Inter.gettext("Protocol")
                });

                // This will be used as the 'id' property of the new stream.
                this.controls.name = new ControlGroup({
                    controlType: "Text",
                    controlOptions: {
                        modelAttribute: "id",
                        model: basicInfoModel,
                        save: false
                    },
                    label: "Name"
                });

                // This will be used as the 'name' property of the new stream.
                basicInfoModel.set("description", ""); // because the server requires 'name' to hold a string, which can be empty
                this.controls.description = new ControlGroup({
                    controlType: "Textarea",
                    controlOptions: {
                        modelAttribute: "description",
                        model: basicInfoModel,
                        save: false
                    },
                    label: "Description"
                });
            },
            /**
             * Validation routine (like Backbone.Model.validate(), although this isn't a model)
             * If validation fails:
             * @returns {String} - validation error message
             */
            validate: function() {
                var validId = this.model.get("id") && this.model.get("id").match(/^\w+$/);
                var uniqueId = this.model.get("id") && this.usedStreamIds.indexOf(this.model.get("id").toLowerCase()) == -1;
                var validDescription = typeof(this.model.get("description")) == 'string';

                // set or clear error status for all fields
                this.controls.name.error(!validId);
                this.controls.description.error(!validDescription);

                // return error message for first validation error, if any
                if (!this.model.get("id"))
                    return "Please specify a name for the stream.";
                if (!validId)
                    return "Please specify a name using only letters, digits and underscores ('_').";
                if (!uniqueId)
                    return "A stream with that name already exists.";
                if (!validDescription)
                    return "Please specify a description for the stream.";
            },
            /**
             * Renderer
             */
            render: function() {
                var nameFieldExplanation = "The name of a stream will be used as the source of the events.  It cannot be changed afterwards.";

                this.$el.append(this.controls.protocol.render().el)
                    .append(this.controls.name.render().el)
                    .append('<div class="field-explanation">' + nameFieldExplanation + '</div>')
                    .append(this.controls.description.render().el)
                this.$("textarea", this.controls.description.$el).attr("rows", "5");
                return this;
            }
        });
        return ControlsView;
    }
);
