# Local Splunk TA Packages

Place Splunk Technology Add-on packages (`.tgz`, `.spl`, `.tar.gz`) in this
directory for local installation via the `splunk-app-install` skill.

The `install_app.sh` script will list files in this directory when you choose
the **local file** installation source.

## Naming Convention

Use descriptive filenames that include the app name and version:

```
Splunk_TA_cisco_meraki-2.1.0.tgz
TA_cisco_catalyst-3.0.0.spl
cisco_dc_networking_app-1.2.0.tar.gz
```

## Obtaining TA Packages

- **Splunkbase**: Download from <https://splunkbase.splunk.com> (requires a
  splunk.com account).
- **Internal builds**: Place custom or pre-release TA packages here for
  distribution to your team.

## Important

- Do **not** commit credentials, license files, or other secrets alongside
  TA packages.
- Large `.tgz`/`.spl` files are tracked by Git. Consider using Git LFS if
  packages exceed ~50 MB.
