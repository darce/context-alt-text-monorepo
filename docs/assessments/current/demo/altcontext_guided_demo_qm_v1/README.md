# AltContext guided-demo implementation package

**Document:** ACX-QM-GUIDED-DEMO-01  
**Date:** 7 September 2026 (America/Toronto)  
**Status:** Proposal. No website changes or browser interactions were performed.

## Start here

`implementation-brief.json` is the canonical implementation specification. It contains 15 findings, 104 replacement copy strings, a proposed state contract, eight sequenced work items, and 26 acceptance tests. `copy.en.json` is an identical export of the copy catalog, not another authoring source. Regenerate it when the canonical catalog changes.

Give the junior agent this instruction:

> Read implementation-brief.json. Start at W00 and record the actual source paths, symbols and current commit. Implement the scoped changes in dependency order. Keep the recorded walkthrough independent of live generation. Do not invent fixture output, backend capabilities, source URLs or test results. Return the evidence required by handoff_contract. Do not push or merge without authorization.

The package does **not** claim that JSON instructions are executable application code. The state expressions are language-neutral specifications. The acceptance tests are Given/When/Then requirements to implement in the existing test framework; all start as `not_run`.

## What is wrong with the current flow

The supplied page already has valuable ingredients: a real example, disclosed recorded recognition, visible reference photographs, an unnamed option, an editable draft, explicit application, Undo, and local history. Preserve them.

The main problem is that three different states are narrated as one journey. The recorded face suggestions drive sample drafts. The visitor edits and applies to a browser-local copy. The optional live generator uses a server roster that does not follow those choices and cannot change the draft being applied. The current live prerequisite implies a connection its own copy says does not exist. This is a product-boundary issue before it is a wording issue. See F01 and F13, with HAI-05 and INT-03.

A second problem is the ambiguous saved-versus-visible draft. The textarea, Save my edit and Apply create an unclear contract about which text wins. The snapshot does not reveal the handlers, so this is a risk to investigate rather than a proven stale-save bug. W01 replaces the ambiguity with one editable draft, a versioned preview and local applied text.

The page also tells the success story before the reviewer makes a choice: matched/done/strong precedes two undecided face controls. HAI-15 makes the limit important: agreement with an already revealed model answer is not independent verification. For this demo, use an explicitly assisted editorial review. Do not bolt an identity test onto a hiring walkthrough or claim the flow now satisfies a blinded-verification requirement. X01 records this limited exception.

## The proposed visitor experience

### Entry

**AltContext guided demo**

# Review an AI-assisted alt text draft

You are editing a photo in a festival gallery. Review two saved name suggestions, edit the alt text, then apply it to a demo copy. You can leave either person unnamed.

This walkthrough uses recorded face suggestions and sample drafts. Your choices change only the demo copy in this tab and reset when you reload.

An optional live test at the end runs separately on the server.

**Start the walkthrough**

### 1. Understand the page

Show the photo, the supplied festival-gallery context and the current alt text once. Keep credits and saved-run provenance behind a disclosure. Do not remove the credits or convert them into invented source URLs.

Names can be useful in this gallery when the editor has enough evidence to include them. Leaving someone unnamed is also a valid choice.

### 2. Choose which names to use

Put each face's controls inside its evidence article. Use “Saved suggestion: [name]”, then neutral radio choices: “Use [name]” and “Leave this person unnamed”. Neither starts selected. Provide a larger comparison of the assets actually available. If only three of five references are included, say that; do not manufacture the other two.

“This is an assisted review of saved suggestions, not an independent identity check.”

### 3. Edit the alt text

Use one textarea and no intermediate Save my edit. Editing changes the local draft; it does not apply it. The origin label distinguishes the recorded sample from the visitor's edit. The visitor can preview the change or keep the existing alt text.

The four name combinations must resolve to actual existing samples. Only the unnamed sample was supplied in this review. A missing combination gets an honest missing-sample state, not a fabricated model output. A separately labelled human-authored sample would be a new content decision, not a recovery trick hidden in the code.

When a changed name choice would replace manual text, ask before replacing it and retain that text in local Draft history. An old draft can be restored only under matching choices; otherwise it can be copied and reviewed as a fresh edit. Never silently restore old name decisions.

### 4. Apply and undo

Show **Current alt text** and **Will be applied**. Apply copies exactly the displayed, current, explicitly previewed string into the local demo-image alternative. Keep this preview image separate from the evidence image so inspecting the original photograph does not become inaccessible when demonstrating the weak starting alternative.

“Applied to the demo copy in this tab. WordPress media has not been updated.”

**Undo last application** restores the previous local alternative. Repeated applications must have corresponding undo records. Keeping the original text is a completed editorial decision, not a failed demo.

### Optional live test

Place this after the outcome, closed by default but inspectable at any time. Remove the artificial prerequisite to decide both faces. Opening the panel never starts a server request.

**Optional: test live description generation**

Generate a separate description of this photo on the server. It will not replace your draft or change the demo copy.

The server uses its own saved people. Your name choices in the walkthrough do not change this live test.

**Generate a separate live description**

Enable the action only after the existing request contract is verified. State the destination and data boundary using the actual adapter, without assuming whether image bytes, an attachment reference, context or logs are transmitted/stored. Do not infer that a browser-local editing promise means there is no server request.

Use “Stop waiting” unless real server cancellation is supported and acknowledged. A browser abort does not by itself prove a server job stopped. Requests need a timeout and stale-response protection. A late result must not replace a reset or newer workspace.

## Why this is stronger for Quartermaster

The useful evidence is a small product decision carried through to a working consequence: a name can be omitted, the wording can be revised, and an application can be reversed. That makes uncertainty and agency visible. A faster GPU or a celebrity match does not establish those capabilities.

The selected transfer to Quartermaster is a design pattern, not domain equivalence: machine-derived information must remain reviewable before a person acts. This demo does not prove property-data expertise, homeowner research, production adoption or model accuracy.

Use one closed **Design notes** disclosure after the outcome. The three notes in the copy catalog explain the recorded/live split, optional naming and explicit application. Preserve the existing AltContext case-study link. No new Practice section or portfolio-navigation change is required.

## Canon application boundaries

The main UI sources are NAV, INT and HAI in `lexicons/interaction-ux.md`. Accessibility and writing rows support the implementation and edit pass. Each finding lists the exact rule IDs used and their source anchors.

Some rule applications are deliberately limited. HAI-17 is used as a reference-coverage lens: the current page already shows multiple reference images, so it is not the literal single-reference case. HAI-02 applies to local demo authority and does not justify writing a visitor's simulated choices to the real roster. NAV-11 applies to the hash-router risk, not global navigation. W3C APG makes aria-controls optional; its absence is not by itself a conformance failure. HAI-08's bare-percentage trigger is not present here, so this review does not invent a violation of that rule merely because “strong” is weak copy.

A `strong` label without inspectable meaning is still poor evidence for the current narrative. Replacing it with **Saved suggestion** is a scope/claims change, not a claim that confidence displays are universally forbidden.

The writing lexicon calls its source basis provisional. It is used here for plain terms and concrete, nonrepetitive sentences, not as a scientific AI-writing detector.

## Verification and implementation order

W00 must precede changes. It finds the actual component, fixtures, state handlers and live adapter. No source paths have been invented from CSS selectors. Most evidence anchors are existing IDs or classes in the supplied HTML. New test hooks are explicitly labelled new.

Then implement local state and draft safety, the four-step reflow, the isolated live panel, and accessibility checks. Add the outcome/design notes and integrate. Default to sequential work; split lanes only after ownership is genuinely disjoint. The codebase, not this artifact, determines its branch and test commands.

Automated live tests should use a stub. A real billable smoke test requires explicit approval. Do not change authentication, backend permissions or managed browser restrictions to make a test pass.

The included validator checks the brief's structure, ID references, task dependency graph, copy export, input hash and source selectors. It **does not** run any of the 26 product acceptance tests.

```sh
python -m pip install jsonschema beautifulsoup4
python validate_brief.py
```

The schema is `implementation-brief.schema.json`. There are no remote schema dependencies.

## What the attachment establishes

The source is one supplied `<main>` snapshot, preserved byte-for-byte as `source-snapshot.html`. It contains 883 whitespace-delimited words under the documented whitespace count, including screen-reader-only text, 35 paragraphs and 12 buttons. These counts describe the source, not reading time or observed usability.

The document does not supply CSS, screenshots, event handlers, network traces or later states. For example, both entrance and workspace occur in the DOM, but their computed initial visibility is unknown. Apply is enabled in the snapshot, but its click behavior is unknown. The hash-only skip link is a routing risk until the handler is inspected. Existing ARIA attributes are promising implementation evidence, not proof of screen-reader usability.

Images, identities, event details and licensing records were not independently verified. The supplied photo/context wording remains unchanged except where repetitive. The saved-run date is inherited and must match the actual fixture before release.

## Files

- `implementation-brief.json`: canonical, machine-readable plan.
- `implementation-brief.schema.json`: structural schema.
- `copy.en.json`: export of the proposed copy catalog.
- `evidence-anchors.json`: export of original DOM evidence, with counts and selectors.
- `source-snapshot.html`: unchanged supplied HTML; reference input only.
- `validate_brief.py`: offline handoff validator.
- `README.md`: this explanatory view of the proposal.

## Sources

1. User-supplied `Pasted text.txt`, SHA-256 `5aad68d0d7b3b3a7b59c27f41dc112a3f04469004928f41ef82fe8d84fc90953`.
2. Quartermaster role pasted earlier in this conversation; availability was not rechecked for this task.
3. [Interaction & UX lexicon](https://github.com/darce/heuristics-canon/blob/main/lexicons/interaction-ux.md), Git blob `180740093900725559b00833adc1a1e1a95547af`.
4. [Accessibility lexicon](https://github.com/darce/heuristics-canon/blob/main/lexicons/accessibility.md), Git blob `1c3e80a608da2ee44757e6383d60aea416832659`.
5. [Writing lexicon](https://github.com/darce/heuristics-canon/blob/main/lexicons/writing.md), Git blob `30ea4356833641ce9f3de88fbac812a6063e11f6`.
6. [W3C WAI alt decision tree](https://www.w3.org/WAI/tutorials/images/decision-tree/).
7. [W3C APG disclosure pattern](https://www.w3.org/WAI/ARIA/apg/patterns/disclosure/).
8. [W3C Understanding Status Messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html).

The canon source IDs record the retrieved file contents; `main` links can change. Retrieve the specified Git blobs when exact reproducibility is required.
