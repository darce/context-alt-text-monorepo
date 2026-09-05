# Guided prototype: manual test runbook

Use the authenticated AltContext plugin screen for a controlled walkthrough. This build contains one illustrative portrait scenario with confirmed, unidentified, edited and rejected states. It does not run face recognition or live description generation. Apply changes only the in-memory practice copy; refreshing starts a new practice. The public homepage and passwordless guest access are separate work.

Keep the portfolio and resume linked to the [AltContext case study](https://darce.xyz/projects/altcontext/). The branch is suitable for reviewing this guided interaction; installing it does not replace the public demo entrance or restrict the rest of WordPress admin.

## Prepare the installed branch

1. Use a local/test WordPress installation and the `feature/guided-prototype-1` worktree. Installing the main checkout will not include these changes.
2. Build/package from the plugin directory:

   ```sh
   cd /Users/daniel/Development/context-alt-text-monorepo-guided-prototype-1/apps/prototype-wp-alt-context
   npm ci
   npm run release:package
   ```

   Install the ZIP reported by the packaging command through **Plugins → Add New → Upload Plugin** on that test site, then activate AltContext. Use a normal development account with `manage_options`; this branch does not create a restricted guest account. If the test site already loads this worktree, `npm run build` updates its compiled frontend.

3. Sign in yourself before a hiring-manager screen share. Open:

   ```text
   http://localhost:10010/wp-admin/admin.php?page=alt-context-dashboard#/guided-prototype
   ```

   Replace the origin with the test site's address. The WordPress page slug is `alt-context-dashboard`; the React route is `#/guided-prototype`. The AltContext Dashboard also links to the guided practice.

4. Confirm the branded title, the illustrative scenario label, visible generation-unavailable explanation, photograph and credit. If the old interface appears, check the installed ZIP/worktree and hard-refresh cached assets.

## The two-minute walkthrough

| Action                                                            | Expected result                                                                                                                         |
| ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| Choose **Open a saved example**                                   | The guide opens and receives focus. No inference job starts.                                                                            |
| Choose **Confirm identity** in the guide                          | The identity section scrolls into view and receives focus.                                                                              |
| Inspect the source record, then choose **Confirm Keanu Reeves**   | The proposed description uses the supplied name; generic visual description and page context remain visible. Applied text is unchanged. |
| Edit **Description draft** to `Keanu Reeves wears a grey jacket.` | A pending-edit notice appears. Apply is unavailable with a visible explanation.                                                         |
| Choose **Save description edit**                                  | The saved candidate matches the edit. Applied text is still unchanged.                                                                  |
| Choose **Apply to practice copy**                                 | Only the practice value changes to the exact saved text. A decision appears in history.                                                 |
| Choose **Undo practice apply**                                    | The previous practice value returns; focus moves to the stable Apply section.                                                           |
| Choose **End guide**                                              | The guide closes and focus returns to the image/context section; practice decisions remain.                                             |

Suggested narration: “This is a guided WordPress prototype. The example is illustrative, and current generation is unavailable. The core interaction combines visual description, identity evidence and page context. Confirmation can change the draft; editorial review and an explicit Apply remain separate decisions.”

## Recovery and alternative paths

Start each independent path with **Reset practice → Reset practice**.

| Path                    | Actions and expected result                                                                                                                                                                                                     |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Uncertain identity      | Choose **Keep the person unidentified**. The candidate stays generic and review remains available. Merely opening the scenario must not confirm a name.                                                                         |
| Known-name guard        | Before confirming identity, type the sample's full name into a draft and save. The edit remains available for correction with an error; applied text is unchanged. This guards this sample name, not arbitrary identity claims. |
| Unsaved text            | Type a distinct edit. Apply and identity replacement are blocked with explanations. **Discard unsaved edit** restores the saved draft and focuses the editor.                                                                   |
| Saved draft replacement | Save an edit, then change the identity choice. Read the visible replacement consequence before proceeding; inspect the newly selected candidate before applying.                                                                |
| Empty input             | Clear the editor, enter spaces and save. The labelled editor retains the input, shows an associated error and receives focus.                                                                                                   |
| Rejection               | Confirm identity and reject the draft. Apply is disabled with a visible reason; applied text stays unchanged. Edit and save a replacement to recover.                                                                           |
| Multiple undos          | Save/apply revision A, then save/apply revision B. Undo restores A; a second Undo restores the original. Draft and applied value remain distinct.                                                                               |
| Reset cancellation      | Save an edit, then type a different pending edit. Open Reset. **Cancel** and **Escape** each retain both versions and return focus to the Reset button.                                                                         |
| Reset confirmation      | Confirm Reset. Candidate, editor buffer, error, identity, applied text and history return to the seed. Focus moves to image/context.                                                                                            |
| Reload                  | Refresh after edits. The initial scenario returns, consistent with the visible in-memory boundary.                                                                                                                              |
| Photograph unavailable  | In browser DevTools, block the bundled JPEG request and reload. A visible unavailable message and text description remain; the review path still works. Remove the request block afterward.                                     |

## Keyboard, display and assistive technology

- Use Tab, Shift+Tab, Enter and Space throughout. Focus must remain visible and follow document order. Guide steps move focus to their named section; the skip link reaches the current section without changing the React route.
- Open Reset by keyboard. Cancel receives initial focus; Tab stays in the dialog. Escape cancels and restores the Reset button. Confirming Reset moves focus to image/context.
- Check at 320 CSS pixels and at 200% browser zoom. No label, status badge, photo or action should clip. Check both the page and open Reset dialog. Repeat with increased text size and OS reduced motion.
- With VoiceOver/Safari or NVDA/Firefox, inspect headings, regions, image text, editor label/error and disabled-action explanations. Listen for a concise action result without repeated announcements of the entire page. This manual pass is required before claiming screen-reader coverage.
- Check the installed WordPress shell as well as the guided content: admin bar overlap, menus, browser Back, route reload and expired authentication. Signing out should return a fresh admin request to WordPress login. An already-loaded practice page can retain its local state; it is not a session-security monitor.
- Open DevTools Network before the journey. Save, reject, apply, undo and reset should not issue generation or WordPress mutation requests. The enclosing admin app may make normal status reads. The generation-unavailable explanation should remain accurate even if the GPU service is down.

## Repeatable frontend checks

From the plugin directory:

```sh
npx vitest run js/admin/guidedPrototype/state.test.ts js/admin/pages/guided/__tests__/GuidedPrototypePage.test.tsx js/admin/__tests__/App.test.tsx js/admin/styles
npm run typecheck
npm run build
npm run arch
git diff --check
```

The architecture checker has existing failures outside this slice. Compare its output with main; require no new guided-file violations. Do not interpret a component-only browser or axe pass as an installed WordPress, authentication, or full WCAG conformance test.

For the repository's installed-WordPress Playwright checks, use `npm run e2e:auth`, then `npm run e2e:localwp` and `npm run a11y:localwp`. Follow the existing auth playbook and ignored environment configuration. Those suites cover their configured routes; the guided journey above still needs its own installed-site pass.

## Recording backup

Capture the two-minute journey after the installed-site checks pass. Include the prototype status, photo/source record, name entering the description, a saved edit, explicit Apply and Undo. Stop on the case-study link. Exclude login, credentials and unrelated admin settings. Keep this recording available during the screen share; this branch does not create or publish a recording.

## ASCII interaction contract and research

The machine-readable inventory is [guided-prototype.uxmap.json](ux-maps/guided-prototype.uxmap.json); [its rendered map](ux-maps/guided-prototype.md) contains screen/state/action inventory and flows. These are sections and state variants of one route, not separate page navigations.

```text
+-----------------------------------------------------------+
| ALTCONTEXT - guided WordPress prototype                    |
| Saved example available. Live generation unavailable.      |
| [Open a saved example]    [Read the case study]             |
| Practice changes stay in memory.                          |
+-----------------------------------------------------------+
| GUIDE: Context > Identity > Review > Apply                 |
| Clicking a step moves focus to that section. [End guide]   |
+-----------------------------------------------------------+
| [Actual photograph / described unavailable state]          |
| Credit + scenario origin + supplied identity record        |
| Visual facts        Page context        Identity evidence |
| [Confirm sample name] [Keep person unidentified]           |
+-----------------------------------------------------------+
| GENERIC BASELINE       | PROPOSED DRAFT                    |
| Portrait of a person  | Keanu Reeves wears a grey jacket  |
| Description draft [editable text.......................]  |
| Pending edits: save/discard before identity change/apply. |
| [Save description edit] [Discard...] [Reject draft]        |
+-----------------------------------------------------------+
| Current practice value: <previous applied description>    |
| [Apply to practice copy] [Undo practice apply]             |
| Visible reason beside Apply when pending or rejected.     |
| History: ordered identity / review / apply / undo events   |
+-----------------------------------------------------------+

Reset overlay:
+-----------------------------------------------------------+
| Reset this practice?                                     |
| Clears saved decisions and pending edits in this practice.|
| [Cancel] (initial focus)       [Reset practice]             |
+-----------------------------------------------------------+
  Cancel/Escape -> preserve work; focus Reset button
  Confirm       -> restore seed; focus image/context
```

The review used the local `~/Development/heuristics-canon-research` corpus: A11Y keyboard/focus/reflow/error rules; NAV-09 and INT-01/07/09 for named steps, action cues, preview and reversible commands; HAI-02 for saving corrections into scenario state; REF-09 for one owner of transition logic; DATA-14 for a single authoritative state; RES-03 for graceful dependency failure. The reasoning cards `correction-at-source`, `reversible-commitments`, `feedback-bounded-waiting` and `perceived-enforced-boundaries` shaped error placement, undo/reset, local feedback and truthful scope. The distilled DDIA, Latency and Release It! material supports those design checks; it does not establish production reliability from this small scenario.
