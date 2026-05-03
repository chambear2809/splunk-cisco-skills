# Third-party integrations

All third-party integrations are configured in the Splunk On-Call UI under
**Integrations → 3rd Party Integrations**. The skill renders deterministic
operator steps for each, but does not call third-party APIs to install
anything.

## Slack

- UI flow: Integrations → 3rd Party Integrations → Slack → **Add to Slack**.
- Renders deeplinks for inviting the bot to channels and configuring per-team
  routing.
- The bidirectional integration uses Splunk On-Call's public API to push
  incident updates into Slack channels and webhooks to receive
  acknowledgements.

## Microsoft Teams

- UI flow: Integrations → 3rd Party Integrations → Microsoft Teams →
  **Connect**.
- Uses the Splunk>VictorOps app for Microsoft Teams.
- Renders deeplinks for the M365 admin install consent flow.

## Webex Teams

- UI flow: Integrations → 3rd Party Integrations → Webex Teams.
- Bidirectional via the Webex Teams bot account.
- Renders deeplinks for adding the Splunk On-Call bot to a Webex space.

## ServiceNow (bidirectional)

- UI flow: Integrations → 3rd Party Integrations → ServiceNow.
- Renders the ServiceNow Update Set IDs to import on the ServiceNow side and
  the Splunk On-Call REST endpoint URL to paste into the ServiceNow Business
  Rule.
- Both sides must be configured by an admin with rights on each platform.

## Statuspage

- UI flow: Integrations → 3rd Party Integrations → Statuspage.io.
- Renders the Splunk On-Call → Statuspage automation rules and the
  Statuspage page-id field that maps to a routing key.

## Twilio Live Call Routing

- UI flow: Integrations → 3rd Party Integrations → Twilio.
- Requires a Twilio account; renders the Twilio TwiML bin contents and the
  Splunk On-Call routing-key map for inbound calls.

## Conference Bridges (Enterprise tier)

- UI flow: Settings → Conference Bridges.
- Each team can attach a default conference bridge URL to incidents.
- The Splunkbase 4886 Add-on ships `bin/getConferenceBridges.py` which
  confirms a public-API path exists. A future revision of this skill will
  upgrade this section to `api_validate`.

## How the skill exposes them

The `integrations` spec section accepts:

```yaml
integrations:
  - kind: slack
    name: Slack notifications for Checkout SRE
  - kind: microsoft_teams
    name: Teams notifications for Platform Ops
  - kind: webex_teams
    name: Webex bridge for SRE
  - kind: servicenow
    name: ServiceNow SecOps bidirectional
    instance_url: https://example.service-now.com
  - kind: statuspage
    name: Customer status page
    page_id: abc123
  - kind: twilio_live_call_routing
    name: Twilio LCR for paging
  - kind: conference_bridge
    name: Checkout war room bridge
    team: Checkout SRE
    url: https://meet.example.com/checkout-warroom
```

Each entry renders a deeplink + handoff in `handoff.md` and `deeplinks.json`.
None of them ever call the third-party API directly.
