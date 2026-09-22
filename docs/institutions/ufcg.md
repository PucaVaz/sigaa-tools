# UFCG onboarding status

UFCG support remains incomplete. Classic authentication has been reported as
working with a live account. Portal parsers and class navigation have not passed
live acceptance. No public academic capability is enabled for this profile.

## Live validation reported on 2026-09-21

A student tester reported these results from a clean checkout of
`pucavaz/multi-institution-phase-5`, against SIGAA `4.20.6-ufcg.4`.
The tested commit SHA and private capture manifest were not supplied with the
report. These are attributed results, not a new live run by this checkout.

| Check | Reported result |
| --- | --- |
| Public login probe | `classic-struts` |
| Authenticated capture | Three pages; zero recorded `nav_failed` entries |
| Student, classes and deadlines probe | All `unrecognized` |
| Onboarding gate | Failed: no verified feature |
| Offline suite | 515 tests passed; Ruff passed |
| Diff whitespace check | Failed: trailing blank line in `participantes.py` |
| Review verdict | Request changes; do not approve |

The old capture implementation hid class-discovery failures as `not_captured`.
Therefore the reported zero navigation failures does not establish working
class navigation. New captures preserve those failures as `nav_failed`. Offline
probing retains captured evidence and errors even if a capability is disabled.

## Current boundaries

| Feature | Evidence and availability |
| --- | --- |
| Classic login | Synthetic tests and the attributed live success above |
| Student portal parsers | Live report says `unrecognized`; public access disabled |
| Portal/class navigation | Not implemented; needs private live captures |
| Grades, news, professors, attendance, course plan | No verified live evidence |
| Calendar slots | M1–M5, T1–T5, N1–N4; clock times unconfirmed; export unsupported |
| SIPAC, curriculum JSON, enrollment and documents | Unsupported |

The profile is provisional, so `sigaa init` does not offer it. Select it with
`SIGAA_INSTITUTION=ufcg` for the diagnostic capture workflow. Authentication-only
capture saves the portal for student, class and deadline diagnostics without
advertising portal support to CLI or MCP users. A failed class lookup makes
capture return a nonzero status; its private output remains available to probe.

A UFCG student must continue the [onboarding playbook](../onboarding.md) in the
checkout that holds their private captures. Add navigation and parser variants
supported by minimal sanitized fixtures, pass `onboard check`, and regenerate
the compatibility report with the tested commit before requesting approval.
Skip `onboard init ufcg`: the profile already exists. Do not publish raw captures
or identity files. This document records the supplied summary; it was not
regenerated from private captures that are unavailable here.

Synthetic login and portal fixtures originate from
[JucaGF/sigaa-tools-ufcg](https://github.com/JucaGF/sigaa-tools-ufcg), under its MIT
license. Pseudo session tokens were removed. Those fixtures alone do not
establish live compatibility. The extraordinary-enrollment worker remains out
of scope.
