# Contributing

Thanks for wanting to help `sigaa-ai-agent`. This is an unofficial open-source
project that makes SIGAA UFPB data more useful in local workflows, including a
CLI and an MCP server for agents.

Small contributions matter: parser fixes, sanitized fixtures, documentation,
clearer error messages, tests for real cases, or well-described issues all help.

## Before You Start

- This project is not affiliated with, endorsed by, or maintained by UFPB or
  SIGAA.
- Use SIGAA responsibly, avoid aggressive automation, and keep request rates
  low.
- Never publish credentials, cookies, live HTML with personal data, local SQLite
  databases, downloaded PDFs, screenshots with academic data, or `.env` files.
- When opening issues or pull requests, remove names, student IDs, sensitive
  class details, and any third-party data.

## Development Setup

Requirements:

- Python 3.11+
- Git
- A SIGAA account only if you need to test networked commands

Clone the repository and install it in editable mode:

```bash
git clone https://github.com/PucaVaz/sigaa-for-ai-agents.git
cd sigaa-for-ai-agents
python -m venv .venv
```

Linux/macOS:

```bash
source .venv/bin/activate
pip install -e ".[mcp,dev]"
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e ".[mcp,dev]"
```

To configure local credentials:

```bash
sigaa init
```

You can also use `SIGAA_USER`, `SIGAA_PASS`, and `SIGAA_DB`, but keep those
values out of Git.

## Running Tests

Tests should be offline and based on sanitized fixtures:

```bash
pytest
```

If a change needs new SIGAA HTML, only commit a sanitized version under
`tests/fixtures/`, with personal data removed.

## Where To Change Things

The project is organized in layers:

- `sigaa/parsers/`: SIGAA HTML into structured data.
- `sigaa/client.py`: authenticated navigation and high-level calls.
- `sigaa/store/`: local SQLite persistence.
- `sigaa/services/`: sync and application rules.
- `sigaa/cli.py`: terminal commands.
- `sigaa/mcp_server.py`: MCP tools for agents.
- `tests/`: offline tests with fixtures.
- `docs/`: user documentation.

A typical feature change looks like this:

1. Add or update a sanitized fixture.
2. Create or adjust the parser with a unit test.
3. Expose the data through the needed client or service.
4. Persist it in the store when appropriate.
5. Expose it through the CLI and/or MCP.
6. Update README/docs if the user-facing interface changed.

## MCP Guidelines

MCP tools should be predictable for agents:

- Prefer fast reads from the local database.
- Make it clear in the docstring when a tool touches the network.
- Avoid side effects in tools that look like read-only queries.
- Return simple, JSON-friendly, stable structures.
- Write error messages that help the agent find the next step, such as running
  `sigaa_sync` or configuring credentials.

## Code Style

- Keep changes small and focused.
- Preserve existing APIs and naming where possible.
- Isolate HTML-specific changes inside `sigaa/parsers/`.
- Prefer deterministic fixture-based tests over tests against the live SIGAA
  site.
- Write useful error messages for both CLI and MCP users.
- Do not add new dependencies without a clear reason.

## Opening An Issue

When reporting a bug, include:

- The command or MCP tool you used.
- The expected result.
- The actual result.
- Your Python version and operating system.
- A sanitized HTML or output snippet, if it helps.

Do not include personal data or credentials.

## Opening A Pull Request

Before opening a PR:

```bash
pytest
```

Recommended checklist:

- The change has a clear scope.
- Tests were added or updated when needed.
- New fixtures are sanitized.
- Networked commands remain explicit.
- Documentation was updated if the user-facing interface changed.
- No secrets, local databases, live HTML, or academic PDFs were included.

In the PR, explain the problem, the solution, and how you tested it. If the
change depends on behavior observed in the live SIGAA site, describe the case
without exposing personal data.

## Security And Privacy

This project handles local academic data. Treat everything that comes from SIGAA
as sensitive by default. When in doubt, do not publish the data: reproduce the
format with fake information or ask for guidance in the issue.

