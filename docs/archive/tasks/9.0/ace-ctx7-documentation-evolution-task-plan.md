# ACE + ctx7 Documentation Evolution v9.0

## Purpose

This plan carries forward the remaining deferred and incomplete items from the 8.0 ACE + ctx7 documentation evolution task. The implementation work in 8.0 is complete; what remains here is follow-on scope that was intentionally deferred because it depends on environment-specific setup, separate rollout timing, or research validation.

## Deferred Scope

- [DEFERRED] Install portless locally.
- [DEFERRED] Configure portless service map.
- [DEFERRED] Verify portless resolves configured hostnames.
- [DEFERRED] Add portless installation and service map to `docs/agentic/BOOTSTRAP.md`.
- [DEFERRED] Replace `http://localhost:8000` in `class-abstract-recognition-proxy-controller.php` with the portless hostname.
- [DEFERRED] Update `class-admin.php` fallback warning to reference the portless hostname.
- [DEFERRED] Document portless service map alongside docker-compose port configuration.
- [DEFERRED] Replace remaining hardcoded `localhost:PORT` references in trimmed guideline files with portless `.localhost` hostnames.
- [DEFERRED] Verify portless resolves all configured service hostnames.
- [DEFERRED] Run a representative agent session with the trimmed guidelines to confirm no critical project-specific context was lost.
- [DEFERRED] Portless installed and service map configured; at least `backend.localhost` and `db.localhost` resolve.
- [DEFERRED] Hardcoded `localhost:PORT` references replaced with portless hostnames in at least PHP controller and admin warning.

## Stretch Goals

- [DEFERRED] ACE runtime evaluation: install the ACE library, implement a `HandoffDataProcessor`, run offline adaptation, and compare generated playbook deltas against the current regex-based reflection path.
- [DEFERRED] ACE online adaptation mode: evaluate live `ace_system.run(mode='online', ...)` during task execution.
- [DEFERRED] ACE `use_bulletpoint_analyzer` mode: evaluate whether ACE's built-in bullet-point analyzer improves strategy bullet structure.

## Follow-On Notes

- The 8.0 task completed the core ctx7 registration, guideline trimming, ACE playbook formatting, reflection hooks, metrics tooling, and ACE autorun trigger work.
- This 9.0 plan exists to hold only the deferred environment-specific and research-heavy items so they can be scheduled independently.
- Any future edits to the 9.0 plan should avoid reintroducing already-completed 8.0 implementation items.
