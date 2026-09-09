# Public guide evaluation — 2026-09-09

The public job is to try contextual alt-text review: inspect a photo and its page,
choose names using evidence, edit, preview, apply, and undo in the current tab.

| Surface | Decision | Canon rationale |
| --- | --- | --- |
| WordPress toolbar | Suppress on the enabled guide route, including signed-in visitors. | NAV-08: administration is not an entry point for this public job. |
| Workspace Design notes disclosure | Keep in admin only; the public case-study link is the explanation path. | NAV-08: secondary implementation explanation competes with task completion. |
| Workspace action history | Keep in admin only. Retain live action feedback, before/after comparison, draft recovery and Undo. | COG-02, INT-09: visible current state and reversal support the task without a second narration of every click. |
| Roster suggestions | Open the existing reference galleries by default; keep enlargement and neutral unnamed choices. | HAI-01, HAI-17: inspect evidence before choosing a label; show available captures across conditions. |
| Second full scene | Do not add a second required exercise in this wave. Existing independent reference captures strengthen the identity decision; repeating the same review would lengthen first use without proving a new capability. A later optional scene should demonstrate remembered names in a different context, with licensed media and truthful persistence. | HAI-17, NAV-08. |
| Typography | Self-host the exact Roboto Flex and Geist Mono font files used by darce.xyz/work, with their OFL licenses. | Consistent typography; no external font request needed. |
| Apply layout | Replace the public single-row flex layout with a responsive comparison grid. | PERC: retain readable labels and adjacent before/after evidence; no mobile horizontal overflow. |

Canon source: heuristics-canon lexicons/interaction-ux.md (local canon consulted;
HAI-01, HAI-17, NAV-08, COG-02, INT-09). Existing sample coverage stays honest:
all two Justin references and three of five Katy references are bundled.

The automated UX-map critique reports no high findings. Its two RLSE-04 medium
findings concern the static outcome and external escape screens. Named exemptions:
the outcome is only rendered after a successful local operation (errors belong to
apply), and escape is an external exit with no local loading/error state to own.
The installed map CLI predates two metadata fields; critique used a temporary copy
omitting only domain_state_mappings and slices, retaining all screens/actions/flows.

Integration includes guidedeploy-1, issuedag-1 (including its cutover and hygiene
ancestors), gpu-launch-1, and issuedag-1-secure-resume-2. The review worktree is a
duplicate ref; guidedeploy-devfir has no commits or dirty files. Original worktrees
are retained. Secure replay tests were reconciled to the capability-bearing poll
contract and separate terminal cache, and the browser poll now forwards that key. The unfinished skipped-probe result
metadata slice is also completed (seven existing regressions pass).

Release scope: plugin-only version 0.0.9, using the existing wpcli install and
activation steps. The public recorded guide makes no recognition calls. No
producer adapter/profile, GPU lifecycle, seed-generation, or Caddy mutation is
part of this deployment. Full-stack preflight remains blocked by the registered
but absent dev-fir environment; its registration is preserved pending clarification.
Backend changes are integrated in Git, not claimed deployed by this plugin release.

Live verification: plugin activation required a fresh-request rewrite flush to
restore /guide/. bootstrap-wp.sh now performs that flush after activation. The
enabled option was preserved. Rollback copy is retained on the VM under
/opt/acx-backend/demo/rollback-guidepolish-20260909/alt-context.

Follow-up release 0.0.10: replaced the second Trudeau crop with Lea-Kim
Chateauneuf’s July 2023 REM-opening portrait (CC BY-SA 4.0), using the Commons
960 px thumbnail. This is an illustrative reference replacement; recognition
was not rerun. Source and licence are recorded in the asset ledger and packaged
as js/public/guided-image-credits.md. Removed the public entrance’s Watch the
recording action, as requested by its nth-child(2) selector.

Validation: 81 focused tests, TypeScript and production build passed. Live
1440 px and 393 px browser checks confirmed the new image, absent recording
action, all five loaded references, apply/undo, fonts, no overflow, no page
errors and no recognition API requests. Version 0.0.10 is active; uploaded ZIP
SHA-256 was verified. Version 0.0.9 backup:
/opt/acx-backend/demo/rollback-guidepolish-0.0.9/alt-context.
