define([
    "app-js/contrib/underscore",
    "app-js/contrib/jquery",
    "app-js/contrib/backbone",
    "swc-stream/index"
    ],
    function(
        _,
        $,
        Backbone,
        index
    ) {
        const DateInputModel = index.DateInputModel;
        const ControlGroup = index.ControlGroup;
        const Popdown = index.Popdown;

        var ControlsView = Backbone.View.extend({

            events: {
                'click .total-bytes-captured'   : 'showTotalBytesCaptured',
                'click .total-packets-captured' : 'showTotalPacketsCaptured',
                'click .total-flows-captured'   : 'showTotalFlowsCaptured',
                'click .absolute-time'          : 'showAbsoluteTime',
                'click .elapsed-time'           : 'showElapsedTime',

                'click #remove-bytes-captured'   : 'removeBytesCaptured',
                'click #remove-packets-captured' : 'removePacketsCaptured',
                'click #remove-flows-captured'   : 'removeFlowsCaptured',
                'click #remove-elapsed-time'     : 'removeElapsedTime',
                'click #remove-absolute-time'    : 'removeAbsoluteTime'
            },

            initialize: function(options) {
                this.controls = {};
                this.app = options.app;
                this.model = options.model;
                this.shownFields = 0;
            },

            showTotalBytesCaptured: function() {
                var expirationModel = this.model;

                this.controls.bytes = new ControlGroup({
                    controlType: "Text",
                    controlOptions: {
                        modelAttribute: "maxBytesCaptured",
                        model: expirationModel,
                        save: false
                    },
                    label: "Total Bytes Captured"
                });

                var formElement = this.controls.bytes.render();
                formElement.$el.addClass("bytes-captured-field");
                formElement.$el.find(".control").append('<a class="btn-pill" id="remove-bytes-captured"> X </a>');
                this.$(".expiration-form-controls").append(formElement.el);
                this.$(".total-bytes-captured").hide();
                this._showNewField();
            },

            removeBytesCaptured: function() {
                this.controls.bytes.remove();
                this.controls = _.omit(this.controls, "bytes");
                this.$(".bytes-captured-field").remove();
                this.$(".total-bytes-captured").show();
                this.model.unset("maxBytesCaptured");
                this._removeShownField();
            },

            showTotalPacketsCaptured: function() {
                var expirationModel = this.model;

                this.controls.packets = new ControlGroup({
                    controlType: "Text",
                    controlOptions: {
                        modelAttribute: "maxPacketsCaptured",
                        model: expirationModel,
                        save: false
                    },
                    label: "Total Packets Captured"
                });

                var formElement = this.controls.packets.render();
                formElement.$el.addClass("packets-captured-field");
                formElement.$el.find(".control").append('<a class="btn-pill" id="remove-packets-captured"> X </a>');
                this.$(".expiration-form-controls").append(formElement.el);
                this.$(".total-packets-captured").hide();
                this._showNewField();
            },

            removePacketsCaptured: function() {
                this.controls.packets.remove();
                this.controls = _.omit(this.controls, "packets");
                this.$(".packets-captured-field").remove();
                this.$(".total-packets-captured").show();
                this.model.unset("maxPacketsCaptured");
                this._removeShownField();
            },

            showTotalFlowsCaptured: function() {
                var expirationModel = this.model;

                this.controls.flows = new ControlGroup({
                    controlType: "Text",
                    controlOptions: {
                        modelAttribute: "maxFlowsCaptured",
                        model: expirationModel,
                        save: false
                    },
                    label: "Total Flows Captured"
                });

                var formElement = this.controls.flows.render();
                formElement.$el.addClass("flows-captured-field");
                formElement.$el.find(".control").append('<a class="btn-pill" id="remove-flows-captured"> X </a>');
                this.$(".expiration-form-controls").append(formElement.el);
                this.$(".total-flows-captured").hide();
                this._showNewField();
            },

            removeFlowsCaptured: function() {
                this.controls.flows.remove();
                this.controls = _.omit(this.controls, "flows");
                this.$(".flows-captured-field").remove();
                this.$(".total-flows-captured").show();
                this.model.unset("maxFlowsCaptured");
                this._removeShownField();
            },

            showAbsoluteTime: function() {
                var expirationModel = this.model;
                var dateModel = new DateInputModel();
                var absoluteTime = '00:00:00';

                if (expirationModel.get('absoluteLatestTime')) {
                    var date = new Date(parseInt(expirationModel.get('absoluteLatestTime') * 1000));
                    dateModel.set('year', date.getFullYear());
                    dateModel.set('month', date.getMonth());
                    dateModel.set('day', date.getDate());
                    var hour = date.getHours() > 9 ? date.getHours().toString() : '0' + date.getHours().toString();
                    var min = date.getMinutes() > 9 ? date.getMinutes().toString() : '0' + date.getMinutes().toString();
                    var sec = date.getSeconds() > 9 ? date.getSeconds().toString() : '0' + date.getSeconds().toString();
                    absoluteTime = hour + ':' + min + ':' + sec;
                }

                expirationModel.set('absoluteDate', dateModel);
                expirationModel.set('absoluteTime', absoluteTime);

                this.controls.absoluteDate = new ControlGroup({
                    controlType: "Date",
                    controlOptions: {
                        modelAttribute: "inputDatePicker",
                        model: expirationModel.get('absoluteDate'),
                        save: false
                    },
                    label: "Absolute Time"
                });

                this.controls.absoluteTime = new ControlGroup({
                    controlType: "Text",
                    controlOptions: {
                        placeholder: "00:00:00",
                        modelAttribute: "absoluteTime",
                        model: expirationModel,
                        save: false
                    },
                });

                var formElement = this.controls.absoluteDate.render();
                var absoluteTimeElement = this.controls.absoluteTime.render().$el.find(".control");
                var absoluteTimeHelperText = 'HH:MM:SS';

                formElement.$el.addClass("absolute-time-field");
                absoluteTimeElement.css("display", "inline");

                formElement.$el.find(".control").append(absoluteTimeElement);
                formElement.$el.find(".shared-controls-datecontrol").append('<a class="btn-pill" id="remove-absolute-time"> X </a>')
                    .append('<div class="field-explanation">' + absoluteTimeHelperText + '</div>');

                this.$(".expiration-form-controls").append(formElement.el);
                this.$(".absolute-time").hide();
                this._showNewField();
            },

            removeAbsoluteTime: function() {
                this.controls.absoluteTime.remove();
                this.controls.absoluteDate.remove();
                this.controls = _.omit(this.controls, "absoluteTime");
                this.controls = _.omit(this.controls, "absoluteDate");
                this.$(".absolute-time-field").remove();
                this.$(".absolute-time").show();
                this.model.unset("absoluteTime");
                this.model.unset("absoluteDate");
                this._removeShownField();
            },

            showElapsedTime: function() {
                var expirationModel = this.model;
                var maxElapsedTime = expirationModel.get('maxElapsedTime');

                if (maxElapsedTime % 86400 === 0) {
                    expirationModel.set('maxElapsedTime', maxElapsedTime / 86400);
                    expirationModel.set('maxElapsedTimeUnits', 'days');
                } else if (maxElapsedTime % 3600 === 0) {
                    expirationModel.set('maxElapsedTime', maxElapsedTime / 3600);
                    expirationModel.set('maxElapsedTimeUnits', 'hours');
                } else if (maxElapsedTime % 60 === 0) {
                    expirationModel.set('maxElapsedTime', maxElapsedTime / 60);
                    expirationModel.set('maxElapsedTimeUnits', 'minutes');
                } else {
                    expirationModel.set('maxElapsedTimeUnits', 'seconds');
                }

                this.controls.elapsedTime = new ControlGroup({
                    controlType: "Text",
                    controlOptions: {
                        modelAttribute: "maxElapsedTime",
                        model: expirationModel,
                        save: false
                    },
                    label: "Elapsed Time"
                });

                var units = ['seconds', 'minutes', 'hours', 'days'];
                var unitItems = units.map(function(unit) { return { value: unit, label: unit } });

                this.controls.elapsedTimeUnits = new ControlGroup({
                    controlType: "SyntheticSelect",
                    controlOptions: {
                        modelAttribute: "maxElapsedTimeUnits",
                        model: expirationModel,
                        toggleClassName: 'btn',
                        save: false,
                        items: unitItems
                    }
                });

                var formElement = this.controls.elapsedTime.render();
                var unitSelectElement = this.controls.elapsedTimeUnits.render().$el.find(".control");

                formElement.$el.addClass("elapsed-time-field");
                unitSelectElement.css("display", "inline");
                formElement.$el.find(".control").append(unitSelectElement);
                formElement.$el.find(".shared-controls-textcontrol").append('<a class="btn-pill" id="remove-elapsed-time"> X </a>');

                this.$(".expiration-form-controls").append(formElement.el);
                this.$(".elapsed-time").hide();
                this._showNewField();
            },

            removeElapsedTime: function() {
                this.controls.elapsedTime.remove();
                this.controls.elapsedTimeUnits.remove();
                this.controls = _.omit(this.controls, "elapsedTime");
                this.controls = _.omit(this.controls, "elapsedTimeUnits");
                this.$(".elapsed-time-field").remove();
                this.$(".elapsed-time").show();
                this.model.unset("maxElapsedTime");
                this.model.unset("maxElapsedTimeUnits");
                this._removeShownField();
            },

            _showNewField: function() {
                this.shownFields += 1;
                if (this.shownFields === 5) {
                    this.$(".expiration-dropdown").hide();
                }
            },

            _removeShownField: function() {
                this.shownFields -= 1;
                if (this.shownFields < 5) {
                    this.$(".expiration-dropdown").show();
                }
            },

            validate: function() {
                var validBytes = this.model.get("maxBytesCaptured") && this.model.get("maxBytesCaptured").match(/^[1-9]\d*$/);
                var validPackets = this.model.get("maxPacketsCaptured") && this.model.get("maxPacketsCaptured").match(/^[1-9]\d*$/);
                var validFlows = this.model.get("maxFlowsCaptured") && this.model.get("maxFlowsCaptured").match(/^[1-9]\d*$/);
                var validAbsoluteTime = this.model.get("absoluteTime") && this.model.get("absoluteDate") && this.model.get("absoluteTime").match(/^([0-1]\d|2[0-3]):[0-5]\d:[0-5]\d$/);
                var validElapsedTime = this.model.get("maxElapsedTime") && this.model.get("maxElapsedTimeUnits") && this.model.get("maxElapsedTime").match(/^[1-9]\d*$/);

                //Remove if we want to allow users to have permanent packet streams
                if (!this.controls.bytes && !this.controls.packets && !this.controls.flows && !this.controls.absoluteTime && !this.controls.elapsedTime) {
                    return "Please set at least one expiration condition for this packet stream";
                }

                //Validate that absolute time is not set to a past datetime value
                if (validAbsoluteTime) {
                    var date = this.model.get("absoluteDate");
                    var time = this.model.get("absoluteTime").split(':');
                    var unixTime = new Date(date.get('year'), date.get('month'), date.get('day'), parseInt(time[0]), parseInt(time[1]), parseInt(time[2])).getTime();
                    var curTime = new Date().getTime();
                    if (unixTime <= curTime) {
                        this.controls.absoluteDate.error(true);
                        return "Please set absolute time to a future datetime";
                    }
                }

                if (this.controls.bytes) this.controls.bytes.error(!validBytes);
                if (this.controls.packets) this.controls.packets.error(!validPackets);
                if (this.controls.flows) this.controls.flows.error(!validFlows);
                if (this.controls.absoluteTime) this.controls.absoluteDate.error(!validAbsoluteTime);
                if (this.controls.elapsedTime) this.controls.elapsedTime.error(!validElapsedTime);

                if (this.controls.bytes && !validBytes) return "Please specify total bytes captured as a positive integer";
                if (this.controls.packets && !validPackets) return "Please specify total packets captured as a positive integer";
                if (this.controls.flows && !validFlows) return "Please specify total flows captured as a positive integer";
                if (this.controls.absoluteTime && !validAbsoluteTime) return "Please enter a valid time format for absolute time";
                if (this.controls.elapsedTime && !validElapsedTime) return "Please enter a positive integer value for elapsed time";
            },

            render: function() {
                var self = this;

                new Popdown({ el: self.$(".expiration-dropdown") });

                if (this.model.get('maxBytesCaptured')) {
                    this.showTotalBytesCaptured();
                }
                if (this.model.get('maxFlowsCaptured')) {
                    this.showTotalFlowsCaptured();
                }
                if (this.model.get('maxPacketsCaptured')) {
                    this.showTotalPacketsCaptured();
                }
                if (this.model.get('maxElapsedTime')) {
                    this.showElapsedTime();
                }
                if (this.model.get('absoluteLatestTime')) {
                    this.showAbsoluteTime();
                }

                return this;
            }
        });
        return ControlsView;
    }
);
