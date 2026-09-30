```json
{
  "verdict": "fail",
  "findings": [
    {
      "id": "EM2PR-01",
      "severity": "high",
      "canon": "WEB-16",
      "file": "docs/plans/0004-envman-2-vm-env-materializer-task-plan.md",
      "line": 42,
      "summary": "The authoritative D-5 text contradicts its key-only promise by requiring differing managed values to be printed.",
      "failure_scenario": "A prod POSTGRES_DSN or RECOGNITION_ADMIN_TOKEN differs during --check, and an implementation follows the value-printing clause, sending the secret to stdout or logs.",
      "fix": "Remove the value-printing requirement and specify that every drift report contains key names and metadata only."
    },
    {
      "id": "EM2PR-02",
      "severity": "high",
      "canon": "PG-09",
      "file": "docs/plans/0004-envman-2-vm-env-materializer-task-plan.md",
      "line": 37,
      "summary": "D-5 does not make incorrect .env permissions a check failure.",
      "failure_scenario": "A prod .env has correct keys and values but mode 0644; --check reports no key drift and exits 0, so the check-first rollout leaves database credentials readable beyond the owner.",
      "fix": "Include a 0600 mode check in --check and return drift when the existing file is not owner-only."
    },
    {
      "id": "EM2PR-03",
      "severity": "high",
      "canon": "CARD-10",
      "file": "docs/plans/0004-envman-2-vm-env-materializer-task-plan.md",
      "line": 80,
      "summary": "The promised owner and group preservation is not provided by the reused atomic writer.",
      "failure_scenario": "The existing VM .env is ubuntu:ubuntu and materialize runs under sudo; render_env.py's _atomic_write replaces it with a root:root tempfile, breaking the documented owner and group contract and user-level deploy access.",
      "fix": "Specify and test an owner-preserving atomic write path for materialize, including the adopted-file backup."
    },
    {
      "id": "EM2PR-04",
      "severity": "medium",
      "canon": "CARD-01",
      "file": "docs/plans/0004-envman-2-vm-env-materializer-task-plan.md",
      "line": 70,
      "summary": "The loader does not require the two Vault secrets the service fetches at boot.",
      "failure_scenario": "A target maps only ACX_GPU_ENDPOINT_API_KEY to Vault and selects oci_vault; the generated map passes the stated loader rules but validate_oci_vault_boot fails before serving because PGPASSWORD and RECOGNITION_ADMIN_TOKEN are absent.",
      "fix": "Require each oci_vault target and environment to map PGPASSWORD and RECOGNITION_ADMIN_TOKEN before accepting the manifest."
    },
    {
      "id": "EM2PR-05",
      "severity": "medium",
      "canon": "CARD-01",
      "file": "docs/plans/0004-envman-2-vm-env-materializer-task-plan.md",
      "line": 121,
      "summary": "The rollout requires ADOPT=1, but the published make and remote-wrapper interfaces do not expose adoption.",
      "failure_scenario": "The first dev run passes ADOPT=1 to make env-materialize, but the variable is ignored and no --adopt reaches materialize; an existing unheaded .env is refused and rollout cannot proceed.",
      "fix": "Add ADOPT=1 to the make contract and specify that the wrapper forwards it as --adopt."
    },
    {
      "id": "EM2PR-06",
      "severity": "medium",
      "canon": "CON-11",
      "file": "docs/plans/0004-envman-2-vm-env-materializer-task-plan.md",
      "line": 107,
      "summary": "em2-frag shares targets.toml with em2-lows but has no explicit dependency on it.",
      "failure_scenario": "A dependency-driven scheduler starts em2-frag after em2-vault while em2-lows still has an open worktree; both edit targets.toml and merging the lane results conflicts or drops one lane's settings.",
      "fix": "Add em2-lows to em2-frag's dependencies or encode the wave barrier as an explicit DAG edge."
    }
  ]
}
```
