define([
    "app-js/components/loadLayout",
    "app-js/views/FlowVisualizationView"
    ],
    function(
        LoadLayout,
        FlowVisualizationView
        ) {

        LoadLayout(function(layout) {
            var appContent = new FlowVisualizationView({});
            layout.create()
                .getContainerElement()
                .appendChild(appContent.render().el);
        });

    }
);
