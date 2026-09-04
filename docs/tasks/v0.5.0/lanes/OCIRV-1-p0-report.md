# OCIRV-1 P0 deploy test gate report

## Change summary

- Added a credential-handling contract gate to
  `.github/workflows/deploy-recognition.yml`. It checks out the repository,
  selects Python 3.12, installs only `pytest` and `pyyaml`, and runs
  `make test-deploy-contract` on `ubuntu-latest` with a 10-minute timeout.
- Made `deploy` depend on `gate`, so both push and `workflow_dispatch` runs are
  blocked when the contract gate fails. The gate has no GitHub Environment,
  tailnet step, Docker dependency, or secrets; the existing concurrency,
  permissions, and 45-minute deploy timeout are unchanged.
- Added push path coverage for `scripts/test_ocirv1_vault_readiness.py`,
  `scripts/deploy/tests/**`, and the root `Makefile`.
- Added `scripts/test_deploy_workflow_gate.py` to enforce the workflow structure
  and prove with `make -n` that the Make target retains both credential suites.
- Updated the CI/CD runbook's trigger table and documented the test gate.
- Python 3.12 is consistent with the root pin: `pyproject.toml:7` requires
  `>=3.12` and `pyproject.toml:26` sets Ruff's target to `py312`; the service's
  `.python-version` pins `3.12.7`. Imports in the four pytest files were
  inspected before implementation; only `pytest` and `yaml` are third-party
  imports.
- Follow-up review aligned workflow commentary and the runbook with Vault-backed
  OCIR authentication and the actual Free-plan `PROMOTE` production control.
  Cached Docker-login setup and the nonexistent required-reviewer pause were
  removed from the operator instructions.

## RED evidence

The structural test was written and run before editing the workflow.

Command:

```text
git switch -c feature/ocirv-1-p0 && lane_root="$(git rev-parse --show-toplevel)"; if [ -x "$lane_root/.venv/bin/python" ]; then resolved_python="$lane_root/.venv/bin/python"; else resolved_python="$(command -v python3)" || { echo 'python3 is unavailable' >&2; exit 1; }; fi; "$resolved_python" -m pytest scripts/test_deploy_workflow_gate.py -q
```

Tail:

```text
FAILED scripts/test_deploy_workflow_gate.py::test_deploy_needs_contract_gate
FAILED scripts/test_deploy_workflow_gate.py::test_contract_gate_is_isolated_and_bounded
FAILED scripts/test_deploy_workflow_gate.py::test_push_paths_cover_the_gate_inputs
3 failed, 1 passed in 1.15s
```

The passing test was the pre-existing Makefile expansion assertion, while the
three failures identified the absent gate and missing trigger paths.

## tests_run

1. Structural regression test:

   ```text
   python3 -m pytest scripts/test_deploy_workflow_gate.py -q
   ....                                                                     [100%]
   4 passed in 0.42s
   ```

2. PyYAML parse check:

   ```text
   python3 -c 'import yaml; yaml.safe_load(open(".github/workflows/deploy-recognition.yml", encoding="utf-8")); print("workflow YAML parsed")'
   workflow YAML parsed
   ```

3. Local Actions runner availability:

   ```text
   if command -v act >/dev/null 2>&1; then echo "act available at $(command -v act)"; else echo "act unavailable; structural validation only"; fi
   act unavailable; structural validation only
   ```

   Per the lane instructions, the workflow was not executed locally.

4. Full command used by the CI gate:

   ```text
   make test-deploy-contract
   ........................................................................ [ 75%]
   .......................                                                  [100%]
   95 passed in 2.14s
   ...
   all assertions passed
   ...
   all assertions passed
   ```

5. Targeted lint and format checks:

   ```text
   python -m ruff check scripts/test_deploy_workflow_gate.py
   All checks passed!
   python -m ruff format --check scripts/test_deploy_workflow_gate.py
   1 file already formatted
   ```

6. Patch whitespace validation:

   ```text
   git diff --check
   (no output; exit 0)
   ```

## Mutants

Workflow mutants were applied temporarily to the lane-owned workflow and then
restored. The Makefile mutant used an isolated copy under `/tmp`, so no frozen
source outside this lane's ownership was changed.

### A. Remove the deploy dependency — KILLED

Diff:

```diff
   deploy:
-    needs: gate
     runs-on: ubuntu-latest
```

Tail:

```text
E       AssertionError: deploy must depend on the deploy-contract gate
E       assert 'gate' in []
FAILED ...::test_deploy_needs_contract_gate
1 failed in 0.11s
```

### B. Replace the contract target with app-only `make test` — KILLED

Diff:

```diff
       - name: Run deploy-contract tests
-        run: make test-deploy-contract
+        run: make test
```

Tail:

```text
E       AssertionError: workflow must run make test-deploy-contract before deploying
E       assert []
FAILED ...::test_deploy_needs_contract_gate
1 failed in 0.19s
```

### C. Drop `test-ocir-auth.sh` from the Make target — KILLED

Diff:

```diff
 test-deploy-contract:
     @python3 -m pytest ... scripts/test_ocirv1_vault_readiness.py -q --tb=short
     @bash scripts/deploy/tests/test-smoke-gate.sh
-    @bash scripts/deploy/tests/test-ocir-auth.sh
```

Tail:

```text
E       AssertionError: assert 'test-ocir-auth.sh' in 'python3 -m pytest ...'
FAILED ...::test_make_target_keeps_credential_suites
1 failed in 0.30s
```

No mutants survived.

## Blockers

None for the lane-owned workflow, test, and runbook scope. `act` is not
installed, so validation used the required structural test, an explicit PyYAML
parse check, and the complete Make target.

## Finding references

See `OCIRV1-H-01`, `OCIRV1-H-02`, `OCIRV1-H-03`, `OCIRV1-H-04`,
`OCIRV1-M-05`, `OCIRV1-M-06`, `OCIRV1-M-07`, `OCIRV1-L-07`, and
`OCIRV1-L-08` in the handoff store.
