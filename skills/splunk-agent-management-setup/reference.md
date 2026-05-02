# Splunk Agent Management Reference

Splunk Enterprise 10.x uses the term Agent Management for the deployment-server
workflow. The same core pieces remain important:

- agent manager: a Splunk Enterprise instance that distributes content
- agents: Splunk instances configured by agent management
- deployment apps: app or configuration directories distributed to agents
- server classes: mappings between agent filters and deployment apps

Agent management cannot be an agent of itself.

Agent management can distribute updates to non-clustered indexers and search
heads, but Splunk documentation says not to use it for indexer cluster peer
nodes or search head cluster members. Use the indexer cluster manager bundle or
the search head cluster deployer for those clustered roles.

## Rendered Files

| File | Purpose |
|------|---------|
| `serverclass.conf` | Server class and app mapping |
| `deploymentclient.conf` | Client-side target broker and phone-home settings |
| `deployment-apps/<app>/local/app.conf` | Placeholder deployment app metadata |
| `apply-agent-manager.sh` | Installs `serverclass.conf`, deploys the app, and reloads deploy-server |
| `apply-deployment-client.sh` | Installs deployment client config and restarts Splunk |
| `status.sh` | Runs btool and deploy-client status commands |

## Server Class Notes

The `serverclass.conf` file has a three-level hierarchy:

- `[global]`
- `[serverClass:<name>]`
- `[serverClass:<name>:app:<appName>]`

Splunk Enterprise 9.4.3 and later changed the implicit app-level `filterType`
default from blacklist-style behavior to whitelist-style behavior. This skill
renders `filterType` at both server-class and app levels to make behavior
explicit during upgrades.

## Deployment Client Notes

The rendered `deploymentclient.conf` uses:

- `[deployment-client]`
- `[target-broker:deploymentServer]`
- `targetUri = <agent-manager-uri>`

The default `serverRepositoryLocationPolicy = rejectAlways` keeps deployed apps
under the client-side `$SPLUNK_HOME/etc/apps` path.

## Official References

- Agent management architecture:
  <https://help.splunk.com/en/splunk-enterprise/administer/update-your-deployment/10.2/agent-management/agent-management-architecture>
- Define server classes:
  <https://help.splunk.com/en/splunk-enterprise/administer/update-your-deployment/10.2/configure-the-agent-management-system/use-the-agent-management-interface-to-define-server-classes>
- `serverclass.conf` reference:
  <https://help.splunk.com/en/data-management/splunk-enterprise-admin-manual/10.2/configuration-file-reference/10.2.0-configuration-file-reference/serverclass.conf>
- `deploymentclient.conf` reference:
  <https://help.splunk.com/en/splunk-enterprise/administer/admin-manual/10.2/configuration-file-reference/10.2.0-configuration-file-reference/deploymentclient.conf>
