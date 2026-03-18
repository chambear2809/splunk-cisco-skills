Copyright (c) 2007-2021 Splunk Inc. All Rights Reserved.


The Splunk_TA_stream provides passive capture of event data from live network traffic, and sends that data to Splunk indexers via modular input.

Splunk_TA_stream is a seperate download package and provides passive capture of network data. The companion app Splunk App for Stream (splunk_app_stream), provides configuration management for Splunk_TA_stream. You can use the splunk_app_stream to configure the TA to capture a variety of network event types for multiple network protocols.

You can also use the app to perform data aggregation, as well as additional filtering and translation, prior to indexing. And the app provides a variety of default dashboards that let you view important Network Interface and Processor metrics. 

For Splunk Cloud deployments, run this add-on on a customer-controlled heavy or universal forwarder, configure `splunk_stream_app_location` to the Cloud search-tier Stream app over `443` or `8443`, and configure forwarding to Splunk Cloud separately at the host forwarder layer.

# Binary File Declaration

linux_x86_64/bin/streamfwd
linux_x86_64/bin/streamfwd-rhel6
darwin_x86_64/bin/streamfwd
windows_x86_64/bin/vccorlib140.dll
windows_x86_64/bin/concrt140.dll
windows_x86_64/bin/msvcp140.dll
windows_x86_64/bin/vcruntime140.dll
windows_x86_64/bin/qmframework.dll
windows_x86_64/bin/qmflow.dll
windows_x86_64/bin/Packet.dll
windows_x86_64/bin/wpcap.dll
windows_x86_64/bin/streamfwd.exe
windows_x86_64/bin/qmprotocols.dll
windows_x86_64/bin/npcap-1.55-oem.exe

For installation and configuration instructions, see http://docs.splunk.com/Documentation/StreamApp/latest/DeployStreamApp
