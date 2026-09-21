# Agent guidelines

`AGENTS.md` is a symlink to this file. Edit `CLAUDE.md` only.

## What this tool does, and which surface to use

Two surfaces over one local SQLite store (`SIGAA_DB`, default
`~/.local/share/sigaa-tools/sigaa.db`):

- **CLI** (`sigaa --help`). `sync` and `watch` fetch from SIGAA; `classes`,
  `news`, `grades`, `deadlines`, `materials`, `whatsnew` and `ics` read the
  store; `curriculum`, `cra`, `extensao`, `attendance`, `plan`, `matricula`, the
  document downloads and `sipac` go live. Most accept `--json`.
- **MCP server** (`sigaa-mcp`), for chat agents that need to answer questions
  about one student's academic life. `SIGAA_MODE=hosted` drops the tools that
  write to disk.

Pick the surface by the job:

- **Notifications and monitoring: use the CLI, never an LLM judgement.**
  `sigaa watch --once --bodies --json --fail-on-error` emits one JSON event per
  change and ends every run with a `sync` event whose status is `changes`,
  `no_changes`, `failed` or `baseline`. Feed those events straight to the
  notifier. A model deciding "did anything change?" is how announcements got
  missed before; that is why no `watch` MCP tool exists. Schema and a cron
  example: `docs/notificacoes.mdx`.
- **Answering a question about the student: use the MCP tools** (or the
  store-backed CLI commands), which read what `sync` already persisted.

State worth knowing about:

- `watch_state` is the watcher's memory, keyed by SIGAA ids. The `is_new` flags
  behind `whatsnew` and `sigaa_whats_new` are a separate feed. Keep them
  separate: clearing one must not silence the other.
- Failures are staged (`auth`, `network`, `parse`, `sync`), recorded in
  `sync_run`, and surfaced as `error` events. Never let a failure degrade into
  an empty result or `no_changes` — that is the bug this design exists to
  prevent. An empty news list is only trusted when SIGAA itself says
  "Não há notícias cadastradas".

Credentials: `sigaa login` stores the password and the active account in the OS
keyring, which is enough for unattended runs. `SIGAA_USER`/`SIGAA_PASS` are
fallbacks for machines with no keyring (headless servers).

## Data in fixtures, tests, docs and PRs

Class-level SIGAA/UFPB data is public. Use it verbatim in fixtures, tests, docs,
commit messages and PR descriptions, and do not replace it with placeholders:

- class (turma) names and component codes (e.g. `DSCO00022`)
- turma ids (`idTurma`), schedule codes and room names
- teacher names as published on the class page
- announcement titles and text that a teacher posts to a class

Personal data must never be committed or published:

- credentials, `.env` files, cookies, session ids and ViewState tied to a session
- the student's name, matrícula (registration number), CPF and e-mail
- grades, attendance, transcripts, declarations and other exported PDFs
- local SQLite stores (`*.db`)
- raw live HTML that still contains any of the above

Before turning a live page into a fixture, cut it down to the parts the test
needs and anonymize any personal data left in it.

Generate test passwords at runtime (e.g. `secrets.token_urlsafe()`). Never
hard-code a password literal, even a dummy one: a literal dummy password once
set off GitGuardian secret scanning.
