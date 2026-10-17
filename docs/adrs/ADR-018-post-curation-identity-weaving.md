# ADR-018: Post-curation identity weaving — deterministic re-weave over a frozen, grounded base

- **Status:** Proposed (needs operator acceptance before an IDWEAVE implementation plan is drafted)
- **Date:** 2026-10-16
- **Context task:** IDWEAVE-1
- **Extends:** [ADR-009](ADR-009-recognition-curation-refresh-and-person-review-projection.md) (post-curation derived refresh) to image descriptions. Builds on [ADR-017](ADR-017-description-authority-wordpress-curation-service-generation.md) (Proposed) and the E19-4a identity-merge layer.
- **Heuristics (Canon v0.26.2):** ATTRIB-02, ATTRIB-05, BOUND-01, BOUND-05, CAL-02, FM-01, FM-04, SERVE-04, COST-07, AIPX-01, AIPX-03, AIPX-07, ARCH-13, REF-12, PROD-03, SEC-01, PROV-01, PROV-12, DATA-13, DATA-14, DATA-18, HAI-04, HAI-05, HAI-06, HAI-11, HAI-12, HAI-13, HAI-18, INT-06, INT-07, INT-09, INT-11, INT-19, INT-20, NAV-05, EVAL-01, EVAL-22, WRIT-06. Cards: CARD-02, CARD-03, CARD-12, CARD-18, CARD-19. Principles 3, 9, 10, 11, 12, 13.

## Status

Proposed.

## Date

2026-10-16

## Context

Here is the workflow:

1. An operator uploads images and selects all.
2. They send the images to the description service.
3. Because this is the first run, the people roster is empty. Every person comes back as a generic phrase ("a man", "a woman").
4. The operator then curates identities. Some people are named. Others, such as strangers in a public space, are deliberately never named.

This ADR decides how the curated names reach descriptions that were already generated on the GPU. The options considered were:

- (A) insert names deterministically in the frontend;
- (B) re-run the GPU VLM with the names;
- (C) rewrite the text with a smaller CPU LLM;
- (D) something else.

Most of the machinery already exists:

- The E19-4a merge layer: containment matching, realizers and a consent gate.
- GPUFLOW-3 N0. When a describe request hits the cache, it re-weaves the cached base with the current confirmed faces and makes no VLM call (`visual_facts_service.py:686-717`).
- A naming-status vocabulary (`policy.py:43-52`, `describeApi.ts:17-32`).

What is missing is a path that starts *after curation*, works without the image bytes, and never pays for the GPU again. The current code also does three things that conflict with that path:

- On the single-image path it sends names into the prompt.
- It counts strangers as absent.
- It has two consent checks, and only the service check is authoritative.

### Constraints from prior decisions

- **ADR-017 (Proposed).**
  - The generation log stores adapter output from *before* weaving.
  - WordPress is the only writer of applied alt text, human edits and provenance.
  - Regenerate bypasses the cache (rule 9).
- **ADR-009 and ADR-003.**
  - Post-curation work is derived asynchronous work.
  - It starts from a durable outbox event and reports status per event.
  - WordPress owns the person label.
  - Replay uses `expected_base_version`. Stale local intent is a conflict, not a silent apply (ADR-003 rule 6).
- **Prior art.**
  - [3473] VLM-6: a name must stay bound to the face box it came from. A left/right identity swap was invisible to every metric.
  - [12462]: the only VLM-side naming numbers on record are from prompt-injected naming. Bakeoff v3 measured 0.890 insertion and 0.684 name precision, with 204 of 640 images getting a wrong name (0.319). The report itself says those figures were never re-scored. They show the direction of the risk, not a baseline.
  - GPUFLOW-3 notes: "A wrong name is worse than no name."

## Current State Inventory

| Concern | Today | Evidence |
| --- | --- | --- |
| Frozen base | One cache row per image and context hash. It holds the caption (`visual_facts`), `alt_text_draft` and `phrase_boxes`. | `db/models/scene.py:62-100` |
| Names as generation input | **Yes on the single-image path.** The whole `ContextPack`, including `identity`, becomes adapter context. Every key is rendered into the prompt as "editorial metadata". The names change `compute_context_hash`, so the request misses the cache and the GPU runs again. Bulk requests carry no identity. | `routers/describe.py:980-982`, `gpu_remote_adapter.py:263-277`, `visual_facts_service.py:258-261`, `class-describe-controller.php:434-441`. EXECUTED: a pack carrying "Daniel" put the name into the prompt and changed the hash. |
| Second name source | WordPress `build_identity_context` sends `is_user_confirmed && person_name` rows. Skip (dismiss) sets `curation_state=dismissed` without clearing `person_id`, and this read does not filter on `curation_state`. That is a possible named-while-dismissed path. The service join does filter `dismissed_at`. | `class-describe-media-service.php:1154-1208`, `class-cluster-curation-writer.php:85-88`, `identity_merge/join.py:25-93` |
| Re-weave without bytes | None. Box normalization reads the image dimensions from the bytes. | `naming_preview_service.py:105`, `join.py` |
| Trigger after curation | None for descriptions. Person operations get an ACK with no write. `cluster_person_unbound` and every person operation are excluded from follow-up. A rename reaches the mirror only as `cluster_label_updated`. | `roster/application/curation_sync_service.py:70-85, 231-242, 302-326`, `class-api.php:1267` |
| Strangers in the counts | The ungrounded n-count and the 1:1 same-region guard see only confirmed and eligible faces. With one person named and two unconfirmed, n is 1, so lone-noun substitution can fire on the wrong person. | `merge.py:267-279, 281-289`, `fusion/reconcile.py:220-247` |
| Ungrounded fallback text | `Pictured from left: X.` This is an order claim and a completeness claim. | `realizer.py:272-291` |
| Coreference | Later mentions of a named person become singular "they", even when other people are in the image. | `realizer.py:130-140, 202-206` |
| Consent | There are two checks. The WordPress option is a tenant-bound cache of the service agreement. It is cleared before the service call and set only after the service confirms. It gates only the single-image identity context. The service gate (`agreement_enabled`, a per-roster suppress list, detection confidence ≥ 0.8) is skipped when `policy is None`. | `class-settings-controller.php:359-377, 468-505, 593-621`, `class-describe-media-service.php:1154-1158`, `policy.py:19, 100-113`, `merge.py:282` |
| Grounding default | On in code. The GPUFLOW-3 plan says off. The deployed value has not been verified. | `gpu_remote_adapter.py:463-467` |
| Named text held by the service | `DescribeRunItem.alt_text_draft` holds the woven draft. | `db/models/scene.py:337-357` |
| WordPress apply | Existing alt is never clobbered; overwriting needs an opt-in. Apply never reads the human-edit flag. | `class-describe-controller.php:820-826, 893-898`, `class-description-history-service.php:35` |
| Eval | Metrics exist: wrong-name hits, insertion rate, name precision and position accuracy. Floors: wrong-name 0.0, position accuracy 0.5 (a chance floor). | `caption_metrics.py:107, 285, 327`, `face_metrics.py:1125`, `report.py:293, 316` |

### Downstream surfaces that must migrate together

- The adapter context and the cache-key hash.
- The `ContextPack.identity` consumers: the prompt and Stage-2 reconcile.
- WordPress `build_identity_context`.
- Run-item storage.
- The curation ACK path.
- The WordPress apply path and `_acx_description_provenance`.
- The review UI.
- The eval fixtures.

## Decision

Weave names into descriptions **deterministically, on the service CPU, over the stored pre-weave base**:

- The base is the caption plus phrase boxes, captured at first generation.
- A re-weave is triggered by each naming-relevant curation event.
- The result reaches WordPress as a proposal.
- The weave makes no frontend insertion, no GPU re-run and no LLM rewrite.

The answer to "where does the name go?" is geometry: a face box inside a phrase box. It is fixed once, at generation time, before any names exist.

### Stage contracts (CARD-19)

| Stage | Runs | Contract | Judged by |
| --- | --- | --- | --- |
| Caption | GPU VLM, first describe or Regenerate | Describes only what is visible. People appear as generic phrases. Never sees names or free-text metadata. | Existing caption eval |
| Ground | GPU, same pass | Links phrase spans to boxes for generic person phrases (`_is_generic_subject_label`). Runs whatever the roster state. | Position accuracy |
| Weave | Service CPU, pure function | Forbids new facts. The only inventory is the eligible roster names plus matched boxes. Unnamed faces keep the base text byte-for-byte. | Wrong-binding ledger, then coverage |
| Apply | WordPress | The output is a proposal. WordPress is the only writer. | Accept, edit and reject events |

### Chosen design rules

1. **Names are never generation inputs (FM-01, SEC-01).**
   - Delete `identity` from the generation context and from the cache key.
   - Free-text attachment metadata is not a generation input either: title, caption, description, alt text and filename. Only typed fields, such as image dimensions, may be sent.
   - The caption prompt asks for generic people only.
   - A base that contains a roster name, or a named-person phrase, fails closed and is not stored.
   - The person-naming policy also stays out of the prompt.
   - Names reach text only through the weave. Their single source is the service mirror (`load_confirmed_faces`).
   - Stage-2 reconcile moves to that same face set.
   - WordPress `build_identity_context` is deleted (greenfield). That removes the second name source and the dismissed-cluster read with it.
2. **Ground once, at first generation (CARD-25 shape: frozen base, additive delta).**
   - Every first pass that yields a generic person phrase stores `phrase_boxes` and the image width × height with the base, whether or not the roster is empty.
   - *Capturing* boxes is unconditional. *Using* them for naming two or more people waits for the position gate (rule 13).
   - Before anything else, the plan reads the deployed grounding flag value.
   - Greenfield: there is no backfill. Rows without boxes use rule 6 or Regenerate.
3. **One weave function.** `weave(base, faces, policy) -> (text, provenance)`.
   - It is pure and deterministic and runs on CPU.
   - `policy` is required (ARCH-13). The geometry-only survivor check in reconcile uses a containment helper that cannot emit text.
   - The describe response (both miss and hit), the bulk worker, run-item reads and the re-weave endpoint all call this one function.
   - The same inputs always give byte-identical output (PROV-01).
4. **Geometry assigns names; text never does (CAL-02, CARD-03).**
   - Matching is `containment_match` over **every detected face** in the image. It is 1:1, takes the smallest box and requires a face-to-phrase area ratio ≤ 0.5 (`merge.py:25, 165`).
   - The weave abstains for a face on any tie or many-to-one match.
   - It also abstains when a phrase box contains two or more detected faces, whether those faces are confirmed or not.
   - Lone-noun substitution (`N1SubstitutionRealizer`) needs exactly one *detected* person, exactly one generic person phrase, and a unique face-to-phrase box binding. Without the binding it uses presence only (rule 6).
5. **Unnamed is the default, not a label (ATTRIB-02, BOUND-01).**
   - The system never classifies anyone as a stranger, bystander or unknown person.
   - Only eligible named faces are woven. Every other face keeps the base phrase unchanged.
   - Curator controls:
     - leave a group unbound, or choose Leave unnamed. Leave unnamed is a durable dismiss, and its Undo is undismiss;
     - the existing per-roster suppress for a known person who should never be named (`policy.py:100-113`);
     - **one new curation state:** a per-image *withhold* ("Don't name them in this photo"). It is WordPress-authoritative and mirrored to the service, and the weave treats a withheld face as unnamed. It is what a *Don't name here* choice records (rule 10).
6. **Ungrounded fallbacks state no order and no completeness (BOUND-05, BOUND-01).**
   - An eligible face with no unique box can still be named, but only as presence.
   - Use `Pictured: X.` when X is the only detected person. Otherwise use `Among those pictured: X.`
   - Never `Pictured from left`.
   - Placement by order is not used in this decision. Two or more people are named by presence only. Box placement for two or more people waits for the position gate (rule 13).
   - Pronoun coreference is used only when exactly one person is detected. Otherwise the name is repeated (WRIT-06).
7. **Each naming-relevant curation event triggers one derived re-weave (ADR-009, DATA-13, DATA-14, CARD-02).**
   - Sequence:
     1. WordPress commits the operation and its outbox row.
     2. The service applies the operation to its mirror and ACKs with `weave_revision`.
     3. In the same local transaction as the ACK, WordPress records a durable naming-refresh intent for the source event.
     4. WordPress enqueues a coalesced Action Scheduler job for the affected media. A recovery sweep re-enqueues any intent that has no job.
   - Each event keeps its own status. Coalesced events record their outcome against the event that caused them.
   - A local commit records the newest naming intent for the media. Proposals built on an older intent are invalid, including pending removals.
   - WordPress derives the affected media set and its count from its own projection. The service is the authority for `weave_revision`.
   - These are naming-relevant:
     - bind, unbind and label update (which carries renames);
     - dismiss and undismiss;
     - merge, split and member moves;
     - withhold and suppress changes;
     - consent changes.
   - Person operations change nothing in the mirror. The plan must prove that `person_deleted` reaches the mirror as an unbind or a label clear (CARD-02).
   - Idempotency key: `(tenant, media_id, base generation_id, weave_revision)`.
   - Each request carries `min_weave_revision`. The service defers if its mirror is older.
   - `weave_revision` replaces `backend_version` for naming. Today `backend_version` is the newest cluster `updated_at`, so consent and suppression changes do not move it. `weave_revision` advances on membership, label, dismiss, withhold, suppression, consent and relevant detection changes. The service reads it in the same snapshot as the faces and the policy.
   - WordPress keeps a result only if its `weave_revision` is at least the newest one applied to that media. Older results are dropped. Apply repeats the check (rule 9).
   - Retries are bounded, with no-progress detection (rg-007). When retries run out, the item shows "couldn't get names" with a per-item Retry (INT-20).
8. **Compute on read; the service stores no woven text (ADR-017 rule 5, DATA-14, PROV-01).**
   - `POST /describe/reweave {items: [{media_id, generation_id}], min_weave_revision}` returns, per item:
     - `generic_text`
     - `woven_text`
     - `naming_provenance`
     - `weave_revision`
   - It needs no VLM and no image bytes, runs on CPU and writes nothing. That makes retries safe.
   - Run items store the generic base, its `phrase_boxes`, the image width and height, the image sha256 and the cache key. They weave on read. This way an unbind or delete reaches every service-side surface without a purge.
   - Replay needs an immutable base. Until ADR-017's generation log exists, the run item is that record. The cache row is not a replay source.
   - If the base is gone (expired or regenerated), the outcome is "Regenerate to name". Text never changes silently.
9. **Apply: name additions are proposals; removals execute (HAI-12, INT-07, Principle 3).**
   - **Review.** WordPress shows "Names ready for N descriptions — Review". Proposals are a filter on the existing media queue. Status, pause and retry live in the existing activity strip as one naming state. No second queue or poller is added (NAV-05).
     - Each item shows a diff with the name highlighted.
     - A per-person crop strip sits above the batch (HAI-13).
     - The face crop sits next to each woven name.
     - A chip in plain words names the realizer: "Placed by face position", "Only person in photo", or "Named, position not shown".
   - **Batch apply.** Use a smart label such as "Add names to 12 descriptions" (INT-06), plus per-item undo (INT-09).
   - **Apply fence.** Apply is one compare-and-set on the stored alt value, in one request (DATA-18). It checks the reviewed proposal hash, the base `generation_id`, the current naming intent, `weave_revision` and the policy snapshot. Any mismatch refreshes the proposal for review.
   - **Undo never writes old text.** Undo on an applied addition returns the item to its proposal. Undo on a removal reverses the curation step, and the name returns as a proposal. Deletion and consent-off have no undo into text.
   - **Each target state:**

     | Target | Name additions | Name removals (unbind, delete, withhold, suppress, consent off, rename of the old label) |
     | --- | --- | --- |
     | Pending draft | Replace the proposal. Still needs Apply. | — |
     | Machine-owned alt | Preselected in the batch | Apply automatically, revert to the base phrase, and show a notice with Undo, which reverses the curation step |
     | Human-edited alt (`_acx_description_human_edit`; apply must start reading this flag) | Suggestion only: the name and its face crop, with "Add to my text" and "Don't name here". Never woven text. | Never edit. Raise a review item if the removed name still appears. "Keep my text" is a logged override (HAI-06). |

   - **Machine-owned** means the human-edit marker is absent and the stored alt equals the last machine-applied value. The removal is a compare-and-set on that value. A mismatch makes the alt human-owned, and the item goes to review.
   - **Rename** removes the old name from machine-owned text, then proposes the new name for review. Other names in the text stay.
   - Auto-apply of *additions* is a later operator opt-in, available only after rule 13 passes.
10. **Corrections reach the source (CARD-02, INT-19, HAI-11).**
    - A proposal has three actions. Each one records a different fact:
      - **Not Daniel** unbinds the face from the cluster. It also corrects other photos and roster views.
      - **Don't name here** records a withhold for this photo only.
      - **Edit** is a human edit to this text.
    - A rejection never implies a withhold. A wrong-identity error is an unbind, so the wrong binding leaves the cluster.
    - The review keeps an edit path, because the model pre-labels the proposal (HAI-11).
    - When a curator edits an applied alt and removes a woven name, WordPress offers the same two choices, "Not Daniel" (unbind) or "Don't name here" (withhold), plus "Just wording", which records nothing. The prompt is inline, after save, not a modal.
    - Accept, edit and reject events on proposals go to `wp_acx_description_events` (AIPX-03).
11. **One consent gate, and it is required (ARCH-13, PROV-12, CARD-12, Principle 10).**
    - The enforced gate is the service tenant naming agreement, evaluated inside the weave.
    - The WordPress option is not an independent gate. It caches the service agreement, and it is written only after the service confirms (`class-settings-controller.php:468-505`). The plan reuses that settings control and adds durable change and revocation handling. A test asserts that WordPress shows the same state the weave enforces.
    - The agreement names "names in image descriptions" as a purpose of the curated identities.
    - Turning consent off shows a preview before commit (INT-07). The preview states how many published descriptions revert and how many human-edited ones are flagged. Then the rule 9 removals run.
12. **Provenance (PROV-01, HAI-06, ATTRIB-02, CARD-18).**
    - Each woven result carries:
      - the base `generation_id`;
      - the realizer kind and version;
      - for each name: the cluster or roster id plus the span or the presence mode;
      - `weave_revision`;
      - the policy snapshot.
    - WordPress stores this as a naming block in `_acx_description_provenance`.
    - Replaying `weave(base, weave_revision)` from the stored base must reproduce the text exactly.
    - The public alt carries only the name. It has no on-page source frame. The roster record is the admin-side source.
    - Until the operator chooses an on-page attribution or records an admin-only exception, the public identity claim does not meet ATTRIB-02 or CARD-18.
    - Copy discloses that names were placed automatically from curated people (HAI-05).
    - At curation time, and on first-run drafts, copy names the deferred effect (HAI-18). For example: "Naming Daniel updates 12 descriptions for your review." On a first-run draft: "Naming people adds names for your review. Accepting now loses nothing."
    - A pause control stops name additions and proposal refresh (HAI-04). Revocations still run, so a pause never keeps a revoked name public.
13. **Evidence gates (Principle 13, EVAL-01, AIPX-07, PROD-03).**
    - Report per realizer, in this order:
      1. Wrong-binding ledger. It must be zero on fixtures.
      2. Coverage and insertion, consulted only after the wrong-binding gate passes.
    - The wrong-binding ledger counts these as wrong-name events:
      - a face attached to the wrong span, role or possessor;
      - swapped identities;
      - a name on a stranger or on an unnamed person.
    - Gold associations are required for every fixture.
    - Baselines: no naming, and presence-appendix only.
    - The position-accuracy floor of 0.5 gates using boxes for two or more people. It is a chance floor, so it is supplementary to the ledger.
    - Fixtures, each non-vacuous for the realizer under test:
      - strangers (the unnamed phrase must stay byte-identical);
      - one named face among unconfirmed faces;
      - coreference with several people;
      - rename, unbind and delete;
      - a swapped pair of identities.
    - Auto-apply of additions waits for a controlled offline-to-online correlation experiment. Observed accept and reject rates do not count as that experiment (EVAL-22).
14. **Regenerate is the only path that runs the GPU again (COST-07, INT-11).**
    - The VLM runs only on first describe and on an explicit Regenerate.
    - Regenerate bypasses the cache (ADR-017 rule 9) and yields a new generic base and new boxes. The weave then runs over that base.

### Target outcome

1. Select all and describe with an empty roster. Every description is generic. Each image with people also stores boxes and dimensions. Nothing is lost.
2. The operator names Daniel's cluster and leaves the strangers alone.
3. The outbox operation reaches the mirror, the mirror ACKs, and the re-weave job runs. The weave takes milliseconds per image on CPU.
4. The operator sees "Names ready for 12 descriptions". One diff reads "A man and a woman by a fountain" → "Daniel and a woman by a fountain". The woman is untouched.
5. The operator applies the batch and can undo any item.
6. Later, Daniel is unbound from one photo. That photo's machine-owned alt reverts automatically, with a notice.
7. The GPU does not run again unless the operator clicks Regenerate.

## Why This Decision

### Placement is a geometry question, not a language question

- The hard part of option A — "where in the sentence does the name go" — is already answered by grounding: a span such as "a man" has a box, and the curated face lies inside it.
- That binding exists only on the service, and it does not depend on whether names exist yet. So it can be captured on the first run and reused for every later roster state.
- Re-weaving is then a pure function. It is cheap, replayable and testable down to the byte (Principle 9).

### Why strangers drive the rules

- Partial naming is the normal case, not an edge case.
- Today's counts look only at confirmed faces. With one named person and two unconfirmed strangers, lone-noun substitution can put the name on a stranger.
- Counting every detected face gives the abstention rule its input (CAL-02, Principle 11). The count is only a lower bound on people, because a back-turned person has no face (`caption_metrics.py:362-365`). So inline naming also needs a unique box (rule 4).
- Never labelling anyone a stranger avoids an identity claim nobody made (ATTRIB-02).

### Canon tensions and their cuts

- **Object:**
  - **The conflict.** ATTRIB-05 says to keep a name the source supplies. CAL-02 and AIPX-07 say to abstain on weak placement.
  - **The cut.** Split *presence* ("Daniel is pictured" — certain, because the curator confirmed his face in this image) from *placement* ("Daniel is 'the man'" — needs a unique box). Presence is kept; placement abstains.
- **Sequence:**
  - **The conflict.** INT-07 and HAI-12 call for preview before commit. Principle 3 and CARD-02 say a withdrawn claim must reach every artifact.
  - **The cut.** Additions are previewed. Removals on machine-owned text execute.
- **Surface:**
  - **The conflict.** ATTRIB-02 asks for the identity's source frame. Alt text must stay short.
  - **The cut.** The public alt carries the name. The admin carries the citation. The public gap stays open until the operator decides (rule 12).
- **Sequence:**
  - **The conflict.** AIPX-01 and COST-07 favour the cheap path. Fluent prose favours a model.
  - **The cut.** Deterministic first. Escalate only against a measured failure (CARD-19, Principle 13).
- **Object:**
  - **The conflict.** WRIT-06 says to repeat the precise term. Fluent prose favours pronouns.
  - **The cut.** Use pronouns only when one person is detected.

## Alternatives Considered

### 1. Deterministic insertion in the frontend (A)

Rejected:

- WordPress has no phrase boxes and no face-to-phrase geometry, so it would guess positions from text — exactly the hard part.
- A frontend copy of the realizer would duplicate it and drift from the service (ARCH-13).
- A PHP port (D) is rejected for the same reasons.
- The frontend's job is to render proposals, diffs, per-face states and reason chips.

### 2. Re-run the GPU VLM with names (B)

Rejected for naming:

- Every curation change would route through the most expensive tier, with a fresh cache miss each time (COST-07).
- Names would sit in a prompt beside faces with no binding between them (FM-01).
- The only measurement of this path is a 0.319 wrong-name rate, and it was never re-scored.
- Recovering from a generic draft by full regeneration throws away a valid base (INT-11).
- This path exists today by accident on the single-image route. Rule 1 removes it.

### 3. A small CPU LLM rewrite (C)

Rejected for placement:

- A text-only model given no associations would have to guess placement (CAL-02). Given the decided associations, it only needs to phrase them.
- Stacking a model on the VLM's prediction to correct it is a correction cascade (SERVE-04).
- No rules-first measurement justifies the model (AIPX-01).

Deferred for fluency. If online edit data show grammar edits rather than name edits, a bounded rewrite may be tried behind the existing `ReflowRealizer` interface, with no new seam (REF-12). Its contract:

- the exact name multiset is preserved;
- each identity-to-span, role and possessor relation is preserved, and checked;
- no new content words;
- a bounded change in length;
- any violation falls back to the deterministic text.

It is evaluated per CARD-19, with an inventory-grounded check of relations as well as words and names.

### 4. Require curation before describe

Rejected as a requirement, kept as a hint:

- It blocks the first run, the very case this ADR addresses (rg-003).
- When recognition is on, scan-then-describe already exists (`MediaSelection.tsx:420-456`). The UI may suggest it.

### 5. Store woven text in the service

Rejected:

- It contradicts ADR-017 rule 5.
- It creates a second store that every unbind or delete must purge (DATA-14, CARD-02).

## Consequences

### Positive

- Naming after curation costs no GPU time.
- Results are byte-reproducible from the stored base.
- Strangers are protected by construction.
- One function serves every path.
- Deletion and consent withdrawal reach text automatically.
- Names never inflate the cache.

### Negative

- Deterministic prose is less fluent than a model rewrite.
- A base that uses a collective noun ("a crowd") can take only the presence appendix.
- Quality depends on grounding, which adds GPU latency on first pass for images with person phrases.
- Image dimensions must be persisted.
- Free-text attachment context no longer reaches the caption prompt, so the generic base loses that context.
- There are new moving parts:
  - an endpoint;
  - a WordPress job and its refresh intent;
  - a recovery sweep;
  - version coordination (`weave_revision`);
  - one new curation state (withhold).
- WordPress loses its own name gate and depends on the service flag.

### Guardrails for the follow-on implementation task

- These tests must fail on today's code:
  - names in the prompt or the cache key;
  - free-text attachment metadata that carries a name reaching the caption prompt;
  - a phrase box holding two detected faces, where only one is confirmed;
  - lone-noun substitution with unconfirmed others present;
  - `Pictured from left`;
  - "they" with several people present;
  - a weave call without a policy;
  - a rename that leaves the old name in machine-owned text;
  - an Apply that succeeds after a newer naming intent or `weave_revision`.
- Rule 1 and rule 4 land before any trigger or UI work, because they remove live wrong-name paths.
- The re-weave endpoint is side-effect free. WordPress is the only alt writer (ADR-017 rule 2).
- The human-edit flag is read before any automatic removal. Machine ownership also needs the stored-value match in rule 9.
- The consent-parity test and the `person_deleted` mirror test are both required.
- Line references in this ADR are as of `main` d25922fa5. Re-read them before the plan cites them.

### Open questions for the task plan

- What is the debounce window for coalescing re-weave jobs?
- What is the deployed grounding flag value, and what is the grounding latency cost?
- What is the final copy for withhold and the reason chips? The UX map sets their placement (`docs/ux/v0.5.0/post-curation-naming-ux-map.md`).
- Does the public alt carry an on-page attribution, or does the admin-only exception stand (rule 12)?
- Which mechanism makes the rule 9 compare-and-set atomic? `update_post_meta` has no conditional update.

## Canon v0.26.2 grounding

Each row below is cited only where its trigger fires.

| Row | Rule | Source | Applied in |
| --- | --- | --- | --- |
| [ATTRIB-02] | **Captions explain or falsify identity** | Regarding the Pain of Others, ch. 1 | rules 5, 12 |
| [ATTRIB-05] | **Honor source identity decisions** | Regarding the Pain of Others, ch. 5 | rule 6, tensions |
| [BOUND-01] | **Assertable set is bounded** | Ways of Seeing, ch. 1 + On Photography + Regarding the Pain of Others, ch. 8 + Image Music Text, ch. 3 + The Civil Contract of Photography, ch. 6 + Under the Sign of Saturn, §syberbergs-hitler | rules 5, 6 |
| [BOUND-05] | ***Emphase* is not image privilege** | Système de la mode, ch. 1 | rule 6 |
| [CAL-02] | **Unknown is a valid result** | Designing Machine Learning Systems | rule 4, alt. 3 |
| [FM-01] | **Instruction-authority contract** | AI Engineering | rule 1, alt. 2 |
| [FM-04] | **Structured output is a contract** | AI Engineering | stage contracts (spans, not prose parsing) |
| [SEC-01] | **Validate at every trust boundary** | The Developer's Playbook for LLM Security, ch. 3 | rule 1 (free text crosses the WordPress-to-service boundary) |
| [SERVE-04] | **No correction cascades** | Hidden Technical Debt in ML Systems | alt. 3 |
| [COST-07] | **Quality–cost–coverage trade** | Reliable Machine Learning | rule 14, alt. 2 |
| [AIPX-01] | **Heuristic before ML** | Building ML Powered Applications, ch. 1 | alt. 3 |
| [AIPX-03] | **Instrument the flywheel** | Building ML Powered Applications, ch. 4 | rule 10 |
| [AIPX-07] | **Precision-first guidance** | Building ML Powered Applications, ch. 7 | rule 13 |
| [ARCH-13] | **Architecture hoisting** | Just Enough Software Architecture, ch. 2 | rules 3, 9, 11 |
| [REF-12] | **YAGNI / speculative-generality gate** | Refactoring (2nd ed), ch. 3 | alt. 3 |
| [PROD-03] | **Cheapest learning first** | Lean UX (3rd ed., Gothelf/Seiden), ch. 12 + INSPIRED (2nd ed.), ch. 33 + INSPIRED (2nd ed.), ch. 34 | rules 2, 13 |
| [PROV-01] | **Every output walks back to its evidence** | Model Cards + AI Engineering | rules 3, 8, 12 |
| [PROV-12] | **Consumers are scoped to the collection purpose, not merely registered** | Face Recognition Technology (Compulsory Visibility), ch. 3 | rule 11 |
| [DATA-13] | **End-to-end request ID** | DDIA, ch. 12 | rule 7 |
| [DATA-14] | **No dual writes** | DDIA, ch. 11 | rules 7, 8, alt. 5 |
| [DATA-18] | **Snapshot-isolation check-then-act gap** | DDIA, ch. 7 | rule 9 (apply fence) |
| [HAI-04] | **Activate–operate–override** | Human-Centered AI | rule 12 |
| [HAI-05] | **Imperceptible AI is not ethical** | Human-Centered AI | rule 12 |
| [HAI-06] | **Audit trail as design fuel** | Human-Centered AI | rules 9, 12 |
| [HAI-11] | **Interface-mode trade-off** | Human-in-the-Loop ML | rule 10 |
| [HAI-12] | **Output is a proposal, not the answer** | Designing AI Interfaces (Macfadyen 2026) | rule 9 |
| [HAI-13] | **User is the last error detector** | Designing AI Interfaces (Macfadyen 2026), § surfacing-state | rule 9 |
| [HAI-18] | **Name the deferred effect** | Guidelines for Human-AI Interaction, ch. 2 | rule 12 |
| [INT-06] | **Smart action labels** | Designing Interfaces, 3rd ed. | rule 9 |
| [INT-07] | **Preview before commit** | Designing Interfaces, 3rd ed. | rules 9, 11 |
| [INT-09] | **Reversible command stack** | Designing Interfaces, 3rd ed. + Designing Interfaces, 3rd ed., ch. 8 | rule 9 |
| [INT-11] | **Refine over restart** | Designing AI Interfaces (Macfadyen 2026) | rule 14, alt. 2 |
| [INT-19] | **One outcome per interaction** | Microinteractions, ch. 1 + Microinteractions, ch. 3 | rule 10 |
| [INT-20] | **Manage automatic starts** | Microinteractions, ch. 2 | rule 7 |
| [NAV-05] | **MECE categories** | Designing Interfaces, 3rd ed. | rule 9 (review placement) |
| [EVAL-01] | **Require offline baselines** | Designing Machine Learning Systems | rule 13 |
| [EVAL-22] | **Validate the offline proxy against online impact** | The ML Test Score, § model-2 | rule 13 |
| [WRIT-06] | **Repeat the precise term** | The Sense of Style, ch. 5 | rule 6 |

Cards, by `reasoning/` slug:

- CARD-02 `correction-at-source`
- CARD-03 `designed-unknown`
- CARD-12 `perceived-enforced-boundaries`
- CARD-18 `attribute-claims-to-their-bearer`
- CARD-19 `bounded-role-lets-a-small-model-be-safe`

CARD-25 `frozen-base-additive-delta` names the shape of rule 2 only. None of its rows fire.

Principles (`PRINCIPLES.md`):

- 3 — The safe side is cheap
- 9 — A claim must walk back
- 10 — Perceived boundaries must match enforced boundaries
- 11 — Unknown is a designed state
- 12 — Correction must reach the source
- 13 — Evidence precedes commitment

## References

- [ADR-003](ADR-003-wordpress-local-authority-and-durable-outbox-replay.md), [ADR-009](ADR-009-recognition-curation-refresh-and-person-review-projection.md), [ADR-017](ADR-017-description-authority-wordpress-curation-service-generation.md)
- `docs/tasks/19.0/E19-4a-identity-prose-merge-task-plan.md`
- `docs/tasks/v0.5.0/GPUFLOW-3-demo-triage-identity-gpu-lifecycle-and-unified-queue-task-plan.md`, slice group N
- `docs/assessments/GPUFLOW-3-position-accuracy-eval-20260918.md` (swapped-attachment and stranger fixtures are safety failures)
- `docs/ux/v0.5.0/post-curation-naming-ux-map.md` (screens S1–S8, placement and copy)
- Handoff decisions [3473], [12462], [15348], [15358], [15362], [16666], [17526]
- Canon v0.26.2 rows, by lexicon file (`lexicons/`):
  - `depiction.md`: `#attrib-02`, `#attrib-05`, `#bound-01`, `#bound-05`
  - `ml-systems.md`: `#cal-02`, `#fm-01`, `#fm-04`, `#serve-04`, `#cost-07`, `#prov-01`, `#prov-12`, `#eval-01`, `#eval-22`
  - `engineering.md`: `#arch-13`, `#ref-12`, `#data-13`, `#data-14`, `#data-18`
  - `interaction-ux.md`: `#hai-04`, `#hai-05`, `#hai-06`, `#hai-11`, `#hai-12`, `#hai-13`, `#hai-18`, `#int-06`, `#int-07`, `#int-09`, `#int-11`, `#int-19`, `#int-20`, `#nav-05`
  - `business-marketing.md`: `#aipx-01`, `#aipx-03`, `#aipx-07`, `#prod-03`
  - `security.md`: `#sec-01`
  - `writing.md`: `#writ-06`
