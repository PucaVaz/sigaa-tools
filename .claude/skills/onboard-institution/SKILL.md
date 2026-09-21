---
name: onboard-institution
description: Add a SIGAA institution using private captures, parser probes, sanitized fixtures, and the deterministic onboarding gate. Use for a new institution or its compatibility failures.
---

Read [the onboarding playbook](../../../docs/onboarding.md) before work.
Use `sigaa onboard` as the source of capture, probe, check and report results.

Run the loop: probe, inspect the private failing capture, add a navigation method
or distinct parser variant, trim a sanitized fixture, add a regression test, and
probe again. An empty result requires a recognized empty state. Never alter an
existing variant to make a new institution pass.

Limit edits to the target provider module (the registry discovers it), new parser variants,
tests and its fixture directory, and its compatibility document. Never stage a
capture or identity file. Stop and ask on CAPTCHA, 2FA, an unhandled vínculo
picker, edits outside that scope, or private data that trimming cannot remove.

Before preparing the PR, stage the intended files and run `onboard check` with
the private identity file complete. Report actual failures and uncaptured
features. A report file or synthetic fixture is not live verification. Opening
a PR does not authorize merging or contacting reviewers.
