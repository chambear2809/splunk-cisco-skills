define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "contrib/text!app-js/templates/EphemeralStreams/DatepickerTemplate.html",
    "app-js/contrib/jquery-ui.min",
    "app-js/contrib/moment",
    "app-js/contrib/moment-timezone-with-data"
], function(
    $,
    _,
    Backbone,
    DatepickerTemplate,
    jQueryUI,
    moment,
    Moment
    ) {
    return Backbone.View.extend({

        className: 'modal',

        initialize: function(options){
            this.options  = _.extend({}, this.options, options);
            this.template = _.template($(DatepickerTemplate).html());
            this.app      = this.options.app;

            this.startTime = new Date(this.options.startTime);
            this.endTime   = new Date(this.options.endTime);
            this.timezone  = this.options.timezone;

        },

        events:{
            'click .apply'        :'apply',
            'change #date-picker' : 'validateDate',
            'keyup #date-picker'  : 'validateDate'
        },

        //check validity of date format & that it is in future
        validateDate: function(e) {
            var input =  $(e.target).val();
            var m = Moment(input);

            if (input.split("/").length == 3 && m.isValid()){
                if (m.isAfter(Moment())){
                    setValid();
                } else {
                    setInvalid("date is in the past");
                }
            } else{
                setInvalid("invalid date");
            }

            function setValid(){
                $("#warning").html("");
                $("#btnYes").removeAttr("disabled");
            }

            function setInvalid(msg){
                $("#warning").html(msg);
                $("#btnYes").attr("disabled", "disabled");
            }
        },

        show: function(){

            this.$el.html(this.template({
                groupName     : this.options.groupId,
                startTimeDate : this.formatDate(this.startTime, this.timezone),
                startTimeTime : this.formatTime(this.startTime, this.timezone),
                endTimeDate   : this.formatDate(this.endTime, this.timezone),
                endTimeTime   : this.formatTime(this.endTime, this.timezone),
                countdown     : this.options.countdown
            }));

            var streams = this.app.streams.where({
                category: this.options.groupId
            });

            this.$("#date-picker").datepicker({
                minDate     : 0,
                changeMonth : true,
                changeYear  : true
            });

            this.$el.modal('show');
        },

        formatTime: function(utcTime, timezone){
            if (timezone)
                return Moment(utcTime).tz(timezone).format("HH:mm:ss");
            else
                return Moment(utcTime).format("HH:mm:ss");
        },

        formatDate: function(utcTime, timezone){
            if (timezone)
                return Moment(utcTime).tz(timezone).format("MM/DD/YYYY");
            else
                return Moment(utcTime).format("MM/DD/YYYY");
        },

        apply: function(e){

            var self = this;
            e.preventDefault();

            //prevent further actions if button is disabled
            if( $(e.target).attr("disabled") === "disabled" ) {
                return false;
            }

            var userDate = $("#date-picker").val();
            var d        = new Date(userDate);
            var t        = $("#time").val().split(":");

            var m = createMoment({
                year   : d.getFullYear(),
                month  : d.getMonth(),
                day    : d.getDate(),
                hour   : t[0] || 0,
                minute : t[1] || 0,
                second : t[2] || 0
            }, this.timezone);

            var streams = this.app.streams.where({
                category: this.options.groupId
                //what happens if non-ephemeral streams share the same category name??
            });

            if (m.isValid()){
                _.each(streams,function(each) {
                    each.set("expirationDate", m.unix());
                    each.save(null, {
                        success: function(e){
                            //close modal & refresh page
                            self.$el.modal('hide');
                            self.remove();
                            Backbone.history.loadUrl();
                        },
                        error: function(obj, err){
                            console.log("Error saving stream");
                            alert("Error saving stream: " + err.responseJSON.error);
                        }
                    });
                })
            } else {
                alert("invalid time!");
            }

            function createMoment(timeObj, timezone){
                if (timezone)
                    return Moment.tz(timeObj, timezone);
                else
                    return Moment(timeObj);
            }
        }

    });
});