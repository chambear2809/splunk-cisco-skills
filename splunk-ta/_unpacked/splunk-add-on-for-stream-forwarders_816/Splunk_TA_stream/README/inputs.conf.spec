[streamfwd://<name>]

splunk_stream_app_location = <value>
* URI including full path to splunk_app_stream installation. For Splunk Cloud, use the externally reachable search-tier URL, for example https://searchHead:443/en-us/custom/splunk_app_stream/
* Splunk App For Stream provides configuration information for Stream Forwarder TA

stream_forwarder_id = <value>
* A string identifier for Stream Forwarder. stream_forwarder_id is used to resolve groups stream forwarder belongs to. If left empty, uses the host name of the server stream forwarder runs on.

sslVerifyServerCert = <value>
* When set to true enables server(splunk app stream) certificate validation on client(stream forwarder) side. Use true for Splunk Cloud deployments.

rootCA = <value>
* Points to the file name of root ca certificate file. If sslVerifyServerCert is set to true, rootCA must point to the full path of the root ca certificate file.
* If this parameter is left empty or points to a non-existent file, certificate validation cannot be performed.

sslCommonNameToCheck = <value>
* Allows for overriding common name value to compare against the certificate CN.
* If this parameter is left blank, fully qualified host name of the splunk app for stream server is verified against the CN in server certificate.
