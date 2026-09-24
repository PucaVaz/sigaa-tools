# UFCG onboarding status

This profile is provisional. Classic authentication is tested with synthetic
login and portal fixtures from [JucaGF/sigaa-tools-ufcg](https://github.com/JucaGF/sigaa-tools-ufcg)
under the repository's MIT license. Pseudo session tokens were removed from the
copied fixtures. A private live validation was also run on 2026-09-21 against
SIGAA UFCG 4.20.6-ufcg.4; at the tested phase-5 commit it proved classic login
and capture only. Later parser changes were checked offline against that capture.
Because it is provisional, `sigaa init` does not offer it; select it with
`--institution ufcg` or `SIGAA_INSTITUTION=ufcg`.

| Feature | Evidence |
| --- | --- |
| Classic login | Synthetic tests plus a successful private live capture |
| Student and class-list parsers | Fresh authenticated portal capture; offline probe recognized one student and five classes; acceptance gate pending |
| Portal deadlines | The old capture confirms an empty 15/7-day window; the fresh portal capture has two parsed assessments with local content-derived IDs; acceptance gate pending |
| Portal/class navigation | Class pages were not captured by the fresh portal capture; separate navigation evidence required |
| Store-backed CLI/MCP and sync | Blocked while the UFCG profile is provisional; account/store binding remains unimplemented |
| Grades, news, professors, attendance, course plan | Not captured in this checkout |
| Calendar slots | M1–M5, T1–T5, N1–N4; clock times unconfirmed; export unsupported |
| SIPAC, curriculum JSON, enrollment and documents | Unsupported |

A UFCG student must run the capture/probe loop in [the onboarding playbook](../onboarding.md),
add the navigation and parser variants established by those captures, complete
`onboard check`, and generate the separate compatibility report from real evidence. The profile
already exists, so skip `onboard init ufcg`.

The fork's full parser compatibility table has not been reproduced: its older
authenticated captures are private and are not in this checkout. The private
portal captures support only the portal parser results below; synthetic tests
do not establish live course-plan, grades, professor, or news compatibility.
The extraordinary-enrollment worker is outside this implementation.

## Private live validation, 2026-09-21

Tested commit: `33fb842` (`pucavaz/multi-institution-phase-5`). The capture,
identity file, and raw HTML remain local and ignored by Git.

| Check | Result |
| --- | --- |
| Public `onboard login-probe --institution ufcg --json` | Detected the classic Struts login form |
| Authenticated `onboard capture --json` | 3 pages captured; 0 navigation failures |
| Offline `onboard probe` | `student`, `turmas`, and `deadlines` unrecognized |
| `onboard check` | Rejected: no verified features; the same three features unresolved |
| `pytest` | 515 passed |
| `ruff check .` | Passed |

This section records the original phase-5 result, not the status of later code.
No raw capture, identity file, credential, or student value belongs in a commit
or pull request.

## Offline recovery on the phase-5 follow-up branch

The old private portal capture now probes as `student: ok` (one record) and
`turmas: ok` (five records). The class code is absent from that render and is
not inferred. Sanitized fixture tests cover changed identity and class markup,
update links that are not classes, and unchanged UFPB parsing. This is offline
parser evidence, not a fresh authenticated acceptance run.

The same private capture now probes `deadlines: empty_confirmed` with count `0`:
`form#formAtividades #avaliacao-portal p.vazio` explicitly reports no activities
in the next 15 days or past 7 days. This confirms only that activity window,
not the absence of all deadlines or parsing of populated UFCG events. This is
an offline parser regression, not fresh live acceptance. No compatibility
report, PR approval, or claim of working class navigation follows from it.
The UFCG profile remains provisional and all store-backed consumers remain
blocked until institution and account binding is implemented and tested
separately. The fresh capture below provides additional portal evidence.

## Authenticated portal capture, 2026-09-24

The student captured three pages with zero navigation failures from SIGAA UFCG
`4.20.6-ufcg.6`. On this branch, the offline probe reports `student: ok` (one),
`turmas: ok` (five), and `deadlines: ok` (two). The two deadline records are
portal assessments, not captured task details. Their `ufcg:portal:v1:` IDs are
derived locally from turma, date, kind, and title; SIGAA did not supply event
IDs. An edited date or title changes the key, and duplicate or ambiguously
associated rows are rejected rather than guessed.

The private identity file still needs a local e-mail before `onboard check` can
evaluate this capture. No identity values or raw HTML belong in Git. This
portal result does not prove class-page navigation or store-backed UFCG access;
the profile remains provisional and the compatibility/approval gate is pending.
