require(["splunkjs/mvc/utils"], function(SplunkUtil) {
    var app_name = SplunkUtil.getCurrentApp();
    require(['jquery',
            'splunkjs/mvc',
            'splunkjs/mvc/searchmanager',
            'underscore',
            'splunkjs/mvc/simplexml/ready!'
        ],
        function($, mvc, searchManager) {


            var tokens = mvc.Components.get("default");

            function getValueByElementId(id) {
                return document.getElementById(id).value.trim();
            }

            function getCurrentUrl() {
                return window.location.href;
            }

            function getSearchString(warning_threshold, critical_threshold) {
                var current_url = getCurrentUrl()
                var outputlookup = ""
                if (current_url.match("change_portutil_threshold_xml")) {
                    outputlookup = "cisco_dc_portutilThreshold.csv"
                } else {
                    outputlookup = "cisco_dc_tcamThreshold.csv"
                }
                var search_string = "eventtype=cisco_dc_aci_health component=fabricNode role=leaf OR role=spine NOT \"code\" | stats dc(name) AS COUNT | eval warningThreshold="+warning_threshold+" | eval criticalThreshold="+critical_threshold+" | table warningThreshold, criticalThreshold | outputlookup "+outputlookup;

                return search_string
            }

            function saveConfigurations() {
                var warning_threshold = getValueByElementId("warning_threshold");
                var critical_threshold = getValueByElementId("critical_threshold");

                if((warning_threshold!=0) && (warning_threshold < critical_threshold) && (critical_threshold < 100))
                {
                    var search_string = getSearchString(warning_threshold, critical_threshold)
                    var search2 = new searchManager({
                        "id": Math.random().toString(),
                        "status_buckets": 0,
                        "search": search_string,
                        "cancelOnUnload": true,
                        "latest_time": "now",
                        "earliest_time": "-5m",
                        "app": app_name,
                        "auto_cancel": 90,
                        "preview": true,
                        "runWhenTimeIsUndefined": false
                    }, {tokens: true, tokenNamespace: "submitted"});
                    search2.startSearch();
                    search2 = null;
                    var submit_button_status_msg = "#submit_button_status_msg";
                    $(submit_button_status_msg).html("<font class='success'>Configuration saved successfully.</font>");
                    setTimeout(function() {
                        $(submit_button_status_msg).html("");
                    }, 5000);
                    return true;
                }
                else
                {
                    window.alert('Please enter proper threshold values.\n i.e. Warning should be lesser than Critical \nand Critical should be lesser than hundred.');
                    return false;
                }
            }

            function redirect_page() {
                window.location.href = "/en-US/app/cisco_dc_networking_app_for_splunk/fabric_dashboard";
                return false;
            }

            $("#submit_button").click(saveConfigurations);
            $("#warning_threshold").keypress(function (e) {
                //if the letter is not digit then don't type anything
                if (e.which != 8 && e.which != 0 && (e.which < 48 || e.which > 57)) {
                    return false;       
                }
            });
            $("#critical_threshold").keypress(function (e) {
                //if the letter is not digit then don't type anything
                if (e.which != 8 && e.which != 0 && (e.which < 48 || e.which > 57)) {
                    return false;       
                }
            });

            $("#cancel_button").click(redirect_page);

        });
});
