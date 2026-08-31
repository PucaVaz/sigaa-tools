# sigaa-tools

> [!IMPORTANT]
> This is an unofficial personal project and is not affiliated with, endorsed
> by, or supported by UFPB, SIGAA, or SIPAC. Use it responsibly, keep request rates low,
> and follow the rules that apply to your SIGAA account.

Friendly CLI and MCP server for **SIGAA UFPB** and **SIPAC** public process lookup. Fetch your classes, grades, deadlines, and curriculum all at once without opening the web portal.

## Quickstart

**Step 1:** Install `pipx` (once only):
```bash
brew install pipx
# or: python -m pip install --user pipx
```

**Step 2:** Install sigaa:
```bash
pipx install "sigaa-tools[mcp]"
```

**Step 3:** Run the setup wizard:
```bash
sigaa init
```

That's it. The wizard prompts for your SIGAA credentials, stores them securely, syncs your data, and optionally sets up MCP for Claude Code or background polling.

## What you get

- **CLI**: `sigaa classes`, `sigaa news`, `sigaa grades`, `sigaa deadlines`, etc. Fast, offline-first queries from a local SQLite database.
- **MCP server**: Wire into Claude Code (or any MCP client) to let AI agents fetch your SIGAA data on demand.
- **SIPAC lookup**: `sigaa sipac process 23074.056437/2026-26` — look up public UFPB administrative processes without a browser.

## Common commands

```bash
sigaa sync                 # fetch & persist new news, deadlines, grades
sigaa sync --bodies        # also fetch full news article text
sigaa classes --schedule   # enrolled classes with decoded weekly schedule
sigaa news --class DSCO00022   # news for one class
sigaa news --unread --mark-seen
sigaa grades --semester 2025.1 # grades by semester
sigaa deadlines            # assessment/task due dates
sigaa ics --out sigaa.ics  # export classes + deadlines as calendar
sigaa curriculum           # live progress & required courses
sigaa cra --json           # official CRA as JSON
sigaa watch --interval 900 # continuous sync in foreground
```

Store-backed commands (`classes`, `news`, `grades`, `deadlines`) are fast and offline. Network commands (`sync`, `watch`, `curriculum`, `cra`, downloads) need internet.

## SIPAC public process lookup

Use this feature to follow UFPB administrative processes without opening each SIPAC page manually. Look up one process by its complete number or find processes by an interested party name or identifier. Process details include the current status, subject, interested parties, public documents, routing movements, status changes, and attached files.

```bash
sigaa sipac process 23074.056437/2026-26
sigaa sipac process 23074.056437/2026-26 --json
sigaa sipac search --name "Fulano de Tal"
sigaa sipac search --identifier "12345678901" --page 2 --json
```

Example summary:

```text
23074.056437/2026-26  [ATIVO]
  ANÁLISE DE PROPOSTA DE RESOLUÇÃO SOBRE DISTRIBUIÇÃO DE ENCARGOS DIDÁTICOS
  Origin: CI - DIREÇÃO DE CENTRO (11.01.45.01)
  Opened: 12/06/2026 17:26
  Interested parties: 1 | Documents: 14 | Movements: 6
```

Agents can call `sipac_get_public_process` with `{"number": "23074.056437/2026-26"}`. To search, call `sipac_search_public_processes` with either `name` or `identifier`. Both interfaces use the same `schema_version: 1` contracts as the CLI JSON output. Public SIPAC commands do not authenticate, bypass restricted documents, change processes, or persist results. See the [SIPAC process guide](docs/sipac-processes.mdx) for fields, use cases, privacy guidance, and error handling.

Headless fallback: `export SIGAA_USER=... SIGAA_PASS=...`.
Optional `SIGAA_DB=/path/to/sigaa.db` to override the store location.

## MCP server (for code agents)

Run `sigaa init`; it can detect or create `.mcp.json` and add the `sigaa` MCP
server without manual absolute-path editing.

Tools: `sigaa_list_classes`, `sigaa_list_news`, `sigaa_get_news_body`,
`sigaa_get_schedule`, `sigaa_list_grades`, `sigaa_list_deadlines`,
`sigaa_get_curriculum`, `sigaa_get_cra`, `sigaa_export_ics`,
`sipac_get_public_process`, `sipac_search_public_processes`,
`sigaa_download_historico`,
`sigaa_download_declaracao_vinculo`, `sigaa_download_atestado_matricula`,
`sigaa_sync`. Store-backed reads are offline; sync, live lookups, and downloads
touch the network.

`sipac_get_public_process(number)` returns the public process metadata exposed
by UFPB: general data, interested parties, documents and public download links,
movements, status changes, and attached files. It shares schema version 1 with
`sigaa sipac process --json` and does not require credentials.

`sipac_search_public_processes(name?, identifier?, page=1)` finds public
processes by one interested-party field. Pass exactly one of `name` or
`identifier`. Each response contains at most the 15 results exposed by one
portal page. Results are not retained after the request finishes.
Identifiers such as CPF, registration number, and CNPJ are personal data. Query
them only for a legitimate purpose and avoid copying them into logs.

`sigaa_get_curriculum` is networked and uses the same normalized contract and
filters as `sigaa curriculum`: `status`, `required_only`, `period`,
`include_requirements`, and `include_cra`. Its default `current` view contains
enrolled components plus required pending ones. Pending optional components are
choices toward the remaining optional workload, not courses that must all be
completed. `sigaa_get_cra` is also networked and reads the official CRA from the
academic transcript; a new student may receive `source: "unavailable"` until
SIGAA reports one. Neither response exposes SIGAA's internal student id.

Document tools accept a safe filename (not an arbitrary path), never overwrite,
and write under the app's private `downloads` directory. Set
`SIGAA_DOWNLOAD_DIR` on the MCP server to choose another directory. A successful
call returns both structured metadata (filename, MIME type, and size) and
an opaque MCP `ResourceLink`. Clients that support resource links can present the
document as an attachment or download; opening it reads the saved file through
MCP without putting its bytes in the original tool response. The resource link is
valid for the current server session, while the local file remains on disk. HTML
certificates are exposed as download-only binary resources so an MCP client does
not execute the report's active SIGAA markup inline.

## Scheduled polling

Run `sigaa init`; it can write the launchd plist on macOS or print the cron
entry for other operating systems.

## Credentials

Keyring-first, env-second. Never commit credentials, cookies, downloaded live HTML, SQLite databases, exported PDFs, or `.env` files.

`sigaa init` stores your SIGAA password securely in your OS keyring and verifies the login. Public SIPAC queries do not need credentials.

For headless environments: `export SIGAA_USER=username SIGAA_PASS=password`. Optional: `SIGAA_DB=/path/to/sigaa.db` to override the store location.

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
  sipac.py      unauthenticated public SIPAC process client + JSON contract
  models.py     Student, Turma, NewsItem, Schedule, CurriculumStatus
  parsers/      portal, news, schedule, curriculum, transcript, SIPAC process
  store/        SQLite db + repository (dedup, queries)
  services/     sync (fetch -> diff -> persist)
  cli.py        command line
  mcp_server.py agent tools
```

Adding a feature (materials, attendance) = a parser + client method and a
CLI/MCP surface, plus store columns when it is persisted. HTML changes touch
only `parsers/`. Implemented so far: classes, news (+bodies), grades, deadlines,
curriculum progress, official CRA, academic documents, and ICS export.
Public SIPAC administrative-process consultation is also available live.

`exporters/` turns store data into interchange formats (currently `ics`).

## Schedule decoding

`6M2345` → Fri (day 6) morning slots 2–5. Days 2=Mon..7=Sat, shift M/T/N.
Clock times in `config.SLOT_TIMES_UNCONFIRMED` are an **unconfirmed** default —
verify against a turma's "Plano de Curso" before using them for calendar export.

## Tests

```bash
pytest        # offline: parsers run on fixtures, store on in-memory sqlite
```

## Contributing

Interested in hacking on sigaa-tools? See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and release instructions.

## Security

Single-user, local-first tool. `config.py` reads credentials from keyring first
and environment variables second. The SQLite db is local and may contain student
data copied from SIGAA. `.gitignore` excludes `*.db`, `.env`, and live HTML
dumps, but review generated files before sharing logs, issues, or screenshots.
The SIPAC process feature is read-only and public; it does not send stored
credentials, but its responses can contain names and identifiers already shown
by the public portal, so handle exported JSON responsibly.

## License

MIT. See [LICENSE](LICENSE).
