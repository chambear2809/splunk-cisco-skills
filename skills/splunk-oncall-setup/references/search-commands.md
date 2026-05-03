# SPL helpers shipped by the alert-action app

The Splunk On-Call alert-action app (Splunkbase 3546, `victorops_app`)
ships four custom SPL search commands in `default/commands.conf`. Operators
can compose these into their own SPL automations without re-implementing
the underlying API plumbing.

## `recoveralerts`

```
[recoveralerts]
filename = recoverAlerts.py
passauth = true
python.version = python3
python.required = 3.13
```

Scans the `mycollection` and `activealerts` KV-store collections for open
alerts whose underlying Splunk search no longer fires, and posts a
`RECOVERY` to the REST endpoint. Used by the
`victorops-alert-recovery` saved search (cron `*/5 * * * *`).

Example:

```spl
| recoveralerts
```

## `retrieveroutingkeys`

```
[retrieveroutingkeys]
filename = retrieveRoutingKeys.py
passauth = true
python.version = python3
python.required = 3.13
```

Pulls the org's routing-key list from `/api-public/v1/org/routing-keys`
and emits one event per routing key. Useful for populating dropdowns in
custom dashboards.

Example:

```spl
| retrieveroutingkeys
| sort routingKey
| table routingKey, isDefault, targets{}.policyName
```

## `settestresult`

```
[settestresult]
filename = setTestResult.py
passauth = true
python.version = python3
python.required = 3.13
```

Marks a generated alert as test-only — used by smoke tests that should
never escalate to live paging.

Example:

```spl
| settestresult result_id=ABC123
```

## `setorganization`

```
[setorganization]
filename = setOrganization.py
passauth = true
python.version = python3
python.required = 3.13
```

Updates the stored org slug in the `deployment` KV-store collection. Run
this once after the alert-action app is installed and the operator has
confirmed the org slug from the On-Call portal.

Example:

```spl
| setorganization org=acme-corp
```

## How the skill exposes them

These are documented for operator awareness only. The skill itself does not
emit SPL referencing these commands — it uses the Splunk REST API. The
`splunk-side-apps.md` reference includes a one-line summary table; this
file contains the verbose reference.
