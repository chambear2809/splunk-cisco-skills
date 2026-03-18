define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "contrib/text!app-js/templates/MountPoints/EditMountPointTemplate.html"
], function(
    $,
    _,
    Backbone,
    EditMountPointTemplate
    ) {
    return Backbone.View.extend({

        className: 'modal',

        initialize: function(options) {
            this.template        = _.template($(EditMountPointTemplate).html());
            this.create          = options.create;
            this.mountPointModel = options.mountPointModel;
            this.collection      = options.collection;
        },

        events: {
            'click .save'  : 'save',
            'click .cancel': 'cancel'
        },

        show: function() {
            var mountPointModel = this.mountPointModel.toJSON();

            this.$el.html(this.template({
                mountPointModel: mountPointModel,
                create: this.create
            }));

            this.$el.on('hide', function() {
                this.remove();
            }.bind(this))

            this.$el.modal('show');

            return this;
        },

        save: function(e) {
            var self = this;

            // Because model MountPoint has idAttribute = _key, backbone considers the model to be
            // new iff it doesn't contain '_key'.
            // If it's new, we send the id specified by the user, and the server will set '_key' to
            // the same value.
            // If it's not new, then the model already contains 'id', which we shouldn't change.
            // Note that when updating (i.e. !isNew()), backbone will do a PUT with the id included
            // in the URL.  It takes care of calling encodeURIComponent, so we don't have to.
            if (this.mountPointModel.isNew()) {
                var fileServer = $("input.file-server").val();
                if (! fileServer) {
                    alert('Please specify a file server.');
                    return;
                }
                this.mountPointModel.set('id', fileServer);
            }

            var modelJson = {
                mount_point: $("input.mount-point").val()
            };
            if (! modelJson.mount_point) {
                alert('Please specify a mount point.');
                return;
            }

            this.mountPointModel.save(
                modelJson,
                {
                    success: function(model, response) {
                        console.log("model saved", response);
                        if (self.create)
                            self.collection.add(self.mountPointModel);
                        self.$el.modal('hide');
                        self.remove();

                        // If there were query params, e.g. ?file_server=something, remove them now.
                        if (location.search)
                            location = location.origin + location.pathname;
                    },
                    error: function(model, response) {
                        console.log("error editing file server mount point: ", response);
                        alert(response.responseJSON.error);
                    }
                }
            );
        },

        cancel: function() {
            this.remove();
        }
    });
});
