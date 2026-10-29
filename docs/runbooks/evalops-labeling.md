# Private finding review

A small loopback tool for actual humans to label finding claims beside frozen code evidence. No dependencies, model calls, public hosting, source-file browsing, or recommended labels. Canon v0.26.2 supplied and digest-verified by the coordinator: evidence before label [HAI-01], designed unknown [CAL-02/RLSE-04], scoped controls [INT-03], visible completion [INT-05], minimal required fields [FORM-01], and contrast [A11Y-01]. The pinned macOS canon is unavailable on this remote VM; this source uses the supplied verified evidence, not another checkout as row-text authority. The supplied CARD-18 verification concerns image claims and is not triggered by this text/code interface; CARD-19 introduces no generation stage here. CARD-03 applies to explicit missing evidence and pending QC.

## Start and resume

```sh
python benchmarks/tools/evalops/label_ui.py serve --packet /private/reviewer-public-packet.json --state-dir /private/reviewer-state --role reviewer --port 0
```

Open the printed `http://127.0.0.1:PORT` URL. Enter your actual name, read the visible rubric, and review each claim and its frozen source. Choose **Defect**, **Not a defect**, or **Need more context**; notes are optional. No new item has a selected label. Missing source has an explicit state. Save judgment and continue durably saves before advancing. Previous and Skip preserve drafts within the tab; Skip records no event. Unsaved drafts do not survive closing the tab, and a close warning protects them. Failed saves retain their retry ID and payload. If you edit after a failure, the next save first resolves that original request, then asks you to save the retained correction.

Stop with Ctrl-C. Resume with the same command, packet, role and state directory. Saved identity and answers resume; the first unanswered item opens. Use Previous or Review from beginning to correct an answer. Corrections append events and reference the superseded event; original events remain. Export my judgments downloads this session's sanitized JSONL history, including corrections. Completion reports saved/unanswered counts and **reference QC pending**, never quality acceptance.

A directory belongs to one human identity, role and frozen public packet digest. Use a new directory for another human, role or packet. Identity cannot change after starting. Keep the directory on a private local filesystem; do not manually edit its files. Startup refuses an exclusive-lock conflict, invalid metadata, truncated/corrupt logs or packet/role mismatch. Back up logs before investigating failures; never repair history by guessing labels. A storage failure requires stopping and restarting; retain the browser draft.

## Independent expert and offline coordination

The coordinator supplies the reviewer public packet. A separate expert curator independently launches the same command with `--role expert`, a **separate expert public packet file**, and a **separate state directory**, preferably on a separate private machine/account. Never give the expert reviewer answers or a reviewer log, or give reviewers expert gold. Loopback access is not OS-user authentication: anyone with access to the same machine/browser session can view that session. Keep reviewer and expert sessions outside each other's access. Prior exposure cannot be undone by hiding fields later.

The server receives no private mapping. Packets contain only the public contract below. Offline repeat/gold assignments and original finding mappings stay with the coordinator. Each presentation uses an opaque ID, including repeats; no identifier should reveal task/model/severity/fix/outcome/gold/repeat membership. The validator can enforce shape and uniqueness, not the semantic opacity of coordinator-created IDs or independence of people.

**This UI does not supply independent humans or reference gold.** Those remain the user's blocker. It does not create hidden repeats, certify coverage, adjudicate labels or run quality acceptance. Independently sourced expert reference and QC decisions must be prepared and checked separately.

Read `benchmarks/tools/evalops/score_judge.py` before downstream scoring. UI exports are **raw human events, not findings-v0** and cannot be passed directly as scorer findings. The administrator joins completed HUMAN judgments (latest event per opaque presentation, with history retained) to the frozen private map and original seed offline, then constructs the scorer findings and QC files without guessing labels. `unclear` stays inconclusive, never a negative. The scorer documents QC requirements per annotator/field: at least 20 gold and 20 repeat decisions, each at least 10%, at least .90 gold accuracy and repeat agreement. Kappa is diagnostic only; the UI makes no QC or quality-acceptance claim.

## Frozen public packet

Schema: `evalops.label-packet.v1`; required packet fields are `packet_id`, `rubric_version`, `rubric`, and a nonempty `items` array. Each item requires `presentation_id`, `description`, and `context_status` (`verified_recorded_commit` or `unavailable`). Optional/null fields are `file_path`, `line_start`, `line_end`, and `source_context`; optional `context_note` is plain text. Verified context requires a nonempty frozen snippet; unavailable context requires null context. Coordinator verification establishes the recorded commit; the UI does not fetch source files or verify a commit. Unknown fields are discarded before state binding, HTTP and exports, rather than echoed. Never supply private mappings even though projection discards extra fields.

Synthetic **DEMO only** packet for UI QA (not human reference evidence):

```json
{"schema":"evalops.label-packet.v1","packet_id":"DEMO-only","rubric_version":"finding-rubric-v1","rubric":"DEMO: compare the synthetic claim with its code. Choose Need more context when evidence is insufficient.","items":[{"presentation_id":"demo-opaque-a","description":"DEMO claim: the function returns the wrong constant.","file_path":"demo.py","line_start":1,"line_end":2,"source_context":"def demo():\n    return 1","context_status":"verified_recorded_commit","context_note":"Synthetic frozen example; no real finding."},{"presentation_id":"demo-opaque-b","description":"DEMO claim with no available code.","file_path":null,"line_start":null,"line_end":null,"source_context":null,"context_status":"unavailable","context_note":"Synthetic missing-context case."}]}
```

Only DEMO synthetic packets may be used for automated/browser QA. Never inspect real human decisions through AI tooling. Test labels are synthetic fixtures, not human evidence.

## Local boundaries and limits

The CLI binds only IPv4 `127.0.0.1`, defaults to port 8765, and accepts port 0 to print the actual port. Only matching `127.0.0.1:PORT` or `localhost:PORT` Host headers are accepted. POST requires the matching HTTP Origin and session CSRF token; there is no CORS. Static assets use an exact whitelist, no external resources, textContent for all dynamic text, and a restrictive CSP. JSON rejects duplicate keys and nonfinite numbers. No client can supply a file path to read. This is a private local tool, not a multiuser service.

Limits: 8 MiB packet; 1–1,000 items; 128-character IDs/versions; 16,000-character rubric/claims; 64,000-character snippets; 1,024-character display paths; positive source line numbers up to 10,000,000; 100-character names; 4,000-character notes; 32 KiB request bodies; 50,000 events and 64 MiB log. Metadata uses atomic replacement and directory fsync; event acknowledgments follow fsync. State children must be regular files without symlinks/hardlinks, state paths cannot traverse symlinks, and the packet cannot live inside or alias a state child. Use a local filesystem supporting flock/fsync/atomic rename.

## Validation and remaining QA

Run `LC_ALL=C uv run --no-project --with pytest python -m pytest benchmarks/tests/test_evalops_label_ui.py -q -p no:cacheprovider`. Tests use synthetic packets and cover packet sanitization, missing context, identity/resume, fsync, retries/corrections, independent role/packet state, locks, corrupt logs, file collisions, and actual HTTP handler parsing for origin/CSRF/static boundaries. The remote sandbox forbids socket creation: HTTP tests use an in-memory transport, so live loopback binding is **not verified here**.

Coordinator browser QA remains pending: use only the DEMO packet to check desktop/narrow layout, keyboard and screen reader operation, no default selection, missing evidence, corrected labels, failed-save retry/draft preservation, reload/resume, completion/export and hostile text display. JavaScript syntax checks are not browser interaction evidence.
