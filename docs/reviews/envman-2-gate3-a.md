VERDICT: REVISE
POR: {"file_count":26,"line_count":2663,"md5":"4d414f6c4163348546ad207f223e4c41","sample_lines":{"41":" # Multi-environment deployment template for OCI VM.","173":" sections = [\"Compose\", \"Runtime mode\", \"Secret backend\", \"Postgres\", \"Database DSNs\", \"Face pipeline\", \"Cache directories\", \"Database pool tuning\", \"Worker behavior\", \"API security\", \"Operator /admin surface\", \"Image description\"]"}}

## Findings
- M-1 (MEDIUM): scripts/env/render_env.py:1129 Rejecting any existing adoption backup makes interruption recovery non-idempotent. Failure: if materialization crashes after publishing `<path>.pre-envman` at `materialize.py:918` but before replacing `<path>` at `materialize.py:919`, retrying the same `--adopt` sees the unchanged unheaded file plus its valid backup and returns 2 instead of converging. Canon: RES-19.
- M-2 (MEDIUM): scripts/env/manifest.py:579 Target validation checks only that `lease_env` keys have remote paths, leaving its values unchecked until `_lease_path`. Failure: `lease_env = {dev = "bad label"}` with a matching `remote_paths.dev` passes `load_manifest`; render/check accept the manifest but materialization later rejects it with status 2. Canon: rg-008.

## Coverage
- `scripts/env/manifest.py` patch lines 526-703: manifest loading, remote-source validation, vault mapping and digest.
- `scripts/env/materialize.py` patch lines 704-936: lock and lease lifecycle, required host-secret checks, drift outputs, owner/mode preservation, backup and replacement.
- `scripts/env/materialize_remote.sh` patch lines 937-1027: argument handling, SSH command quoting/options, tar streaming and producer/SSH status.
- `scripts/env/render_env.py` patch lines 1028-1194: host/vault rendering, runtime preflight/adoption, CLI dispatch and checks.
- `scripts/env/tests/test_em2f_gate2_secrets.py` patch lines 1195-1343: empty required host-secret and stale managed-key drift regressions.
- `scripts/env/tests/test_em2f_host_secret.py` patch lines 1344-1502: host-secret manifest, CLI and materializer behavior.
- `scripts/env/tests/test_em2f_lease_env.py` patch lines 1503-1600: lease escape and symlink refusal.
- `scripts/env/tests/test_em2f_remote_status.py` patch lines 1601-1745: SSH bounds and producer/SSH failure status.
- `scripts/env/tests/test_harden_render.py` patch lines 1746-1886: adoption backup collision, unmanaged keys and runtime rendering.
- `scripts/env/tests/test_materialize.py` patch lines 1887-2140: apply/check behavior, locks/leases, modes, ownership and unmanaged keys.
- `scripts/env/tests/test_materialize_remote.py` patch lines 2141-2371: wrapper/Make forwarding, archive contents and exit handling.
- `scripts/env/tests/test_secret_resolvers.py` patch lines 2372-2394: newline-only keychain output rejection.
- `scripts/env/tests/test_vm_manifest.py` patch lines 2395-2663: remote metadata and vault/host reference validation.
