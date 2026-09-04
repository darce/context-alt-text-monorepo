# OCIRV-1 adversarial credential/auth review

Scope: the OCIR auth, rotation, push, and operator-documentation surfaces in the supplied feature snapshot. The execution checkout is history-stripped and remote-severed, so `main` and `2f6763d59` are unavailable for reconstructing the requested merge-base diff; all anchors below were re-derived from the supplied tree.

## Carried-observation dispositions

Observation (a) is **confirmed as a process-wide leak but refuted as load-bearing in the current call graph**. `init_deploy_ocir_docker_config` changes the parent shell's umask from the ordinary `0022` to `0077`; the `mktemp -d` directory is already private. No later command in the current deploy/promote paths intentionally creates a group-readable deployment artifact in that shell, and remote files are created by separate SSH shells, so I found no present group-read failure. The ambient side effect is still recorded as OCIRV1-RA-05 because it silently constrains every later local child and future file creation.

Observation (b) is **confirmed structurally but refuted as a currently reachable unauthenticated operational path**. `do_push_tag` does not authenticate. The only direct production call is in `do_deploy`, after `do_push_sha`; a failed SHA push aborts under `set -e`, a failed smoke never calls the tag push, and a rerun starts the full deploy again. `do_promote` authenticates on its own path and does not call `do_push_tag`. No Makefile target, documented command, or dispatched subcommand invokes `do_push_tag` directly; only a caller that sources this internal script can do so.

## Findings

### OCIRV1-RA-01 — high

`scripts/deploy/recognition-service.sh:203-224` derives `ACX_DEPLOY_OCIR_CONFIG_DIR` from the inherited, unvalidated `TMPDIR`, then single-quotes that derived path into an SSH command; the same unsafe interpolation recurs in cleanup and registry commands at `scripts/deploy/recognition-service.sh:185-188,797-803,1273,1433,1545,1559`. A caller can create a local temp parent whose name contains a quote and shell operators and set `TMPDIR` to it; `mktemp` succeeds locally, but a value such as `.../q';touch PWNED;#` closes the remote quote and executes injected commands as the deployment SSH user during remote config initialization (the local harness emitted exactly `if [ ! -d '.../q';touch PWNED;#/acx-ocir-deploy...`). This turns a nominal temp-directory environment override into remote command execution on the production VM and also makes cleanup/push/pull reusable execution sinks.

### OCIRV1-RA-02 — high

`scripts/deploy/recognition-service.sh:807-814` calls the SHA-tagged ref "immutable" but pushes an ordinary mutable registry tag, and `scripts/deploy/recognition-service.sh:1243-1274,1483-1488` later pulls that tag for the boot smoke before promoting the separately built environment tag; no digest is captured or compared. Two authorized deploys of the same commit but different build inputs (dev explicitly permits dirty trees), or an actor with OCIR push rights, can replace `:SHA` after the first push so deploy A smokes deploy B's image and then publishes A's unsmoked `:dev`/`:latest` image. The race defeats the release gate and also means a later "rollback by SHA" can retrieve attacker-replaced or merely different bytes; for production this can promote code that never passed the advertised smoke.

### OCIRV1-RA-03 — medium

`scripts/deploy/recognition-service.sh:180-196` removes the remote Docker config only through a fresh best-effort SSH connection and suppresses every cleanup failure with `|| true`; the config is deliberately caller-owned, so the generated remote login program declines to remove it at `scripts/deploy/lib/ocir-auth.sh:84-99`. If the deploy exits because the VM or tailnet becomes unreachable, or the local process is killed with SIGKILL after remote login, the cleanup cannot run successfully and the valid `config.json` remains in `/tmp` indefinitely despite the runbook's claim at `infra/oci/vault-instance-principal-runbook.md:126-131` that no credential remains. Its `0700` directory limits immediate reads to the deploy account/root, but any later compromise of that account recovers a long-lived registry credential that should have existed only for the deployment.

### OCIRV1-RA-04 — medium

`infra/oci/README.md:539-546` still instructs operators to run `docker login` once on the VM and explicitly says the token is stored in `~ubuntu/.docker/config.json`, while the current credential contract says to use ephemeral Vault-backed login and not pre-seed cached auth (`infra/oci/vault-instance-principal-runbook.md:126-131` and `docs/runbooks/deploy-recognition-cicd.md:105-112`). Following the documented prerequisite as written creates a second, unrotated credential copy outside the deploy cleanup lifecycle; on a normal Linux Docker setup it remains recoverable by the `ubuntu` account and root after the deploy ends. Operators following the primary README therefore reintroduce the exact persistent credential exposure OCIRV-1 claims to remove, and later token revocation/rotation can leave an unnoticed stale credential on disk.

### OCIRV1-RA-05 — low

`scripts/deploy/recognition-service.sh:199-213` executes bare `umask 077` in the long-lived deploy shell even though `mktemp -d` already creates the credential directory with mode `0700`, and never restores the prior mask. A direct harness observed `0022` before initialization and `0077` afterward. Current remote artifact creation runs in separate SSH shells and I found no present artifact that requires group read, so the leak is not currently load-bearing; nevertheless every later local subprocess and any future local redirection/install step silently inherits owner-only defaults, which can produce hard-to-diagnose permission failures unrelated to OCIR auth.
