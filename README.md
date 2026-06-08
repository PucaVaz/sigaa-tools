# sigaa-ai-agent

User-friendly client for **SIGAA UFPB** (sigaa.ufpb.br) built for automation:
a **CLI** and an **MCP server** over a layered Python core. Scope: single user.

SIGAA has no official API. This wraps the JSF web flow: login (cookie jar +
`ViewState`, no JWT, no CAPTCHA), enrolled classes, and **per-class news
channels** persisted to SQLite with stable dedup by news id.

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[mcp,dev]"
```

## Credentials

Keyring-first, env-second. Recommended:

```bash
sigaa --user YOUR_USER login        # prompts, stores in macOS Keychain, verifies
```

Or headless via env: `export SIGAA_USER=... SIGAA_PASS=...`.
Optional `SIGAA_DB=/path/to/sigaa.db` to override the store location.

## CLI

```bash
sigaa sync                 # hit SIGAA: persist new news, deadlines, grades (only networked cmd)
sigaa sync --bodies        # also fetch full news article text
sigaa classes --schedule   # enrolled classes with decoded weekly schedule
sigaa news --class DSCO00022   # news for one class, from the store
sigaa news --unread --mark-seen
sigaa grades --semester 2025.1 # grades report by semester
sigaa deadlines            # assessment/task due dates
sigaa ics --out sigaa.ics  # export classes + deadlines as a calendar
sigaa watch --interval 900 # foreground loop
```

`sync` writes the store; everything else reads it (fast, offline).

## MCP server (for code agents)

Run with `sigaa-mcp` (stdio). Wire into Claude Code via `.mcp.json`:

```json
{
  "mcpServers": {
    "sigaa": {
      "command": "/abs/path/.venv/bin/sigaa-mcp",
      "env": { "SIGAA_USER": "your_user" }
    }
  }
}
```

Tools: `sigaa_list_classes`, `sigaa_list_news`, `sigaa_get_news_body`,
`sigaa_get_schedule`, `sigaa_list_grades`, `sigaa_list_deadlines`,
`sigaa_export_ics`, `sigaa_sync`. Reads come from the store; only
`sigaa_sync` touches the network.

## Scheduled polling

**macOS (launchd)** — sync every 30 min. Save as
`~/Library/LaunchAgents/ai.sigaa.sync.plist` then
`launchctl load` it:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>ai.sigaa.sync</string>
  <key>ProgramArguments</key>
  <array>
    <string>/abs/path/.venv/bin/sigaa</string>
    <string>sync</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>SIGAA_USER</key><string>your_user</string></dict>
  <key>StartInterval</key><integer>1800</integer>
</dict></plist>
```

**Linux (cron)**: `*/30 * * * * SIGAA_USER=you /abs/.venv/bin/sigaa sync`
(password from keyring, or add `SIGAA_PASS`).

## Architecture

```
sigaa/
  config.py     endpoints, JSF constants, slot-time table, creds resolution
  http.py       session: cookie jar, ViewState, re-login + retry
  auth.py       login flow
  client.py     SigaaClient -> domain models
  models.py     Student, Turma, NewsItem, Schedule
  parsers/      portal, news, schedule (HTML isolated here)
  store/        SQLite db + repository (dedup, queries)
  services/     sync (fetch -> diff -> persist)
  cli.py        command line
  mcp_server.py agent tools
```

Adding a feature (materials, attendance) = a parser + client method + store
columns + a CLI/MCP surface. HTML changes touch only `parsers/`. Implemented so
far: classes, news (+bodies), grades, deadlines, ICS export.

`exporters/` turns store data into interchange formats (currently `ics`).

## Schedule decoding

`6M2345` → Fri (day 6) morning slots 2–5. Days 2=Mon..7=Sat, shift M/T/N.
Clock times in `config.SLOT_TIMES_UNCONFIRMED` are an **unconfirmed** default —
verify against a turma's "Plano de Curso" before using them for calendar export.

## Tests

```bash
pytest        # offline: parsers run on fixtures, store on in-memory sqlite
```

## Security

Single-user, but never commit credentials. `config.py` reads keyring then env.
The SQLite db is local. `.gitignore` excludes `*.db`, `.env`, and live HTML dumps.
