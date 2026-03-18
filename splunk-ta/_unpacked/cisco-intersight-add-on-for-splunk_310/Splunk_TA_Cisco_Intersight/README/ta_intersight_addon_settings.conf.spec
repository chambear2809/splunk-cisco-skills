[proxy]
proxy_enabled = 
proxy_password = 
proxy_port = 
proxy_type = 
proxy_url = 
proxy_username = 

[logging]
loglevel = 

[splunk_rest_host]
splunk_rest_host_url = Enter the Splunk rest host or localhost (without http(s) scheme) to collect data.(Default: localhost).
splunk_rest_port = Enter the management port of the Splunk.(Default: 8089).
splunk_username = Not required if Splunk Rest Host URL is localhost or 127.0.0.1. Configured user should have at least power role capabilities.
splunk_password = Enter the password for Splunk account. No need to provide a Password if Splunk Rest Host URL is localhost or 127.0.0.1.
collection_type = Type of collection. (Default: index)