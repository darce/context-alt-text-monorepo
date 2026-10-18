VERDICT: REVISE
POR: {"file_count":22,"line_count":2035,"md5":"ece5e5b48f8111b955ea4de9e04717df","sample_lines":{"41":" # Multi-environment deployment template for OCI VM.","173":" sections = [\"Compose\", \"Runtime mode\", \"Secret backend\", \"Postgres\", \"Database DSNs\", \"Face pipeline\", \"Cache directories\", \"Database pool tuning\", \"Worker behavior\", \"API security\", \"Operator /admin surface\", \"Image description\"]"}}

## Findings
- H-1 (HIGH): scripts/env/materialize.py:834 interpolates the unchecked `lease_env` value into a privileged lease path. Failure: `lease_env = { dev = "../../../../../../tmp/marker" }` can make apply replace `/tmp/marker.lease` outside the backup root. Canon: rg-008.
- H-2 (HIGH): scripts/env/render_env.py:1015 silently omits a `host:` secret when `host_lines` is absent, and manifest validation at patch line 644 allows that source on backend targets without a remote path. Failure: a target with `path = "runtime.env"` and a required `secret = { dev = "host:" }` can render for `dev`, omit the key, and exit 0. Canon: CARD-07.

## Coverage
`scripts/env/manifest.py` patch lines 526-701: target and variable schema, remote-source validation, vault mapping, target digest.
`scripts/env/materialize.py` patch lines 702-892: lock and lease handling, atomic owner-preserving writes, apply and check drift behavior, exit codes.
`scripts/env/render_env.py` patch lines 965-1124: host and vault rendering, runtime preflight and adoption, CLI dispatch.
`scripts/env/tests/test_harden_render.py` patch lines 1125-1265: adoption backup refusal and unmanaged-key behavior.
`scripts/env/tests/test_materialize.py` patch lines 1266-1519: apply, lease, lock, check, mode, and ownership behavior.
`scripts/env/materialize_remote.sh` patch lines 893-964: caller contract, quoted SSH arguments, remote extraction and command execution.
`scripts/env/tests/test_materialize_remote.py` patch lines 1519-1743: wrapper modes, SSH status propagation, and Make entry point coverage.
`scripts/env/tests/test_secret_resolvers.py` patch lines 1744-1766: newline-only keychain output refusal.
`scripts/env/tests/test_vm_manifest.py` patch lines 1767-2035: remote path, preserve, secret-ref, and vault-map validation cases.
