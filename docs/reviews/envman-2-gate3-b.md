VERDICT: REVISE
POR: {"file_count":26,"line_count":2663,"md5":"4d414f6c4163348546ad207f223e4c41","sample_lines":{"41":" # Multi-environment deployment template for OCI VM.","173":" sections = [\"Compose\", \"Runtime mode\", \"Secret backend\", \"Postgres\", \"Database DSNs\", \"Face pipeline\", \"Cache directories\", \"Database pool tuning\", \"Worker behavior\", \"API security\", \"Operator /admin surface\", \"Image description\"]"}}

## Findings
- M-1 (MEDIUM): infra/oci/demo/bootstrap-wp.sh:446 Applying the strict dotenv decoder to every value now rejects literal credentials containing `$` or backslash. Failure: `WP_ADMIN_PASSWORD='p$ss'` is a valid single-quoted Compose dotenv value, but `acx_env_literal_value` rejects `$`; with `set -e`, `env_get` exits nonzero and bootstrap stops before reconciling the WordPress account. Canon: TEST-15.

## Coverage
- `apps/prototype-description-service/.env.example`, `.env.fir.example`, `.env.prod.example` patch lines 4-45: generated digests and auth annotation.
- `config/env/manifest.d/10-service-shared.toml` patch lines 46-85: host refs for shared VM secrets.
- `config/env/manifest.d/21-service-vm.toml` patch lines 86-98: image-description host ref.
- `config/env/manifest.d/40-demo.toml` patch lines 99-153: demo host refs.
- `config/env/manifest.d/targets.toml` patch lines 154-195: remote paths, preserved key, leases, and template docs.
- `docs/plans/0004-envman-2-vm-env-materializer-task-plan.md` patch lines 196-403: design and interface contract, skimmed for cross-checks.
- `docs/runbooks/env-manifest.md` patch lines 404-428: Keychain service examples.
- `infra/oci/demo/.env.example` patch lines 429-439: generated digest.
- `infra/oci/demo/bootstrap-wp.sh` patch lines 440-461: dotenv value decoding and bootstrap use.
- `infra/oci/demo/tests/test-credential-lifecycle.sh` patch lines 462-495: quoted-password behavior test skimmed.
- `mk/env.mk` patch lines 496-525: materialize arguments and safety gates.
- `scripts/env/materialize_remote.sh` patch lines 937-1024: manifest lookup, shell quoting, tar/SSH status handling.
- `scripts/env/tests/test_materialize_remote.py` patch lines 2141-2370: argv, mode, failure, tar, and make behavior tests skimmed.
- `scripts/env/manifest.py`, `scripts/env/render_env.py`, and `scripts/env/materialize.py` patch lines 526-932 and 1025-1210: caller/callee contract only.
