# VLM-6 lane `gx6` — whole-tree lane-report SHA guard EXIT:0 (docs only)

**Lane:** `gx6`  
**Branch:** `fix/gx6` (forked from `feature/vlm-6` @ `fc18e27d0ae6e882169eaeaa509c8dab2902b235`)  
**Scope:** `.s2a/` report prose only — no guard code, no tests, no application code.  
**Heuristics:** AUDIT-07, EVAL-23, rg-006, rg-015, sr-001.

> Before-guard stderr below names unresolvable sandbox/truncated tokens so the
> audit trail is concrete. Each deliberate foreign token carries nearest-token
> `sha-guard:ignore` (visible prose — not comment-hidden; S5-01 / S5-07).

## What changed

| File | Old text cited | New text says |
| --- | --- | --- |
| `.s2a/vlm6-fix-f2d-report.md:7` | comment quoted sandbox SHA `ac2740b` sha-guard:ignore | prose-only correction: lane wrote its own sandbox-clone SHA that does not exist here |
| `.s2a/vlm6-fix-f2e-report.md:7` | comment quoted sandbox SHA `a3ebb2f9` sha-guard:ignore | prose-only correction: lane wrote a sandbox-clone SHA that does not exist here |
| `.s2a/vlm6-fix-f3-report.md:153` | comment quoted sandbox SHAs `12b8cfd4` sha-guard:ignore and `d6340e99` sha-guard:ignore | prose-only correction: cited sandbox-clone SHAs that resolve nowhere here |
| `.s2a/vlm6-fix-f4-report.md:133` | comment quoted sandbox SHA `add1aeb8` sha-guard:ignore | prose-only correction: cited a sandbox-clone SHA and its own cat-file verification |
| `.s2a/vlm6-fx4-report.md:178` | truncated digest literal `859a083e` sha-guard:ignore | dropped truncated literal; operators must read digest from the artifact |
| `.s2a/vlm6-fx7-report.md:119` | truncated manifest digest `1209733e` sha-guard:ignore | **unchanged** (truncated prefix omitted; corpus body byte-identical) |
| `.s2a/vlm6-gx4-report.md:147–153` | seven truncated generator digests (`d105f3adccb2f574` sha-guard:ignore etc.) | each line now `match=True (truncated digest omitted; read from artifact)` |

**gx4 was not on the gx5 cross-lane list** (gx5 expected six violations). Live whole-tree run at lane start also failed on seven truncated content digests in the gx4 report's hashseed block. Same Class-2 failure mode as fx4/fx7 (bare truncated hex, no digest label). Fixed so whole-tree can exit 0 honestly — guard not weakened (sr-001).

Applied gx5-drafted prose-only replacements for the four comment-hidden sandbox SHAs and two truncated digests. Prefer prose over relocating tokens (a comment is invisible in rendered Markdown; the guard now refuses to vouch for comment-hidden hex either).

## Guard output

### Before (live at lane start)

```
Lane reports cite commits that do not exist in this repository:
  - .s2a/vlm6-fix-f2d-report.md:7: cited commit `ac2740b` sha-guard:ignore does not resolve — resolve it against `git log` in this worktree, or drop the citation (or add `sha-guard:ignore` on the nearest token if it is deliberately foreign)
  - .s2a/vlm6-fix-f2e-report.md:7: cited commit `a3ebb2f9` sha-guard:ignore does not resolve — resolve it against `git log` in this worktree, or drop the citation (or add `sha-guard:ignore` on the nearest token if it is deliberately foreign)
  - .s2a/vlm6-fix-f3-report.md:153: cited commit `12b8cfd4` sha-guard:ignore does not resolve — resolve it against `git log` in this worktree, or drop the citation (or add `sha-guard:ignore` on the nearest token if it is deliberately foreign)
  - .s2a/vlm6-fix-f3-report.md:153: cited commit `d6340e99` sha-guard:ignore does not resolve — resolve it against `git log` in this worktree, or drop the citation (or add `sha-guard:ignore` on the nearest token if it is deliberately foreign)
  - .s2a/vlm6-fix-f4-report.md:133: cited commit `add1aeb8` sha-guard:ignore does not resolve — resolve it against `git log` in this worktree, or drop the citation (or add `sha-guard:ignore` on the nearest token if it is deliberately foreign)
  - .s2a/vlm6-fx4-report.md:178: cited commit `859a083e` sha-guard:ignore does not resolve — resolve it against `git log` in this worktree, or drop the citation (or add `sha-guard:ignore` on the nearest token if it is deliberately foreign)
  - .s2a/vlm6-fx7-report.md:119: cited commit `1209733e` sha-guard:ignore does not resolve — resolve it against `git log` in this worktree, or drop the citation (or add `sha-guard:ignore` on the nearest token if it is deliberately foreign)
  - .s2a/vlm6-gx4-report.md:147: cited commit `d105f3adccb2f574` sha-guard:ignore does not resolve — resolve it against `git log` in this worktree, or drop the citation (or add `sha-guard:ignore` on the nearest token if it is deliberately foreign)
  - .s2a/vlm6-gx4-report.md:148: cited commit `1dea1f8d98bfb55d` sha-guard:ignore does not resolve — resolve it against `git log` in this worktree, or drop the citation (or add `sha-guard:ignore` on the nearest token if it is deliberately foreign)
  - .s2a/vlm6-gx4-report.md:149: cited commit `d2eeee5558f240e1` sha-guard:ignore does not resolve — resolve it against `git log` in this worktree, or drop the citation (or add `sha-guard:ignore` on the nearest token if it is deliberately foreign)
  - .s2a/vlm6-gx4-report.md:150: cited commit `1209733ed2b62e83` sha-guard:ignore does not resolve — resolve it against `git log` in this worktree, or drop the citation (or add `sha-guard:ignore` on the nearest token if it is deliberately foreign)
  - .s2a/vlm6-gx4-report.md:151: cited commit `a5264540eb1fe7aa` sha-guard:ignore does not resolve — resolve it against `git log` in this worktree, or drop the citation (or add `sha-guard:ignore` on the nearest token if it is deliberately foreign)
  - .s2a/vlm6-gx4-report.md:152: cited commit `fbea3c228f527d65` sha-guard:ignore does not resolve — resolve it against `git log` in this worktree, or drop the citation (or add `sha-guard:ignore` on the nearest token if it is deliberately foreign)
  - .s2a/vlm6-gx4-report.md:153: cited commit `6452cc66134ec07d` sha-guard:ignore does not resolve — resolve it against `git log` in this worktree, or drop the citation (or add `sha-guard:ignore` on the nearest token if it is deliberately foreign)

A lane's sandbox-clone SHA is not the SHA the work landed under. Use `git log --diff-filter=A -- <report>` to find the real one. Do not hide unresolvable tokens in HTML comments — quote them in visible prose with `sha-guard:ignore` on the nearest token if deliberately foreign.
EXIT:1
```

Note: live stderr had bare tokens without ignore markers; markers above are report-local only so this file does not re-fail the guard. Brief expected six violations; live tree also named seven gx4 truncated digests (gx4 already merged after gx5's list was written).

### After

```
lane report SHA citations: 47 file(s), 39 citation(s) resolved
EXIT:0
```

## Guard unit tests

Guard script and tests **unmodified**. Command (venv path from brief missing in this worktree; used sibling lane venv at same package path, also confirmed via system `python3 -m pytest`):

```
................                                                         [100%]
16 passed in 1.16s
```

## Confirmation — no hex in replacement text

Inspected every added/changed line via `git diff` against `\b[0-9a-fA-F]{7,40}\b`:

- f2d, f2e, f3, f4, fx4, fx7, gx4 replacements: **no hex token in any added line**.
- Replacements are prose-only (sandbox-clone wording) or "truncated prefix/digest omitted; read from artifact".
- No invented SHAs. No resolvable-but-wrong substitutions. No guard weakening, skip category, allow-list, or new ignore convention in owned report bodies (ignore markers appear only in this gx6 report's before-stderr audit quote, nearest-token, for deliberately foreign tokens).

## What you could not verify

- `apps/prototype-description-service/.venv/bin/python` does not exist in this worktree; unit tests run via `/home/ubuntu/lane-gx5/.../.venv/bin/python` and system `python3 -m pytest` — same 16 passed.
- `make context` unavailable (`No rule to make target 'context'`); MCP handoff not used — this report is the transport.
- Did not run `scene/tests/` (no application code changed; 27 known-red tests owned by other lanes are not this lane's signal).
- Did not re-verify that the dropped truncated digests still match on-disk artifacts byte-for-byte — operator instruction is to read digests from the artifact, which is correct because a truncated prefix cannot be verified anyway (EVAL-23 / AUDIT-07).
- Did not edit `scripts/check_lane_report_shas.py` or its tests (hard prohibition; sr-001).

## Landing note

Commits on `fix/gx6` only. No merge/rebase into `feature/vlm-6`. Coordinator integrates.
