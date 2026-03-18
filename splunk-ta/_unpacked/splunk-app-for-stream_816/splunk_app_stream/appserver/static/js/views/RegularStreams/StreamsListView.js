define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "app-js/contrib/jquery.sparkline",
    "contrib/text!app-js/templates/RegularStreams/StreamsListTemplate.html",
    "app-js/contrib/jquery.tablesorter.min",
    "app-js/views/ConfirmView",
    "app-js/views/RegularStreams/PermanentStreamRowView",
    "swc-stream/index"
], function(
    $,
    _,
    Backbone,
    Sparklines,
    StreamsListTemplate,
    Tablesorter,
    ConfirmView,
    PermanentStreamRowView,
    index
    ) {
    const Popdown = index.Popdown;
    const mvc = index.mvc;
    const utils = index.utils;
    const SearchManager = index.SearchManager;
    const CSRFProtectionUtil = index.CSRFProtectionUtil;

    return Backbone.View.extend({

        initialize: function(options){

            console.log('Streams List View created');

            var viewRef       = this;
            this.options      = _.extend({}, this.options, options);
            this.app          = this.options.app;
            this.template     = _.template($(StreamsListTemplate).html());
            this.isPacket     = this.options.isPacket;

            this.collection.comparator = function( model ) {
                return model.get( 'id' );
            };

        },

        events: {
            'click input.stream-select'       : 'showBulkEditOptions',
            "keyup #reg-stream-search"        : "filterTable",
            'click .main-page-search a.clear' : 'resetSearch',
            'click #bulkDelete'               : 'bulkDelete',
            'click #bulkDisable'              : 'bulkDisable',
            'click #bulkEnable'               : 'bulkEnable',
            'click #bulkStatsOnly'            : 'bulkStatsOnly',
            'click .streams-select-all'       : 'bulkSelectStreams'
        },

        resetSearch: function(e) {
            e.preventDefault();
            $('#reg-stream-search').val('');
            this.app.mediator.publish("search-filtered", '');
            this._checkIfAllStreamsSelected();
        },

        filterTable: function () {
            var searchString = $('#reg-stream-search').val();
            this.app.mediator.publish("search-filtered", searchString);
            this._checkIfAllStreamsSelected();
        },

        showBulkEditOptions: function () {
            var selectedStreams = this.getSelectedStreams();
            if (selectedStreams.length > 0){
                $("#num-streams-selected .num").html(selectedStreams.length);
                $("#regular-streams-bulk-edit-controls").css("visibility", "visible");
            } else {
                $("#regular-streams-bulk-edit-controls").css("visibility", "hidden");
            }
            this._checkIfAllStreamsSelected();
        },

        bulkSelectStreams: function(e) {
            if ($(e.target).is(":checked")) {
                $('.stream-select:visible').each(function() {
                    this.checked = true;
                });
            } else {
                $('.stream-select:visible').each(function() {
                    this.checked = false;
                });
            }
            this.showBulkEditOptions();
        },

        getSelectedStreams: function() {
            var self = this;
            var streams = [];
            $('.stream-select:checked').each(function() {
                var streamId = $(this).closest('tr').data('id');
                var stream = self.collection.get(streamId);
                //Exclude external streams.
                if (stream.get('app') && stream.get('app') === 'Stream') {
                    streams.push(stream);
                }
            });
            return streams;
        },

        bulkDelete: function(e) {
            e.preventDefault()
            var streams = this.getSelectedStreams();
            if (streams.length > 0) {
                this.app.mediator.publish("view:bulk-delete-streams-dialog", {
                    streams: streams,
                    location: Backbone.history.fragment
                });
            } else {
                this.app.mediator.publish("view:info-dialog", "No selection made!", "Please select a stream");
            }
        },

        bulkDisable: function(e) {
            e.preventDefault()
            var streams = this.getSelectedStreams();
            if (streams.length > 0) {
                this.app.mediator.publish("view:bulk-disable-streams-dialog", {
                    streams: streams,
                    location: Backbone.history.fragment
                });
            } else {
                this.app.mediator.publish("view:info-dialog", "No selection made!", "Please select a stream");
            }
        },

        bulkEnable: function(e) {
            e.preventDefault()
            var streams = this.getSelectedStreams();
            if (streams.length > 0) {
                this.app.mediator.publish("view:bulk-enable-streams-dialog",{
                    streams: streams,
                    location: Backbone.history.fragment
                });
            } else {
                this.app.mediator.publish("view:info-dialog", "No selection made!", "Please select a stream");
            }
        },

        bulkStatsOnly: function(e) {
            e.preventDefault()
            var streams = this.getSelectedStreams();
            if (streams.length > 0) {
                this.app.mediator.publish("view:bulk-stats-only-streams-dialog",{
                    streams: streams,
                    location: Backbone.history.fragment
                });
            } else {
                this.app.mediator.publish("view:info-dialog", "No selection made!", "Please select a stream");
            }
        },

        render: function(){

            var self = this;

            var output = self.template({isPacket: self.isPacket });
            this.$el.empty();
            this.$el.append(output);

            var tableBody = self.$("#permanent-streams-tbody");

            this.collection.each(function (eachModel) {

                var newRow = new PermanentStreamRowView({
                    model         : eachModel,
                    app           : self.app
                }).render().$el.appendTo(tableBody);

            });

            $("#config-page-streams-table").tablesorter({
                headers:{
                    //select boxes
                    0: { sorter:false },
                    //actions
                    2: { sorter:false },
                    //mode
                    3: { sorter:false },
                    //sparklines
                    8: { sorter:false }
                },
                //sort the name column in ascending order case-insensitive
                sortList:[[1,0]]
            });

            this.showSparklines();

            return self;
        },

        /*
         * Kicks off a continuous loop, calling a search manager for stream-stats data every X seconds,
         * and updating all sparklines on the page each time.
         */
        showSparklines: function() {
            var self = this;

            /*==========================================
            =            Sparkline Promises            =
            ==========================================*/
            // promise holds all the logic for sparkline creation.
            // jump to bottom to see how search manager is managed

            var streamIDs = _.pluck(self.collection.toJSON(), "id");
            var searchPromise = $.Deferred();

            var bindPromiseEvents = function(results) {

                $("#totalSparklineContainer  .loadingMsg").hide();
                $(".stream-row .loadingMsg").hide();

                var fields = results.fields;
                var rows = results.rows;
                //array of 0s
                var totalData = zeroArray(rows.length);

                /*==========  Create Individual Sparklines  ==========*/
                $(".sparkline").each(function(index, eachSparkline) {

                    var streamId =  $(eachSparkline).closest("tr").data("id");
                    var streamIndex = fields.indexOf(streamId);

                    var data = [];

                    /*==========  Determine data  ==========*/
                    if (streamIndex === -1){
                        //fill w/ zeroes if no data
                        data = zeroArray(rows.length);
                    } else {
                        //keep track of current data as well as totalData for the large sparkline
                        _.each(rows,function(eachRow, index_num) {
                            if (eachRow[streamIndex]){
                                var value = roundNplaces(eachRow[streamIndex],2);
                                data.push(value);
                                totalData[index_num] += parseFloat(value);
                            }
                            else { data.push(0); }
                        });
                    }

                    /*==========  Create Sparklines  ==========*/
                    $(eachSparkline).sparkline(data,{
                        width: "200px",
                        fillColor: "#CDDEFE",
                        lineColor: "#A8BBD5",
                        spotColor: false,
                        minSpotColor: false,
                        maxSpotColor: false,
                        numberFormatter: function(num) {
                            //num is perMinute traffic so divide by 60 for perSecond rate
                            return self._bitsFormatter(roundNplaces(num/60 * 8,2), true) + "/s";
                        },
                        lineWidth: 1,
                        height: "25px"
                    });

                });

                /*==========  Create the Total Traffic Sparkline  ==========*/
                $("#totalSparkline").sparkline(totalData,{
                    width: "100%",
                    fillColor: "#CDDEFE",
                    lineColor: "#A8BBD5",
                    minSpotColor: false,
                    maxSpotColor: false,
                    numberFormatter: function(num) {
                        //num is perMinute traffic so divide by 60 for perSecond rate
                        return self._bitsFormatter(roundNplaces(num/60 * 8,2), true) + "/s";
                    },
                    height: "80px",
                    lineWidth: 1
                });

                /*==========  Calculate the Avg Traffic  ==========*/
                var sumData = _.reduce(totalData, function(memo, next) {
                    return memo + next;
                })

                //Avg on a per sec. basis -- time range is last 15 minutes
                var avgTraffic = sumData/900;
                var formattedTrafficValue = "~ " + self._bitsFormatter(roundNplaces(avgTraffic * 8,2), true) + "/s";
                $("#avgTraffic").html(formattedTrafficValue);

                function zeroArray(N) {
                    return Array.apply(null, new Array(N)).map(Number.prototype.valueOf,0);
                }
                function roundNplaces(num, N) {
                    var rounder = Math.pow(10,N);
                    return Math.round(num * rounder)/rounder;
                }

            }//end bindPromiseEvents function

            searchPromise.done(bindPromiseEvents);

            /*============================================
            =            Search Manager Logic            =
            ============================================*/

            var sparklineSearch;

            //get existing search manager
            if (mvc.Components.getInstance("sparklineSearch")){
                //don't need to do anything as the search loop has already started
            }
            //else create a new one
            else {
                /*==========  Create Search Manager and resolve promise  ==========*/
                // http://docs.splunk.com/DocumentationStatic/WebFramework/1.0/compref_searchmanager.html
                // http://dev.splunk.com/view/SP-CAAAEU6
                sparklineSearch = new SearchManager({
                    id             : "sparklineSearch",
                    earliest_time  : "-15m", // time range is 16m so as to enable diff. calculation for first minute
                    latest_time    : "now",
                    app            : utils.getCurrentApp(),
                    max_time       : 4,
                    auto_cancel    : 8,
                    search         : '`stream_stats` host=* | spath Output=streamId path=senders{}.streams{}.id | spath Output=streamBytes path=senders{}.streams{}.delta_bytes | fields - _raw | fields _time, host, streamId, streamBytes | eval x=mvzip(streamId, streamBytes) | mvexpand x | eval x = split(x,",") | eval streamId=mvindex(x,0) | eval streamBytes=mvindex(x,1) | stats sum(streamBytes) as sumStreamBytes by streamId, _time, host | timechart span=1m limit=0 sum(sumStreamBytes) by streamId'
                });

                sparklineSearch.on("search:done", function(state, job) {

                    /*==========  If data is found  ==========*/
                    if (state.content.resultCount > 0){

                        job.results({count:0}, function(error, data){

                            var results = {
                                fields : data.fields,
                                rows   : data.rows
                            }
                            searchPromise.resolve(results);
                            rerunSearch();
                        });
                    }

                    /*==========  If no data is found  ==========*/
                    else{
                        //resolve it with 0 data for a straight line
                        var data = {
                            fields : [0,0,0,0],
                            rows   : [0,0,0,0]
                        }
                        searchPromise.resolve(data);
                        rerunSearch();
                    }

                    function rerunSearch(){
                        setTimeout(function() {
                            sparklineSearch.cancel();
                            sparklineSearch.startSearch();
                            //reset and rebind promise
                            searchPromise = $.Deferred();
                            searchPromise.done(bindPromiseEvents);
                        }, 10000)
                    }

                });
            }

        },

        _bitsFormatter: function(bits, si) {
            var thresh = si ? 1000 : 1024;
            if(bits < thresh) return bits + ' B';
            var units = si ? ['kb','Mb','Gb','Tb','Pb','Eb','Zb','Yb'] : ['Kib','Mib','Gib','Tib','Pib','Eib','Zib','Yib'];
            var u = -1;
            do {
                bits /= thresh;
                ++u;
            } while(bits >= thresh);
            return bits.toFixed(1)+' '+units[u];
        },

        _checkIfAllStreamsSelected: function() {
            //Check if all visible streams are selected
            var visibleStreams = $('.stream-select:visible');
            var allChecked = _.every(visibleStreams, function(s) { return s.checked; });
            $('.streams-select-all').prop('checked', allChecked && visibleStreams.length);
        },

        removeSelf: function () {
            console.log("Removing StreamListView");
            // empty the contents of the container DOM element without taking it out of the DOM

            this.unbind();

            this.$el.empty();
            // clears all callbacks previously bound to the view with delegateEvents method
            // (I would expect stopListening to do the job but it doesn't)
            this.undelegateEvents();

            return this;
        }

    });
});
