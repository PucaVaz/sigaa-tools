# UFG onboarding status

UFG support is provisional and partial. It is selectable only with
`--institution ufg` or `SIGAA_INSTITUTION=ufg`. The profile declares only the
capabilities whose parsers passed `sigaa onboard probe` on live captures:

| Capability | Status | Source |
| --- | --- | --- |
| `portal` (student, classes, activities) | declared | live capture 2026-09-26, variants `ufg-student`, `ufg-turmas`, `ufg-deadlines` |
| `news` (list and body) | declared | live capture 2026-09-26, existing `news-builtin` variants; one class with news, one with the confirmed "no news" state |
| `materials` | declared | live capture 2026-09-26, existing `class-topic-items` variant with UFG's per-file `key` (12 and 2 items) |
| `attendance` | declared | live capture 2026-09-26 (3rd), existing `frequency-map` variant (12, 13 records) |
| `plan` | declared | live capture 2026-09-26 (3rd), existing `course-plan-tables`; new `course-plan-not-registered` for SIGAA's "Esta turma ainda não possui um plano cadastrado." |
| `participants` | declared | live capture 2026-09-26 (3rd), existing `participants-role-count` variant |
| grades | not declared | per-class "Ver Notas" parses (`class-grade-headers`, no grade posted yet), but the capability also covers the portal's "Minhas Notas", a JSCook menu not mapped yet |
| tasks, calendar, curriculum, matrícula, documents, extensão, SIPAC | not declared | not captured |

`sigaa sync` reads only declared capabilities and lists the rest under
`unsupported` in `sync --json`.

## Authentication: CAS with reCAPTCHA

`https://sigaa.sistemas.ufg.br/sigaa/verTelaLogin.do` redirects to CAS at
`https://sso.ufg.br/cas/login?service=...`, and the SSO enforces reCAPTCHA. A
username/password login can therefore never run unattended, and this tool does
not try: the profile uses `auth_mode="session"`.

1. Log in to SIGAA in a browser, solving the reCAPTCHA yourself.
2. Copy the whole `Cookie` request header of any SIGAA page (DevTools > Network
   > the page request > Request Headers > Cookie). SIGAA needs both
   `JSESSIONID` and `_ufg_br_sess`; `JSESSIONID` alone lands on `expirada.jsp`.
   The Application tab's cookie list can miss `_ufg_br_sess`, so copy from
   Network.
3. Run `sigaa login --institution ufg` and paste it at the hidden prompt. It is
   stored in the OS keyring (service `sigaa-ufg`) in the slot a password would
   use. `SIGAA_SESSION` is the fallback where no keyring exists.

The tool sends that cookie only to `sigaa.sistemas.ufg.br` and never contacts
`sso.ufg.br`. A dead session is an `auth` failure either way SIGAA reports it:

- A portal page requested with a dead session 302s to an empty
  `/sigaa/expirada.jsp` on the SIGAA host (observed live on 2026-09-25 with an
  invalid cookie). The navigator treats that page as logged out.
- A hop to CAS (as `verTelaLogin.do` does) is refused by the request guard,
  which raises `SsoRedirectError`.

`sigaa watch` reports either as an `error` event, never as `no_changes`. The fix
is to repeat the steps above.

The cookie is a live session credential: never paste it in chat, commit it, or
put it in a fixture.

## Live check, 2026-09-25

Run from this branch with a student's own browser session, through
the production `Session` (tool's default User-Agent, request guard, navigator).
Only GETs; structural output only, no personal values recorded.

| Check | Result |
| --- | --- |
| Cookies in the browser's Cookie header | `JSESSIONID`, `_ufg_br_sess` |
| `login()` with both cookies | OK, authenticated portal reached |
| Two further reads of the portal | still authenticated |
| `JSESSIONID` alone | `expirada.jsp`, reported as an expired session (`auth`) |
| Session bound to the browser's User-Agent | no (an iPhone Safari session worked with the tool's desktop UA) |
| `/sigaa/portais/discente/discente.jsf` | portal with logout link; no vínculo picker |
| `/sigaa/verPortalDiscente.do`, `/sigaa/paginaInicial.do` | redirect to the same portal (the latter via `telasPosSelecaoVinculos.jsf`) |
| Hosts contacted | `sigaa.sistemas.ufg.br` only |

## Captures, 2026-09-26

Two private captures (not committed) from the student's own session, SIGAA
`4.2.651`. The first read the portal only; the second entered two classes with
PORTAL, NEWS and MATERIALS granted in memory, never in the committed profile.
`sigaa onboard probe` on the second: student ok (1), turmas ok (4), deadlines ok
(1), materials ok (12, 2), news ok (1) and empty_confirmed (0), news_body ok (1).

Fixtures `tests/fixtures/ufg/portal.html` and `turma_topics.html` are cut down
from those pages. Class data, teacher announcements and material titles are
verbatim; the student's name, matrícula, course, unit and e-mail are replaced,
academic indices, the chat link's user id and the per-file download keys are
removed or replaced.

## End-to-end sync, 2026-09-26

`sigaa sync --json` then `sigaa watch --once --json --fail-on-error`, with the
student's imported session and a throwaway database:

| Check | Result |
| --- | --- |
| `sync` | exit 0, `ok: true`, 4 classes, no class errors |
| New items | 7 news, 31 materials, 1 deadline |
| `unsupported` | `grades`, `plan`, `attendance`, `participants` |
| `watch --once` | exit 0, status `changes`, events `news`, `material`, `deadline` |
| Same run with an invalid cookie | both exit 1, stage `auth`, "imported SIGAA session expired" |

## Class menu capture, 2026-09-26

A third private capture entered two classes and followed the Turma Virtual
`formMenu` (same labels as UFPB: Ver Notas, Frequência, Plano de Curso,
Participantes). UFG's form carries one hidden field more than the clicked
item's, so the navigator replays every hidden input, as a browser does. Probe:
attendance ok (12, 13), participants ok (1, 1), plan ok (12 entries) and
empty_confirmed (no plan registered), per-class grades empty_confirmed (2), and
the portal's "Minhas Notas" nav_failed (not mapped).

## End-to-end sync with the class menu, 2026-09-26

The same run after declaring attendance, plan and participants:

| Check | Result |
| --- | --- |
| `sync` | exit 0, `ok: true`, 4 classes, no class errors |
| New items | 7 news, 31 materials, 3 deadlines (1 portal activity, 2 plan evaluations) |
| `unsupported` | `grades` |
| `watch --once` | exit 0, status `changes`, events `news`, `material`, `deadline`, `attendance` |

## Open questions before live acceptance

- **How long a session lasts**, idle and with a `watch` every 15 minutes. This
  decides whether unattended monitoring is practical or only interactive use.
- **Empty states.** No class list or activity list without rows has been seen
  live, so an empty one fails as unrecognized rather than being trusted. A
  student with no pending activity will see sync fail until that page is
  captured and a variant added.
- **Activity kinds.** Only `Tarefa:` has been seen. Other labels (avaliação,
  questionário) fail as unrecognized until captured.
- **Grades.** Map the portal's "Minhas Notas" JSCook item (`jscook_action`
  on `menu:form_menu_discente`) and capture that report before declaring
  `grades`.
- **No component code.** The UFG portal shows no code per class, so
  `Turma.code` is empty and `--class` must be given the `idTurma`.
- **Material downloads.** Listing is verified; downloading with the replayed
  `key` has not been run live.

Session tests still use the UFCG classic-portal contract fixture for the login
landing; the parser tests use the UFG fixtures above.
