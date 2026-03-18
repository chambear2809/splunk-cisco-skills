define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "swc-stream/index",
    "contrib/text!app-js/templates/ForwarderManagement/SetupStreamForwarderAuthTemplate.html"
], function(
    $,
    _,
    Backbone,
    index,
    SetupStreamForwarderAuthTemplate
    ) {
    const SplunkUtils = index.SplunkUtils;
    return Backbone.View.extend({

        className: 'modal',

        initialize: function (options) {
            this.options       = _.extend({}, this.options, options);
            this.app           = this.options.app;
            this.template      = _.template($(SetupStreamForwarderAuthTemplate).html());
            this.streamfwdAuth = this.options.streamfwdAuth;

            this.authEnabled = !!this.streamfwdAuth.get('enabled');
            this.authKey     = this.streamfwdAuth.get('authKey');

            var self = this;

            //listen for validation errors
            this.listenTo(this.streamfwdAuth, 'invalid', function (model, errors) {
                //reset auth values due to invalidity
                self.streamfwdAuth.set('authKey', self.authKey);
                self.streamfwdAuth.set('enabled', self.authEnabled);
                alert("\n\u2022 " + errors.join("\n\u2022 "));
            }.bind(this));
        },

        events: {
            'click #auth-checkbox' : 'toggleAuth',
            'click .cancel'        : 'cancel',
            'click .save'          : 'save'
        },

        toggleAuth: function (e) {
            var authEnabled = $(e.target).is(':checked');
            $('#auth-textarea').prop('disabled', !authEnabled);
        },

        cancel: function () {
            this.remove();
        },

        save: function (e) {

            var self = this;
            var authKey = $('#auth-textarea').val().trim();
            var authEnabled = $('#auth-checkbox').is(':checked');

            this.streamfwdAuth.set('authKey', authKey);
            this.streamfwdAuth.set('enabled', authEnabled);

            this.streamfwdAuth.save(null, {
                url: SplunkUtils.make_url([
                    'custom',
                    'splunk_app_stream',
                    'streamfwdauth'
                ].join('/')),
                success: function (model, resp) {
                    self.$el.modal('hide');
                },
                error: function (model, resp) {
                    console.log('Error saving stream forwarder auth');
                    alert("\n\u2022 " + resp.responseJSON.error);
                }
            });
        },

        show: function () {

            var self = this;

            this.$el.html(this.template({
                authEnabled : this.authEnabled,
                authKey     : this.authKey
            }));

            this.$el.on('hide', function() {
                self.remove();
            });

            this.$el.modal('show');

            return this;
        }
    });
});
