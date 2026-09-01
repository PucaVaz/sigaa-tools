# Contributing

Thanks for wanting to help `sigaa-tools`. This is an unofficial open-source
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

## Fork and Pull Request Workflow

We use the standard fork-and-PR workflow to keep contributions organized:

1. **Fork** the repository on GitHub.
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/YOUR-USERNAME/sigaa-for-ai-agents.git
   cd sigaa-for-ai-agents
   ```
3. **Create a branch** for your change:
   ```bash
   git checkout -b fix/description-of-change
   ```
4. **Make your changes**, test them, and commit:
   ```bash
   git add .
   git commit -m "description of what you fixed"
   ```
5. **Push** to your fork:
   ```bash
   git push origin fix/description-of-change
   ```
6. **Open a Pull Request** on GitHub. The PR template and CI checks will guide you.

CI tests and linting run automatically on every PR. If tests fail, push fixes to the same branch—the PR updates automatically.

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

The repository's committed `.mcp.json` runs the MCP server from your checkout
via `uv run --extra mcp sigaa-mcp`, so agents you point at this repo exercise
your local changes rather than a published build. Install
[uv](https://docs.astral.sh/uv/) if you want that; the venv flow above works
fine without it.

### First-Time Contributor?

Welcome! If this is your first contribution, here's what to expect:

- **CI checks run automatically** on your PR. The workflow runs tests and linting
  (see `.github/workflows/ci.yml`). If it fails, you'll see details in the PR
  status—push fixes to your branch and the PR updates automatically.
- **At least one review is required** before merging. This keeps code quality high
  and is not personal—reviewers are here to help.
- **Start small.** A parser fix, a new test case, or improved documentation is
  easier to review than a large feature. Questions? Open an issue first.

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

## Release Process

Maintainers can publish new releases to PyPI via GitHub Actions:

1. **Update the version** in `sigaa/__init__.py` (e.g., `__version__ = "0.2.0"`).
2. **Commit and push** the change to `main`.
3. **Create a git tag** matching the version: `git tag v0.2.0 && git push origin v0.2.0`.
4. **GitHub Actions** (`publish.yml`) automatically builds the package and pushes to PyPI.

Note: The package version is read from `sigaa/__version__` at build time, so a single source of truth is maintained.

