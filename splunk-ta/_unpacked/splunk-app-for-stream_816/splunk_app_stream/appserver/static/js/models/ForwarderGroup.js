define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "swc-stream/index"
], function(
    $,
    _,
    Backbone,
    index
    ) {
    const SplunkUtils = index.SplunkUtils;
    return Backbone.Model.extend({

        urlRoot: SplunkUtils.make_url([
            "custom",
            "splunk_app_stream",
            "streamforwardergroups"
        ].join('/')),

        initialize: function () {

        },

        defaults: {

            // id      : "",
            // description : "",
            // enabled : true,
            // rule    : "",
            // streams : [],
            // includeEphemeralStreams : true,
            // hec : {}

            // TODO: The FowarderGroup model should use a model for hec
            // e.g. hec: new HttpEventCollectorConfig()
        },

        validate: function (attrs, options) {

            var errors = [];

            errors = errors.concat(this.validateBasic(attrs));
            errors = errors.concat(this.validateRegex(attrs.rule));

            return errors.length > 0 ? errors: false

        },

        validateBasic: function (attrs) {

            var errors = [];

            //due to cherrypy conflict over name 'default'
            if (attrs.id === "default") {
                errors.push("Name can't be 'default'");
            }
            if (!attrs.id) {
                errors.push("Name is required");
            }
            if (attrs.id && !attrs.id.match(/^\w+$/)) {
                errors.push("Please specify a name using only letters, digits and underscores ('_')");
            }
            if (!attrs.description) {
                errors.push("Description is required");
            }
            if (attrs.id.indexOf(' ') >= 0) {
                errors.push("No whitespace allowed in name");
            }

            //validate endpoint urls
            if (!attrs.hec.autoConfig) {

                if (attrs.hec.urls.length == 0) {
                    errors.push("Http endpoint urls are required");
                }

                var parsedUrls = [];

                _.each(attrs.hec.urls, function(url) {

                    if (!url.match(/^https?:\/\//)) {
                        errors.push("Url needs valid http protocol: " + url);

                    } else if (!url.match(/^https?:\/\/[^<>\s]+$/)) {
                        errors.push("Invalid http endpoint url: " + url);

                    } else {
                        var offset = url.match(/^http:/) ? 7 : 8;
                        parsedUrls.push(url.substring(offset));
                    }
                });

                var urlCounter = _.countBy(parsedUrls);

                for (var url in urlCounter) {
                    if (urlCounter[url] > 1) {
                        errors.push("Duplicate url detected: http(s)://" + url);
                    }
                }
            }

            return errors;
        },

        validateRegex: function (regexString, isNewGroup) {

            var errors = [];

            if (isNewGroup && regexString === "") {
                errors.push("Regex rule cannot be blank");
            }

            var isValidRegex;
            try {
                new RegExp(regexString);
                isValidRegex = true;
            } catch(e) {
                isValidRegex = false;
            }

            if (!isValidRegex) {
                errors.push("Regex is invalid");
            }

            return errors;
        }

    });
});
