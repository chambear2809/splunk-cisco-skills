STEPS to USE the external script, this script will validate the external app which is currently not installed. 
To use this script unzip the package of exteral app on a different location in your machine, Example is given below

1. Copy External Script from Stream App to /home/splunker (You can also copy it to another path depending on your machine)
    - cd /opt/splunk/etc/apps/splunk_app_stream/bin/splunk_app_stream/utils/netflow_validate_ipfix_app_script
    - cp validate_app.py /home/splunker (You can also copy it to another path depending on your machine)
    - cp vocabulary_schema /home/splunker (Use same path used in above command)
    - cp stream_schema /home/splunker (Use same path used in above command)
			
2. Add the ipfix app from local machine to your host machine: Example given below
    - scp  splunk_app_stream_ipfix_gigamon.tgz splunker@10.202.17.153:/home/splunker (To the path used in step-1)
    - tar -xvzf splunk_app_stream_ipfix_gigamon.tgz 

3.  In the validate_app.py file, Update this APP_PATH variable at line16  to full path of the ipfix  app added in step-2
    - Eg. /opt/splunk/etc/apps/splunk_app_stream_ipfix_gigamon 

4.  Install belove dependencies
    - pip3 install lxml
    - pip3 install jsonschema

5.  Run the Command python3 validate_app.py (NOTE: Use PYTHON-3 or above)
    - If app is valid then it will print APP IS VALID message
    - Otherwise it will print all the errors which the ipfix app has(XMLsyntaxError,Vocab Not Found etc.)

