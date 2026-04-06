# SC4SNMP Compose Templates

These files are the base templates for Docker Compose managed SC4SNMP
deployments.

They render:

- `.env`
- `docker-compose.yml`
- helper scripts for install or upgrade
- config placeholders for inventory, scheduler, and traps

The rendered output is intended for local-only operator use and should not be
committed when it contains secrets.
