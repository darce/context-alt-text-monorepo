VERDICT: REVISE
POR: {"file_count":25,"line_count":2498,"md5":"2a888d3474c132b440f6d14d48f09c02","sample_lines":{"41":" # Multi-environment deployment template for OCI VM.","173":" sections = [\"Compose\", \"Runtime mode\", \"Secret backend\", \"Postgres\", \"Database DSNs\", \"Face pipeline\", \"Cache directories\", \"Database pool tuning\", \"Worker behavior\", \"API security\", \"Operator /admin surface\", \"Image description\"]"}}

## Findings
- H-1 (HIGH): scripts/env/materialize.py:868 treats an empty assignment as a present required host secret. Failure: with `PGPASSWORD=` in the existing VM env file, apply preserves the empty value and returns 0 instead of refusing a missing required secret. Canon: CARD-07.
- H-2 (HIGH): scripts/env/materialize.py:878 excludes every managed key from `unmanaged` without reporting managed keys absent from `expected`. Failure: with an optional secret lacking a value for the selected env and a stale assignment still on disk, `--check` returns 0 even though apply would remove that assignment. Canon: CARD-07.

## Coverage
`scripts/env/manifest.py` patch lines 526-703: target metadata, host/vault source validation, derived vault map, and digest behavior.
`scripts/env/materialize.py` patch lines 704-920: lease and image locks, host secret selection, adoption backup, atomic owner-preserving writes, apply/check outcomes.
`scripts/env/materialize_remote.sh` patch lines 921-1011: caller contract, shell quoting, transfer statuses, and bounded SSH options.
`scripts/env/render_env.py` patch lines 1012-1178: host/vault rendering, runtime preflight, and materialize CLI dispatch.
`scripts/env/tests/test_em2f_host_secret.py` patch lines 1179-1337: required host-secret absence in render/check/apply.
`scripts/env/tests/test_em2f_lease_env.py` patch lines 1338-1435: lease path escape and symlink refusal.
`scripts/env/tests/test_em2f_remote_status.py` patch lines 1436-1580: SSH timeouts and producer-versus-SSH failures.
`scripts/env/tests/test_harden_render.py` patch lines 1581-1721: adoption backups and runtime unmanaged-key behavior.
`scripts/env/tests/test_materialize.py` patch lines 1722-1975: apply, check drift, leases, locks, adoption, modes, and ownership.
`scripts/env/tests/test_secret_resolvers.py` patch lines 2207-2229: newline-only keychain output rejection.
`scripts/env/tests/test_vm_manifest.py` patch lines 2230-2498: remote target and secret-reference validation.
