# Plan 0003 - ENVMAN-1. Env manifest and deterministic renderer

- **Task ID:** ENVMAN-1 (Phase A). Phase B = ENVMAN-2, gated on APP-1 merging.
- **Task Plan Status:** approved for dispatch (operator: "scope and plan … maximize parallelism").
- **Date:** 2026-09-27.
- **Target branch:** `feature/envman-1`. **Worktree:** `../context-alt-text-monorepo-envman-1`.
- **Baseline:** `016789be8ddc25191240a674d5d4ff9b856297bc`.
- **Intake:** [scope](../scopes/env-manifest-render-scope.md); MCP decisions APP-1 #13960 (proposal) and ENVMAN-1 scope decision.
- **Routing:** every lane codex-remote `gpt-6-luna`, effort `max`, speed `fast`. RED lanes write tests only; GREEN lanes inherit them.

## Objective

Make `config/env/manifest.d/*.toml` the single hand-edited source for env configuration (secrets stay in Keychain/CI env). `make env-render` produces runtime files; `make env-check` proves every committed template equals its rendered example.

## Interface contract (pinned; RED and GREEN both code to this)

Package: `scripts/env/` (`__init__.py`, stdlib only, Python ≥3.11, `tomllib`). Import names: `env.manifest`, `env.secret_refs`, `env.render_env` with `scripts/` on `sys.path` (tests: `scripts/env/tests/conftest.py` inserts it; CLI: `render_env.py` inserts `Path(__file__).resolve().parents[1]` before its imports). No module may be named `secrets.py` (the CLI's script dir lands on `sys.path[0]` and would shadow the stdlib). Tests: `scripts/env/tests/`, run with `python3 -m pytest scripts/env/tests -q`. Tests build fixture manifests under `tmp_path`; they never read the real `config/env/`.

**RED rule:** RED test modules import the code under test inside a helper/fixture (`importlib.import_module("env.manifest")`), never at module top level, so the suite collects on a tree without the implementation and every test fails individually. RED lane gate: `python3 -m pytest scripts/env/tests --collect-only -q` (must pass); the coordinator confirms the tests fail before landing.

### Manifest format

`<root>/manifest.d/targets.toml`:

```toml
version = 1
[targets.svc-local]
audience = "backend"            # backend | public_build | test
envs = ["local"]
path = "apps/prototype-description-service/.env"          # optional; repo-relative
example = "apps/prototype-description-service/.env.example" # optional; repo-relative
sections = ["Database", "Security"]                        # render order
```

Any other `<root>/manifest.d/*.toml` (loaded in sorted filename order):

```toml
version = 1
[[var]]
name = "PGPASSWORD"
class = "secret"                 # public | config | secret
targets = ["svc-local"]
section = "Database"
doc = "Postgres password."       # optional; rendered as '# ' comment lines
example = "change-me"            # required
required = true                  # optional, default true
secret = { local = "keychain:acx-local/PGPASSWORD" }    # secret only
# values = { local = "..." }     # public/config only
# derive = "postgresql://${PGUSER}:${PGPASSWORD}@..."   # alternative to values/secret
```

### `scripts/env/manifest.py`

- `class ManifestError(ValueError)`; message names the fragment file and key.
- Frozen dataclasses `Target(name, audience, envs: tuple[str, ...], path: str | None, example: str | None, sections: tuple[str, ...])`, `Var(name, cls, targets: tuple[str, ...], section, doc, example, required: bool, values: Mapping[str, str], secret: Mapping[str, str], derive: str | None, source: str)`, `Manifest(targets: Mapping[str, Target], vars: tuple[Var, ...])`.
- `load_manifest(root: Path) -> Manifest`. Raises `ManifestError` for: missing `manifest.d/targets.toml`; `version != 1`; unknown or missing keys; wrong types; duplicate var names across fragments; `targets` naming an unknown target; `section` not in every one of its targets' `sections`; `values`/`secret`/`derive` not exactly one; secret with `values`; non-secret with `secret`; `derive` naming an unknown var or forming a cycle; a derive that references a secret while `class != "secret"`; an env key in `values`/`secret` not in some target's `envs`; secret ref scheme not in `keychain:`, `env:`, `vault:`.
- **Public-build guard** (inside `load_manifest`): for a var targeting any `audience="public_build"` target → refuse `class="secret"`, a derive that reaches a secret, a name not starting `VITE_`, and a name matching `SECRET|TOKEN|PASSWORD|PRIVATE|(?<!PUBLISHABLE)_KEY$`.
- **Literal guard** (all targets): refuse any `values`/`example` string matching `sk_(test|live)_`, `\brk_(test|live)_`, `whsec_`, or `-----BEGIN`.
- `target_digest(manifest, target_name) -> str`: sha256 hex of a canonical JSON of the target and its vars (order-independent of fragment filenames).

### `scripts/env/secret_refs.py`

- `class SecretUnavailable(RuntimeError)`; message contains var name and scheme, never a value.
- `resolve_secret(var_name: str, ref: str, *, environ: Mapping[str, str] | None = None, runner=subprocess.run) -> str`:
  - `keychain:<service>/<account>` → `runner(["security", "find-generic-password", "-s", service, "-a", account, "-w"], capture_output=True, text=True, check=False)`; non-zero or empty → `SecretUnavailable`; strip one trailing newline.
  - `env:<NAME>` → `environ` (default `os.environ`); absent or empty → `SecretUnavailable`.
  - `vault:` → `SecretUnavailable` ("vault refs render in ENVMAN-2").

### `scripts/env/render_env.py`

- `HEADER_LINE = "# GENERATED by make env-render from config/env/manifest.d - do not edit."`; line 2 `# target: <name> env: <env|example> digest: <target_digest>`.
- `render_target(manifest, target_name, env: str | None, *, resolve=resolve_secret) -> str`. `env=None` = example mode (every var renders `example`; a `required = false` var renders commented as `# NAME=example`; no resolver call). Runtime mode: public/config → `values[env]`; secret → `resolve(name, secret[env])`; derive → `${VAR}` substituted with the rendered values; a missing non-required var is omitted, a missing required var raises `ManifestError`.
- Layout: header, blank line; per section in `sections` order: `# == <section> ==`, then per var in declaration order its `doc` lines as `# ...` and `NAME=value`; one blank line between sections; single trailing newline. Values containing whitespace, `#`, `"`, `'`, `$` or `\` are double-quoted with `\\`, `\"`, `\$` escaped.
- `write_env_file(path: Path, text: str, *, adopt: bool = False, allow_unmanaged: frozenset[str] = frozenset()) -> None`: refuse a symlink (`lstat`); refuse an existing file whose first line is not `HEADER_LINE` unless `adopt`; on adopt, back up to `<path>.pre-envman` (0600) and refuse keys present in the old file but absent from `text` unless in `allow_unmanaged`; write temp in the same dir with mode 0600, `fsync`, `os.replace`.
- `check_example(manifest, target_name, repo_root) -> list[str]` and `check_runtime(manifest, target_name, env, path, *, resolve=...) -> list[str]`: drift messages; secret mismatches read `NAME: secret differs` and never include a value.
- CLI `python3 scripts/env/render_env.py {render,check} [--root config/env] [--repo-root .] [--env ENV] [--target T|--all-examples] [--adopt] [--allow-unmanaged K,...]`. Exit: 0 ok, 1 drift, 2 manifest/usage error, 3 secret unavailable. `render --all-examples` rewrites every template.

### Make

`mk/env.mk`: `env-render ENV=… TARGET=… [ADOPT=1]`, `env-examples` (render all templates), `env-check` (all templates), `env-secret-set NAME=… [SERVICE=acx-local]` (`security add-generic-password -U -s … -a … -w` with no value so `security` prompts; never argv). `Makefile` `check-all` runs `env-check`.

## Lanes and DAG

Each lane owns disjoint paths (1–3 files). Merge order = layer order.

| Lane | Layer | Kind | Owned paths | Depends on |
|---|---|---|---|---|
| `em-red-loader` | 0 | RED | `scripts/env/tests/test_manifest_loader.py` | — |
| `em-red-render` | 0 | RED | `scripts/env/tests/test_render.py` | — |
| `em-red-secrets` | 0 | RED | `scripts/env/tests/test_secret_resolvers.py` | — |
| `em-loader` | 1 | GREEN | `scripts/env/__init__.py`, `scripts/env/manifest.py` | all RED |
| `em-secrets` | 1 | GREEN | `scripts/env/secret_refs.py` | all RED |
| `em-render` | 2 | GREEN | `scripts/env/render_env.py`, `mk/env.mk`, `Makefile` | `em-loader`, `em-secrets` |
| `em-docs` | 2 | docs | `docs/runbooks/env-manifest.md`, `apps/prototype-description-service/docs/secrets-inventory.md` | `em-loader` |
| `em-frag-shared` | 3 | migrate | `config/env/manifest.d/targets.toml`, `config/env/manifest.d/10-service-shared.toml` | `em-render` |
| `em-frag-local` | 4 | migrate | `config/env/manifest.d/20-service-local.toml`, `apps/prototype-description-service/.env.example` | `em-frag-shared` |
| `em-frag-vm` | 4 | migrate | `config/env/manifest.d/21-service-vm.toml`, `apps/prototype-description-service/.env.prod.example` | `em-frag-shared` |
| `em-frag-fir` | 4 | migrate | `config/env/manifest.d/22-service-fir.toml`, `apps/prototype-description-service/.env.fir.example` | `em-frag-shared` |
| `em-frag-demo` | 4 | migrate | `config/env/manifest.d/40-demo.toml`, `infra/oci/demo/.env.example` | `em-frag-shared` |
| `em-frag-wp` | 4 | migrate | `config/env/manifest.d/50-wp-e2e.toml`, `apps/prototype-wp-alt-context/.env.local.example` | `em-frag-shared` |

Targets live only in `targets.toml`. `em-frag-shared` declares all five targets (`svc-local`, `svc-vm`, `svc-fir`, `demo`, `wp-e2e`) with their `sections` from the current templates, plus the vars shared by the three service templates, so L4 lanes only add vars.

```
L0  em-red-loader   em-red-render   em-red-secrets
        \               |               /
L1   em-loader  ───────────────  em-secrets
        |  \                         |
L2      |  em-docs              em-render ◄─(loader, secrets)
        |                            |
L3                            em-frag-shared
                        /     /      |      \      \
L4          em-frag-local em-frag-vm em-frag-fir em-frag-demo em-frag-wp
```

Critical path: RED → `em-loader` → `em-render` → `em-frag-shared` → any L4 lane (5 layers). Peak width 5 (L4), admitted ≤4 open lane worktrees at a time; a finished lane lands and retires before the next admits.

### Migration-lane rule

A migrate lane moves every key of its template into the fragment with the same section order and doc text (comments become `doc`), then runs `python3 scripts/env/render_env.py render --target <t> --all-examples` and commits the regenerated template. Gate: `python3 -m pytest scripts/env/tests -q && python3 scripts/env/render_env.py check --all-examples`. The key set of the regenerated template must equal the baseline template's key set (commented-out `# KEY=` lines count as `required = false` vars); the brief lists the baseline keys and the coordinator re-diffs them at landing. Real values: only public/config values already present in the old template's examples; no secret value is ever written.

## Verification

- Per lane: its gate in `test_commands`.
- Merge candidate: `python3 -m pytest scripts/env/tests -q`, `make env-check`, `make lint-task-plans`.
- One harmonizing review before `main` (codex-remote luna max fast); highs block, mediums fixed, lows deferred.

## Out of scope

See scope § Not doing and § Phase B.
