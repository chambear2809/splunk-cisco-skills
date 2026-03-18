define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "app-js/models/Stream",
    "swc-stream/index"
], function(
    $,
    _,
    Backbone,
    Stream,
    index
    ) {

    const SplunkUtils = index.SplunkUtils;
    const CurrentContexts = index.CurrentContexts;
    return Backbone.Collection.extend({
        model: Stream,
        url: SplunkUtils.make_url([
            "custom",
            "splunk_app_stream",
            "streams?repository=true"
        ].join('/')),

        returnPermanentStreams: function () {
            var filtered = this.filter(function (eachModel) {
                return !_.has(eachModel.attributes, 'expirationDate');
            })
            return new this.constructor(filtered);
        },

        returnMetadataStreams: function () {
            var filtered = this.filter(function (eachModel) {
                return !_.has(eachModel.attributes, 'expirationDate') &&
                (!_.has(eachModel.attributes, 'isPacketStream') || eachModel.attributes.isPacketStream === false);
            })
            return new this.constructor(filtered);
        },

        returnPacketStreams: function () {
            var filtered = this.filter(function (eachModel) {
                return (!_.has(eachModel.attributes, 'expirationDate') && eachModel.attributes.isPacketStream);
            })
            return new this.constructor(filtered);
        },

        //orders collection by whether or not each model is contained in 'streams'
        //returns array instead of collection to avoid collection automatically re-ordering
        //this way, user selected streams will appear on top first.
        sortByContains: function (streams) {
            var sorted = this.sortBy(function (eachModel) {
                if (_.contains(streams, eachModel.get('id'))) {
                    return 0;
                } else {
                    return 1;
                }
            }).map(function (eachModel) {
                return eachModel.toJSON();
            });
            return sorted;

        },

        returnGroupedEphemeralStreamsPromise: function () {

            // 1. Filter for Ephemeral streams
            // 2. Group based on category
            // 3. Append additional time information (uses a splunk search so we return a promise.)
            // 4. Create a new array of elements with combined time & model info.

            var ephemeralModels = this.filter(function(eachModel){
                return eachModel.get('expirationDate');
            })

            var groupedModels = _.groupBy(ephemeralModels,function(model) {
                return model.attributes.category;
            })

            var groupsWithTimeInfo = [];

            _.each(groupedModels,function(group,key) {

                // We show only the max-min time for each group of ephemeral streams.
                var maximum = _.chain(group).map(function(each) {return each.attributes.expirationDate; }).max().value();
                var minimum = _.chain(group).map(function(each) {return each.attributes.createDate; }).min().value();

                // Figure out status of the group. (should theoretically be all-enabled or all-disabled.)
                var status = "Mixed"

                var allEnabled = _.every(group,function(each){ return each.attributes.enabled === true });
                if (allEnabled) { status = "Enabled"; }

                var allDisabled = _.every(group,function(each){ return each.attributes.enabled === false });
                if (allDisabled){ status = "Disabled"; }

                //create a new element
                var thisElement = {};

                thisElement.models        = _.pluck(group,"attributes");
                thisElement.earliestTime  = utcToString(minimum);
                thisElement.latestTime    = utcToString(maximum);
                thisElement.name          = key;
                thisElement.numStreams    = thisElement.models.length;
                thisElement.application   = group[0].attributes.app; //app should be the same for all, just grab first one
                thisElement.timeRemaining = secondsToString(maximum - Math.floor(Date.now() / 1000));
                thisElement.status        = status;

                groupsWithTimeInfo.push(thisElement);

                /*==========  Helper functions ==========*/

                function utcToString(seconds){
                    var d = new Date(0);
                    d.setUTCSeconds(seconds);
                    return d.toISOString();
                }

                function secondsToString(seconds){
                    var seconds = Number(seconds);
                    var d = Math.floor(seconds / (3600 * 24))
                    var h = Math.floor(seconds % (3600 * 24) / 3600);
                    var m = Math.floor(seconds % 3600 / 60);
                    return ( (d > 0 ? d + "d " : "") + (h > 0 ? h + "h " : "") + (m > 0 ? m + "m " : ""));
                }

            })

            var timezonePromise = $.Deferred();
            var context = new CurrentContexts();
            context.fetch({
                success: function(data){
                    var timezone;
                    try {
                        timezone = data.fetchXhr.responseJSON.entry[0].content.tz;
                    }
                    catch(e) {
                        console.log("Timezone fetch failure: defaulting to system timezone.");
                        timezone = null;
                    }
                    timezonePromise.resolve({
                        timezone: timezone,
                        ephemeralStreamGroups: groupsWithTimeInfo
                    });
                },
                error: function() {
                    console.log('failed to get timezone');
                }
            })

            return timezonePromise;

        },

        comparator: 'id'
    });
});
