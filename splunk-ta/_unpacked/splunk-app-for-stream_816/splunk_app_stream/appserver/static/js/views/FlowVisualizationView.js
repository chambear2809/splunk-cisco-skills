define([
    "app-js/contrib/jquery",
    "app-js/contrib/underscore",
    "app-js/contrib/backbone",
    "swc-stream/index",
    'app-js/contrib/heatmap.min',
    'contrib/text!app-js/templates/FlowVisualizationTemplate.html'
    ],
    function(
        $,
        _,
        Backbone,
        index,
        Heatmap,
        FlowVisualizationTemplate
        ) {

        const mvc = index.mvc;
        const utils = index.utils;
        const DashboardController = index.DashboardController;
        const DropdownView = index.DropdownView;
        const Visualizations = index.Visualizations;
        const VisualizationRegistry = index.VisualizationRegistry;


        const TableView =index.TableView;
        const TimeRangeView = index.TimeRangeView;
        const TimelineView = index.TimelineView;
        const SearchManager = index.SearchManager;

        return Backbone.View.extend({

        initialize: function(options){
            this.options = _.extend({}, this.options, options);
            this.template = _.template($(FlowVisualizationTemplate).html());

            this.isRealTimeSearch = true;
            this.isHeatmapVisible = false;
            this.heatmapSearchResults = [];
            this.playbackState = 'stop'; //play, pause, stop, done
            this.startWindowTime = 0;
        },

        events: {
            'click .icon-play'  : 'playPlayback',
            'click .icon-pause' : 'pausePlayback',
            'click .icon-stop'  : 'stopPlayback',

            'click .heatmap-tooltip' : 'showIpTable'
        },

        getTimelineSearchQuery: function () {
            var query = 'index=* source=stream:Splunk_IP';
            return query;
        },

        getHeatmapSearchQuery: function () {
            var query = 'index=* source=stream:Splunk_IP' +
                ' | rex field=src_ip \"(?<src1>.*)\\.(?<src2>.*)\\.(?<src3>.*)\\.(?<src4>.*)\"' +
                ' | where src1 NOT null' +
                ' | rex field=dest_ip \"(?<dest1>.*)\\.(?<dest2>.*)\\.(?<dest3>.*)\\.(?<dest4>.*)\"' +
                ' | where dest1 NOT null' +
                ' | eval unixTime=strptime(timestamp, "%FT%T.%6NZ")' +
                ' | eval sum(packets) = $sum(packets_in)$ + $sum(packets_out)$' +
                ' | eventstats sum(sum(bytes)) as sum_bytes, sum(sum(packets)) as sum_packets, sum(count) as sum_flows by src1, dest1, src2, dest2' +
                ' | table sum_bytes sum_packets sum_flows src1 dest1 src2 dest2 unixTime _time' +
                ' | dedup src1 dest1 src2 dest2';
            return query;
        },

        getIpTableSearchQuery: function (srcRange1, srcRange2, destRange1, destRange2) {
            var src2Operator = srcRange2[1] > srcRange2[0] ? 'AND' : 'OR';
            var dest2Operator = destRange2[1] > destRange2[0] ? 'AND' : 'OR';
            var query = 'index=* source=stream:Splunk_IP' +
                ' | rex field=src_ip \"(?<src1>.*)\\.(?<src2>.*)\\.(?<src3>.*)\\.(?<src4>.*)\"' +
                ' | where src1 NOT null' +
                ' | rex field=dest_ip \"(?<dest1>.*)\\.(?<dest2>.*)\\.(?<dest3>.*)\\.(?<dest4>.*)\"' +
                ' | where dest1 NOT null' +
                ' | search src1 >= ' + srcRange1[0].toString() + ' AND src1 <= ' + srcRange1[1].toString() +
                ' AND src2 >= ' + srcRange2[0].toString() + ' ' + src2Operator + ' src2 < ' + srcRange2[1].toString() +
                ' AND dest1 >= ' + destRange1[0].toString() + ' AND dest1 <= ' + destRange1[1].toString() +
                ' AND dest2 >= ' + destRange2[0].toString() + ' ' + dest2Operator + ' dest2 < ' + destRange2[1].toString() +
                ' | eval sum(packets) = $sum(packets_in)$ + $sum(packets_out)$' +
                ' | eventstats sum(sum(bytes)) as sum_bytes, sum(sum(packets)) as sum_packets, sum(count) as sum_flows by src_ip dest_ip' +
                ' | table src_ip dest_ip sum_bytes sum_packets sum_flows' +
                ' | dedup src_ip dest_ip' +
                ' | rename src_ip AS "Source IP" dest_ip AS "Destination IP" sum_bytes as "Total Bytes" sum_packets as "Total Packets" sum_flows as "Total Flows"';
            return query;
        },
        playPlayback: function() {
            if (this.isHeatmapVisible && this.playbackState != 'play') {
                var heatmapData = this.generateHeatmapData();
                if (this.playbackState == 'stop' || this.playbackState == 'done') {
                    this.startWindowTime = heatmapData.min - this.getWindowSize(heatmapData);
                    this.showWindowTime(heatmapData.data[0].dateTime);
                }
                this.playbackState = 'play';
                this.scrollThroughData(heatmapData);
            }
        },

        pausePlayback: function () {
            if (this.isHeatmapVisible && this.playbackState == 'play') {
                this.enableTooltips();
                this.playbackState = 'pause';
            }
        },

        stopPlayback: function () {
            if (this.isHeatmapVisible && this.playbackState != 'stop') {
                this.playbackState = 'stop';
                this.hideWindowTime();
                if (this.isRealTimeSearch) {
                    this.clearHeatmap();
                    this.startHeatmapSearch();
                } else {
                    this.updateHeatmap();
                }
            }
        },

        getWindowSize: function (heatmapData) {
            return Math.round((heatmapData.max - heatmapData.min) / 10);
        },

        getWindowIncrement: function (heatmapData) {
            var increment = Math.ceil((heatmapData.max - heatmapData.min) / 300);
            return Math.min(increment, 3600);
        },

        getDisplayDate: function (date) {
            return date.toString().substring(4, 24);
        },

        incrementWindowTimeDisplay: function (heatmapData) {
            var timestamps = this.$('#playback-timestamps').text().split('-');
            var startTime = new Date(timestamps[0]);
            var endTime = new Date(timestamps[1]);
            var increment = this.getWindowIncrement(heatmapData);
            var windowSize = this.getWindowSize(heatmapData);
            endTime = new Date(endTime.getTime() + increment * 1000);
            if (endTime.getTime() - startTime.getTime() >= windowSize * 1000) {
                startTime = new Date(startTime.getTime() + increment * 1000);
            }
            this.$('#playback-timestamps').text(this.getDisplayDate(startTime) + ' - ' + this.getDisplayDate(endTime));
        },

        showWindowTime: function (dateTime) {
            var start = this.getDisplayDate(new Date(dateTime));
            this.$('#playback-timestamps').text(start + ' - ' + start);
            this.$('#playback-timestamps').show();
        },

        hideWindowTime: function () {
            this.$('#playback-timestamps').hide();
        },

        scrollThroughData: function (heatmapData) {
            var self = this;
            if (this.isHeatmapVisible && this.playbackState == 'play') {
                var endWindowTime = this.startWindowTime + this.getWindowSize(heatmapData);
                var windowIncrement = this.getWindowIncrement(heatmapData);
                //if playback has reached the end of the time range, end playback
                if (endWindowTime > heatmapData.max + windowIncrement) {
                    this.enableTooltips();
                    this.playbackState = 'done';
                    return;
                }
                this.clearTooltips();
                this.hideIpInfo();
                var startIndex = 0;
                var windowData = [];
                //find data that exists within the playback window
                for (var i = 0; i < heatmapData.data.length; i++) {
                    var dataPoint = heatmapData.data[i];
                    if (dataPoint.value < this.startWindowTime) {
                        startIndex += 1;
                    } else if (dataPoint.value <= endWindowTime) {
                        windowData.push(dataPoint);
                        this.generateTooltip(dataPoint);
                    } else {
                        break;
                    }
                }
                //draw data to heatmap canvas
                this.heatmap.setData({
                    min: Math.max(this.startWindowTime, heatmapData.min),
                    max: Math.min(endWindowTime, heatmapData.max),
                    data: windowData
                });
                this.incrementWindowTimeDisplay(heatmapData);
                //alter playback state values for next frame of playback sequence
                heatmapData.data = heatmapData.data.slice(startIndex);
                this.startWindowTime += windowIncrement;
                //continuously scroll through time range
                setTimeout(function () { self.scrollThroughData(heatmapData); }, 100);
            }
        },

        generateHeatmapData: function () {
            this.clearTooltips();
            var width = this.$('#heatmap-container').width();
            var height = this.$('#heatmap-container').height();
            var results = this.heatmapSearchResults;
            var data = [];
            var minTime = Infinity;
            var maxTime = 0;
            var resultToInt = function (x) { return parseInt(x); };

            for (var i = 0; i < results.length; i++) {

                var row = _.map(results[i], resultToInt);

                var sum_bytes = row[0];
                var sum_packets = row[1];
                var sum_flows = row[2];
                var src1 = row[3];
                var dest1 = row[4];
                var src2 = row[5];
                var dest2 = row[6];
                var time = row[7];
                var dateTime = results[i][8];

                //Don't add data point if sum_bytes is not an integer
                if (!(typeof sum_bytes === 'number' && sum_bytes % 1 === 0)) {
                    continue;
                }

                //Check if time is min or max time
                minTime = Math.min(minTime, time);
                maxTime = Math.max(maxTime, time);

                //Scale src_ip and dest_ip values to fit within chart
                src = src1 * 1000 + src2;
                dest = dest1 * 1000 + dest2;
                var x = Math.floor(src * width / 255255);
                var y = height - Math.floor(dest * height / 255255);

                //Get date string for playback display
                dateTime = dateTime.split(/T|\./).slice(0, 2);
                dateTime = dateTime.join(' ');

                var dataPoint = {
                    //data for heatmapjs
                    x: x,
                    y: y,
                    value: time,
                    //data for tooltips
                    src_ips: [src1 + '.' + src2],
                    dest_ips: [dest1 + '.' + dest2],
                    sum_bytes: [sum_bytes],
                    sum_packets: [sum_packets],
                    sum_flows: [sum_flows],
                    //data for playback
                    dateTime: dateTime
                };

                data.push(dataPoint);
            }
            data = this.formatHeatmapData(data);
            return {min: minTime, max: maxTime, data: data};
        },

        formatHeatmapData: function (data) {
            var self = this;
            //if two data points map to the same x, y location, merge them into a single data point
            data = _.groupBy(data, function(a) { return a.x + a.y * 0.001; });
            var maxRadius = 0;
            var selectedMetric = this.metricPicker.val();
            var add = function (a, b) { return a + b; };
            data = _.map(_.values(data), function(dataPoints) {
                var aggPoint = _.reduce(dataPoints, function(a, b) {
                    a.src_ips = a.src_ips.concat(b.src_ips);
                    a.dest_ips = a.dest_ips.concat(b.dest_ips);
                    a.sum_bytes = a.sum_bytes.concat(b.sum_bytes);
                    a.sum_packets = a.sum_packets.concat(b.sum_packets);
                    a.sum_flows = a.sum_flows.concat(b.sum_flows);
                    return a;
                });
                if (selectedMetric === 'bytes') {
                    aggPoint.radius = aggPoint.sum_bytes.reduce(add, 0);
                } else if (selectedMetric === 'packets') {
                    aggPoint.radius = aggPoint.sum_packets.reduce(add, 0);
                } else {
                    aggPoint.radius = aggPoint.sum_flows.reduce(add, 0);
                }
                maxRadius = Math.max(maxRadius, aggPoint.radius);
                return aggPoint;
            });

            //logarithmically normalize data point sizes between 8 and 30
            var maxLogRadius = Math.log10(maxRadius);
            _.each(data, function(p) {
                p.radius = (Math.log10(p.radius) / maxLogRadius) * 8;
                p.radius = Math.round(p.radius) * 3 + 6;
                self.generateTooltip(p);
            });

            //sort data in ascending order based on timestamp
            return data.sort(function(a, b) { return a.value - b.value; });
        },

        updateHeatmap: function () {
            this.$('#heatmap-waiting-container').hide();
            this.$('#heatmap-not-found-container').hide();
            this.$('.heatmap-labels').show();
            var heatmapData = this.generateHeatmapData();
            this.heatmap.setData(heatmapData);
            if (heatmapData.data.length === 0) {
                this.showNoResultsFound();
            } else {
                this.enableTooltips();
                this.isHeatmapVisible = true;
            }
        },

        clearHeatmap: function () {
            this.hideIpInfo();
            this.$('.heatmap-labels').hide();
            this.$('#heatmap-not-found-container').hide();
            this.$('#heatmap-waiting-container').show();
            this.heatmap.setData({data: []});
            this.isHeatmapVisible = false;
            this.playbackState = 'stop';
            this.hideWindowTime();
        },

        showNoResultsFound: function () {
            this.hideIpInfo();
            this.$('.heatmap-labels').hide();
            this.$('#heatmap-waiting-container').hide();
            this.$('#heatmap-not-found-container').show();
            this.isHeatmapVisible = false;
            this.playbackState = 'stop';
            this.hideWindowTime();
        },

        startHeatmapSearch: function() {
            this.heatmapSearch.startSearch();
        },

        generateTooltip: function (data) {
            var tooltip = $('<div/>');
            //setup tooltip config
            var dataPlacement = data.y > 80 ? 'top' : 'bottom';
            tooltip.addClass('heatmap-tooltip');
            tooltip.attr('data-toggle', 'tooltip');
            tooltip.attr('data-placement', dataPlacement);
            //add text to tooltip
            tooltip.attr('title', this.getTooltipText(data));
            //center the div on the datapoint
            tooltip.css('left', data.x - 4);
            tooltip.css('top', data.y - 4);
            this.$('#heatmap-tooltips-container').append(tooltip);
        },

        getTooltipText: function (data) {
            var selectedMetric = this.metricPicker.val();
            var sum_metrics = data.sum_flows;
            if (selectedMetric === 'bytes') {
                sum_metrics = data.sum_bytes;
            } else if (selectedMetric === 'packets') {
                sum_metrics = data.sum_packets;
            }
            //sort relevant data on sum_metrics value: [[src_ip, dest_ip, max_sum], ..., ['', '', min_sum]]
            var sortedData = _.zip(data.src_ips, data.dest_ips, sum_metrics).sort(function (a, b) { return b[2] - a[2]; });
            var tooltipText = '';
            for (var i = 0; i < Math.min(5, sortedData.length); i++) {
                if (i !== 0) tooltipText += '\n';
                //construct tooltip text
                var ipDisplay = sortedData[i][0] + ' → ' + sortedData[i][1];
                var metricDisplay = sortedData[i][2] + ' ';
                //remove plurality if sum_metric is 1
                metricDisplay += sortedData[i][2] == 1 ? this.metricPicker.val().slice(0, -1) : this.metricPicker.val();
                tooltipText += ipDisplay + '\n' + metricDisplay;
            }
            if (sortedData.length > 5) {
                tooltipText += '\n\n+' + (sortedData.length-5) + ' more';
            }
            return tooltipText;
        },

        enableTooltips: function () {
            this.$('[data-toggle="tooltip"]').tooltip();
        },

        clearTooltips: function () {
            this.$('#heatmap-tooltips-container').empty();
        },

        showIpTable: function (e) {
            var width = this.$('#heatmap-container').width();
            var height = this.$('#heatmap-container').height();
            var x = parseInt($(e.target).css('left').replace(/[^\d]/g, '')) + 4;
            var y = parseInt($(e.target).css('top').replace(/[^\d]/g, '')) + 4;

            //Find min and max ip values that map to the clicked x and y location
            var srcMin = 255255 * x / width;
            var srcMax = 255255 * (x + 1) / width;
            var srcRange1 = [Math.floor(srcMin / 1000), Math.floor(srcMax / 1000)];
            var srcRange2 = [Math.floor(srcMin % 1000), Math.floor(srcMax % 1000)];

            var destMin = 255255 * (1 - (y / height));
            var destMax = 255255 * (1 - ((y - 1) / height));
            var destRange1 = [Math.floor(destMin / 1000), Math.floor(destMax / 1000)];
            var destRange2 = [Math.floor(destMin % 1000), Math.floor(destMax % 1000)];

            //Show crosshair to indicate which blot is selected
            this.$('#heatmap-crosshair').show();
            this.$('#heatmap-crosshair-horizontal').css('top', y);
            this.$('#heatmap-crosshair-vertical').css('left', x);
            this.$('#heatmap-crosshair-circle').css({'left': x-4, 'top': y-4});

            var ipTableSearchQuery = this.getIpTableSearchQuery(srcRange1, srcRange2, destRange1, destRange2);
            this.ipInfoSearch.search.set({search: ipTableSearchQuery});
            this.ipInfoTable.render();
            this.ipInfoTable.show();
        },

        hideIpInfo: function () {
            this.$('#ipInfoTable').hide();
            this.$('#heatmap-crosshair').hide();
        },

        render: function () {

            var that = this;
            this.$el.html(this.template({}));

            //
            // SEARCH MANAGERS
            //

            this.timelineSearch = new SearchManager({
                id: 'timelineSearch',
                autostart: true,
                status_buckets: 300,
                earliest_time: mvc.tokenSafe('$timeRange.earliest_time$'),
                latest_time: mvc.tokenSafe('$timeRange.latest_time$'),
                search: that.getTimelineSearchQuery()
            });

            this.heatmapSearch = new SearchManager({
                id: 'heatmapSearch',
                autostart: true,
                app: utils.getCurrentApp(),
                earliest_time: '-1h',
                latest_time: 'now',
                cache: true,
                preview: true,
                search: that.getHeatmapSearchQuery()
            });

            this.ipInfoSearch = new SearchManager({
                id: 'ipInfoSearch',
                earliest_time: mvc.tokenSafe('$timeRange.earliest_time$'),
                latest_time: mvc.tokenSafe('$timeRange.latest_time$')
            });

            //
            // VIEWS: FORM INPUTS
            //

            this.timeRange = new TimeRangeView({
                id: 'time-input',
                managerid: 'timelineSearch',
                value: mvc.tokenSafe('$timeRange$'),
                default: {'earliest_time': 'rt-1h', 'latest_time': 'rt'},
                el: this.$('#time-input')
            }).render();

            this.metricPicker = new DropdownView({
                id: 'metric-dropdown',
                default: 'flows',
                choices: [
                    {value: 'flows', label: 'flows'},
                    {value: 'bytes', label: 'sum(bytes)'},
                    {value: 'packets', label: 'sum(packets)'}
                ],
                showClearButton: false,
                el: this.$('#metric-dropdown')
            }).render();

            //
            // FORM INPUTS EVENTS
            //

            this.timeRange.on('change', function () {
                that.clearHeatmap();
                var range = that.timeRange.val();
                this.isRealTimeSearch = range.latest_time == 'rt';
                if (this.isRealTimeSearch) {
                    range.earliest_time = range.earliest_time.substring(2);
                    range.latest_time = 'now';
                }
                that.heatmapSearch.search.set(range);
            });

            this.metricPicker.on('change', function() {
                var isVisible = that.isHeatmapVisible;
                that.clearHeatmap();
                if (isVisible) {
                    that.updateHeatmap();
                }
            });

            //
            // VIEWS: TIMELINE
            //

            this.timeline = new TimelineView({
                id: 'timeline',
                managerid: 'timelineSearch',
                value: mvc.tokenSafe('$timeRange$'),
                el: this.$('#timeline')
            }).render();

            //
            // VIEWS: TABLE
            //

            const visualizationCollection = new Visualizations();
            const VisCollection =  visualizationCollection.fetch({data: {count:-1}});

            VisCollection.done(function () {
                var self2 = that;
                const viz_prom = VisualizationRegistry.registerVisualizationsCollection({
                    collection:{
                        visualizations:visualizationCollection
                    }
                })

                viz_prom.then(function(){
                    self2.ipInfoTable = new TableView({
                        id: 'ipInfoTable',
                        managerid: 'ipInfoSearch',
                        value: mvc.tokenSafe('$timeRange$'),
                        pageSize: 10,
                        drilldown: "row",
                        el: self2.$('#ipInfoTable')
                    });
        
                    self2.ipInfoTable.on("click", function (e) {
                        e.preventDefault();
                        var query = 'search index=* source=stream:*' +
                            ' src_ip=' + e.data['row.Source IP'] +
                            ' dest_ip=' + e.data['row.Destination IP'];
                        var timeRange = '&earliest=' + e.data['earliest'] +
                            '&latest=' + e.data['latest'];
                        window.open("search?q=" + query + timeRange, "_blank");
                    });
        
                    self2.hideIpInfo();
                })
            })
            
            // Add minimal timeout to ensure container is ready before heatmap initialization
            setTimeout(function() {
                that.heatmap = Heatmap.create({
                  container: that.$('#heatmap-container')[0],
                  gradient: {1.0: "blue"},
                  maxOpacity: 1,
                  minOpacity: 0.1,
                  blur: 0.9
                });
            }, 10);

            this.heatmapSearch.on("search:done", function (state, job) {
                if (that.playbackState == 'stop') {
                    if (state.content.resultCount > 0) {
                        job.results({ count: 0 }, function (error, data) {
                            that.heatmapSearchResults = data.rows;
                            that.updateHeatmap();
                        });
                    } else {
                        that.showNoResultsFound();
                    }
                    if (that.isRealTimeSearch) {
                        setTimeout(function () { that.startHeatmapSearch(); }, 10000);
                    }
                }
            });

            this.$(window).resize(function () {
                if (this.isHeatmapVisible) {
                    this.clearHeatmap();
                    this.updateHeatmap();
                }
            });

            return this;
        }
    });
});
