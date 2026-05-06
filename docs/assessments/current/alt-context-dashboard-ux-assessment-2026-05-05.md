# Alt Context Dashboard UX Assessment

> **Metadata**
>
> - **Date**: 2026-05-05
> - **Author**: Codex
> - **Scope**: `apps/prototype-wp-alt-context` dashboard route and dashboard-adjacent admin UX
> - **Status**: Draft

The Alt Context dashboard is a useful operator landing page, especially for library coverage, recognition backlog, and sync health. In the current local instance at `http://localhost:10010/wp-admin/admin.php?page=alt-context-dashboard#/dashboard`, the page also exposes several prioritization problems: urgent failure work competes with first-run onboarding, retention failure is non-actionable, and batch/recent activity panels are mostly empty or local-storage-bound. The next spec should preserve the dashboard as a triage surface, but make it less of a general brochure and more of an action console.

**Related docs:**

- [Recognition roster suggestion workflow assessment](recognition-roster-suggestion-workflow-assessment-2026-05-05.md)
- [WP alt-context cross-cutting assessment](wp-alt-context-cross-cutting-assessment.md)
- [E15-13 roster curation loop task plan](../../tasks/15.0/E15-13-roster-curation-loop-task-plan.md)
- `literature/extracted/refactoring/Refactoring-UI.txt`
- `literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt`
- `literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt`
- `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt`
- `literature/extracted/refactoring/modern-software-engineering.txt`

## Executive Summary

The useful dashboard elements are the operator-mode warning, coverage summary, identity recognition summary, sync health card, and direct links into Workbench/Roster remediation paths. These align with the project goal: a WordPress admin should know what needs attention without understanding the backend topology.

The less useful elements are the permanent first-run orientation card, a generic Batch Operations hub, and local-only Recent Activity. They occupy high-value dashboard space but do not reflect the most important current state. In the observed local session, the page reports 6,682 media items, 6,682 missing alt text, 16 pending identity clusters, 10 media with faces, and 91 failed replay operations. That is a clear operational story, but the layout still leads with onboarding and broad navigation.

The next direction should keep the dashboard, but split it into three priority bands: blocking health, review queues, and secondary utilities. Retention should either become actionable or move behind a lower-priority governance link when unavailable. Batch history should come from durable backend/local records rather than browser local storage before it remains a prominent dashboard component.

The extracted literature supports that direction. Refactoring UI frames dashboard work as visual hierarchy and data-label clarity, which makes blocking health and review work outrank onboarding copy (`literature/extracted/refactoring/Refactoring-UI.txt:465`, `literature/extracted/refactoring/Refactoring-UI.txt:635`). Release It! cautions that health checks and monitoring must reflect real user/system behavior, not just a shallow status page (`literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:888`, `literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:3233`). DDIA's derived-data framing applies to Recent Activity: a browser-local feed is not an authoritative job history unless its source and refresh semantics are explicit (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:4727`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:4733`).

## Findings

### F1. The local/hosted recognition mode notice is useful and should stay

The dashboard shows a top WordPress admin notice when the plugin is in local recognition mode. This is desirable because it explains why requests target `http://localhost:8000` and gives a direct settings escape hatch.

Current examples:

- `apps/prototype-wp-alt-context/src/admin/class-admin.php:277` - the admin notice only renders on supported ACX pages.
- `apps/prototype-wp-alt-context/src/admin/class-admin.php:282` - the notice is limited to local recognition source.
- `apps/prototype-wp-alt-context/src/admin/class-admin.php:286` - the notice links to the settings page.
- `apps/prototype-wp-alt-context/src/admin/class-admin.php:290` - the copy names local mode and the hosted-service switch.

**Impact:** This is a high-signal environmental affordance. It prevents debugging confusion when local recognition, hosted recognition, and demo environments diverge.

### F2. Coverage and identity stats are desirable, but should be triage-weighted

The page gives a concise coverage and recognition summary. In the observed session it showed 0% coverage, 16 pending-review clusters, and 10 media items with faces. These are useful operator facts.

Current examples:

- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:103` - renders Library Coverage with total media, missing alt text, coverage, and progress.
- `apps/prototype-wp-alt-context/js/admin/hooks/useMediaStats.ts:12` - fetches total media with a page-size-one query.
- `apps/prototype-wp-alt-context/js/admin/hooks/useMediaStats.ts:18` - fetches missing-alt media with a second page-size-one query.
- `apps/prototype-wp-alt-context/src/api/class-api.php:970` - exposes dashboard identity stats from local person/cluster/member tables.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:131` - renders People, Assigned, Pending Review, and Media with faces.
- `apps/prototype-wp-alt-context/js/admin/pages/dashboard/GuidanceCard.tsx:11` - converts pending clusters into a "faces are waiting for names" next action.

**Impact:** These elements are useful and desirable, but the dashboard should visually prioritize pending review and missing alt text over static totals once actionable work exists.

### F3. Sync Health is the most important dashboard panel and needs more diagnostic depth

The observed session reported 91 failed replay operations. The dashboard correctly surfaces that failure count and links to the dead-letter queue, but it does not show age, last failure, affected entity type, replay owner, or whether failures are growing.

Current examples:

- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:191` - renders Sync Health.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:218` - maps sync health states into summary copy.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:231` - renders pending replay, conflict, and failed replay counters.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:245` - conditionally renders topology backlog counts.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:266` - links failed replay work to `#/workbench?tab=scan&panel=dead-letter`.
- `apps/prototype-wp-alt-context/js/admin/hooks/useSyncStatus.ts:6` - polls sync status every 120 seconds.
- `apps/prototype-wp-alt-context/js/admin/pages/__tests__/DashboardPage.test.tsx:694` - tests failure summary copy and dead-letter link visibility.

**Impact:** Preserve this panel, but make it the top band when failures/conflicts exist. A count of 91 without recency or dominant cause is not enough to decide whether to retry, reset, ignore, or investigate.

**Planning literature:** Release It! distinguishes real health from superficial status checks and emphasizes transparency for action (`literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:888`, `literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt:3272`). Latency adds that failure/replay delays must be understood as a distribution, especially tail behavior, not a single stale count (`literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:796`, `literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt:798`).

### F4. The onboarding orientation card is now superfluous once real work exists

The first large card explains Scan Media -> Cluster Faces -> Assign Labels and persists until dismissed via local storage. In the observed session, it appears above 91 failed replays and 16 pending face reviews.

Current examples:

- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:100` - renders `OrientationCard` before all operational panels.
- `apps/prototype-wp-alt-context/js/admin/pages/dashboard/OrientationCard.tsx:6` - stores visibility in local storage rather than deriving it from product state.
- `apps/prototype-wp-alt-context/js/admin/pages/dashboard/OrientationCard.tsx:20` - renders the large getting-started region.
- `apps/prototype-wp-alt-context/js/admin/pages/dashboard/OrientationCard.tsx:88` - links to the first scan.

**Impact:** This is helpful for a first empty install, but superfluous for an active operator dashboard. It should collapse, move to a help/onboarding surface, or render only when there are no scans, no clusters, no failures, and no pending work.

**Planning literature:** Refactoring UI's hierarchy guidance applies directly: onboarding should not compete visually with blocking operational data once the system has real work (`literature/extracted/refactoring/Refactoring-UI.txt:465`, `literature/extracted/refactoring/Refactoring-UI.txt:467`).

### F5. Retention posture needs work or should be demoted when unavailable

The dashboard includes a Retention posture card. In the observed session it only said retention status is unavailable and provided no action. That makes it feel like a broken panel rather than a useful governance summary.

Current examples:

- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:277` - renders Retention posture.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:279` - unavailable status renders as plain text.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:307` - when available, the card links to Retention Controls.
- `apps/prototype-wp-alt-context/js/admin/hooks/useRetentionStatus.ts:28` - fetches retention status with a standard query.
- `apps/prototype-wp-alt-context/js/admin/pages/__tests__/DashboardPage.test.tsx:293` - tests the available-state summary and link.

**Impact:** Governance is valuable, but unavailable governance without diagnostics or a settings/control link is noise. Either make the unavailable state actionable or demote the card below current remediation work.

### F6. Batch Operations duplicates Workbench navigation and should be narrowed

The Batch Operations card links to Analysis Queue, Review Hub, and Managed Identities. Those destinations are useful, but the panel itself is broad navigation copy rather than a current-state summary. In the observed session it also said no recent batches exist, despite the larger workflow investigating a known batch job.

Current examples:

- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:317` - renders Batch Operations.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:325` - latest batch display depends on `latestRecognitionJobId`.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:345` - always renders three navigation action cards.
- `apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionJobHistory.ts:7` - stores job history under a browser local-storage key.
- `apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionJobHistory.ts:35` - derives job history from component state and local storage, not a durable job index.

**Impact:** The links are desirable, but the panel should become "Active or recent recognition jobs" only when durable job data exists. Generic Workbench navigation can move to a smaller action bar.

### F7. Recent Activity should be deprecated in its current local-storage form

Recent Activity is a prominent panel, but it only knows about jobs remembered by the browser. The observed session showed no recent jobs even though the broader investigation references specific batch job `4f7236f5-55ed-4b55-8eae-51e5b7d256f4`.

Current examples:

- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:361` - renders Recent Activity as a dashboard panel.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:363` - shows the empty message when browser-local history is empty.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:367` - maps local `jobHistory` into activity rows.
- `apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionJobHistory.ts:13` - reads job history from local storage.
- `apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionJobHistory.ts:56` - fetches status only for remembered IDs.
- `apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionJobHistory.ts:63` - detects 404s by matching `'(404)'` inside an error message.

**Impact:** A dashboard activity feed that forgets server-side work misleads operators. Deprecate the current panel or replace it with a durable recent-job source before treating it as authoritative.

**Planning literature:** DDIA's materialized-view framing requires a derived activity feed to declare its source and update behavior (`literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:4727`, `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt:4733`). Modern Software Engineering's empirical framing also argues that operator dashboards should improve feedback loops rather than obscure them with local-only memory (`literature/extracted/refactoring/modern-software-engineering.txt:799`, `literature/extracted/refactoring/modern-software-engineering.txt:805`).

### F8. The dashboard fetches many independent surfaces on first load

The dashboard mounts media stats, job history, identity stats, sync status, and retention status independently. This supports modular panels, but it also means the landing page can show a mixture of loaded, unavailable, and stale panels with no unified page-level health model.

Current examples:

- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:30` - loads media stats.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:31` - loads recognition job history.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:32` - loads sync status.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:34` - loads retention status.
- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx:35` - loads identity stats.
- `docs/assessments/current/wp-alt-context-cross-cutting-assessment.md:113` - previously flags the five-hook dashboard mount as a frontend risk.

**Impact:** The dashboard should keep panel independence, but needs a top-level prioritization model so partial failures do not flatten urgent, actionable state into a general grid.

## Recommendations

### 1. Preserve the dashboard as an operator triage surface

**Traces:** F1, F2, F3  
**Priority:** P0

Keep local/hosted mode, coverage, identity backlog, and sync health. Promote blocking failure/conflict states above onboarding and static summaries.

### 2. Replace the orientation-first layout with state-aware onboarding

**Traces:** F4  
**Priority:** P1

Show the large orientation card only on true first-run/empty installs. Once pending clusters, failed replay, conflicts, or recent jobs exist, collapse onboarding into a help link or compact checklist.

### 3. Make Sync Health diagnostic, not just numeric

**Traces:** F3, F8  
**Priority:** P1

Add enough context for failed replay and conflict work: oldest failure age, latest failure time, dominant operation/entity type, and direct links to filtered workbench views. Keep the existing dead-letter and conflict links.

### 4. Demote or fix unavailable Retention posture

**Traces:** F5  
**Priority:** P2

If retention is unavailable, show why and link to the relevant settings/control surface. If the backend cannot explain the failure, demote the panel below active recognition and sync work.

### 5. Deprecate local-storage Recent Activity as an authoritative feed

**Traces:** F6, F7  
**Priority:** P1

Replace browser-local recent jobs with a durable backend/local job index, or label it explicitly as "This browser's recent jobs" and move it out of the primary dashboard grid.

## Useful, Superfluous, Needs Work, Deprecate

| Classification | Elements | Rationale |
| --- | --- | --- |
| Useful and desirable | Local-mode notice, Library Coverage, Identity Recognition, Sync Health counts, Workbench/Roster remediation links | They answer "what state is the system in?" and "where do I act next?" |
| Superfluous in active installs | Large OrientationCard, generic Batch Operations copy | They are helpful onboarding/navigation, but compete with live failure and review work. |
| Needs more work | Sync Health diagnostics, Retention posture unavailable state, dashboard-level priority ordering | These are conceptually right but under-explain current state or next action. |
| Deprecate or replace | Local-storage Recent Activity as a primary panel, generic three-card Batch Operations hub | They can misrepresent real job history and duplicate Workbench navigation. |

## Code-Verified Critique

### What the assessment gets right

The core dashboard panels are real and tested. Sync Health has coverage for conflict/dead-letter links, queued/stale/failure states, and stale mirror reset behavior in `apps/prototype-wp-alt-context/js/admin/pages/__tests__/DashboardPage.test.tsx:474` and `apps/prototype-wp-alt-context/js/admin/pages/__tests__/DashboardPage.test.tsx:615`.

### Where the assessment overstates the problem

The dashboard is not merely decorative. The current UI already has meaningful remediation links for Workbench, Dead-Letter Queue, Conflict Inbox, Retention Controls when available, and Roster clusters. The problem is prioritization and authority, not that the dashboard should be removed.

### Recommendations the assessment is missing

R-MISS-1: Add a dashboard information hierarchy rule: blocking health first, review queues second, guidance third, governance/utilities last.

R-MISS-2: Add an explicit "current browser only" label if any local-storage-derived activity remains.

## Priority Ordering

| Priority | Change | Impact | Effort | Trace |
| -------- | ------ | ------ | ------ | ----- |
| **P0** | Promote sync failures/conflicts and identity review above onboarding | Operators see blocking work first | Medium | F2, F3, F4 |
| **P1** | Replace local-storage Recent Activity with durable job history or demote it | Avoids misleading job state | Medium | F6, F7 |
| **P1** | Make onboarding state-aware | Reduces noise after real work exists | Low | F4 |
| **P2** | Make Retention unavailable state actionable | Turns a dead panel into a next step | Low/Medium | F5 |

## Deferred or Rejected Directions

- Do not remove the dashboard entirely; it has useful triage value.
- Do not add more generic navigation cards as a substitute for real status.
- Do not treat browser-local job history as an authoritative activity feed.
- Do not make Retention posture block the dashboard unless retention is part of the active operator task.

## Suggested Spec Direction

Create a dashboard UX spec only if this work is scheduled outside E15-13. Keep it separate from the roster curation loop unless the dashboard becomes the entry point for curriculum review queues. The spec should focus on state hierarchy, durable activity sources, sync diagnostics, and onboarding de-emphasis.

## Next Step

- [ ] Write a dashboard UX spec at `docs/specs/alt-context-dashboard-operator-triage-spec.md` if dashboard work is prioritized.
- [ ] Feed Sync Health diagnostics into the E15-13/refactoring follow-on only if replay failure visibility becomes part of curation refresh status.

## References

- `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx`
- `apps/prototype-wp-alt-context/js/admin/pages/dashboard/OrientationCard.tsx`
- `apps/prototype-wp-alt-context/js/admin/pages/dashboard/GuidanceCard.tsx`
- `apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionJobHistory.ts`
- `apps/prototype-wp-alt-context/src/api/class-api.php`
- `literature/extracted/refactoring/Designing-Data-Intensive-Applications-The-Big-Ideas-Behind-Martin-Kleppmann2017.txt`
- `literature/extracted/refactoring/Latency-Reduce-delay-in-software-systems-PekkaEnberg.txt`
- `literature/extracted/refactoring/Refactoring-UI.txt`
- `literature/extracted/refactoring/Release-it--design-and–deploy–production-ready-software--Michael-T-Nygard.txt`
- `literature/extracted/refactoring/modern-software-engineering.txt`
