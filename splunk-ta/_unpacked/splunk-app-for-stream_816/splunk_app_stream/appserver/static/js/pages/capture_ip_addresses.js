define([
    "app-js/contrib/underscore",
    "app-js/contrib/jquery",
    "app-js/contrib/backbone",
    "app-js/components/loadLayout",
    "app-js/contrib/backbone.listview",
    "app-js/collections/CaptureIpAddresses",
    "app-js/views/CaptureIpAddressesView",
    "app-js/contrib/mediator"
    ],
    function(
        _,
        $,
        Backbone,
        LoadLayout,
        ListView,
        CaptureIpAddresses,
        CaptureIpAddressesView,
        Mediator
        ) {

        var app = app || {};
        var splunkd = splunkd || {};
        app.mediator = new Mediator()
        var captureIpAddresses = new CaptureIpAddresses();

        var self = this;

        LoadLayout(function(layout) {
            var appContent = new CaptureIpAddressesView({
                app                : app,
                captureIpAddresses : captureIpAddresses
            });
            layout.create()
                .getContainerElement()
                .appendChild(appContent.render().el);
        });
    }
);
