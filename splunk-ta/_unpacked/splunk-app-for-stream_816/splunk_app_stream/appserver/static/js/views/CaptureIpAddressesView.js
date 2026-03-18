define([
        "app-js/contrib/underscore",
        "app-js/contrib/jquery",
        "app-js/contrib/backbone",
        "app-js/contrib/mediator",
        "app-js/views/BlacklistWhitelist/IpAddressListView",
        "app-js/views/BlacklistWhitelist/IpAddressView",
        "contrib/text!app-js/templates/CaptureIpAddressesTemplate.html",
        "swc-stream/index"
    ],
    function(
        _,
        $,
        Backbone,
        Mediator,
        IpAddressListView,
        IpAddressView,
        CaptureIpAddressesTemplate,
        index
        ) {
        
        const CSRFProtectionUtil = index.CSRFProtectionUtil;
        return Backbone.View.extend({

        initialize: function(options){
            this.options = _.extend({}, this.options, options);
            this.template = _.template($(CaptureIpAddressesTemplate).html());
            this.app = this.options.app;
            this.captureIpAddresses = this.options.captureIpAddresses;

            var self = this;

            IpAddressRouter = Backbone.Router.extend({
                routes: {
                    "": "showCaptureIps"
                },

                initialize: function(options){
                    this.fetchingIpAddresses = self.captureIpAddresses.fetch();
                },

                showCaptureIps: function() {
                    this.fetchingIpAddresses.done(
                        function(data){
                            var blackListView = new IpAddressListView({
                                app: self.app,
                                componentId: 'blacklist',
                                ipAddressList: self.captureIpAddresses.get("blacklist"),
                                el: '#blacklist',
                                ipAddressView: IpAddressView
                            });

                            var whiteListView = new IpAddressListView({
                                app: self.app,
                                componentId: 'whitelist',
                                ipAddressList: self.captureIpAddresses.get("whitelist"),
                                el: '#whitelist',
                                ipAddressView: IpAddressView
                            });

                            whiteListView.render();
                            blackListView.render();
                        }
                    );
                }
            });

            var router = new IpAddressRouter();
            Backbone.history.start();
        },

        events: {
            'click #toggle-help': 'toggleHelp'
        },

        toggleHelp: function () {
            $('#help').fadeToggle();
        },

        render: function () {
            this.$el.html(this.template());
            return this;
        }
    });
});
