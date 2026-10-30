# Private finding review

A small loopback tool for humans to annotate operational finding claims beside frozen code evidence. These records come from handoff.db operational telemetry, not application production traffic; aggregated rows are not independent episodes. No model calls, public hosting, source-file browsing, or recommended labels. Validity, action-scoped disposition and annotation provenance are separate. Unknowns stay unknown.

This EVALOPS-3 source1 slice uses the trusted VM Canon v0.26.2 at `/home/gate/workbay-sandbox/evalops-1-assets-20261029/canon`; interaction-ux, ml-systems and accessibility lexicons and the relevant reasoning cards were checked against its release manifest. The supplied `resume-canon-rows.txt` supplies the pinned evaluation rows. Evidence remains beside the claim ([HAI-01] **Evidence before label**, *Designing AI Interfaces (Macfadyen 2026)* + *Guidelines for Human-AI Interaction*). Unknown disposition and uncertain validity remain separate options ([CAL-02] **Unknown is a valid result**, *Designing Machine Learning Systems*). History and explicit versions preserve lineage ([PROV-01] **Every output walks back to its evidence**, *Model Cards* + *AI Engineering*; [EVAL-13] **Pin the judging protocol**, *AI Engineering*). Agreement or an expert role never establishes truth ([HITL-05] **Agreement is a diagnostic, not the truth**, *Human-in-the-Loop ML*). Independent gold and judge validation remain external ([EVAL-12] **Validate the judge against humans**, *AI Engineering*). No generation stage or model selection is introduced; the caption/runtime/license cards have no triggered implementation action here. The designed-unknown card is checked through explicit enum/replay tests; evidence-before-commitment through the baseline and bounded behavior checks.

## Start and resume

```sh
python benchmarks/tools/evalops/label_ui.py serve --packet /private/reviewer-public-packet.json --state-dir /private/reviewer-state --role reviewer --port 0
```

Open the printed `http://127.0.0.1:PORT` URL. Enter your actual name, read the visible rubric, and review each claim and its frozen source. Choose **Defect**, **Not a defect**, or **Uncertain / need more context**. Then choose the action disposition and record provenance/exposure as described below; notes are optional. No new item has a selected label. Missing source has an explicit state. Save & Next acknowledges journal fsync before advancing. Previous and Skip preserve drafts within the tab; Skip records no event. Unsaved drafts do not survive closing the tab, and a close warning protects them. Failed saves retain their retry ID and payload. If you edit after a failure, the next save first resolves that original request, then asks you to save the retained correction.

Stop with Ctrl-C. Resume with the same command, packet, role and state directory. Saved identity and answers resume; the first unanswered item opens. Use Previous or Review from beginning to correct an answer. Corrections append events and reference the superseded event; original events remain. Export my judgments downloads this session's sanitized JSONL history, including corrections and explicit legacy/unknown projection fields. Exports are views, not journal backups or an import format; never replace `events.jsonl` with an export. Completion reports saved/unanswered counts and **reference QC pending**, never quality acceptance.

A directory belongs to one human identity, role and frozen public packet digest. Use a new directory for another human, role or packet. Identity cannot change after starting. Keep the directory on a private local filesystem; do not manually edit its files. Startup refuses an exclusive-lock conflict, invalid metadata, truncated/corrupt logs or packet/role mismatch. Back up logs before investigating failures; never repair history by guessing labels. A storage failure requires stopping and restarting; retain the browser draft.

## Independent expert and offline coordination

The coordinator supplies the reviewer public packet. A separate expert curator independently launches the same command with `--role expert`, a **separate expert public packet file**, and a **separate state directory**, preferably on a separate private machine/account. Never give the expert reviewer answers or a reviewer log, or give reviewers expert gold. Loopback access is not OS-user authentication: anyone with access to the same machine/browser session can view that session. Keep reviewer and expert sessions outside each other's access. Prior exposure cannot be undone by hiding fields later.

The server receives no private mapping. Packets contain only the public contract below. Offline repeat/gold assignments and original finding mappings stay with the coordinator. Each presentation uses an opaque ID, including repeats; no identifier should reveal task/model/severity/fix/outcome/gold/repeat membership. The validator can enforce shape and uniqueness, not the semantic opacity of coordinator-created IDs or independence of people.

**This UI does not supply independent humans or reference gold.** Those remain external requirements for reference acceptance. It does not create hidden repeats, certify coverage, adjudicate labels or run quality acceptance. Independently sourced expert reference and QC decisions must be prepared and checked separately.

Read `benchmarks/tools/evalops/score_judge.py` before downstream scoring. UI exports are **raw human events, not findings-v0** and cannot be passed directly as scorer findings. The administrator joins completed HUMAN judgments (latest event per opaque presentation, with history retained) to the frozen private map and original seed offline, then constructs the scorer findings and QC files without guessing labels. `unclear` stays inconclusive, never a negative. `unknown` disposition is neither blocking nor nondefect. Export provenance must be checked before reference use: legacy/unknown, user-assisted and post-review answers are not independent gold. Even an independently attested expert entry is a recorded claim requiring separate attestation/QC verification. The current 58/57/5 human counts include user-adjudicated answers and are not independent gold. The scorer documents QC requirements per annotator/field: at least 20 gold and 20 repeat decisions, each at least 10%, at least .90 gold accuracy and repeat agreement. Kappa is diagnostic only; the UI makes no QC or quality-acceptance claim.

## Annotation contract (v2)

Every new decision requires the existing `presentation_id`, `label`, `client_id` and optional `note`, plus:

| Field | Values / meaning |
| --- | --- |
| `label` | `defect`, `not_defect`, `unclear`; validity only |
| `disposition` | `blocks`, `nonblocking`, `unknown`; scoped to the affected action |
| `affected_action` | Nonempty text for either known disposition; otherwise null or text |
| `blocking_reason` | Evidence/conditions required for `blocks`; otherwise null or text |
| `provenance.kind` | `blind_human`, `user_assisted`, `post_review`, `independent_expert`, `unknown` |
| `provenance.exposure` | `unexposed` (explicit attestation), `exposed`, `unknown` |
| `provenance.attestation_ref` | Independent attestation reference for expert claims; otherwise null or text |
| `provenance.original_ref` | Optional external original annotation/adjudication reference, else null |
| `provenance.protocol_version` | Required version of the annotation procedure used |

`blocks` requires `label=defect`, an affected action and nonempty evidence/conditions. A valid defect may be `nonblocking`; choosing a disposition does not change validity. Both uncertain and nondefect may have unknown disposition. Blind human and independent expert require explicit `unexposed`; independently attested expert also requires `attestation_ref`. Assisted/post-review may record exposed or unknown exposure, never unexposed. Neither session role nor notes, majority, saved count or reference text proves independence. References are inert bounded text, never fetched.

The built-in `evalops-annotation-v2` procedure is: inspect frozen evidence, judge validity, decide impact on a named action under stated conditions, then attest source/exposure or select unknown. Use the actual procedure version when another protocol was used. The frozen packet's `rubric_version` is copied by the server and shown in the UI; opening an old packet does not silently upgrade its rubric. The coordinator must supply an appropriate frozen rubric for a new session.

New events carry `annotation_schema=evalops.annotation.v2`, server-generated `event_id`, `original_event_id` (first journal event for this presentation), `supersedes` (immediate prior journal event or null), packet/rubric identity and UTC timestamp. External `original_ref` supplements those server-owned links. The complete structured payload participates in retry conflict detection, including provenance and versions. New unstructured requests are rejected; exact retries of existing legacy events remain idempotent.

Legacy events replay with their original labels, notes and references unchanged. Only their snapshot/export views add `annotation_schema=evalops.annotation.legacy`, `disposition=unknown`, null action/reason and `provenance={kind:legacy_unknown, exposure:unknown, attestation_ref:null, original_ref:null, protocol_version:null}` plus the derived original event ID. Opening, exporting or retrying a legacy session never rewrites its stored events. Corrections explicitly append v2 events. No labels or independence are inferred from prior notes or roles; there is no automatic adjudication or migration.

The existing real 140 events / 120 answers and 99 unlisted presentations are outside this implementation's test inputs. Private real sessions and expert answers must not be inspected or altered for QA. No changes to original UI19998/action171 or capture19999 identities/counters or fixes are part of this slice; their source2/source4 routes remain authoritative.

## Screen contract and critique

The existing SSOT is `docs/ux-maps/evalops-labeler.uxmap.json`. Before UI editing, the inspected layout was recorded as:

```text
[Evidence] | [Defect validity: defect / not defect / uncertain]
           | [Action disposition: blocks affected action /
           |  nonblocking / unknown + affected action / reason]
           | [Provenance / exposure]
           | [Save & Next]
[progress]
```

Evidence remains beside the annotation controls on desktop; narrow screens retain evidence first in reading order. Separate groups and associated visible labels prevent validity, policy and provenance from visually implying one another ([PERC-01] **Proximity binds meaning**, *Designing with the Mind in Mind* + *Refactoring UI, § avoid-ambiguous-spacing*; [A11Y-03] **Label every input (3.3.2/1.3.1)**, *Web Content Accessibility Guidelines 2.2, SC 3.3.2*). New items have no factual attestations selected. Errors appear by Save, announce through an alert and receive focus ([PERC-05] **Fovea-first feedback**, *Designing with the Mind in Mind*). Native radio/select keyboard behavior and existing focus styling are retained. Human keyboard/screen-reader acceptance remains external.

Typed tool limitation: `ToolUnavailable(codebase-memory-mcp)` — no graph tools exposed; supplied anchors were refreshed by direct source reads. `ToolUnavailable(ux-map critique)` — no critique tool or CLI available; the existing map was inspected and updated in place, with a manual contract critique above. No substitute map, scheduler or paid reviewer was introduced.

## Frozen public packet

Schema: `evalops.label-packet.v1`; required packet fields are `packet_id`, `rubric_version`, `rubric`, and a nonempty `items` array. Each item requires `presentation_id`, `description`, and `context_status` (`verified_recorded_commit` or `unavailable`). Optional/null fields are `file_path`, `line_start`, `line_end`, and `source_context`; optional `context_note` is plain text. Verified context requires a nonempty frozen snippet; unavailable context requires null context. Coordinator verification establishes the recorded commit; the UI does not fetch source files or verify a commit. Unknown fields are discarded before state binding, HTTP and exports, rather than echoed. Never supply private mappings even though projection discards extra fields.

Synthetic **DEMO only** packet for UI QA (not human reference evidence):

```json
{"schema":"evalops.label-packet.v1","packet_id":"DEMO-only","rubric_version":"finding-rubric-v1","rubric":"DEMO: compare the synthetic claim with its code. Choose Need more context when evidence is insufficient.","items":[{"presentation_id":"demo-opaque-a","description":"DEMO claim: the function returns the wrong constant.","file_path":"demo.py","line_start":1,"line_end":2,"source_context":"def demo():\n    return 1","context_status":"verified_recorded_commit","context_note":"Synthetic frozen example; no real finding."},{"presentation_id":"demo-opaque-b","description":"DEMO claim with no available code.","file_path":null,"line_start":null,"line_end":null,"source_context":null,"context_status":"unavailable","context_note":"Synthetic missing-context case."}]}
```

Only DEMO synthetic packets may be used for automated/browser QA. Never inspect real human decisions through AI tooling. Test labels are synthetic fixtures, not human evidence.

## Local boundaries and limits

The CLI binds only IPv4 `127.0.0.1`, defaults to port 8765, and accepts port 0 to print the actual port. Only matching `127.0.0.1:PORT` or `localhost:PORT` Host headers are accepted. POST requires the matching HTTP Origin and session CSRF token; there is no CORS. Static assets use an exact whitelist, no external resources, textContent for all dynamic text, and a restrictive CSP. JSON rejects duplicate keys and nonfinite numbers. No client can supply a file path to read. This is a private local tool, not a multiuser service.

Limits: 8 MiB packet; 1–1,000 items; 128-character IDs/versions; 16,000-character rubric/claims; 64,000-character snippets; 1,024-character display paths; positive source line numbers up to 10,000,000; 100-character names; 4,000-character notes and blocking reasons; 1,024-character actions and provenance references; 128-character protocol versions; 32 KiB request bodies; 50,000 events and 64 MiB log. Metadata uses atomic replacement and directory fsync; event acknowledgments follow fsync. State children must be regular files without symlinks/hardlinks, state paths cannot traverse symlinks, and the packet cannot live inside or alias a state child. Use a local filesystem supporting flock/fsync/atomic rename.

## Validation and remaining QA

Refreshed source anchors in `benchmarks/tools/evalops/label_ui.py`: `_payload` 184–221, `_restore` 223–251, `decide` 270–307, `snapshot` 309–314, `_project` 316–324, `export` 326–328 and `main` 404–427.

Run `LC_ALL=C uv run --no-project --with pytest python -m pytest -q --noconftest benchmarks/tests/test_evalops_label_ui.py` in one process. Baseline: 19 passed; final suite: 62 passed. The expanded synthetic suite covers legacy restore/export without byte rewrites, new independent fields, assisted provenance roundtrip, valid nonblocking defects, uncertainty, invalid combinations, replay corruption and retries/conflicts, plus existing durability and private HTTP/path boundaries. The HTTP test exercises actual handler parsing through an in-memory transport; it does not establish live loopback acceptance. `node --check benchmarks/tools/evalops/label-ui/app.js` passed. A temporary DEMO-only Node VM harness executed the actual app.js and passed checks for blank attestations, assisted/nonblocking payloads, focused validation errors, uncertainty, unchanged retry payload/ID, edited provenance retention (including a blank required field during retry), navigation and whitespace validation. This is simulated DOM behavior, not browser or keyboard evidence.

Browser smoke was attempted only with a DEMO packet and synthetic state. Playwright was unavailable and its installation failed on DNS resolution; the cached Chromium 153.0.8010.12 aborted before loading the page (`sandbox_host_linux.cc:41`, `shutdown: Operation not permitted`). Browser interaction/reflow acceptance is unverified. Human usability, assistive technology, independently verified attestations, frozen rubric suitability and external private-session acceptance remain unknown. No independent gold, judge calibration, production reliability or native dispatch success is established by these tests. No deployment is authorized. This VM job uses the external transport precedent20551 with `codex-remote`; the job receipt records original source `fd4aca96df2b11222d575cb59de5fe8219412329` / tree `111c27d87e0707f966aeb0a0236c1a9c60a6a91b` and matching synthetic snapshot tree, without asserting original Git ancestry.
