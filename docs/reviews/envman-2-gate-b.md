VERDICT: REVISE
POR: {"file_count":22,"line_count":2035,"md5":"ece5e5b48f8111b955ea4de9e04717df","sample_lines":{"41":" # Multi-environment deployment template for OCI VM.","173":" sections = [\"Compose\", \"Runtime mode\", \"Secret backend\", \"Postgres\", \"Database DSNs\", \"Face pipeline\", \"Cache directories\", \"Database pool tuning\", \"Worker behavior\", \"API security\", \"Operator /admin surface\", \"Image description\"]"}}

## Findings
- H-1 (HIGH): scripts/env/materialize_remote.sh:961 The wrapper discards the local tar producer's exit status and returns only SSH's status. Failure: with `ENV_MANIFEST_ROOT` pointing to a valid manifest directory containing an unreadable extra file after `manifest.d`, the packer can emit the complete manifest and then fail on that file; the remote tar and materializer can still succeed, so `make env-materialize` exits 0 despite the packaging error. Canon: CARD-07.
- M-1 (MEDIUM): scripts/env/materialize_remote.sh:949 SSH has no bounded connection or session timeout. Failure: if the configured host blackholes SSH traffic, `make env-materialize` waits on the network without a lane-level deadline and cannot report a terminal result promptly. Canon: RES-02.

## Coverage
- `apps/prototype-description-service/.env.example` patch lines 4-14: generated digest update.
- `apps/prototype-description-service/.env.fir.example` patch lines 15-34: generated digest and auth documentation update.
- `apps/prototype-description-service/.env.prod.example` patch lines 35-45: generated digest update.
- `config/env/manifest.d/10-service-shared.toml` patch lines 46-85: shared VM host-secret refs.
- `config/env/manifest.d/21-service-vm.toml` patch lines 86-98: GPU endpoint secret ref.
- `config/env/manifest.d/40-demo.toml` patch lines 99-153: demo host-secret refs.
- `config/env/manifest.d/targets.toml` patch lines 154-195: remote paths, preserved key, lease environments, and FIR auth text.
- `docs/plans/0004-envman-2-vm-env-materializer-task-plan.md` patch lines 196-403: design, interface, rollout, and verification skim.
- `docs/runbooks/env-manifest.md` patch lines 404-428: Keychain command documentation.
- `infra/oci/demo/.env.example` patch lines 429-439: generated digest update.
- `infra/oci/demo/bootstrap-wp.sh` patch lines 440-461: dotenv literal decoding in `env_get`.
- `infra/oci/demo/tests/test-credential-lifecycle.sh` patch lines 462-495: quoted-password credential test skim.
- `mk/env.mk` patch lines 496-525: `env-materialize` target and production confirmation.
- `scripts/env/materialize_remote.sh` patch lines 893-964: local manifest resolution, shell quoting, tar/SSH stream, and exit propagation.
- `scripts/env/tests/test_materialize_remote.py` patch lines 1520-1743: mode forwarding, SSH argv/stdin, refusal, status, and make-target test skim.
