Directory Structure:

    Splunk_TA_Cisco_Intersight/
    ├── bin/                        # Contains Python code (modular inputs, helper libs, etc.)
    │   ├── <input>.py
    │   └── ...
    ├── default/
    │   ├── inputs.conf            # Default configurations
    │   └── app.conf
    ├── local/                     # Local configs (not version controlled, usually empty in dist)
    ├── metadata/
    │   └── default.meta
    ├── README/                    # Documentation folder
    ├── static/
    │   └── js/
    |       ├── build/
    |           ├── custom/
    │               └── <hooks>.js  # to perform UI manipulations
    │           └── globalConfig.json  # Global configuration schema for UI
    │       └── openapi.json
    ├── default/data/ui/
    │   ├── nav/                   # Navigation (default.xml)
    │   └── views/                 # UI dashboards


🔁 How Input Data Collection Works in Add-on
1. Input Configuration via UI  
   The add-on exposes data input options through the Splunk UI. These are defined in:
   - globalConfig.json — defines global settings like account credentials, logging level, etc.

2. Splunk Schedules the Input  
   Based on the configured interval, Splunk’s input framework kicks off the execution of your input script, which lives in the bin/ directory:
   - Example: bin/<input_name>.py

3. <input_name>.py Calls stream_events  
   This script defines a stream_events(self, inputs, ew) method. When Splunk starts the input:
   - It calls this stream_events method.
   - inputs contains all configuration details.
   - ew is the EventWriter object used to write events into the Splunk index.

4. Data Collection Happens Inside stream_events  
   Within the stream_events() method, you:
   - Retrieve configuration parameters (like credentials, time range, filters).
   - Make API calls to the external service (e.g., Cisco Intersight).
   - Parse and process the API response.
   - Format the data as Splunk events.

5. Data Is Ingested Into Splunk  
   The processed data is written to the index using:
   ew.write_event(data=json.dumps(event))
   Splunk takes care of storing that event in the appropriate index and source type.
