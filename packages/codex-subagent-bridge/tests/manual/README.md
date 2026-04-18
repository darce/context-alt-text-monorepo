# Manual Codex probes

Ad-hoc harnesses that drive the packaged Codex app-server over stdio JSON-RPC.
They are NOT part of the pytest suite — each one shells out to a live Codex
binary and is intended for re-verifying protocol surfaces during discovery
work.

## E17-12 skill-registration probes

Written for the E17-12 Slice 1 discovery pass (see
[docs/assessments/e17-12-codex-skill-registration-discovery-2026-04-18.md](../../../../docs/assessments/e17-12-codex-skill-registration-discovery-2026-04-18.md)).

| Script | Purpose |
|---|---|
| `e17-12-probe.py` | Baseline `skills/list`; `perCwdExtraUserRoots` as map (rejected); `skills/config/write` on a SKILL.md path. |
| `e17-12-probe2.py` | Disambiguates the 4 candidate shapes for `perCwdExtraUserRoots`; only shape C `[{cwd, extraUserRoots}]` is accepted. |
| `e17-12-probe3.py` | Persistence test — confirms `perCwdExtraUserRoots` is per-call, and `skills/config/write` toggles enabled-state only. |
| `e17-12-probe4.py` | Project-scope scan test — creates `<repo>/.codex/skills/probe-test/SKILL.md` and confirms Codex natively returns it with `scope: "repo"`. |

Run from the repo root with the `codex-subagent-bridge` package importable:

```bash
python3 packages/codex-subagent-bridge/tests/manual/e17-12-probe4.py
```

Each probe resolves `REPO` from its own path
(`Path(__file__).resolve().parents[4]`) so they can be copied into another
worktree without edits.
