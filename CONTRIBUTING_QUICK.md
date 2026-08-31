# Contributing to sigaa-tools — Quick Start

**How to contribute in 3 steps** (for developers, testers, and documentarians):

## 1. Fork and clone

Fork the repo on GitHub, then clone your fork:

```bash
git clone https://github.com/YOUR-USERNAME/sigaa-for-ai-agents.git
cd sigaa-for-ai-agents
```

## 2. Make a change and test it

- Fix a bug, improve docs, add a test, or improve an error message.
- Run tests locally: `pytest`
- Run linting: `ruff check .`

## 3. Open a pull request

Push your branch and open a PR on GitHub. CI runs automatically, and a reviewer will give feedback.

---

## Not a coder? Help anyway!

- **Documentation:** Improve README, docstrings, or guides.
- **Issues:** Report bugs with steps to reproduce and your environment.
- **Testing:** Try features, report edge cases, or describe confusing parts.
- **Sanitized fixtures:** If you find a real SIGAA HTML case that the parser breaks,
  share a sanitized (no personal data) version for the test suite.

---

## See also

- Full contributing guide: [CONTRIBUTING.md](CONTRIBUTING.md)
- Reporting bugs: `CONTRIBUTING.md#opening-an-issue`
- Code style and structure: `CONTRIBUTING.md#where-to-change-things`
- CI workflow: `.github/workflows/ci.yml`
