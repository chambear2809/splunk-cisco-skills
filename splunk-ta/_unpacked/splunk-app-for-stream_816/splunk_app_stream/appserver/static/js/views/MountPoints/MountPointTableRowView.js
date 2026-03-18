define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "contrib/text!app-js/templates/MountPoints/MountPointTableRowTemplate.html",
    "app-js/views/MountPoints/EditMountPointView",
    "app-js/views/ConfirmView",
    "swc-stream/index"
], function(
    $,
    _,
    Backbone,
    MountPointTableRowTemplate,
    EditMountPointView,
    ConfirmView,
    index
    ) {
    const Popdown = index.Popdown;
    return Backbone.View.extend({

        tagName: 'tr',
        className: 'mount-point-table-row',

        //this attribute unneeded, but useful for selenium testing.
        attributes: function() {
            return {
                'data-id': this.model.get('id')
            }
        },

        initialize: function(options) {
            this.app       = options.app;
            this.template  = _.template($(MountPointTableRowTemplate).html());
            this.model     = options.model;

            var self = this;
            this.app.mediator.subscribe("search-filtered", function(searchString) {
                self._showHideBasedOnRegex(searchString);
            });
            this.listenTo(this.model, 'change', function() {
                self.render();
            })
        },

        //show/hide this row based on user input
        _showHideBasedOnRegex: function(searchString) {
            var self = this;
            var regex = new RegExp(searchString, "i");

            // show if regex matches any of these strings.
            var matchCases = _.flatten([
                self.model.get('id'),
                self.model.get('mount_point')
            ]);

            var regexMatches = _.some(_.map(matchCases, function(str) {
                return regex.test(str);
            }));

            if (regexMatches) {
                self.$el.show();
            } else {
                self.$el.hide();
            }
        },

        events: {
            'click .mount-point-edit'   : 'editMountPoint',
            'click .mount-point-delete' : 'deleteMountPoint'
        },

        editMountPoint: function(e) {
            e.preventDefault();
            var editMountPointView = new EditMountPointView({
                mountPointModel: this.model
            }).show();
        },

        deleteMountPoint: function(e) {
            e.preventDefault();
            var thisModel = this.model;
            var self = this;

            var confirmView = new ConfirmView({
                action  : "delete",
                model   : {text: this.model.get('id')},
                command : function() {
                    thisModel.destroy({
                        success: function(model, response) {console.log(model, " was successfully destroyed"); },
                        error: function() {
                            alert("error: failed to delete");
                            location.reload();
                        }
                    })
                }
            }).show();
        },

        render: function() {
            var self = this;

            this.$el.html(self.template({
                model: this.model.toJSON()
            }));

            new Popdown({el: this.$(".mount-point-action-popdown")});

            if (! this.model.has('mount_point') || this.model.get("mount_point") == '')
                $(this.el).addClass('missing-mount-point')

            return self;
        },

        removeSelf: function() {
            this.unbind();
            this.$el.empty();
            this.undelegateEvents();
            return this;
        }
    });
});
