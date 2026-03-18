[audit_alarms://<name>]
enable_aaa_audit_records = Retrieve audit log events from the aaa/AuditRecords API endpoint
enable_alarms = Retrieve alarm events from the cond/Alarms API endpoint
acknowledge = Retrieve acknowledged alarm events from the Cisco Intersight.
suppressed = Retrieve suppressed alarm events from the Cisco Intersight.
info_alarms = Retrieve alarm events with ‘Info’ severity from the Cisco Intersight.
global_account = Select the intersight account for which you want to collect data.
index = Default: default
interval = Time interval of input in Seconds.  Default: 900
interval_proxy = Indicate to start data collection from the time specified in date_input
date_input = Provide a timestamp to start collecting data from the Cisco Intersight environment. Format: (YYYY-MM-DDTHH:MM:SSZ).

[inventory://<name>]
compute_endpoints = The selected Compute APIs will be retrieved from Intersight.  Default: All
fabric_endpoints = The selected Fabric APIs will be retrieved from Intersight.  Default: All
global_account = Select the intersight account for which you want to collect data.
index = Default: default
interval = Time interval for the input in Seconds. Available options: 15 Minutes, 30 Minutes, 1 Hour, 6 Hours, 12 Hours, 24 Hours. Default: 30 Minutes(1800)
inventory = The selected inventory types will be retrieved from Intersight.
license_endpoints = The selected License APIs will be retrieved from Intersight.  Default: All
advisories_endpoints = The selected Advisory APIs will be retrieved from Intersight.  Default: All
ports_endpoints = The selected Ports APIs will be retrieved from Intersight.  Default: All
pools_endpoints = The selected Pools APIs will be retrieved from Intersight.  Default: All

[metrics://<name>]
global_account = Select the intersight account for which you want to collect data.
host_power_energy_metrics = The selected Host Power And Energy Metrics will be retrieved from Intersight.  Default: All
index = Default: default
interval = Time interval of input in minutes.  Default: 900
memory_metrics = The selected Memory Module Metrics will be retrieved from Intersight.  Default: All
metrics = The selected metrics will be retrieved from Intersight.
network_metrics = The selected Network Interface Metrics will be retrieved from Intersight.  Default: All

[custom_input://<name>]
global_account = Select the intersight account for which you want to collect data.
index = Default: default
interval = Time interval of input in minutes.  Default: 1800
api_type = Inventory or Timeseries
api_endpoint = API Endpoint
filter = Filter Param for Inventory
expand = Expand Param for Inventory
select = Select Param for Inventory
metrics_type = Metrics Type (comma-separated: sum, min, max, avg, latest)
metrics_name = Metrics Name (e.g., hw.fan.speed)
show_metrics_fields = Edit Metrics Fields
groupby = GroupBy(Dimension Fields)
metrics_sum = Field name for Sum aggregation (auto-generated, editable)
metrics_min = Field name for Min aggregation (auto-generated, editable)
metrics_max = Field name for Max aggregation (auto-generated, editable)
metrics_avg = Field names for Avg aggregation (auto-generated, editable, format: sum_field/count_field)
metrics_latest = Field name for Latest aggregation (auto-generated, editable)
