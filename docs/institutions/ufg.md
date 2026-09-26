# UFG onboarding status

UFG support is provisional. Authentication with an imported session passed a
live check on 2026-09-25; nothing past the portal landing has been validated. No public academic capability is enabled for this profile,
and it is selectable only with `--institution ufg` or `SIGAA_INSTITUTION=ufg`.

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

Run from `matheus/ufg-onboarding` with a student's own browser session, through
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

## Open questions before live acceptance

- **How long a session lasts**, idle and with a `watch` every 15 minutes. This
  decides whether unattended monitoring is practical or only interactive use.
- **Portal markup.** Landing is confirmed; the student, class-list and deadline
  parsers still need a private capture and sanitized fixtures.
- **Student parser.** `sigaa login` verifies the account by parsing the student
  from the portal. Until a UFG variant exists, run the first capture with
  `SIGAA_USER` and `SIGAA_SESSION` from the environment, as `docs/onboarding.md`
  describes.

Tests use the UFCG classic-portal contract fixture as a stand-in. It establishes
nothing about UFG's markup; replace it with a sanitized UFG capture.
