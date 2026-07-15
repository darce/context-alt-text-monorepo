# Upstream request — `make workbay-update` is unusable: bash-shim runtime detection, a stale PyPI `workbay` that silently downgrades the stack, and git installs broken by missing workspace root

**Target repo:** `agentic-protocol-monorepo` / `darce/workbay` (`scripts/workbay/update.sh`, package metadata, PyPI publication).
**Consumer:** `context-alt-text-monorepo` (package-mode install, `source_kind: "package"`).
**Discovered while:** upgrading the stack to **v0.1.49** (orchestrator 0.2.10 per-class OS-reserve fix, workbay-system 0.3.16 `os_reserve_remote_api_gib`, bootstrap 0.3.17, anchor 0.3.23).
**Severity:** the documented upgrade path **downgraded a working install**. Recovered manually; a less careful operator would be left with a silently-broken stack.

## Summary

Three independent defects make the shipped upgrade path fail — and defect 2 makes it **actively destructive**:

1. **`update.sh` mis-detects the runtime when `workbay-bootstrap` is a pyenv shim.** The shim is a *bash* script, so the detector concludes the runtime is `/bin/bash`, then runs `uv pip install --python /bin/bash` and pipes Python into bash.
2. **`uv pip install --upgrade workbay` resolves a stale `workbay==0.2.1` from PyPI**, which clobbers the git-installed stack — **downgrading** `workbay-bootstrap` 0.3.12→0.2.1, `workbay-system` 0.3.10→0.2.1, and `workbay-protocol` 0.2.2→**0.2.0**. (0.2.0 is exactly the version that lacks `workbay_protocol.version` — the skew filed in `2026-07-15-offload-lane-venv-workbay-protocol-skew`. This upgrade path *causes* that bug.)
3. **No package installs from git at v0.1.49**: every member pyproject declares `[tool.uv.sources]` with `workspace = true`, but the repo has **no `[tool.uv.workspace]` root**, so uv refuses to build any `git+…#subdirectory=packages/…` requirement — including the exact requirement set recorded in the existing `uv-receipt.toml`.

Combined: the sanctioned upgrade (`make workbay-update`) crashes; the manual fallback silently downgrades; and the recorded git-ref install recipe no longer resolves.

---

## Defect 1 — bash-shim runtime detection

`make workbay-update` (dry run) on this host:

```
workbay-update: runtime: /bin/bash (owns /Users/daniel/.pyenv/shims/workbay-bootstrap)
workbay-update: adapter: uv pip (runtime-pinned)
workbay-update: + uv pip install --python /bin/bash --upgrade workbay
import: delegate library support not built-in '' (X11) @ error/import.c/ImportImageCommand/1302.
/…/.workbay-bootstrap.json: -c: line 2: syntax error near unexpected token `json.load'
make: *** [workbay-update] Error 2
```

`~/.pyenv/shims/workbay-bootstrap` begins `#!/usr/bin/env bash`. The detector resolves the *console-script's* interpreter by reading its shebang, so a pyenv shim (always bash) yields `/bin/bash` as "the runtime". Two consequences: `uv pip install --python /bin/bash` is nonsense, and the later inline `python -c "import json,sys; …"` executes under **bash** — which is why ImageMagick's `import(1)` runs and the JSON probe dies on a bash syntax error.

**Ask:** resolve the owning runtime by **executing** the console script's interpreter rather than parsing a shebang — e.g. `pyenv which workbay-bootstrap` → real path, or import-probe candidate interpreters (`python -c "import workbay_bootstrap"`), or record the runtime in `.workbay-bootstrap.json` at install time. Reject a non-Python "runtime" (anything that fails `-c "import sys"`) with a clear error instead of proceeding. Never pipe Python source through an unverified interpreter.

## Defect 2 — stale PyPI `workbay` silently downgrades a git-installed stack (**destructive**)

The consumer's stack is git-installed (`uv-receipt.toml` pins every member to `git+https://github.com/darce/workbay.git…&rev=v0.1.48`). Running the step `update.sh` itself prescribes:

```
uv pip install --python <runtime> --upgrade workbay
```

resolves **`workbay==0.2.1` from PyPI** and replaces the git distributions:

```
 + workbay==0.2.1
 - workbay-bootstrap==0.3.12 (from git+…@a24852af#subdirectory=packages/workbay-bootstrap)
 + workbay-bootstrap==0.2.1
 - workbay-protocol==0.2.2  (from git+…)
 + workbay-protocol==0.2.0
 - workbay-system==0.3.10   (from git+…)
 + workbay-system==0.2.1
```

There is no version conflict and no warning: PyPI `workbay` 0.2.1 is simply an **older/unrelated release** whose `==` pins are far behind the git line. `--upgrade` happily "upgrades" to it because the git-installed versions carry no index-comparable ordering.

**Ask (any of, ideally all):**
- **Publish the real stack to PyPI** (0.3.x anchor + members), or **yank/claim** `workbay==0.2.1` so it cannot resolve as the front door.
- Have `update.sh` **install from the recorded source** — read `uv-receipt.toml` / `.workbay-bootstrap.json` and reuse the pinned git refs — rather than an unqualified `--upgrade workbay` against the default index.
- **Refuse to cross install-sources**: if the installed dist is git-sourced, fail loudly rather than silently replacing it with an index build.
- Add a **post-upgrade version assertion** (the script already has a "verify the anchor and its exact member pins resolve" step — it did not catch a wholesale downgrade).

## Defect 3 — git installs unresolvable at v0.1.49 (missing workspace root)

Every member declares workspace sources, e.g. `packages/workbay-bootstrap/pyproject.toml:33`:

```toml
[tool.uv.sources]
mcp-workbay-handoff = { workspace = true }
workbay-protocol    = { workspace = true }
workbay-system      = { workspace = true }
```

but `grep -rl "tool.uv.workspace" --include=pyproject.toml .` at `v0.1.49` returns **nothing** — there is no workspace root. So:

```
uv pip install "workbay @ git+https://github.com/darce/workbay.git@v0.1.49#subdirectory=packages/workbay"
  ├─▶ Failed to parse entry: `workbay-protocol`
  ╰─▶ `workbay-protocol` references a workspace in `tool.uv.sources`, but is not a workspace member
```

This fails for `workbay`, `workbay-bootstrap`, and `workbay-system` alike — i.e. **the recorded `uv-receipt.toml` recipe can no longer be replayed**, so `uv tool install --force` at v0.1.49 would fail and could leave the tool env (which hosts the live MCP servers) broken.

**Ask:** add the `[tool.uv.workspace]` root to the repo, **or** drop `workspace = true` in favour of version constraints for published members, **or** document that consumers must `--no-sources`. Also add CI that installs each package from a clean git ref exactly as a consumer would (the receipt recipe is currently untested).

---

## Recovery actually used (for the runbook)

```bash
PY=~/.pyenv/versions/3.13.9/bin/python3
uv pip uninstall --python "$PY" workbay                      # remove the PyPI 0.2.1 clobber
git clone https://github.com/darce/workbay.git /tmp/wb && cd /tmp/wb && git checkout v0.1.49
uv pip install --python "$PY" --no-deps --no-sources ./packages/workbay-system      # 0.3.16
uv pip install --python "$PY" --no-deps --no-sources ./packages/workbay-bootstrap   # 0.3.17
uv pip install --python "$PY" --no-deps "workbay-protocol @ git+…@<ref>#subdirectory=packages/workbay-protocol"  # 0.2.2
```

`--no-sources` from a **local clone** is the only path that worked. The uv-tool anchor (`workbay` 0.3.21 → 0.3.23) was **left un-upgraded on purpose**: reinstalling it requires the git recipe from Defect 3, and a failed `--force` would break the live MCP servers.

## Cross-references

- `docs/workbay/upstream-requests/2026-07-15-offload-lane-venv-workbay-protocol-skew/` — the `workbay_protocol` 0.2.0 skew that **Defect 2 causes**.
- `docs/workbay/upstream-requests/2026-07-13-hostgov-remote-backend-cost-class/` — the fix this upgrade was chasing (orchestrator 0.2.10 / `os_reserve_remote_api_gib`).
