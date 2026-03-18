define([
        "app-js/contrib/underscore",
        "app-js/contrib/jquery",
        "app-js/contrib/backbone",
        "app-js/contrib/mediator",
        "app-js/views/MountPoints/MountPointsView",
        "app-js/collections/MountPoints",
        "app-js/components/loadLayout"
    ],
    function(
        _,
        $,
        Backbone,
        Mediator,
        MountPointsView,
        MountPoints,
        LoadLayout
        ) {

        var app = app || {};
        var splunkd = splunkd || {};
        app.mediator = new Mediator()

        var mountPointsFetched = $.Deferred();
        var mountPoints        = new MountPoints();

        mountPoints.fetch({
            success: function(mountPointsCollection) {
                mountPointsFetched.resolve(mountPointsCollection);
            },
            error: function (e) {
                console.log("error fetching mount points");
            }
        })

        $.when(mountPointsFetched.promise())
         .done(function(mountPointsCollection) {

            LoadLayout(function(layout) {
                var appContent = new MountPointsView({
                    mountPointsCollection: mountPointsCollection,
                    app                  : app
                });
                layout.create()
                    .getContainerElement()
                    .appendChild(appContent.render().el);
            });
        });
});
