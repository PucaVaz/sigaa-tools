# Agent guidelines

`AGENTS.md` is a symlink to this file. Edit `CLAUDE.md` only.

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
