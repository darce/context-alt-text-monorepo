# Manual Codex probes

Ad-hoc harnesses that drive the packaged Codex app-server over stdio JSON-RPC.
They are NOT part of the pytest suite — each one shells out to a live Codex
binary and is intended for re-verifying protocol surfaces during discovery
work.

## Codex skill-registration probes

Originally written for the E17-12 Slice 1 discovery pass (see
[docs/assessments/e17-12-codex-skill-registration-discovery-2026-04-18.md](../../../../docs/assessments/e17-12-codex-skill-registration-discovery-2026-04-18.md)).

| Script | Purpose |
|---|---|
| `probe_skills_list_baseline.py` | Baseline `skills/list`; `perCwdExtraUserRoots` as map (rejected); `skills/config/write` on a SKILL.md path. |
| `probe_per_cwd_skill_root_shapes.py` | Disambiguates the 4 candidate shapes for `perCwdExtraUserRoots`; only shape C `[{cwd, extraUserRoots}]` is accepted. |
| `probe_skills_config_persistence.py` | Persistence test — confirms `perCwdExtraUserRoots` is per-call, and `skills/config/write` toggles enabled-state only. |
| `probe_project_scope_skill_scan.py` | Project-scope scan test — creates `<repo>/.codex/skills/probe-test/SKILL.md` and confirms Codex natively returns it with `scope: "repo"`. |

Run from the repo root with the `codex-subagent-bridge` package importable:

```bash
python3 packages/codex-subagent-bridge/tests/manual/probe_project_scope_skill_scan.py
```

Each probe resolves `REPO` from its own path
(`Path(__file__).resolve().parents[4]`) so they can be copied into another
worktree without edits.
