/**
 * Guided demo interface copy. Generated from
 * docs/assessments/current/demo/altcontext_guided_demo_qm_v1/copy.en.json
 * by scripts/generate_guided_copy.py; edit the catalog, not this file.
 */

export const GUIDED_COPY = {
  "page.title": "Review an AI-assisted alt text draft",
  "page.eyebrow": "AltContext guided demo",
  "page.intro": "You are editing a photo in a festival gallery. Review two saved name suggestions, edit the alt text, then apply it to a demo copy. You can leave either person unnamed.",
  "page.scope": "This walkthrough uses recorded face suggestions and GPU-generated drafts. Your choices change only the demo copy in this tab and reset when you reload.",
  "page.live_scope": "An optional live test at the end runs separately on the server.",
  "page.start": "Start the walkthrough",
  "page.reset": "Reset demo",
  "page.case_study": "Read the AltContext case study",
  "guide.label": "Demo steps",
  "guide.current": "Step {stepNumber} of 4: {stepTitle}",
  "guide.show": "Show all steps",
  "guide.hide": "Hide steps",
  "step.context": "Understand the page",
  "step.names": "Choose which names to use",
  "step.draft": "Edit the alt text",
  "step.apply": "Apply and undo",
  "context.intro": "This photo appears in a festival gallery. Review the existing alt text alongside the photo and its page context.",
  "context.page_label": "Example page",
  "context.current_label": "Current alt text in the demo copy",
  "context.purpose": "Names can be useful in this gallery when the editor has enough evidence to include them. Leaving someone unnamed is also a valid choice.",
  "context.next": "Review name suggestions",
  "provenance.disclosure": "Saved example and image credits",
  "provenance.recorded": "Recorded face-match run: 10 September 2026. Recognition is not running during this walkthrough.",
  "names.intro": "For each face, compare the saved suggestion with the reference photos. Choose whether to include that name in the sample draft.",
  "names.assisted": "This is an assisted review of saved suggestions, not an independent identity check.",
  "names.suggestion": "Saved suggestion: {name}",
  "names.legend": "Name choice for the {position} face",
  "names.include": "Use {name}",
  "names.omit": "Leave this person unnamed",
  "names.pending": "Choose an option for this face.",
  "names.included": "The sample draft will use {name}.",
  "names.omitted": "The sample draft will describe this person without a name.",
  "names.coverage_all": "All {total} reference photos are shown.",
  "names.coverage_partial": "{shown} of {total} reference photos are included in this demo.",
  "names.evidence_open": "Compare the {position} face and reference photos",
  "names.evidence_close": "Close comparison",
  "names.enlarge": "Enlarge comparison",
  "names.enlarge_title": "Enlarged comparison",
  "names.crop_alt": "Detected {position} face",
  "names.next": "Review the draft",
  "names.next_blocked": "Choose an option for both faces. Leaving a person unnamed counts as a choice.",
  "names.change_title": "Change the name choice?",
  "names.change_body": "This loads the sample draft for your new choices. Your current edit will remain in Draft history. The demo image will not change until you apply again.",
  "names.change_confirm": "Change choice and load draft",
  "names.change_cancel": "Keep editing",
  "names.change_status": "Name choice changed. Review the updated draft before applying it.",
  "draft.intro": "Check the wording against the photo and the page context. Edit anything you would not publish.",
  "draft.label": "Alt text draft",
  "draft.origin_saved": "Recorded GPU draft: Qwen3-VL-30B-A3B-Instruct (Q4_K_M), generated 9 September 2026 with page context and your selected names.",
  "draft.origin_edited": "Your edit, based on the recorded example.",
  "draft.effect": "Edits stay in this tab. Nothing is applied until you choose Apply to demo copy.",
  "draft.blocked": "Choose a name option for both faces to load the sample draft.",
  "draft.fixture_missing": "The sample draft for these choices is unavailable. Your choices and the current demo copy have not changed.",
  "draft.fixture_retry": "Retry loading the sample",
  "draft.empty_error": "Enter alt text before reviewing the change.",
  "draft.next": "Preview the change",
  "draft.keep": "Keep current alt text",
  "draft.history": "Draft history",
  "draft.history_note": "Earlier edits are kept in this tab until you reset or reload.",
  "draft.copy_revision": "Copy earlier draft",
  "draft.restore_revision": "Restore earlier draft",
  "draft.restore_guard": "This earlier draft uses different name choices. Change those choices first, or copy the text and review it as a new edit.",
  "apply.intro": "Compare the current alt text with your draft. Applying changes only the demo image below.",
  "apply.before": "Current alt text",
  "apply.after": "Will be applied",
  "apply.preview_title": "Demo image preview",
  "apply.submit": "Apply to demo copy",
  "apply.undo": "Undo last application",
  "apply.undo_unavailable": "There is no application to undo yet.",
  "apply.stale": "The draft changed. Preview it again before applying.",
  "apply.no_change": "The demo copy already uses this text.",
  "apply.success": "Applied to the demo copy in this tab. WordPress media has not been updated.",
  "apply.undone": "Restored the previous alt text in the demo copy.",
  "outcome.applied": "Your demo copy is updated",
  "outcome.kept": "The demo copy is unchanged",
  "outcome.kept_body": "You kept the current alt text. You can return to the draft or inspect the design notes below.",
  "outcome.return": "Return to the draft",
  "history.title": "Your demo actions",
  "history.empty": "Your choices and changes will appear here.",
  "history.scope": "This history is local to this tab. It is not a server audit log.",
  "live.title": "Optional: test live description generation",
  "live.intro": "Generate a separate description of this photo on the server. It will not replace your draft or change the demo copy.",
  "live.names": "The server uses its own saved people. Your name choices in the walkthrough do not change this live test.",
  "live.request_unverified": "Live generation is unavailable in this build. The recorded walkthrough still works.",
  "live.request_confirmed": "This sends a live description request for the example photo to the configured AltContext service. See Request details before starting.",
  "live.details": "Request details",
  "live.submit": "Generate a separate live description",
  "live.pending": "Waiting for the live description. Your demo copy is unchanged.",
  "live.complete": "Live description received. Review it separately from the demo draft.",
  "live.output_label": "Live server result (read-only)",
  "live.failed": "The live description could not be completed. Your demo copy is unchanged.",
  "live.timed_out": "The wait limit was reached. The server job may still be running. {keepWaiting} continues this run; {retry} starts a new one. Your demo copy is unchanged.",
  "live.keep_waiting": "Keep waiting",
  "live.stop_waiting": "Stop waiting",
  "live.stopped": "Stopped waiting for this request. This does not confirm that the server job stopped.",
  "live.retry": "Try live generation again",
  "live.no_result": "The server returned no description. Your demo copy is unchanged.",
  "live.elapsed_of_up_to": "{elapsed} of up to {deadline}",
  "live.budget_local": "No server budget disclosed, so this is how long this page is willing to wait.",
  "live.budget_disclosed": "The service disclosed {generation} of generation time. This page will wait up to {deadline}, which may add GPU warm-up and a short local slack.",
  "live.status_label": "Live run status",
  "reset.title": "Reset this demo?",
  "reset.body": "This clears name choices, drafts and local history, and restores the original demo alt text.",
  "reset.active_live_note": "A live server job may continue after this reset.",
  "reset.confirm": "Reset demo",
  "reset.cancel": "Keep my work",
  "reset.status": "Demo reset. WordPress media was not changed.",
  "notes.title": "Design notes",
  "notes.recorded": "Recorded recognition keeps the core walkthrough repeatable. Live generation is separate so a slow or unavailable service does not prevent review.",
  "notes.names": "A suggested identity and permission to use a name are different decisions. Either person can remain unnamed.",
  "notes.apply": "Drafting and applying are separate actions. The preview shows exactly what will change, and Undo restores the previous demo alt text.",
  "notes.scope": "This prototype demonstrates the interaction. It does not establish recognition accuracy, user trust, or full accessibility conformance.",
} as const;

export type GuidedCopyKey = keyof typeof GUIDED_COPY;

const PLACEHOLDER = /\{(\w+)\}/g;

/**
 * Resolve `{placeholder}` tokens from verified state. Throws on an unresolved
 * token so an unrendered brace can never reach the visitor.
 */
export const interpolateGuidedCopy = (
  key: string,
  template: string,
  values: Record<string, string | number>,
): string =>
  template.replace(PLACEHOLDER, (_match, name: string) => {
    const value = values[name];
    if (value === undefined) {
      throw new Error(`Unresolved guided copy placeholder {${name}} in ${key}`);
    }
    return String(value);
  });

export const guidedCopy = (key: GuidedCopyKey, values: Record<string, string | number> = {}): string =>
  interpolateGuidedCopy(key, GUIDED_COPY[key], values);
