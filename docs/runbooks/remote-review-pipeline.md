# Explicit remote review packet

Owner: EVALOPS-1 coordinator. Tool: `scripts/review/build_review_packet.py` (stdlib).
This wraps the existing deterministic review pipeline; a remote review alone cannot
authorize a merge (prior art decisions20545/17577, IDWEAVE-1). Only successful
`review-adjudicate` followed by `merge-gate` establishes pipeline acceptance. The
tool never merges. The coordinator owns integration, lifecycle and authoritative
review; this source lane's fake-transport tests are bounded smoke evidence.

The measured delay was review-pass → merge (5h), versus implementation (6–10min).
Automating the missing pipeline artifact targets that constraint: **Improve the
measured constraint** [OPS-75], *The DevOps Handbook*, ch. 2. Store and test this
shared procedure: **Make repeatable guidance executable** [TEAM-42], same source,
ch. 20. Canon v0.26.2, pinned read-only release, all 53 manifest digests verified.

## Transport configuration

Prerequisites: POSIX Python, Git, registered review worktree support, installed
WorkBay Make targets and an authenticated remote adapter. This source archive does
**not** ship `Makefile.d`, `scripts/review_pipeline.py`, `scripts/remote_agent.sh`
or its spec builder. Tests use executable fakes implementing the coordinator's
verified CLI. They do not establish live adapter compatibility or acceptance.
Do not reinstall Grok or modify managed payloads/hooks to run this wrapper.

Use an agent-spec produced/accepted by your installed adapter as the template.
Keep its actual schema, executable, routing and output settings; replace values
with these literal placeholders *inside JSON strings*:

| Placeholder | Meaning |
| --- | --- |
| `{backend}`, `{model}`, `{effort}`, `{speed}` | Explicit requested selection |
| `{brief}` or `{brief_text}` | Absolute brief file path, or its complete text |
| `{worktree}` | Absolute registered review worktree |
| `{doc}` | Relative output review document path in that worktree |

Every routing placeholder and both output placeholders are required; choose at
least one brief placeholder. Fields can occur within longer strings. The wrapper
JSON-escapes substituted values; it does not invent adapter fields or launch flags.
The adapter must read that brief, use that selection, and materialize exactly one
new review document at `{worktree}/{doc}` before returning success. A script that
returns a remote artifact elsewhere needs its existing retrieval configuration
set accordingly. Check the installed adapter/spec builder's real contract first.
The supplied template and argv are trusted operator configuration; the wrapper
binds requested routing, but cannot prove a provider honored it.

From the repository root, after saving that real template and selected prior art:

```sh
mkdir -p .task-state/review-config
# Save the adapted real spec as .task-state/review-config/spec-template.json.
# Save selected context/prior art as .task-state/review-config/context.txt.
python3 - <<'PY'
import json
from pathlib import Path
root = Path.cwd()
config = {
    "argv": [str(root / "scripts/remote_agent.sh"), "--agent-spec", "{agent_spec}"],
    "agent_spec_template": "spec-template.json",
}
(root / ".task-state/review-config/transport.json").write_text(json.dumps(config, indent=2))
PY
python3 scripts/review/build_review_packet.py check \
  --repo "$PWD" --subject feature/foo --slug foo --rev 1 \
  --packet "$PWD/.task-state/review-foo-r1" \
  --config .task-state/review-config/transport.json \
  --context .task-state/review-config/context.txt
```

`check` (or `--dry-run`) reads inputs and prints routing and planned commands;
it writes nothing, calls no Make primitive, and spends nothing. It checks local
executables, not authentication or an actual provider invocation. Change `check`
to `prepare` to run `make review-stage SUBJECT=feature/foo SLUG=foo REV=1` and
persist the packet. `--rev-worktree /absolute/path` forwards `REV_WORKTREE` only.
`review-stage` has no backend/model flags. Default routing is **codex-remote,
gpt-6.1-sol, xhigh, fast**, independent of this implementation source's high effort.

With the same arguments, use `resume` to authorize the first remote spend from a
prepared packet, then harvest, adjudicate and gate. `execute` combines preparation
and that spend in one invocation. Review 2 uses `--rev 2` and a new packet/doc;
the coordinator enforces at most two rounds across packets. Explicit adjudication
routing requires both `--backend claude-remote --model claude-opus-5-5` (xhigh,
fast). Do not silently route real gate defects to another model. The managed
`review-adjudicate` primitive remains separate from any model-based adjudication.

To reuse an already staged subject, capture the existing `make review-stage`
JSON stdout in an ignored file, then use `staged --stage-json /absolute/stage.json`
with a **new** packet directory and the same subject/slug/revision/config/context.
This validates the committed patch and prepares inputs without restaging or
spending. `resume` then executes the remaining steps. Imported receipts record
the source JSON and its SHA256; they do not claim to have executed the external
stage command. Preserve the external command log separately.

## Evidence and recovery

Named outputs form explicit data edges: committed patch → brief/spec → review doc
→ harvest → adjudication artifact → gate. **An edge exists only where data moves**
[GRPH-32] and **A node without a contract cannot be parallelised** [GRPH-33],
practice labels. The wrapper validates stage JSON, Git bindings and the reviewer
document. It does not implement a competing adjudication policy.

The first review line must be `VERDICT: MERGE` or `VERDICT: REVISE`, followed by
exactly one `POR: ` JSON line. The brief describes proof derivation but never
supplies expected values or reads/copies the dispatcher's sidecar. Proof uses
exact patch-byte MD5, UTF-8 `splitlines()` count, `+++ ` file count, and string
line-number keys in `sample_lines`. **Correction:** take nonblank lines 41 and
173 only when present, without clamping; fill from nonblank lines starting at
line 1, deduplicating (number,text) pairs until two or exhaustion. Real
MEDIUM/LOW findings do not invent a blocker; HIGH/CRITICAL/BLOCKING are the
existing blocking severities. The pipeline decides acceptance.

`receipt.json` preserves subject tip/tree, integration tip/tree, merge base,
staged commit/worktree, patch SHA256, requested routing, input hashes, exact
executed argv/cwd, per-step exit/outcome, logs and output artifact paths. Resume
preserves previous sections (decision20546), checks freshness and input hashes,
and refuses changed subject/integration tips or malformed proof. Git patch
formatting belongs to the stage producer; validation compares the file with its
committed bytes, without assuming unverified producer diff flags.

Transport nonzero exit, missing executable, timeout or interruption fails loudly
and leaves the attempt in the receipt: **Degrade loudly** [AGT-10], *The Art of
UNIX Programming*, ch. 1. Per-step timeout defaults to 900s (maximum 1800s); a
timeout kills the transport process group. Resume **never redispatches** an
attempted model call. Inspect the adapter's status/output first. If a lost
response left the complete document locally, `resume --recover-doc` explicitly
permits validating it; the failed transport remains recorded. No valid local
document means manual recovery, not an invented verdict or automatic retry.

Failed/interrupted harvest or staging requires manual reconciliation and a new
packet if necessary; no automatic repeat of commits. Failed adjudication/gate can
resume without another model call. Successful steps are reused; a completed
packet's resume revalidates its document and rechecks the cheap gate. Preserve
all operator data and packets, including failed receipts. Roll code back by
reverting its commit; no retention deletion or deployment belongs to this tool.

Scoped validation (no new dependencies or unrelated suites):

```sh
LC_ALL=C uv run --no-project --with pytest python -m pytest scripts/review/test_build_review_packet.py -q -p no:cacheprovider
```
