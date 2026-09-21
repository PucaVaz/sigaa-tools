# UFCG onboarding status

This profile is provisional. Classic authentication is tested with synthetic
login and portal fixtures from [JucaGF/sigaa-tools-ufcg](https://github.com/JucaGF/sigaa-tools-ufcg)
under the repository's MIT license. Pseudo session tokens were removed from the
copied fixtures. No live UFCG account was used for this change.
Because it is provisional, `sigaa init` does not offer it; select it with
`--institution ufcg` or `SIGAA_INSTITUTION=ufcg`.

| Feature | Evidence |
| --- | --- |
| Classic login | Synthetic form, redirect, rejection and host-isolation tests |
| Student portal parsers | Existing classic portal fixture is rejected loudly |
| Portal/class navigation | Not implemented; requires private live captures |
| Grades, news, professors, attendance, course plan | Not captured in this checkout |
| Calendar slots | M1–M5, T1–T5, N1–N4; clock times unconfirmed; export unsupported |
| SIPAC, curriculum JSON, enrollment and documents | Unsupported |

A UFCG student must run the capture/probe loop in [the onboarding playbook](../onboarding.md),
add the navigation and parser variants established by those captures, complete
`onboard check`, and regenerate this report from real evidence. The profile
already exists, so skip `onboard init ufcg`.

The fork's documented parser compatibility table has not been reproduced:
its authenticated captures are private and are not in the fork. Synthetic
portal tests do not establish that course plans work on live UFCG or reproduce
the grades, professors, news, student, and class failures from those captures.
The extraordinary-enrollment worker is outside this implementation.
