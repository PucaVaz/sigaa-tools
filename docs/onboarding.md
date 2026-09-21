# Onboard an institution

Work in an isolated checkout. A student of the institution must supply their
own account through the OS keyring or environment. Never send credentials in
chat or commit a capture. Only the student can complete live acceptance.

1. Run `sigaa onboard login-probe --url https://your-host/sigaa/login-page`.
   This reads the public login form. It never submits credentials.
2. Run `sigaa onboard init your_key --host https://your-host`. The generated
   provider deliberately has no supported capabilities, empty menu labels and
   URLs, and a navigator whose every step raises until you implement it; it
   inherits nothing from UFPB. The registry picks the module up by itself.
   Implement navigation and declare capabilities only for available features.
3. Run `SIGAA_INSTITUTION=your_key sigaa onboard capture` with credentials
   available from keyring or the environment. If the student parser is not yet
   supported, use environment credentials outside the repository for this first
   capture; `sigaa login` also verifies that parser. After it passes, run
   `sigaa login --institution your_key` to save the account. Enrollment capture needs
   `--include-matricula`; capture stops before selection or submission.
4. Run `sigaa onboard probe --from captures/your_key/<date> --json`. Without
   `--from`, probe captures live pages first. Results contain counts, field
   presence, variant names and structural digests, never student values.
5. For each failure, read the private capture, add a navigation method or a
   separately recognized parser variant, and create a minimal sanitized fixture
   with a regression test. Repeat the probe. An unrecognized page must never
   become an empty result. Preserve all existing variants' behavior.
6. Complete private `identity.json` with username, name, matrícula and email
   when the initial parser could not extract them. Remove these values, other
   students' data, cookies and session tokens from every new fixture. Use public
   class names, codes and teacher announcements verbatim.
7. Stage the intended files, then run `sigaa onboard check --from captures/your_key/<date>`.
   The gate scans staged blobs and untracked files, runs pytest and Ruff, and
   rejects unexplained `unrecognized` or `nav_failed` results. A reviewed JSON
   feature-to-reason map can be passed with `--explanations`. Uncaptured features
   remain evidence gaps; a passing gate is not proof of their compatibility.
   The identity scan matches every value in `identity.json`, each word of four or
   more letters in the name, and the e-mail local part, as whole words and
   ignoring accents and case. It fails closed, so expect false positives: a
   teacher, room or class title that shares a word with the student's name (a
   common surname such as Silva) is reported too. Findings name only the
   category and file index. Cut the fixture down until the colliding text is no
   longer needed; if public class data itself collides, stop and ask rather than
   weakening the gate or editing `identity.json`.
8. Run `sigaa onboard report --from captures/your_key/<date>`. Review and stage
   the generated compatibility document, rerun check, then open one PR for the
   institution with actual command results and the tested commit. Do not publish
   private capture directories or their identity files.

Capture directories use mode 0700 and files use 0600. Treat them as private even
though Git ignores them. Never use `git add -f` for a capture. The transport guard
rejects submission controls, but the fixed fetcher registry is the primary
read-only boundary. Do not add enrollment workers to that registry.

Allowed changes during an institution onboarding: `sigaa/institutions/<key>.py`
(the registry needs no edit), new parser variants, tests and sanitized
`tests/fixtures/<key>/` files, and `docs/institutions/<key>.md`. Changes to shared
navigation or existing variants need a separately agreed scope.

Stop and ask the student on CAPTCHA, 2FA, an unhandled vínculo picker, work
outside that allowlist, or private data that cannot be removed by trimming the
fixture. Never work around these conditions or silently select an account.

Synthetic empty-state fixtures document parser contracts. They do not establish
what a live institution renders. Capture real empty states before declaring
compatibility or requesting approval for that institution.
