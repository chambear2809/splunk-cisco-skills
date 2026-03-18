define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "contrib/text!app-js/templates/RegularStreams/PermanentStreamRowTemplate.html",
    "app-js/views/ConfirmView",
    'swc-stream/index',
    "app-js/contrib/jquery.sparkline",
], function(
    $,
    _,
    Backbone,
    PermanentStreamRowTemplate,
    ConfirmView,
    index,
    Sparklines
    ) {
    
    const Popdown = index.Popdown;
    return Backbone.View.extend({

        tagName: 'tr',
        className: 'permanent-stream-table-row stream-row',

        attributes: function () {
            return {
                'data-id': this.model.get('id')
            }
        },

        initialize: function(options){

            this.app           = options.app;
            this.template      = _.template($(PermanentStreamRowTemplate).html());
            this.model         = options.model;
            this.sparklineData = options.sparklineData;

            var self = this;

            this.app.mediator.subscribe("search-filtered", function (searchString) {
                self._showHideBasedOnRegex(searchString);
            });

            this.listenTo(this.model, 'change', function () {
                self.render();
            })

            this.listenTo(this.model, 'destroy', function () {
                self.remove();
            })

        },

        _showHideBasedOnRegex: function (searchString) {

            var self = this;
            var regex = new RegExp(searchString, "i");

            // show if regex matches any of these strings.
            var matchCases = _.flatten([
                self.model.get('id'),
                self.model.get('name'),
                self.matchedFwdGroups
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

            'click .stream-disable'     : 'disableStream',
            'click .stream-enable'      : 'enableStream',
            'click .stream-id'          : 'showStreamDetails',
            'click .edit-stream'        : 'showStreamDetails',
            'click .stream-stats-only'  : 'statsOnlyStream',
            'click .stream-delete'      : 'deleteStream',
            'click .stream-clone'       : 'cloneStream'

        },

        deleteStream: function(e) {
           e.preventDefault();
           this._confirmSingleStreamAction("delete");
        },

        disableStream: function(e) {
            e.preventDefault();
            this._confirmSingleStreamAction("disable");
        },

        enableStream: function(e) {
            e.preventDefault();
            this._confirmSingleStreamAction("enable");
        },

        statsOnlyStream: function(e) {
            e.preventDefault();
            this._confirmSingleStreamAction("estimate");
        },

        showStreamDetails: function(e){
            e.preventDefault();
            var routerString = ["streamConfig", this.model.get('id')].join("/");
            this.app.router.navigate(routerString, {trigger: true});
        },

        //action: delete, enable, statsOnly, disable
        _confirmSingleStreamAction: function(action) {

            var self = this;

            var options = {
                success: function () {
                    console.log(action + " was successful.")
                },
                error: function (model, response) {
                    alert(response.responseJSON.error);
                },
                wait:true
            };

            var confirmView = new ConfirmView({
                action: action,
                model: {text: self.model.get('id') + ":" + self.model.get('name')},
                command: function() {

                    if (action === "enable"){
                        if (self.model.get('isPacketStream')) {
                            var epochTime = parseInt((new Date).getTime() / 1000);
                            self.model.set('latestEnableTime', epochTime);
                        }
                        self.model.save({
                            enabled: true,
                            statsOnly: false
                        }, options)
                    }
                    if (action === "estimate"){
                        self.model.save({
                            enabled: true,
                            statsOnly: true
                        }, options)
                    }
                    if (action === "disable"){
                        self.model.save({
                            enabled: false,
                            statsOnly: false
                        }, options);

                    }
                    if (action === "delete"){
                        self.model.destroy(options);
                    }

                }
            }).show();

        },

        cloneStream: function(e) {
            e.preventDefault();
            this.app.mediator.publish("view:add-stream-dialog", this.model);
        },


        render: function(){

            var self = this;
            this.$el.html(self.template({
                stream: this.model.toJSON()
            }));

            // Create Popdown
            self.$(".stream-edit").each(function(index, item) {
                new Popdown({ el: $(item) })
            });

            return this;

        }

    });
});
