# Upstream request — `apply-hooks` CLI crashes; reinject-hook wiring unreachable via supported path

**Target repo:** `agentic-protocol-monorepo` / `darce/workbay` (`workbay-bootstrap` installer).
**Consumer:** `context-alt-text-monorepo` (package-mode install, no `.workbay/remote` clone).
**Affected release:** `workbay-v0.3.18` — `workbay-bootstrap==0.3.14`, `workbay-system==0.3.12`, `workbay==0.3.18` (monorepo tag `v0.1.46`).
**Discovered while:** enabling semantic embeddings on a clean v0.1.46 install — `doctor` flagged `reinject_readiness_armed_not_wired` and told us to run the exact command that crashes.

## Summary

`workbay apply-hooks` (and the `workbay` front-door that routes through it) is **hard-broken** in bootstrap `0.3.14`. Every invocation, regardless of flags, aborts with a traceback before doing any work. Two independent defects stack on the same code path — fixing the first only exposes the second. Net effect: the **only supported way to wire the `SessionStart` reinject adapter is unreachable**, and `doctor` actively directs users into the crash.

There is no workaround through the CLI; we had to import and call the library function directly.

Worse, wiring the hook is not even sufficient: **Defect 4** shows that in a package-mode (uv-tool) consumer install the reinject hook can never reach the embeddings runtime, because its interpreter self-heal only probes a repo `.venv` / vendored `packages/.../src` that a consumer overlay does not have. So the end-to-end story "enable semantic embeddings" is currently unshippable to a package-mode consumer without manual intervention outside the documented surface.

---

## Defect 1 — `main()` reads `args.no_embeddings` for a subcommand that never defines it (`AttributeError`)

`cli.py::main()` handles the `apply-hooks` command at `cli.py:1222`:

```python
if args.command == "apply-hooks":
    manifest = apply_hooks(
        target=args.target,
        install_claude_stop_hook_local=args.install_claude_stop_hook_local,
        ...
        install_grok_ensure_agent_surfaces_hook=args.install_grok_ensure_agent_surfaces_hook,
        no_embeddings=args.no_embeddings,          # cli.py:1234
    )
```

But `--no-embeddings` is added **only** to the `install` parser (`cli.py:276`) and the `provision-embeddings` parser (`cli.py:772`). The `apply-hooks` subparser (`cli.py:589–639`) adds `--target` plus eight `--install-*` flags and nothing else — no `no_embeddings` attribute is ever set on its `Namespace`.

Result, every `apply-hooks` call:

```
File ".../workbay_bootstrap/cli.py", line 1234, in main
    no_embeddings=args.no_embeddings,
AttributeError: 'Namespace' object has no attribute 'no_embeddings'
```

The `workbay` front-door hits the identical failure — it forwards through `workbay/cli.py:84 → bootstrap_main → cli.py:1234`.

## Defect 2 — even with `args.no_embeddings` present, `apply_hooks()` rejects the kwarg (`TypeError`)

The dispatch passes `no_embeddings=` to the library function, but the function signature has no such parameter:

```
workbay_bootstrap.subcommands.apply_hooks(
    *, target, install_claude_stop_hook_local=False, install_codex_stop_hook=False,
    install_vscode_stop_hook=False, install_grok_stop_hook=False,
    install_claude_reinject_hook_local=False, install_codex_ensure_agent_surfaces_hook=False,
    install_vscode_ensure_agent_surfaces_hook=False, install_grok_ensure_agent_surfaces_hook=False,
) -> dict[str, object]
```

So the `cli.py:1234` line is wrong on **two** counts: it reads an attribute the parser never defines, and it forwards a keyword the callee never accepts. Patching only the parser (adding `--no-embeddings` to `apply-hooks`) turns the `AttributeError` into:

```
TypeError: apply_hooks() got an unexpected keyword argument 'no_embeddings'
```

The correct fix is to **drop `no_embeddings=args.no_embeddings` from the `apply-hooks` dispatch** (`cli.py:1234`) entirely — `apply_hooks()` neither needs nor supports it. (Confirm `cli.py:1294`, another `no_embeddings=args.no_embeddings` site, belongs to a subcommand whose parser actually defines the flag; if not, it has the same latent bug.)

## Defect 3 — `doctor` routes users straight into the crash

On a clean install with the embedding gate armed (`WORKBAY_REINJECT_SEMANTIC=1`), `doctor` emits:

```
reinject_readiness_armed_not_wired: .claude/settings — WORKBAY_REINJECT_SEMANTIC is armed
but the reinject-context SessionStart hook is not wired in settings*.json; semantic
reinjection is dead instrumentation until the hook is installed
(--install-claude-reinject-hook[-local])
```

The remediation it names is `apply-hooks --install-claude-reinject-hook-local` — which is exactly the crashing command. A user who follows `doctor`'s own advice on a fresh install hits a traceback with no hint that the tool, not their repo, is broken.

## Defect 4 (major, separate) — reinject hook cannot reach embeddings in package-mode installs

Even once the hook is wired (via the Defect 1–2 workaround) and the `[embeddings]` extra is installed, **the `SessionStart` reinject hook still cannot do semantic reinjection in a package-mode (uv-tool) consumer install.** The wiring is cosmetic; the runtime path is broken.

Root cause — interpreter resolution assumes artifacts a consumer install does not have:

- The hook command is `python3 "$CLAUDE_PROJECT_DIR/scripts/hooks/reinject-context.py"`. Under the harness that resolves to the ambient `python3` (here `~/.pyenv/shims/python3`), which has **no** real `workbay_handoff_mcp` (`import workbay_handoff_mcp.embeddings.reinjection` → `ModuleNotFoundError: No module named 'workbay_handoff_mcp.embeddings'`).
- `scripts/hooks/_interp.py::ensure_deps_interpreter()` self-heals by re-execing under a project **`.venv`** (`_venv_python()` probes `<toplevel>/.venv/bin/python` and the primary checkout's `.venv`). A package-mode consumer install has **no `.venv`** — the stack lives in `~/.local/share/uv/tools/mcp-workbay-handoff/`, which `_interp` never probes.
- `reinject-context.py::_ensure_in_repo_sources_on_path()` also prepends `packages/mcp-workbay-handoff/src` / `packages/workbay-protocol/src` — vendored source trees that exist in the **source monorepo**, not in a consumer overlay.

So the only interpreter the hook can find is one without the package, and the one interpreter that *does* have `[embeddings]` (the `mcp-workbay-handoff` uv-tool venv) is invisible to the resolution logic. The hook degrades to the lexical/duck-typed fallback and semantic reinjection silently never fires.

`doctor` sees the symptom but not the cause:

```
reinject_readiness_unavailable: (no .venv python found) — semantic reinject is wired and
armed but not ready: cannot import workbay_handoff_mcp.embeddings.reinjection via
(no .venv python found); remedy: install the runtime extra into that interpreter's venv:
`uv pip install 'mcp-workbay-handoff[embeddings]'` (or `uv sync --extra embeddings`)
```

The remedy it prints presupposes a `.venv` and a `pyproject`/`uv.lock`, neither of which a package-mode consumer has. There is **no documented package-mode path** to make the reinject hook reach embeddings.

**Ask:** teach `_interp`/`reinject-context.py` to discover the uv-tool interpreter that owns `mcp-workbay-handoff` (e.g. resolve the `mcp-workbay-handoff` console-script shebang, the same technique `scripts/workbay/update.sh` already uses to find the runtime), or support an explicit `WORKBAY_HANDOFF_PYTHON` / `WORKBAY_HANDOFF_BIN` override the hook honors before falling back to `.venv` probing. Then make `doctor`'s remedy string branch on install mode (`source_kind=package` vs a `.venv`-bearing dev checkout). Verified via console-script path that embeddings themselves work end-to-end (backfill stored 6,638 concept embeddings; `semantic-reinjection-packet` returns `status: selected`, cosine ~0.69) — only the *hook's* interpreter resolution is the gap.

## Defect 5 (minor, separate) — misleading `provision-embeddings` diagnostic

Unrelated to the crash but surfaced in the same session. On the `workbay` front-door venv, `provision-embeddings` prints:

```
embedding provision skipped: mcp-workbay-handoff is not importable; cannot read the
embedding digest pin — skipping provisioning (provider stays unconfigured)
```

`mcp-workbay-handoff` **is** importable in that venv (`importlib.util.find_spec('workbay_handoff_mcp')` → truthy). The real cause is that the embedding-digest module imports the `[embeddings]` runtime extra (`onnxruntime` / `tokenizers` / `numpy`), which the front-door venv lacks. The message should distinguish "package missing" from "optional embeddings extra missing" and name the actual remedy (`pip install 'mcp-workbay-handoff[embeddings]'`), instead of the false "not importable".

Related install-UX gap: a clean git-mirror install does not include the `[embeddings]` extra in the handoff uv-tool venv even when the model artifacts are provisioned and the gate is armed, so semantic reinjection is silently inert until the operator manually reinstalls the tool with the extra. Consider provisioning the extra alongside the model when the gate is enabled, or documenting the extra as a required step of "turn on embeddings".

---

## Consumer workaround (please obsolete)

- **Reinject hook (Defects 1–3):** bypassed the CLI by importing the library function directly from the front-door venv and calling it with no `no_embeddings`:

  ```python
  from workbay_bootstrap.subcommands import apply_hooks
  apply_hooks(target=".", install_claude_reinject_hook_local=True)
  ```

  This correctly merged the adapter into `.claude/settings.local.json`. Re-verify after each upgrade until the CLI is fixed.
- **Embeddings extra (Defect 5):** reinstalled the handoff uv tool with the extra:
  `uv tool install --no-sources --reinstall --from "mcp-workbay-handoff[embeddings] @ git+https://github.com/darce/workbay.git@workbay-v0.3.18#subdirectory=packages/mcp-workbay-handoff" ... mcp-workbay-handoff`
- **Reinject hook reachability (Defect 4):** unresolved — semantic reinjection works only through the `mcp-workbay-handoff` console; the `SessionStart` hook stays on the lexical fallback until `_interp` can find the uv-tool interpreter (or we stand up a repo `.venv` carrying `mcp-workbay-handoff[embeddings]` for the hook to self-heal into).

## Ask

1. **Fix the crash (Defects 1–2):** remove `no_embeddings=args.no_embeddings` from the `apply-hooks` dispatch at `cli.py:1234`; audit `cli.py:1294` for the same pattern. Add a smoke test that runs `apply-hooks --target <tmp> --install-claude-reinject-hook-local` end-to-end (the parser→dispatch→function boundary is currently untested, or the `Namespace`/signature mismatch would have failed CI).
2. **Fix the guidance (Defect 3):** ensure `doctor`'s remediation string names a command that actually runs; ideally have a clean install with the gate armed wire the reinject adapter itself.
3. **Make the reinject hook reach embeddings in package mode (Defect 4):** resolve the uv-tool interpreter that owns `mcp-workbay-handoff` (console-script shebang) or honor a `WORKBAY_HANDOFF_PYTHON`/`WORKBAY_HANDOFF_BIN` override in `_interp`/`reinject-context.py`; branch `doctor`'s remedy on `source_kind`. This is the actual blocker for "turn on embeddings" on a package-mode consumer.
4. **Fix the diagnostic + install UX (Defect 5):** correct the "not importable" message to distinguish a missing package from a missing optional extra, and provision the `[embeddings]` extra (or document it as required) when the embedding gate is enabled.
