# sigaa-ai-agent

> [!IMPORTANT]
> This is an unofficial personal project and is not affiliated with, endorsed
> by, or supported by UFPB, SIGAA, or SIPAC. Use it responsibly, keep request rates low,
> and follow the rules that apply to your SIGAA account.

User-friendly client for **SIGAA UFPB** and the **SIPAC/UFPB public process
portal**, built for automation: a **CLI** and an **MCP server** over a layered
Python core. Authenticated SIGAA features remain single-user and local-first.

SIGAA has no official API. This wraps the JSF web flow: login (cookie jar +
`ViewState`, no JWT, no CAPTCHA), enrolled classes, academic progress and CRA,
plus **per-class news channels** persisted to SQLite with stable dedup by news
id.

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
HTML, SQLite databases, exported PDFs, or `.env` files.

Run `sigaa init`. It prompts for your SIGAA username and password, stores the
password in your OS keyring when available, verifies the login, runs the first
sync, and can configure MCP and scheduled polling for you.

Public SIPAC process queries do not need credentials and never read the stored
SIGAA username or password.

## Public SIPAC process lookup

Use this feature to follow UFPB administrative processes without opening each SIPAC page manually. Look up one process by its complete number or find processes by an interested party name or identifier. Process details include the current status, subject, interested parties, public documents, routing movements, status changes, and attached files.

```bash
sigaa sipac process 23074.056437/2026-26
sigaa sipac process 23074.056437/2026-26 --json
sigaa sipac search --name "Gilberto Farias de Sousa Filho"
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

## CLI

```bash
sigaa sync                 # hit SIGAA: persist new news, deadlines, grades
sigaa sync --bodies        # also fetch full news article text
sigaa classes --schedule   # enrolled classes with decoded weekly schedule
sigaa news --class DSCO00022   # news for one class, from the store
sigaa news --unread --mark-seen
sigaa grades --semester 2025.1 # grades report by semester
sigaa deadlines            # assessment/task due dates
sigaa ics --out sigaa.ics  # export classes + deadlines as a calendar
sigaa curriculum           # live CRA, enrolled + required pending components
sigaa cra --json           # official CRA as JSON from the academic transcript
sigaa sipac process 23074.056437/2026-26 --json # public SIPAC process lookup
sigaa sipac search --name "Gilberto Farias de Sousa Filho" --json # find public processes
sigaa historico --out h.pdf # download the academic transcript PDF (networked)
sigaa declaracao-vinculo --out declaracao-vinculo.pdf # enrollment declaration PDF (networked)
sigaa atestado-matricula --out atestado-matricula.html # enrollment certificate HTML (networked)
sigaa watch --interval 900 # foreground loop
```

Store-backed listing commands are fast and offline. Login, sync/watch, live
lookups, and downloads access the network. `sigaa sipac process` reads only
SIPAC's public portal and does not authenticate.

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
