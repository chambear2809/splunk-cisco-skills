require([
    'splunkjs/mvc/chartview',
    'splunkjs/mvc/searchmanager',
    'splunkjs/mvc/simplexml/ready!'
],
    
    function(ChartView,SearchManager){
        // Load individual components
        var SearchManager = require("splunkjs/mvc/searchmanager");
        var tokens = splunkjs.mvc.Components.get("default");
        var ChartView = splunkjs.mvc.Components.get("health");        
    

        ChartView.on("click", function (e) {
            e.preventDefault(); // Prevent redirecting to the Search app
            var site_name = e['data']['click.name2'];

            var mso_host = tokens.get("mso_host_token");
            var mso_site_id = tokens.get("mso_site_token");
            var time_token_earliest = tokens.get("time_token.earliest");
            var time_token_latest = tokens.get("time_token.latest");
            let apic_host = null;
            let apic_platform = null;

            
            var search_query = new SearchManager({
                search: 'eventtype="cisco_dc_nd_mso" mso_api_endpoint=siteHealth mso_host='+mso_host+" mso_site_id= "+mso_site_id+ ' | rex field=urls "https://(?<url>.*)"$ | mvexpand url | where name = "'+site_name+'" | table url, platform',
                earliest_time: time_token_earliest,
                latest_time: time_token_latest                
                });

            //check results after search query is completed
            search_query.on('search:done', function(properties) {
                let search_query_result = search_query.data("results");
                search_query_result.on("data", function() {
                    let resultArray = search_query_result.data().rows;
                    apic_host = resultArray[0][0];
                    apic_platform = resultArray[0][1];
                    
                    if(apic_platform == "on-premise")
                        window.open('/app/cisco_dc_networking_app_for_splunk/fabric_dashboard?form.mso_host='+mso_host+'&form.apic_host='+apic_host+'&form.time_token.earliest='+time_token_earliest+'&form.time_token.latest='+time_token_latest, '_blank'); 

                    if(apic_platform == "cloud")
                        window.open('/app/cisco_dc_networking_app_for_splunk/cloud_topology?form.apic_host='+apic_host+'&form.timeToken.earliest='+time_token_earliest+'&form.timeToken.latest='+time_token_latest, '_blank'); 
                });
            });
        });
});