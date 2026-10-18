LANE v3-stepper — a scope-aware two-stage public stepper.

OWNED FILE (edit only this one):
  apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedPrototypeGuide.tsx

Zero edits outside this file. Do not touch RecordedWalkthrough.tsx, state.ts, publicGuideCopy.ts, or any SCSS. If another file must change, stop and report it as a handoff note.

CONTEXT
This module exports `GUIDE_STEPS`, `GUIDED_SECTION_IDS`, `GUIDED_FACE_SECTION_ID`, `guidedStepLabel`, `focusGuidedSection`, and the `GuidedPrototypeGuide` nav component.

Today `GUIDE_STEPS` is a single scope-blind constant listing four steps: CONTEXT, NAMES, DRAFT, APPLY. The nav renders one `<li>` per entry with `aria-current="step"` on the active one and `aria-controls={GUIDED_SECTION_IDS[step]}`.

The public guide is collapsing to two stages:
  Stage 1 `Choose names`     -> controls `guided-section-understand`
  Stage 2 `Review and apply` -> controls `guided-section-review`

`#guided-section-face` and `#guided-section-apply` stop being public navigation targets. The admin route keeps all four steps and all four section ids unchanged.

Lane v3-copy has landed these keys in `publicGuideCopy.ts`:
  'step.names.public'   -> 'Choose names'
  'step.review.public'  -> 'Review and apply'
  'guide.current.public'-> 'Step {stepNumber} of {stepCount}: {stepTitle}'

TASK

1. Add a `scope: 'public' | 'admin'` prop to `GuidedPrototypeGuideProps`. Export a scope-aware step list rather than mutating the existing constant:
   - Keep `GUIDE_STEPS` exported and unchanged (four steps) so admin callers and existing tests keep working.
   - Add `export const PUBLIC_GUIDE_STEPS: readonly GuidedStep[] = [GUIDED_STEP.CONTEXT, GUIDED_STEP.DRAFT];`
   - Add `export const guideStepsForScope = (scope): readonly GuidedStep[]` returning the public list for 'public' and `GUIDE_STEPS` otherwise.

2. Add a scope-aware label resolver. `guidedStepLabel(step)` today reads the admin STEP_TITLE map and calls `guidedCopy` from '../../guidedPrototype/copy'. Add `guidedStepLabelForScope(step, scope)` which, for 'public', maps CONTEXT -> 'step.names.public' and DRAFT -> 'step.review.public' via `guidedCopy` imported from '../../guidedPrototype/publicGuideCopy', and otherwise delegates to the existing admin path. Keep `guidedStepLabel` exported with unchanged behaviour.

3. Render the nav from `guideStepsForScope(scope)`. The visible position number must be the index within the rendered list, so public stage 2 shows 2, not 3. Exactly one rendered button carries `aria-current="step"`.

4. The current-step line in `.acx-guided-guide__bar` must be derived from the same list. For 'public' use `guidedCopy('guide.current.public', { stepNumber, stepCount, stepTitle })` where stepCount is the rendered list length and stepNumber is the 1-based index within it. For 'admin' keep the existing `guidedCopy('guide.current', ...)` call from the admin catalog exactly as today. There must be no hidden four-step requirement under the two-step public navigation: the visible label, the numbering, and the announced string all come from one source.

5. If the active step is not in the rendered list (for example a public session somehow sits on NAMES or APPLY), resolve it to the nearest preceding rendered stage instead of crashing or rendering zero current steps. NAMES resolves to CONTEXT, APPLY resolves to DRAFT. Implement this as an explicit exported mapping, not as an index arithmetic accident.

6. `focusGuidedSection` and `GUIDED_SECTION_IDS` keep their current entries; the public stepper simply never targets the two dropped ids. Do not delete `GUIDED_FACE_SECTION_ID` — another component still imports it.

7. Selecting a step must change the value and move focus to the controlled section. It must not change readiness or mutate demo state beyond the existing `onSelect` callback. Keep the existing show/hide toggle and its `aria-expanded`.

HOW TO VERIFY
Run: npx vitest run apps/prototype-wp-alt-context/js
All existing tests must stay green because the admin defaults are unchanged. Do not weaken a test. New public-stepper assertions belong to the tests lane; if you add a quick local test, put it in an existing test file you already own, otherwise just report what should be asserted.

CONSTRAINTS
- Centralize the step-label and section maps as `as const` objects. No scattered string comparisons. [sr-007]
- Use assertion helpers for internal invariants, not non-null assertions. [sr-005]
- Primary controls must be reachable from zero state; never gate a stepper button behind a selection. [rg-003]
- Role semantics must match behaviour. [rg-004]
- Commit only the one owned file.
- NON-GOALS: Co-Authored-By or AI attribution trailers; any edit outside the owned file; new dependencies.

COMMIT MESSAGE
guide v3: scope-aware two-stage public stepper
