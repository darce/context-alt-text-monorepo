VERDICT: MERGE
POR: {"file_count":25,"line_count":2498,"md5":"2a888d3474c132b440f6d14d48f09c02","sample_lines":{"41":" # Multi-environment deployment template for OCI VM.","173":" sections = [\"Compose\", \"Runtime mode\", \"Secret backend\", \"Postgres\", \"Database DSNs\", \"Face pipeline\", \"Cache directories\", \"Database pool tuning\", \"Worker behavior\", \"API security\", \"Operator /admin surface\", \"Image description\"]"}}

## Findings

- L-1 (LOW): `scripts/env/tests/test_materialize_remote.py`:2107 checks that the remote command contains cleanup tokens, but the ssh shim never runs that command. Failure: a broken `EXIT` trap that leaves the remote temporary directory behind still passes the test. Canon: TEST-15.

## Coverage

- `apps/prototype-description-service/.env.example` patch lines 4-14: generated header digest update.
- `apps/prototype-description-service/.env.fir.example` patch lines 15-34: generated digest and Auth-enabled documentation.
- `apps/prototype-description-service/.env.prod.example` patch lines 35-45: generated header digest update.
- `config/env/manifest.d/10-service-shared.toml` patch lines 46-85: host-only secret refs for shared VM vars.
- `config/env/manifest.d/21-service-vm.toml` patch lines 86-98: host-only GPU endpoint key ref.
- `config/env/manifest.d/40-demo.toml` patch lines 99-153: demo host-only secret refs.
- `config/env/manifest.d/targets.toml` patch lines 154-195: VM and demo paths, preserved key, lease mapping, and fir auth docs.
- `docs/plans/0004-envman-2-vm-env-materializer-task-plan.md` patch lines 196-403: skimmed design, pinned materializer/remote contracts, rollout, and verification plan.
- `docs/runbooks/env-manifest.md` patch lines 404-428: secret service variable and documented make invocations.
- `infra/oci/demo/.env.example` patch lines 429-439: generated header digest update.
- `infra/oci/demo/bootstrap-wp.sh` patch lines 440-461: dotenv literal decoding in `env_get` and its consumers.
- `infra/oci/demo/tests/test-credential-lifecycle.sh` patch lines 462-495: skimmed regression assertion for decoded quoted password reaching WordPress.
- `mk/env.mk` patch lines 496-525: materialize usage, apply/adopt gates, and prod confirmation.
- `scripts/env/materialize_remote.sh` patch lines 921-1011: manifest lookup, shell-quoted arguments, tar-over-ssh flow, temp cleanup, and distinct ssh/producer failure handling.
- `scripts/env/tests/test_materialize_remote.py` patch lines 1976-2201: skimmed argv/value redaction, streamed files, make gates, and ssh exit-code assertions; cleanup execution gap recorded above.
