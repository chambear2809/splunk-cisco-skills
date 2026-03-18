ORG_COUNTER = {}
ORG_LAST_API_CALL_TIME = {}
DEFAULT_INDEX = "main"
TIME_FORMAT_WITH_MICRO_SECOND = "%Y-%m-%dT%H:%M:%S.%fZ"
WEBHOOK_HEADER = [{"Key": "Authorization", "Value": "Splunk {{sharedSecret}}"}]
WEBHOOK_TEST_ALERT_TYPE = "power_supply_down"
WEBHOOK_BODY = (
    '{"sourcetype":"meraki:webhook", '
    '"event":{'
    '"version":"0.1", '
    '"sentAt":"{{sentAt}}", '
    '"organizationId":"{{organizationId}}", '
    '"organizationName":"{{organizationName}}", '
    '"organizationUrl":"{{organizationUrl}}", '
    '"networkId":"{{networkId}}", '
    '"networkName":"{{networkName}}", '
    '"networkUrl":"{{networkUrl}}", '
    '"networkTags":{{ networkTags | jsonify }}, '
    '"deviceSerial":"{{deviceSerial}}", '
    '"deviceMac":"{{deviceMac}}", '
    '"deviceName":"{{deviceName}}", '
    '"deviceUrl":"{{deviceUrl}}", '
    '"deviceTags":{{ deviceTags | jsonify }}, '
    '"deviceModel":"{{deviceModel}}", '
    '"alertId":"{{alertId}}", '
    '"alertType":"{{alertType}}", '
    '"alertTypeId":"{{alertTypeId}}", '
    '"alertLevel":"{{alertLevel}}", '
    '"occurredAt":"{{occurredAt}}", '
    '"alertData":{{ alertData | jsonify }}'
    '}'
    '}'
)
