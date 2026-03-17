# Splunk App Install — Quick Start Guide

## Example Prompts

| User says | Agent action |
|-----------|-------------|
| "Install a Splunk app" | Ask source, details → run `install_app.sh` |
| "Install the Cisco Catalyst TA" | Ask for file path or source → run `install_app.sh` |
| "Download and install app 5289 from Splunkbase" | Run with `--source splunkbase --app-id 5289` |
| "Install this TA from https://myserver.com/app.tgz" | Run with `--source remote --url <url>` |
| "Upgrade the Meraki TA" | Ask for file/source → run with `--update` |
| "What Splunk apps are installed?" | Run `list_apps.sh` |
| "List all Cisco TAs" | Run `list_apps.sh --filter cisco` |
| "Remove the old test app" | Run `uninstall_app.sh` |

## What the Agent Must Ask

Scripts read Splunk credentials from the project-root `credentials` file automatically.
The agent should gather non-secret values and pass them as flags.

**NEVER ask for passwords or credentials in conversation.**

### For install_app.sh

1. **Source type** — "How do you want to install? (1) Local, (2) Remote, (3) Splunkbase"
2. **Source details**:
   - Local: "What is the file path?" (or list files in `splunk-ta/` first)
   - Remote: "What is the download URL?"
   - Splunkbase: "What is the app ID?" and "What version? (blank for latest)"
3. **Upgrade?** — "Is this an upgrade of an existing app?"

For remote Splunk hosts, local package installs try REST upload first and then
fall back to SSH staging if needed. Configure `SPLUNK_HOST`, `SPLUNK_URI`,
`SPLUNK_SSH_USER`, and `SPLUNK_SSH_PASS` in the project `credentials` file.

### For list_apps.sh

1. **Filter** (optional) — "Do you want to filter by name?"

### For uninstall_app.sh

1. **App name** — "Which app do you want to remove?" (script lists options)
2. **Confirmation** — script confirms before deleting

## Prerequisites

Ensure Splunk credentials are configured:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

## Example Conversation

```
User: Install a Splunk app for me

Agent: Sure! How do you want to install the app?
  1) Local   — file on this server or in the project
  2) Remote  — download from a remote URL
  3) Splunkbase

User: Local

Agent: [runs]
bash skills/splunk-app-install/scripts/install_app.sh \
  --source local

(The script will list available .tgz files in the project's `splunk-ta/`
directory, preferring the project-local copy, then prompt the user to pick one
and ask if it's an upgrade.)
```

## Fully Non-Interactive Example

When the agent has all values, it can skip all prompts:

```bash
bash skills/splunk-app-install/scripts/install_app.sh \
  --source splunkbase --app-id 5580 --app-version 2.1.0 --update
```

Splunk and Splunkbase credentials are read from the project-root `credentials` file.

## Files

| File | Purpose |
|------|---------|
| `SKILL.md` | Main skill instructions |
| `guide.md` | This quick-start guide |
| `scripts/install_app.sh` | Install from Local, Remote, or Splunkbase |
| `scripts/list_apps.sh` | List installed apps |
| `scripts/uninstall_app.sh` | Remove an app |

## Tips

- Downloaded files are saved in the project's `splunk-ta/` directory by
  default, and repeat downloads reuse the existing package when it is already
  present there.
- `TA_CACHE` can override the destination, but `splunk-ta/` is the preferred
  shared package location for this project.
- Use `--update` when the app already exists and you want to upgrade.
- After install, check if the app needs a Splunk restart or has a setup page.
- To find a Splunkbase app ID, look at the URL:
  `https://splunkbase.splunk.com/app/XXXX` — XXXX is the app ID. You can also pass the full URL as `--app-id`.
- Latest version is resolved automatically (from the app page when the Splunkbase API does not list releases).
