define(['app-js/contrib/underscore', 'swc-stream/index'], function(_, index) {

    const requirejs = index.requirejs;
    var cachedLayout;

    /**
     * Loads the layout component, first checking if it exists on the server,
     * then falling back to one built into the app if it not.
     *
     * @param {Function} callback - Will be invoked with the layout component.
     */
    return function(callback) {
        if (cachedLayout) {
            // Ensure the callback is always invoked asynchronously for a
            // consistent api.
            return _.defer(callback, cachedLayout);
        }
        // Try to load the layout dynamically from the version of splunk that is
        // currently running.
        requirejs(['api/layout'], function(layout) {
            cachedLayout = layout;
            callback(layout);
        }, function(err) {
            console.error("error while loading api/layout ");
        });
    };
});
