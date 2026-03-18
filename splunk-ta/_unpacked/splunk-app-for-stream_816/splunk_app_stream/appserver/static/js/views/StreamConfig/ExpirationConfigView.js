define([
    "app-js/contrib/underscore",
    "app-js/contrib/jquery",
    "app-js/contrib/backbone",
    "app-js/views/PacketStreams/ExpirationControlsView",
    "contrib/text!app-js/templates/PacketStreams/ExpirationStepTemplate.html",
    "css!app-js/templates/PacketStreams/ExpirationStepTemplate.css"
], function(
    _,
    $,
    Backbone,
    ControlsView,
    template
    ) {
    return Backbone.View.extend({

        initialize: function(options) {
            this.app = options.app;
            this.streamModel = options.streamModel;

            this.expirationModel = this.streamModel.clone();
            this.controlsView = new ControlsView({
                model: this.expirationModel,
                app: this.app
            });

            this.listenTo(this.expirationModel, 'add change', _.debounce(function () {
                this.updateStreamModel();
            }.bind(this),100));
        },

        events: {
            'change .hasDatepicker' : 'updateStreamModel'
        },

        updateStreamModel: function() {
            //Save Total Bytes Captured
            if (this.expirationModel.get("maxBytesCaptured")) {
                this.streamModel.set('maxBytesCaptured', parseInt(this.expirationModel.get('maxBytesCaptured')));
            } else {
                this.streamModel.unset('maxBytesCaptured');
            }

            //Save Total Packets Captured
            if (this.expirationModel.get("maxPacketsCaptured")) {
                this.streamModel.set('maxPacketsCaptured', parseInt(this.expirationModel.get('maxPacketsCaptured')));
            } else {
                this.streamModel.unset('maxPacketsCaptured');
            }

            //Save Total Flows Captured
            if (this.expirationModel.get("maxFlowsCaptured")) {
                this.streamModel.set('maxFlowsCaptured', parseInt(this.expirationModel.get('maxFlowsCaptured')));
            } else {
                this.streamModel.unset('maxFlowsCaptured');
            }

            //Save Elapsed Time
            if (this.expirationModel.get("maxElapsedTime") && this.expirationModel.get("maxElapsedTimeUnits")) {
                var conversionToSeconds = { seconds: 1, minutes: 60, hours: 3600, days: 86400 };
                var secondsMultiplier = conversionToSeconds[this.expirationModel.get("maxElapsedTimeUnits")];
                this.streamModel.set('maxElapsedTime', parseInt(this.expirationModel.get('maxElapsedTime')) * secondsMultiplier);
            } else {
                this.streamModel.unset('maxElapsedTime');
            }

            //Save Absolute Time
            if (this.expirationModel.get("absoluteDate") && this.expirationModel.get("absoluteTime")) {
                if (!this.expirationModel.get('absoluteTime').match(/^\d\d:\d\d:\d\d$/)) {
                    this.streamModel.set('absoluteLatestTime', -1);
                } else {
                    var date = this.expirationModel.get("absoluteDate");
                    var time = this.expirationModel.get("absoluteTime").split(':');
                    var unixTime = new Date(date.get('year'), date.get('month'), date.get('day'), parseInt(time[0]), parseInt(time[1]), parseInt(time[2]));
                    unixTime = Math.floor(unixTime.getTime() / 1000);
                    this.streamModel.set('absoluteLatestTime', unixTime);
                }
            } else {
                this.streamModel.unset("absoluteLatestTime");
            }
        },

        render: function() {
            var self = this;
            this.$el.html(_.template(template, {
                stepTitle: ''
            }));
            this.controlsView.setElement(this.$(".expiration-edit-controls")).render();
            return this;
        }
    });
});
