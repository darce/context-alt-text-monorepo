Verdict: fail. The prose compatibility behavior passes isolated checks, but the
manifest reader violates the required fallback for non-release documents. The
required test suite was attempted and blocked before collection by dependency
download failure, so this review cannot certify a green gate.

```FINDINGS
[
  {
    "id": "LEXG-01",
    "severity": "medium",
    "file": "apps/prototype-description-service/scripts/eval_harness/depiction_lexicon.py",
    "line": 274,
    "summary": "A non-release JSON document overrides Git provenance whenever its version looks numeric. The reader never checks the release schema. In a temporary real Git repository tagged legacy-tag, a manifest containing {\"schema\":\"unrelated/document@1\",\"version\":\"9.9.9\"} produced canon v9.9.9 instead of canon legacy-tag; a schema-less version object did the same. The positive test at test_depiction_lexicon.py:246 uses that schema-less shape, and the negative cases omit non-release documents with valid-looking versions, so they do not catch this contract violation.",
    "fix": "Check the supported heuristics-canon release schema identifier before accepting a manifest version; documents with missing or unrelated schema identifiers must take the existing Git fallback. Update the positive fixture to represent a heuristics-canon/release@5 manifest and add negative controls for missing and unrelated schemas carrying valid-looking versions. Retain the malformed-JSON and invalid-version controls."
  }
]
```

Scope and identity: reviewed the two subject files without modifying them. The
sandbox has stripped history (HEAD ca7a67afcdf03e612bb812a00a91967301407f8b),
so the supplied base/tip commits cannot be independently resolved here. The loader
bytes match the bakeoff pin exactly:
`4ac52b4f22fb426eb10067a6cb465f310c9240989166fd395b11b0a491079f68`.
The supplied diff was used to distinguish the change from pre-existing behavior.

Verification:

- Required command: `uv run --directory apps/prototype-description-service pytest scripts/eval_harness/tests/test_depiction_lexicon.py -q`.
  Exit code **1**, before test collection: `uv` failed to download
  `scikit-learn==1.8.0` from files.pythonhosted.org after three retries because
  DNS resolution failed. No passing pytest result is claimed and no alternative
  test suite was run.
- The lane-root `.venv/bin/python` imported
  `scripts.eval_harness.depiction_lexicon` from this worktree before verification.
  Direct, isolated checks through `load_depiction_lexicon` confirmed the prose
  Trigger/body/empty-why projection, preservation of the full body in the rendered
  prompt, rejection of empty prose triggers, rejection of empty arrow actions,
  and rejection of rows before a family heading.
- A temporary real Git repository, without subprocess stubs, confirmed malformed
  JSON falls back to `canon legacy-tag`, a release-schema version fixture yields
  `canon v0.26.2`, and the two non-release cases in LEXG-01 incorrectly override
  the tag. These local probes completed with exit code **0**; they do not replace
  the blocked pytest suite.
- Inspection confirms the new prose branch still passes through the existing
  `_clean` processing for Rule and Trigger cells. Cross-lexicon-tail removal,
  markdown cleanup, and the heading guard remain in the parser; their existing
  pytest controls exercise real parsing/rendering rather than stubbing it. The
  version fallback tests stub Git, while the positive version test exercises real
  file loading. The suite could not execute in this environment.

Canon availability: the pinned read-only checkout at
`/Users/daniel/Development/heuristics-canon-current` is unavailable, as the brief
anticipates. Its AGENTS.md, release-manifest digests, cards, and actual ATTRIB-03
row could not be inspected; no canon-card verification or real-canon parse is
claimed. Release **0.26.2** and schema `heuristics-canon/release@5` are taken from
the authoritative brief. Probe rows are synthetic, not reconstructed canon text.

Disposition: apply LEXG-01 in a lane authorized to edit the subject files, then
rerun the required test command in an environment with the dependencies available.
The existing unrelated `uv.lock` modification was left untouched.
