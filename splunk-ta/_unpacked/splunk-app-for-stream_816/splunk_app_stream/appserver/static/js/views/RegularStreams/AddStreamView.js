define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "app-js/models/Stream",
    "app-js/models/Extras",
    "contrib/text!app-js/templates/RegularStreams/AddStreamTemplate.html",
    "swc-stream/index"
], function(
    $,
    _,
    Backbone,
    Stream,
    Extras,
    AddStreamTemplate,
    index
    ) {
    const SplunkUtils = index.SplunkUtils;
    return Backbone.View.extend({

        className: 'modal',

        initialize: function(options){
            this.options = _.extend({}, this.options, options);
            this.template = _.template($(AddStreamTemplate).html());
            this.app = this.options.app;
            this.selectedStream = this.options.stream;
            this.userHasChanges = this.options.userHasChanges;
        },

        events: {
            'click .yes': 'yes',
            'click .cancel': 'cancel'
        },

        cancel: function() {
            this.remove();
        },

        show: function(){
            //deep copy the collection
            var collectionCopy = $.extend(true, {}, this.app.streams);

            //filter for non-ephemeral streams that are part of Stream-app
            collectionCopy.models = _.filter(this.app.streams.models, function(model) {
                var isEphemeral = ("expirationDate" in model.attributes);
                return (!isEphemeral && (model.attributes.app === "Stream") ) ;
            });

            this.$el.html(this.template({
                streams         : collectionCopy,
                selectedStream  : this.selectedStream,
                userHasChanges  : this.userHasChanges
            }));
            
            this.$el.on('hide', function() {
                this.remove();
            }.bind(this));

            this.$el.modal('show');
            return this;
        },

        yes: function(e) {
            var self = this;
            var data = this.$('form').serializeObject();
            var streamToClone = this.selectedStream || this.app.streams.get(data.streamId);
            var stream = streamToClone.clone();

            e.preventDefault();

            stream.set('id', data.id);
            stream.set('name', data.name);

            stream.set('enabled', false);
            stream.set('isReferenceStream', false);

            if (stream.isValid()) {
                stream.save(null, {
                    type: 'post',
                    url: SplunkUtils.make_url([
                        "custom",
                        "splunk_app_stream",
                        "streams"
                    ].join('/')),
                    success: function(e){
                        console.log('end save...')
                        self.app.pageIsDirty = false;
                        self.app.mediator.publish("event:new-stream-added", stream);
                        self.$el.modal('hide');
                        $('.modal-backdrop').remove();
                        self.remove();
                    },
                    error: function(obj, err){
                        console.log("Error saving stream");
                        alert("Error saving stream: " + err.responseJSON.error);
                    }
                });
            }
            else {
                alert(stream.validationError);
            }
        }

    });
});