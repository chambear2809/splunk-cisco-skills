# Splunk Stream Cloud HF Template

This template is for a customer-controlled heavy forwarder that will:

- run `Splunk_TA_stream`
- receive NetFlow/IPFIX from any device
- fetch Stream configuration from `splunk_app_stream` on the Splunk Cloud search tier
- forward Stream events to Splunk Cloud over the normal forwarder channel

## Topology

- Splunk Cloud search tier:
  - `splunk_app_stream`
  - `Splunk_TA_stream_wire_data`
- Customer-controlled heavy forwarder:
  - `Splunk_TA_stream`
  - local `inputs.conf` and `streamfwd.conf`
  - host-level `outputs.conf`

## Ports

- Inbound to the HF:
  - UDP `9995` from NetFlow/IPFIX senders
- Outbound from the HF:
  - TCP `443` or `8443` to the Splunk Cloud search tier for `splunk_app_stream`
  - TCP `9997` to the Splunk Cloud forwarding endpoint(s)

## Files In This Template

- `Splunk_TA_stream/local/inputs.conf`
- `Splunk_TA_stream/local/streamfwd.conf`
- `system/local/outputs.conf`

## How To Use

1. Install `Splunk_TA_stream` on the heavy forwarder.
2. Copy the files under `Splunk_TA_stream/local/` into:
   - `$SPLUNK_HOME/etc/apps/Splunk_TA_stream/local/`
3. Merge `system/local/outputs.conf` into:
   - `$SPLUNK_HOME/etc/system/local/outputs.conf`
4. Replace all placeholder values:
   - `<stream-search-head-fqdn>`
   - `<hf-identifier>`
   - `<absolute-path-to-root-ca.pem>`
   - `<cloud-forwarder-endpoint-1>`
   - `<cloud-forwarder-endpoint-2>`
5. Restart the heavy forwarder.

## Notes

- This template intentionally does **not** set `netflowReceiver.0.filter`, so any device can send NetFlow/IPFIX to the receiver.
- The template binds the NetFlow receiver to `0.0.0.0` on UDP `9995`.
- Keep `sslVerifyServerCert = true` for the Stream app connection and provide a real CA bundle path in `rootCA`.
- If your HF already forwards other data, merge the `outputs.conf` stanza instead of replacing the whole file.
- This template is for NetFlow/IPFIX receiver mode. If you later enable passive packet capture, you will also need the host capability changes documented by Splunk Stream.
