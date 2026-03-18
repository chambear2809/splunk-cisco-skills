define([
    "app-js/contrib/underscore",
    "app-js/contrib/jquery",
    "app-js/contrib/backbone",
    "swc-stream/index",
    "contrib/text!app-js/templates/MountPoints/MountPointsTemplate.html",
    "app-js/models/MountPoint",
    "app-js/views/MountPoints/EditMountPointView",
    "app-js/views/MountPoints/MountPointTableRowView",
    "app-js/contrib/jquery.tablesorter.min",
    ],
    function(
    _,
    $,
    Backbone,
    index,
    MountPointsTemplate,
    MountPoint,
    EditMountPointView,
    MountPointTableRowView
    ) {

    const Controller = index.Controller;
    return Backbone.View.extend({

        initialize: function(options) {
            this.options = _.extend({}, this.options, options);
            this.app = this.options.app;
            this.template = _.template($(MountPointsTemplate).html());
            this.collection = this.options.mountPointsCollection;

            this.collection.on('change add remove', this.render.bind(this));

            // Handle redirection from pcaps.py, where a file server is specified as a query parameter.
            // Two possible scenarios:
            // 1) The file server id was not found, so pcaps.py created a new entry and left the mount point empty.
            // 2) A mount point is configured, but the specified path does not exist.
            var query_parts = location.search.split('=')
            if (query_parts.length == 2 && query_parts[0] == '?file_server') {
                var id = query_parts[1];
                var model = this.collection.get(id);
                if (model) {
                    editMountPointView = new EditMountPointView({
                        mountPointModel: model,
                        collection: this.collection
                    }).show();
                }
            }
        },

        events: {
            'keyup #mount-point-search-input'    : 'filterTable',
            'click a.clear'                      : 'resetSearch',
            'click #add-file-server-mount-point' : 'addMountPoint'
        },

        filterTable: function() {
            var searchString = $('#mount-point-search-input').val();
            this.app.mediator.publish("search-filtered", searchString);
        },

        resetSearch: function(e) {
            e.preventDefault();
            this.render();
        },

        addMountPoint: function(e) {
            e.preventDefault();
            var model = new MountPoint();
            var editMountPointView = new EditMountPointView({
                create: true,
                mountPointModel: model,
                collection: this.collection
            }).show();
        },

        render: function() {
            var self = this;

            var output = self.template({
                mountPointCount: self.collection.length
            });

            self.$el.empty();
            self.$el.append(output);

            var tableBody = self.$("#mount-point-table");

            //append the table rows
            self.collection.each(function(eachModel) {
                var newRow = new MountPointTableRowView({
                    model                : eachModel,
                    app                  : self.app,
                    mountPointsCollection: self.collection,
                }).render().$el.appendTo(tableBody);
            });

            tableBody.tablesorter({
                //debug: true, // turn on tablesorter debugger
                headers: {
                    0: {sorter: 'text'},
                    1: {sorter: 'text'},
                    2: {sorter: false} // don't sort chevrons
                }
            });

            return this;
        },

        removeSelf: function() {
            this.unbind();
            this.$el.empty();
            this.undelegateEvents();
            return this;
        }
    });
});
