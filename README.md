# sigaa-ai-agent

> [!IMPORTANT]
> This is an unofficial personal project and is not affiliated with, endorsed
> by, or supported by UFPB or SIGAA. Use it responsibly, keep request rates low,
> and follow the rules that apply to your SIGAA account.

User-friendly client for **SIGAA UFPB** (sigaa.ufpb.br) built for automation:
a **CLI** and an **MCP server** over a layered Python core. Scope: single user.

SIGAA has no official API. This wraps the JSF web flow: login (cookie jar +
`ViewState`, no JWT, no CAPTCHA), enrolled classes, and **per-class news
channels** persisted to SQLite with stable dedup by news id.

## Install

Install `pipx` once if you do not already have it:

```bash
brew install pipx
# or: python -m pip install --user pipx
```

Then install and run the setup wizard:

```bash
pipx install "sigaa-ai-agent[mcp]"
sigaa init
```

## Credentials

Keyring-first, env-second. Never commit credentials, cookies, downloaded live
HTML, SQLite databases, exported PDFs, or `.env` files. Recommended
=======

Run `sigaa init`. It prompts for your SIGAA username and password, stores the
password in your OS keyring when available, verifies the login, runs the first
sync, and can configure MCP and scheduled polling for you.
>>>>>>> 86efdfc5c737216768d4fbd4fc659a3e74ec6b93

Headless fallback: `export SIGAA_USER=... SIGAA_PASS=...`.
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
sigaa historico --out h.pdf # download the academic transcript PDF (networked)
sigaa watch --interval 900 # foreground loop
```

`sync` writes the store; everything else reads it (fast, offline).

## MCP server (for code agents)

Run `sigaa init`; it can detect or create `.mcp.json` and add the `sigaa` MCP
server without manual absolute-path editing.

Tools: `sigaa_list_classes`, `sigaa_list_news`, `sigaa_get_news_body`,
`sigaa_get_schedule`, `sigaa_list_grades`, `sigaa_list_deadlines`,
`sigaa_export_ics`, `sigaa_download_historico`, `sigaa_sync`. Reads come from
the store; `sigaa_sync` and `sigaa_download_historico` touch the network.

## Scheduled polling

Run `sigaa init`; it can write the launchd plist on macOS or print the cron
entry for other operating systems.

## Contributing / dev install

```bash
git clone https://github.com/PucaVaz/sigaa-for-ai-agents.git
cd sigaa-for-ai-agents
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[mcp,dev]"
sigaa --user YOUR_USER login
```

## Advanced manual configuration

Usually you should run `sigaa init`. The examples below are for manual setups,
debugging, or custom automation.

### Manual MCP

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

### Manual scheduled polling

**macOS (launchd)** - sync every 30 min. Save as
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

Single-user, local-first tool. `config.py` reads credentials from keyring first
and environment variables second. The SQLite db is local and may contain student
data copied from SIGAA. `.gitignore` excludes `*.db`, `.env`, and live HTML
dumps, but review generated files before sharing logs, issues, or screenshots.

## License

MIT. See [LICENSE](LICENSE).
