# Plan 0003 - ENVMAN-1. Env manifest and deterministic renderer

- **Task ID:** ENVMAN-1 (Phase A). Phase B = ENVMAN-2, gated on APP-1 merging.
- **Task Plan Status:** approved for dispatch (operator: "scope and plan … maximize parallelism"); amended 2026-09-28 after the adversarial canon review.
- **Date:** 2026-09-27.
- **Target branch:** `feature/envman-1`. **Worktree:** `../context-alt-text-monorepo-envman-1`.
- **Baseline:** `016789be8ddc25191240a674d5d4ff9b856297bc`.
- **Intake:** [scope](../scopes/env-manifest-render-scope.md); MCP decisions APP-1 #13960 (proposal) and ENVMAN-1 scope decision.
- **Routing (operator order 2026-09-28):**
  - Implement and RED lanes: codex-remote `gpt-6-astra`, effort `low`, speed `standard`.
  - Review lanes: codex-remote `gpt-6-luna`, effort `max`, speed `fast`.
  - Every brief inlines prior art from `find_related_prior_work` and codemap snippets for `apps/` symbols.
  - RED lanes write tests only; GREEN lanes inherit them.

## Objective

Make `config/env/manifest.d/*.toml` the single hand-edited source for env configuration. Secrets stay in Keychain or CI env. `make env-render` produces runtime files, and `make env-check` proves every committed template equals its rendered example.

## Interface contract (pinned; RED and GREEN both code to this)

Package: `scripts/env/` (`__init__.py`, stdlib only, Python ≥3.11, `tomllib`).
- **Import names:** `env.manifest`, `env.secret_refs` and `env.render_env`, with `scripts/` on `sys.path`. Tests get it from `scripts/env/tests/conftest.py`. The CLI `render_env.py` inserts `Path(__file__).resolve().parents[1]` before its imports.
- **Module names:** no module may be named `secrets.py`. The CLI's script dir lands on `sys.path[0]` and would shadow the stdlib.
- **Tests:** they live in `scripts/env/tests/` and run with `python3 -m pytest scripts/env/tests -q`. They build fixture manifests under `tmp_path` and never read the real `config/env/`.

**RED rule:**
- RED test modules import the code under test inside a helper or fixture (`importlib.import_module("env.manifest")`), never at module top level. That way the suite collects on a tree without the implementation, and each test fails on its own.
- RED lane gate: `python3 -m pytest scripts/env/tests --collect-only -q` must pass.
- Before landing, the coordinator confirms every new test fails. Amendment RED lanes over landed GREEN code need only their new tests to fail.

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
doc = '''
Template preamble; one line per comment line.
'''                                                        # optional
```

Any other `<root>/manifest.d/*.toml` (loaded in sorted filename order):

```toml
version = 1
[[var]]
name = "PGPASSWORD"
class = "secret"                 # public | config | secret
targets = ["svc-local"]
section = "Database"
doc = "Postgres password."       # optional
example = "change-me"            # required
required = true                  # optional, default true
secret = { local = "keychain:acx-local/PGPASSWORD" }    # secret only
# values = { local = "..." }     # public/config only
# derive = "postgresql://${PGUSER}:${PGPASSWORD}@..."   # alternative to values/secret

[[override]]
name = "PGVECTOR_DIM"            # required; a var declared in any fragment
target = "svc-fir"               # required; one of that var's targets
example = "128"                  # optional
required = true                  # optional
doc = "..."                      # optional
section = "Embeddings"           # optional; must be in that target's sections
```

### `scripts/env/manifest.py`

**Types**
- `class ManifestError(ValueError)`. The message names the fragment file and the key.
- Frozen dataclasses:
  - `Target(name, audience, envs: tuple[str, ...], path: str | None, example: str | None, sections: tuple[str, ...], doc: str | None = None)`
  - `Var(name, cls, targets: tuple[str, ...], section, doc, example, required: bool, values: Mapping[str, str], secret: Mapping[str, str], derive: str | None, source: str)`
  - `Override(name, target, example, required, doc, section, source)`, where `None` means inherit.
  - `Manifest(targets: Mapping[str, Target], vars: tuple[Var, ...], overrides: Mapping[tuple[str, str], Override] = {})`
- `effective_var(manifest, var, target_name) -> Var` returns `var` with that target's override fields applied, where they are not `None`.

**`load_manifest(root: Path) -> Manifest` raises `ManifestError` for:**
- a missing `manifest.d/targets.toml`, or `version != 1`;
- unknown or missing keys, or wrong types;
- duplicate var names across fragments;
- `targets` naming an unknown target;
- `values`/`secret`/`derive` not exactly one of the three;
- a secret var with `values`, or a non-secret var with `secret`;
- a secret ref whose scheme is not `keychain:`, `env:` or `vault:`.

**Rules for targets**
- A target `doc` must be a string.
- A target `path`/`example` must be relative and must resolve inside the repo root. An absolute path or a `..` escape is refused before any read or write.
- Two targets may not share a `path` or an `example`.
- Section names contain no control characters.

**Rules for vars**
- A var's `section` must be in the `sections` of every one of its targets, except targets whose override sets `section`.
- Var and override names match `^[A-Z][A-Z0-9_]*$`.
- Docs contain no `\r`.
- **Env union:** each `values`/`secret` env key must be in the union of `envs` across the var's targets. A key in none of them is refused, and the message names the fragment, the var and the env. Rendering target T in env E uses `values[E]` only when E ∈ T.envs.

**Rules for derive**
- A derive may not name an unknown var or form a cycle.
- A derive that references a secret is refused unless `class = "secret"`.
- Every var referenced by `${NAME}` in a derive must target every target of the deriving var. Otherwise loading fails, naming both vars and the missing target.
- Every `$` in a derive must start a complete `${NAME}` interpolation.
- An empty `values = {}` or `secret = {}` table counts as the single value source and loads without runtime values.

**Override rules:** refuse an unknown key; a missing `name` or `target`; none of `example`/`required`/`doc`/`section` present; `name` not a declared var; `target` not among that var's targets; a duplicate `(name, target)` across fragments; `section` not in that target's `sections`; or a wrong type.

**Public-build guard** (inside `load_manifest`). For a var that targets any `audience = "public_build"` target, refuse:
- `class = "secret"`;
- a derive that reaches a secret;
- a name not starting with `VITE_`;
- a name containing any of these `_`-separated tokens: `SECRET`, `SECRETS`, `TOKEN`, `PASSWORD`, `PASSWD`, `PWD`, `PRIVATE`, `CREDENTIAL`, `CREDENTIALS`, or `KEY` when the token before it is not `PUBLISHABLE`.

Separately, a `class = "secret"` var named `VITE_*` is refused on any target.

**Literal guard** (all targets). Refuse any `values`, `example`, `derive`, `doc` or `section` string (var, target or override) that contains:
- `sk_(test|live)_`, `\brk_(test|live)_`, `whsec_` or `-----BEGIN`;
- `ghp_`, `gho_`, `ghs_` or `github_pat_`;
- `AKIA[0-9A-Z]{16}` or `xox[abprs]-`.

**`target_digest(manifest, target_name) -> str`:**
- The value is the sha256 hex of `json.dumps(..., sort_keys=True, separators=(",", ":"))` over the target, its effective vars sorted by name (without `source`) and its overrides.
- Moving a var between fragments does not change it. Changing the target, one of its vars, or one of its overrides does.
- An override for another target does not change it.

### `scripts/env/secret_refs.py`

- `class SecretUnavailable(RuntimeError)`. The message contains the var name and the scheme, never a value.
- `class SecretNotFound(SecretUnavailable)` is raised when the secret is absent (keychain exit 44; `env:` unset or empty); every other failure stays `SecretUnavailable`.
- `resolve_secret(var_name: str, ref: str, *, environ: Mapping[str, str] | None = None, runner=subprocess.run) -> str`:
  - `keychain:<service>/<account>`:
    - Split on the first `/`. An empty service or account, or no `/`, raises `SecretUnavailable` without calling the runner.
    - Otherwise call `runner(["security", "find-generic-password", "-s", service, "-a", account, "-w"], capture_output=True, text=True, check=False)`.
    - Exit 44 raises `SecretNotFound`; any other non-zero exit or empty output raises `SecretUnavailable`. Strip one trailing newline.
  - `env:<NAME>` reads `environ` (default `os.environ`). An unset or empty value raises `SecretNotFound`; an empty NAME raises `SecretUnavailable`.
  - `vault:` raises `SecretUnavailable` ("vault refs render in ENVMAN-2").
  - Any other or missing scheme raises `SecretUnavailable` without calling the runner.

### `scripts/env/render_env.py`

**Header:** `HEADER_LINE = "# GENERATED by make env-render from config/env/manifest.d - do not edit."`. Line 2 is `# target: <name> env: <env|example> digest: <target_digest>`.

**`render_target(manifest, target_name, env: str | None, *, resolve=resolve_secret) -> str`**
- Every per-target use of a var goes through `effective_var`.
- **Example mode** (`env=None`):
  - Every var renders its `example`.
  - A `required = false` var renders commented, as `# NAME=example`.
  - No resolver is called.
- **Runtime mode:**
  - public/config vars render `values[env]`; secret vars render `resolve(name, secret[env])`; derive substitutes `${VAR}` with the rendered values.
  - A `required = false` secret whose resolver raises `SecretNotFound` is omitted; any other resolver error, or an absent required secret, raises `SecretUnavailable` without echo.
  - a missing non-required var is omitted, and a missing required var raises `ManifestError`.

**Layout**
- Header, then a blank line.
- If the target has a `doc`: its doc lines, then one blank line.
- Then, per section in `sections` order: `# == <section> ==`, followed by each var in declaration order, as its doc lines and then `NAME=value`.
- One blank line between sections, and a single trailing newline.

**Doc lines:** split on `\n`. An empty line renders as `#`. Any other line renders as `# ` + the line with trailing whitespace stripped, keeping leading spaces.

**Quoting (portable).** Given a value v:
1. v contains CR or LF → `ValueError` naming the var, never the value.
2. v is empty, or every char is in `[A-Za-z0-9_./:@,+=%?-]` → unquoted.
3. Every `$` in v begins a complete `${NAME}` reference (`NAME` matches `[A-Za-z_][A-Za-z0-9_]*`), and every other char is in the unquoted set → `"v"`. Double quotes keep the reference live in bash `source`, python-dotenv and compose; single quotes would leave it literal in bash. Rule 3 applies only to manifest-authored values: a var's `example`, and a non-secret var's literal `values` entry. A value produced by secret resolution, or by `derive` at runtime, skips rule 3, so a resolved `${X}` renders single-quoted and stays literal. Otherwise a credential containing `${...}` would silently change when bash sources the file.
4. v has no `'` → `'v'`.
5. v has none of `"`, `\`, `$`, `` ` `` → `"v"`.
6. Otherwise → `ValueError` naming the var.

There is no escaping anywhere. This subset reads identically in python-dotenv, pydantic-settings, bash `set -a; source`, npm dotenv and `docker compose config`. The description service's own `.env` loader (`db/settings.py::_load_env_file`) strips these quotes:
- single-quoted text is verbatim;
- double-quoted text is expanded as before.

**`write_env_file(path: Path, text: str, *, adopt: bool = False, allow_unmanaged: frozenset[str] = frozenset()) -> None`**
- Refuse a symlink (`lstat`).
- Refuse an existing file whose first line is not `HEADER_LINE`, unless `adopt`.
- On adopt:
  - Back up to `<path>.pre-envman` (0600).
  - Refuse keys present in the old file but absent from `text`, unless listed in `allow_unmanaged`. Keys count in every assignment form: `NAME=v`, `export NAME=v` and `NAME = v`.
  - Refuse a line that is not a comment, a blank or an assignment. The message names the line number, not its content.
- Write a temp file `<name>.envman-tmp-XXXX` in the same dir, created 0600, then `fsync` and `os.replace`. Root `.gitignore` ignores `*.envman-tmp-*`.
- Every refusal raises `ValueError` naming the path, key or line, never a value. Refusals cover: symlink, broken symlink, directory, un-headed file, unmanaged keys and an unparseable line.

**`check_example(manifest, target_name, repo_root) -> list[str]`**
- Returns drift messages.

**`check_runtime(manifest, target_name, env, path, *, resolve=...) -> list[str]`**
- Reports drift on any byte difference, never printing a value. Messages:
  - `NAME: differs`, `NAME: secret differs`, `NAME: missing`;
  - `NAME: unmanaged key`, `NAME: duplicate assignment`;
  - `<path>: non-assignment lines differ`;
  - `<path>: mode is not 0600`.

**CLI:** `python3 scripts/env/render_env.py {render,check} [--root config/env] [--repo-root .] [--env ENV] [--target T|--all-examples] [--adopt] [--allow-unmanaged K,...]`
- Without `--env`, `--target T` renders or checks T's example.
- `render --all-examples` rewrites every template.
- An `--env` that is not in `target.envs` is a usage error naming the target and env.
- An interpreter older than 3.11 is refused before the `env` imports, with exit 2.
- Exit codes: 0 ok, 1 drift, 2 manifest or usage error, 3 secret unavailable, 4 unexpected exception (prints the exception type name only).

### Make

- `mk/env.mk` targets:
  - `env-render ENV=… TARGET=… [ADOPT=1]`
  - `env-examples` renders all templates.
  - `env-check` checks all templates.
  - `env-secret-set NAME=… [ENV_SECRET_SERVICE=acx-local]` runs `security add-generic-password -U -s … -a … -w` with no value, so `security` prompts; the value is never in argv.
- The interpreter is `ENV_PYTHON ?= python3`. The Keychain service variable is `ENV_SECRET_SERVICE`, not `SERVICE`, because `mk/logs.mk` already defaults `SERVICE`.
- The `Makefile` `check-all` target runs `env-check`.

## Lanes and DAG

Each lane owns disjoint paths (1–4 files). A lane lands only on a green gate in the feature worktree, then retires.

| Lane | Layer | Kind | Owned paths | Depends on |
|---|---|---|---|---|
| `em-red-loader` | 0 | RED | `scripts/env/tests/test_manifest_loader.py` | — |
| `em-red-render` | 0 | RED | `scripts/env/tests/test_render.py` | — |
| `em-red-secrets` | 0 | RED | `scripts/env/tests/test_secret_resolvers.py` | — |
| `em-loader` | 1 | GREEN | `scripts/env/__init__.py`, `scripts/env/manifest.py` | all RED |
| `em-secrets` | 1 | GREEN | `scripts/env/secret_refs.py` | all RED |
| `em-loader-fix` | 1 | fix | `scripts/env/manifest.py`, loader tests | `em-loader` |
| `em-render` | 2 | GREEN | `scripts/env/render_env.py`, `mk/env.mk`, `Makefile` | `em-loader`, `em-secrets` |
| `em-docs` | 2 | docs | `docs/runbooks/env-manifest.md`, `apps/prototype-description-service/docs/secrets-inventory.md` | `em-loader` |
| `em-red-quote` | 2 | RED | `scripts/env/tests/test_render.py` | `em-render` |
| `em-frag-shared` | 3 | migrate | `config/env/manifest.d/targets.toml`, `config/env/manifest.d/10-service-shared.toml` | `em-render` |
| `em-red-contract2` | 3 | RED | loader + render tests | `em-red-quote`, `em-loader-fix` |
| `em-red-svcquote` | 3 | RED | `apps/prototype-description-service/recognition/tests/unit/test_database_settings.py` | — |
| `em-contract2` | 4 | GREEN | `scripts/env/manifest.py`, `scripts/env/render_env.py`, `config/env/manifest.d/targets.toml` | `em-red-contract2`, `em-frag-shared` |
| `em-svc-quote` | 4 | GREEN | `apps/prototype-description-service/db/settings.py` | `em-red-svcquote` |
| `em-red-harden` | 4 | RED | `scripts/env/tests/test_harden_loader.py`, `scripts/env/tests/test_harden_render.py` | — |
| `em-harden-loader` | 5 | GREEN | `scripts/env/manifest.py`, `scripts/env/tests/test_harden_loader.py` (review fix-up) | `em-contract2`, `em-red-harden` |
| `em-red-quote2` | 5 | RED | `scripts/env/tests/test_harden_render.py` | `em-red-harden` |
| `em-harden-render` | 6 | GREEN | `scripts/env/render_env.py`, `mk/env.mk`, `.gitignore`, `apps/prototype-description-service/.env.example` (re-render) | `em-contract2`, `em-red-harden`, `em-red-quote2`, `em-frag-local` |
| `em-red-quote3` | 7 | RED | `scripts/env/tests/test_harden_render.py` | `em-harden-render` |
| `em-quote-literal` | 8 | GREEN | `scripts/env/render_env.py` | `em-red-quote3` |
| `em-frag-local` | 5 | migrate | `config/env/manifest.d/20-service-local.toml`, `apps/prototype-description-service/.env.example` | `em-contract2` |
| `em-frag-vm` | 5 | migrate | `config/env/manifest.d/21-service-vm.toml`, `apps/prototype-description-service/.env.prod.example` | `em-contract2` |
| `em-frag-fir` | 5 | migrate | `config/env/manifest.d/22-service-fir.toml`, `apps/prototype-description-service/.env.fir.example` | `em-contract2` |
| `em-frag-demo` | 5 | migrate | `config/env/manifest.d/40-demo.toml`, `infra/oci/demo/.env.example` | `em-contract2` |
| `em-frag-wp` | 5 | migrate | `config/env/manifest.d/50-wp-e2e.toml`, `apps/prototype-wp-alt-context/.env.local.example` | `em-contract2` |

**Placement rules**
- Targets live only in `targets.toml`. `em-frag-shared` declares all five targets (`svc-local`, `svc-vm`, `svc-fir`, `demo`, `wp-e2e`) and the vars shared by the three service templates. `em-contract2` adds each target's `doc` preamble.
- L5 migrate lanes only add fragments and regenerate their template.
- `em-red-harden` writes new test files, so it runs in parallel with `em-contract2` without sharing a path.

```
L0-2  RED loader/render/secrets → em-loader, em-secrets → em-render, em-docs → em-red-quote   (landed)
L3    em-frag-shared   em-red-contract2   em-red-svcquote                                 (landed)
L4    em-contract2 ◄─(red-contract2, frag-shared)   em-svc-quote ◄─(red-svcquote)   em-red-harden
L5    em-harden-loader ◄─(contract2, red-harden)   em-red-quote2 ◄─(red-harden)
L6    em-harden-render ◄─(contract2, red-harden, red-quote2, frag-local)
L7    em-red-quote3 ◄─(harden-render)
L8    em-quote-literal ◄─(red-quote3)
      em-frag-local  em-frag-vm  em-frag-fir  em-frag-demo  em-frag-wp   ◄─(contract2)
```

Critical path: `em-contract2` → any L5 lane. Up to 4 lane worktrees are open at a time; a finished lane lands and retires before the next is admitted.

### Migration-lane rule

1. A migrate lane moves every key of its template into its fragment:
   - keep the same section order and doc text (comments become `doc`); every baseline comment line survives verbatim, with no length cap, except `# ----` rules and the titles between them;
   - put target-specific examples, docs and sections in `[[override]]` tables, never in a duplicate var.
2. It then runs `python3 scripts/env/render_env.py render --target <t> --adopt` and commits the regenerated template.
   - `--adopt` is required because the committed template has no generated header yet.
   - The `.pre-envman` backup is gitignored by the `.env.*` rule and is not committed.
3. Gate: `python3 -m pytest scripts/env/tests/test_manifest_loader.py scripts/env/tests/test_render.py scripts/env/tests/test_secret_resolvers.py -q && python3 scripts/env/render_env.py check --target <t>`.
   - The harden suites are excluded until both harden GREEN lanes land.
4. The regenerated template's key set must equal the baseline template's key set. Commented-out `# KEY=` lines count as `required = false` vars. The brief lists the baseline keys, and the coordinator re-diffs them at landing (`.task-state/envman1_parity.py <t>`).
5. Real values: only public/config values already present in the old template's examples. No secret value is ever written. A secret-bearing var is `class = "secret"`, even when the old template showed a placeholder (for example `ACX_GPU_ENDPOINT_API_KEY` in `svc-vm`).

## Verification

- **Per lane:** the lane's gate, run in the feature worktree at landing. Service tests (`em-red-svcquote`, `em-svc-quote`) run on the VM, and the lane's `self_verify` tail is the evidence.
- **Merge candidate:** `python3 -m pytest scripts/env/tests -q`, `make env-check` and `make lint-task-plans`.
  - `env-check` is green only after all five migrate lanes land, because each template is un-headed until its lane regenerates it.
  - So `feature/envman-1` does not merge to `main` before every L5 lane has landed.
- **Review:** one harmonizing review before `main` (codex-remote luna max fast). Highs block, mediums are fixed and lows are deferred.

## Out of scope

See scope § Not doing and § Phase B. Prod rendering (vault refs, deploy shipping) is Phase B, so the Phase A renderer has no prod runtime target.
