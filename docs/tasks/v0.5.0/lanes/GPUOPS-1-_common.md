## Rules that apply to every GPUOPS-1 lane

- Read `docs/tasks/v0.5.0/GPUOPS-1-gpu-operator-control-and-named-captions-task-plan.md` first. Contracts C1–C7 are frozen (GRPH-39). If your work needs a contract change, stop, write the reason in your report, and do not edit the contract.
- Edit only the files in your `owned_paths`. Another lane owns every neighbouring file; touching it creates a merge conflict the coordinator must resolve by hand.
- TDD: write the failing test first, make it pass, then refactor. Pin existing behaviour before changing it (TEST-03). Run only your lane's `test_commands`; unrelated suites may be red because another lane owns them.
- Never start, stop or query a live OCI instance, never ssh to a VM, never run terraform. Use fakes.
- Follow `CLAUDE.md` short rules: enums for status values (sr-007), no `assert` for runtime validation (sr-006), design tokens in CSS (sr-004), assertion helpers not `!` in TS (sr-005).
- Commit on your lane branch with a plain subject. No trailers, no attribution lines of any kind.
- Report: what changed, what the tests prove, anything you could not finish, and any contract question. Keep it under 1,500 characters.
- The remote sandbox has no network. `npm ci`, `npx`, and `composer install` will fail there. Write the tests anyway, run whatever tooling is present, and state exactly which commands you could not run; the coordinator runs vitest, tsc and phpunit locally before review. Python and shell checks are the verification surface in the sandbox.
