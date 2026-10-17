# SUBJECT-EVIDENCE-1 — PROPOSED, revision 2

Status: revisedplan_pending_independent_review. This proposal responds to the independent SUBJECT-PLAN-GATE review of SUBJECT-GATE-03. Independent planning review precedes any source implementation; independent source review follows implementation. This document grants neither finding closure nor bakeoff execution, adoption, score, quality or face qualification. A further plan-author revision after additional defects requires the separately requested LOUD/XHIGH boundary.

Image-level pseudonym metadata already independently passed and was adopted under decision 17811. Its 523 note amendments and 1,048 namespace-bound declarations remain adopted for that scope. Do not reopen completed SUBJECT-GATE-01/02 or seek new storage approval. Those declarations do not certify complete person/group enumeration, per-face association, absence of depicted people, or identity equivalence across frames. This source proposal consumes none of the private note/sidecar payload as model context or identification truth.

## Actual defect and chosen scope

At the reviewed input, `build_bakeoff_report.py:691` selects the first present alias from `subject_id`, `subject_ids`, `subject`, `subjects`, `present_identities`. `_selection_disjointness_reasons:745` refuses empty sets at lines 773/797 and intersects literal labels at line 809. There is no structured `subject_evidence` consumer. The existing public alias witness for one shared person exits 5 with legacy keys, 0 with one key qualified, and 5 after aligning the keys; genuinely distinct qualified labels exit 0. A second witness binds the observations to different frame namespaces and still exits 0 for the same person. These characterize existing aliases, not an implemented new schema.

Choose the explicit fail-closed alternative for v1: **no cross-representation identity resolver and no canonical identity registry are introduced**. Every person-bearing comparison involving structured evidence is `incomparable`, including two keys with identical namespace text or identical tokens. This deliberately also refuses genuinely distinct structured people. A manifest/frame namespace binds an observation, not a person. A future authority-backed equivalence resolver is a separate reviewed source contract, not an implicit extension point that may return disjoint today.

The useful v1 change is narrow: independently supported no-person evidence can supply a legitimate empty set at the subject-evidence check. All omitted-field legacy/legacy behavior stays intact. No new known-person mode, waiver, redraw, dummy person, global unknown sentinel, filename parser, sidecar CLI or identity registry is part of this proposal.

## Strict evidence and observation binding

Add only optional `GoldenEntry.subject_evidence`, omitted from serialization when absent. Present JSON null is invalid; an omitted field alone selects legacy behavior. Use strict Pydantic models with unknown fields forbidden and no coercion of booleans/strings into version integers or completeness booleans. Proposed `SubjectEvidenceV1` fields are:

| Field | Type and rule |
| --- | --- |
| version | Integer literal 1; missing, null, string, boolean or other integer refuses |
| status | Literal known, partial, unknown, not_applicable |
| subject_ids | Duplicate-free list of nonempty qualified strings `identity_namespace:token`; exact spelling retained, no name normalization |
| identity_namespace | Nonempty colon-free string for known/partial; null for unknown/not_applicable; every supplied key must use it |
| complete | Strict boolean with the state constraints below |
| scope | Literal image_people_and_depictions, explicitly including reflected people |
| authority | Nonempty authority reference; an asserted string alone is not identity equivalence or complete evidence |
| evidence_reference | Nonempty immutable audit reference |
| support | The typed, embedded attestation described below; unknown may omit it |
| support_sha256 | SHA-256 of C(support.model_dump()) when support is present; otherwise omitted |
| source_binding | Typed SourceBindingV1 described below |

`EvidenceSupportV1` has strict version 1, `authority_reference`, `review_reference`, distinct nonempty `declarer_id` and `reviewer_id`, `basis` (operator_image_declaration or independent_image_evidence), `claim` (incomplete_subjects, complete_subjects or no_people_or_depictions), literal scope image_people_and_depictions, and lowercase SHA-256 `source_original_sha256`. These are opaque audit references, not public names or endpoints. The independently reviewed declaration is embedded rather than fetched from an arbitrary string/URL. Record its exact canonical-body SHA-256 in the sibling field `support_sha256`; verify that hash, source-original binding and status/claim agreement. The outer authority must equal support.authority_reference and evidence_reference must equal support.review_reference. The independent review must actually support the asserted scope before a complete record is published. Schema acceptance proves internal consistency, not the truth of an attestation; source review and subsequent evidence review must retain that distinction. Missing independent review/support cannot become a complete declaration merely by setting complete=true. No new annotation campaign or mandatory media inspection is authorized by this plan.

| State | Required evidence | Subject-comparison result |
| --- | --- | --- |
| known | Nonempty subject_ids; complete=true; independent_image_evidence support with complete_subjects | Enumeration is declared complete locally; person-bearing comparisons remain incomparable in v1 |
| partial | Nonempty subject_ids; complete=false; support claim incomplete_subjects | Incomparable; includes filename-only declarations and unresolved additional/group/depicted people |
| unknown | Empty subject_ids; complete=false; no identity_namespace; missing, ambiguous, conflicting or inadequate evidence | Incomparable, never a synthetic person |
| not_applicable | Empty subject_ids; complete=true; no identity_namespace; independent_image_evidence support with no_people_or_depictions | Supported empty set for the subject-evidence check only |

Support references/IDs are exact nonempty strings, hashes are 64 lowercase hex characters, and unknown fields refuse recursively. A filename declaration, face_count=0, absent detections, empty identity list or art tag cannot supply complete_subjects or no_people_or_depictions. Inconclusive absence support must be unknown. Existing nonempty identification labels, named face boxes, nonempty subject aliases, positive recorded face counts, or any conflicting person/depiction declaration prevent not_applicable; recorded zero is necessary consistency here, never sufficient absence support. Do not overwrite that conflict. Keep all labels, aliases, notes, face counts, boxes and context unchanged; structured person keys never override identification truth.

Bind observations without a recursive self-hash. `SourceBindingV1` contains literal `digest_profile` (golden_v3 or raw_report), `namespace`, `source_manifest_sha256`, positive `source_entry_ordinal`, `source_entry_sha256` and `source_original_sha256`. Let `C(x)` be UTF-8 `json.dumps(x, sort_keys=True)` with its existing default separators/escaping. For golden_v3, take the validated manifest's current model_dump, remove only subject_evidence from every entry, and hash C of that projection. For raw_report, use the actual raw document with only those entry fields removed, preserving entries/items and its order. This projection is a binding identity, not a run digest or a claim about unavailable parent bytes. Namespace must equal `manifest-sha256:` plus that projection digest. Hash C of the corresponding projected entry for source_entry_sha256; the ordinal must identify that exact entry, and source_original_sha256 must equal its existing sha256. Reordering, changed path/media_id, foreign projection/profile, corrupt entry/original hash or copied binding refuses. Ordinals and media IDs never join people across frames. Metadata-only validation compares declared hashes; ordinary source loading still verifies original bytes under its unchanged policy.

## Concrete source API and fail-closed comparison

Proposed typed API in `manifest.py` (names are planned, not existing):

```python
validate_subject_document(
    raw: Mapping[str, object], *, role: SubjectRole
) -> ValidatedSubjectDocument
```

`SubjectRole` is a frozen record with kind Literal[reported, selection] and selection_index (positive integer for selection, null for reported), preserving repeated selections without exposing their paths. `ValidatedSubjectDocument` retains the original ordered entry mappings and an ordinal-indexed tuple of `LegacySubjects | KnownSubjects | SupportedEmpty | IncompleteSubjects`. `LegacySubjects` retains the exact existing alias precedence and `_label_values` behavior; an empty legacy list becomes IncompleteSubjects with reason missing_subject_evidence. KnownSubjects retains the validated structured keys and support without claiming canonical person resolution. Partial/unknown become IncompleteSubjects with their respective reason codes. SupportedEmpty is constructible only after the complete absence-support and binding checks above. These are explicit immutable typed variants, not dictionaries with unchecked status strings. `SubjectEvidenceError` carries code Literal[outer_version, evidence_version, evidence_shape, state_consistency, source_binding, support_binding, evidence_conflict], role and entry ordinal (null for document errors); it never embeds private authority bodies or labels in a public error. Validate outer version, nested version, shape, state, source binding, support binding, then conflicts in that order to make multi-defect error precedence deterministic.

The frozen variant payloads are LegacySubjects(labels: frozenset[str]), KnownSubjects(keys: tuple[str, ...], identity_namespace: str, support: EvidenceSupportV1), SupportedEmpty(support: EvidenceSupportV1), and IncompleteSubjects(reason: Literal[missing_subject_evidence, partial_subject_evidence, unknown_subject_evidence]). Define SubjectObservation as precisely that four-way union. ValidatedSubjectDocument carries role: SubjectRole, entries: tuple[Mapping[str, object], ...] and observations: tuple[SubjectObservation, ...] of equal length, preserving zero-based storage with one-based public ordinals. No caller may instantiate SupportedEmpty from a boolean or raw dictionary without validation.

In `build_bakeoff_report.py`, add:

```python
compare_subjects(left: SubjectObservation, right: SubjectObservation) -> SubjectComparison
```

`SubjectComparison` has result Literal[disjoint, overlap, incomparable] and code Literal[legacy_disjoint, legacy_overlap, supported_empty, missing_subject_evidence, partial_subject_evidence, unknown_subject_evidence, identity_authority_unresolved]. Its exhaustive decision order is:

1. An IncompleteSubjects operand returns incomparable with its reason, even opposite SupportedEmpty. Validate every row first; no row or ordinal disappears.
2. Otherwise a SupportedEmpty operand returns disjoint/supported_empty. This makes no same-person assertion about the other operand.
3. Two LegacySubjects operands use the unchanged literal intersection: overlap/legacy_overlap or disjoint/legacy_disjoint. This preserves all legacy aliases, precedence, empty refusal and existing limitations; it does not retroactively certify that legacy text is a canonical identity authority.
4. Every remaining pair contains person-bearing structured evidence: return incomparable/identity_authority_unresolved. This applies to legacy/known, known/known, same/different namespace, same/different token and foreign/unknown identity keyspaces. Do not try raw-name equality, case folding, shared suffix/media ID, namespace equality, or the manifest projection as an equivalence mapping. There is no positive structured-person disjointness path in v1.

For each reported/selection frame, aggregate all cross-frame pairs and all individual missing/partial/unknown rows. Overlap or incomparable keeps selection not_ready; both reasons may be retained. SupportedEmpty is never a corpus stratum/person label. Keep every existing content-ID, original-hash and path check independently active. `_selection_disjointness_reasons` consumes these results instead of mixing structured strings into `_entry_subjects`; `_corpus_readiness_reasons` stays unchanged.

Caller-visible contract: with --bakeoff-gate, well-formed unresolved identity comparisons write the existing not_ready report and return EXIT_BAKEOFF_GATE=5. Render the stable text `subject comparison incomparable: identity_authority_unresolved` with role/ordinal, without private identities. Existing legacy overlap diagnostics remain compatible. Invalid record/version/binding/support returns EXIT_NOT_COMPARABLE=4 with `subject evidence invalid: <code>` on stderr and writes no report. `--allow-foreign-run` cannot waive either subject refusal. Without --bakeoff-gate, exploratory rendering retains its current non-readiness meaning; malformed supplied structured evidence still exits 4 before rendering. No new mode or CLI flag is added.

Both input roles must call the same validator: reported --manifest and every repeated --selection-manifest. Preserve raw mappings for display/strata and ordered binding validation before reducing entries to a media-ID map. The strict reported-v3 `_expected_shas:454` path stays first. `load_manifest:1582` must perform the same evidence/binding checks before either metadata_only return or original-byte verification. Within the new helper, golden_v3 projection uses GoldenManifest.model_validate, never load_manifest: field models validate record shape, then the helper checks document bindings against the resulting dump. Do not install that document helper as a recursive GoldenManifest model validator. A raw selection does not become validated merely because GoldenEntry gained a field.

Version routing is explicit. With no subject_evidence anywhere, preserve existing raw-report/non-v3 and strict-v3 behavior, including load_legacy_manifest's frozen v2 path and old rejection cases. With any subject_evidence present, a missing outer manifest_version is the raw_report profile, not implicit v3; integer 3 requires golden_v3 and existing strict validation. Any other outer version, including string "3", null or boolean, refuses with exit 4. In either supported profile, an absent/unknown nested version or present-null record refuses; it cannot fall back to legacy aliases. No new structured evidence is admitted through the frozen v2 loader.

## Compatibility, claim boundaries and fixed evidence

Absent-field canonical model dumps and all legacy hashes must remain byte-identical. Use field-level omission when absent, not a new default-null alias or global exclude_none that removes existing fields. Present evidence changes the full manifest/run digest. The report's `_manifest_sha:440` is SHA-256 of C(model_dump); CLI re-exports face_bakeoff._manifest_sha (cli.py:49, face_bakeoff.py:110), which additionally handles existing date values. Do not change either recipe, default separators, escaping or date handling. The new support uses strings, not new datetime values. Preserve digest parity for legacy inputs and verify the two existing helpers agree for supported subject records. An amended v3 manifest with an old candidate, incumbent or baseline pin must still refuse before output; refreshing a digest does not qualify its content.

Keep evidence/support out of context_pack, roster enrichment, prompts and raw model input. Actual describe edges pass `entry.context_pack.model_dump(exclude_none=True)` at cli.py:644 and bakeoff.py:1148; text builders are bakeoff.py:915/936/1169. Tests can extract these unchanged AST nodes without importing cv2 or creating a model client. Raw generation after its execution/serving qualification does not acquire a new fact-label, score, absence-attestation or subject-readiness prerequisite. This lane authorizes no generation or bakeoff launch.

Freeze selection10/heldout20 roles, content IDs, original hashes and paths; four currently shared legacy labels still refuse under the default unseen-person guard. Keep every intended candidate/incumbent and all four arms: zero_rule_context_echo, context_only_heuristic, current_production, blinded_human. Preserve their manifest identities, all corpus/strata and metric prerequisites, historical failed regression37 with its missing original, and the separately reviewed replacement pointer. Retain missing-original nonresponse, denominators, thresholds and all prior failures. No resampling or deletion to pass. Known-person/new-image claims require their own separately authorized frozen protocol; no conditional waiver is accepted here.

A supported empty selection row may eventually remove only its subject-evidence reason and permit exit 0 in an otherwise-ready synthetic frame. A supported empty reported row still fails the unchanged mandatory subject-strata check (currently 99/100 populated in the witness), so its whole report stays exit 5 even if subject comparison becomes disjoint. Do not add a dummy stratum/person or silently change the corpus rule. Strict v3 fixtures may retain other existing corpus reasons; explicitly enumerate them rather than claiming whole-report PASS from schema acceptance.

## Minimal ownership, selectors and dependency DAG

Future source ownership is only `apps/prototype-description-service/scripts/eval_harness/manifest.py` (typed evidence, support/bindings and absent-field serialization) and `apps/prototype-description-service/scripts/eval_harness/build_bakeoff_report.py` (both-role validation, typed comparison, public outcomes). Read cli.py, bakeoff.py and face_bakeoff.py for input/digest parity; do not edit them. Future test ownership is only `scene/tests/test_eval_harness_bakeoff_report.py`, `scene/tests/test_eval_harness_manifest.py` and `scripts/eval_harness/tests/test_manifest_invariants.py` under the same application. This revision edits none of those files or any manifest, metadata, accepted plan or historical record.

The serial DAG is A → B → C → D → E:

| Node | Reads | Produces/owns |
| --- | --- | --- |
| A | Independently reviewed version/state/API/exit contract above and exact current source | Approved selector table and binding/support fixtures; no new plan authority inferred |
| B | A's fixture definitions and predicted exits | Small failing public specifications and saved actual failures in the named test modules |
| C | B's schema/omission failures | manifest.py strict variants, shared validator, binding checks; manifest selectors green |
| D | C's ValidatedSubjectDocument and B's public failures | report both-role consumption, comparison and public refusal contracts; public selectors green |
| E | D's reports/exits and C's dumps | Exact regression/digest/input-isolation results and source-review packet |

The graph has no back-edge; each arrow names consumed data. One bounded lane is sufficient; no workers or concurrency schedule is proposed. Independent planning acceptance is required before A's source-work execution, and independent source review follows E. Neither boundary reopens metadata adoption 17811.

Proposed selectors (all new, not existing/executed) are:

| Module | Selector and required cases |
| --- | --- |
| test_eval_harness_bakeoff_report.py | test_subject_evidence_mixed_same_person_public_cli: legacy/known same person in both directions returns 5/incomparable; genuinely distinct mixed pair also returns 5; all-legacy shared 5/disjoint 0 controls |
| same | test_subject_evidence_namespace_comparison_public_cli: same person across different frames/keyspaces returns 5; distinct structured people also refuse 5; equal namespace/token and numeric-ID collisions never authorize disjointness; no new resolver exists |
| same | test_subject_evidence_supported_empty_scene_public_cli: raw_report supported empty selection with all other prerequisites passes 0; empty reported row keeps exit 5 only for remaining corpus reasons; bind every record to its actual profile/order |
| same | test_subject_evidence_unknown_partial_depiction_public_cli: missing legacy evidence, unknown, partial group, unresolved reflection/depiction refuse 5; face_count=0 alone refuses; no shared sentinel or dropped row |
| same | test_subject_evidence_foreign_binding_and_version_public_cli: both roles, raw/strict profiles; null, absent/unknown nested versions, invalid outer versions, malformed support, missing review, foreign namespace/profile/hash/ordinal/entry binding refuse 4/no output; omitted evidence preserves all old routes |
| same | test_subject_evidence_amendment_rejects_old_digest: present evidence changes canonical digest; stale candidate/incumbent/each baseline pin refuses 4/no output; matching-pin rendering remains comparable without claiming readiness |
| test_eval_harness_manifest.py | test_subject_evidence_omission_preserves_canonical_dump: exact pre-change canonical dumps/hashes, legacy optional fields, v2 frozen loader and no-null alias regression |
| same | test_subject_evidence_state_consistency: complete status/support matrix, strict types, duplicate keys, unknown fields, source projection/order, conflicts and field-present invalidity |
| test_manifest_invariants.py | test_subject_evidence_never_changes_identity_truth: all old labels/notes/counts/boxes/context and legacy loader restrictions unchanged; extracted prompt AST nodes give identical text; inspect actual callers without initializing clients |

Retain existing report selectors test_bakeoff_gate_rejects_selection_subject_or_image_overlap, test_matching_manifest_sha_renders_unbadged, test_foreign_manifest_sha_is_fatal_and_writes_nothing and test_manifest_version_as_string_fails_closed. Keep ID/hash/path and missing-baseline public controls orthogonal to identity cases. A public driver uses the actual `main` argument grammar: --bakeoff-gate, repeated --selection-manifest, --expected-candidate, --expected-incumbent, --run LABEL=PATH, four --baseline-run LABEL=PATH, --score-ok ID=PATH, --manifest, --out, and --media-ids 1 for bounded text-only rendering. Score markers and run records in these controls are explicitly synthetic protocol fixtures, not real scores or inference.

Before each new source test, predict its failure against the current code and retain observed stdout/stderr/exit. A raw structured record currently being ignored or a strict model rejecting a new field is characterization, not proof of future comparison behavior. In the separately authorized implementation lane, make one behavior green at a time; in an isolated owned copy, remove the incomparable branch or bypass one binding check and prove the corresponding public selector goes red. Preserve setup failures separately. Bound each subprocess/fixture to 55 seconds and the resource envelope to 1 GiB / 0.5 CPU; no installs, broad suites, image decoding, inference, vectors, models, GPU/OCI operations, servers or downloads. Stop/reap proven owned processes before any owned cleanup; retain uncertain/foreign resources.

## Evidence and independent acceptance

Private revision evidence is under /tmp/subject-plan-r2: exact input/native provenance, source and prior-review snapshots, six programmatically hashed Canon bodies, fired rows/cards, semantic receipts, source outlines, current public counterexamples/controls, raw outputs/exits and an artifact hash manifest. The logical input is b44624f103476d3877342c0a4aa2d415695a188e, tree e56bda9823231fcb5119ea97579d68dbb08bd29d; native base 5c336a13ba360995d65d6b6175e3020882363e91 has that exact tree. Equal trees establish input bytes, not ancestry. No live graph/handoff refresh or new ONNX inference is claimed.

Published Canon 0.26.2 TEST-06/23/25 and CARD-08 require the predicted public failures and incremental source verification; TEST-15 remains a future source-lane discrimination check and TEST-33 requires independent re-review. GRPH-01/32 ground the data-carrying serial DAG; no cycle, concurrent-node or worker-admission trigger is asserted. RES-02/CARD-09 bound waits. CARD-11/OBS-09 preserve external frame/denominator ownership. The supplied original research distillations inform test design without overriding published triggers: MLDATA-08/09 detector-harvest coverage, EVAL-03 resampling and PROV-02 model release do not impose a new universal pixel/fact-label gate on adopted image metadata or qualified raw generation.

Reject this revision if a reviewer finds any structured person-bearing pair reaching disjoint through name/key/frame equality, any invalid present record falling back to legacy, any unvalidated raw selection, any changed omitted-field digest or identity truth, or any erased corpus/content/baseline refusal. A reviewed future canonical identity authority would need a pinned authority-owned person namespace and explicit legacy/qualified equivalence classes with conflict/unresolved outcomes; none is inferred from decision 17811. This proposal remains pending independent review and does not close SUBJECT-GATE-03.
