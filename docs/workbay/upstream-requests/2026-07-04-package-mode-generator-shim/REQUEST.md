# Upstream request — package-mode-aware `generate_agent_workflows` shim

**Target repo:** `agentic-protocol-monorepo` / `darce/workbay` (`workbay-system` payload).
**Consumer:** `context-alt-text-monorepo` (package-mode install, no `.workbay/remote` clone).
**Affected release:** `workbay-system==0.3.4` (bundled in `workbay-v0.3.8`).

## Problem

In a **package-mode** install, `make generate-agent-workflows` and `make check-agent-workflows` fail out of the box.

Root cause chain (all in the hoisted `workbay-system` payload):

1. `scripts/_overlay_clone.py::overlay_payload_root()` resolves the generator **only** at `.workbay/remote/...` (git-clone mode) or via an explicit `$WORKBAY_OVERLAY_PAYLOAD` pin. Package-mode installs have neither, so `hoisted_generator_path()` returns `None`.
2. `scripts/generate_agent_workflows.py` (v0.3.4) then just prints *"workbay overlay not materialized (.workbay/remote absent) — run `workbay-bootstrap install`"* and exits 1. There is **no package-mode fallback** to the installed uv-tool payload.
3. `Makefile.d/workflows.mk` selects the bare-python shim (not the `uv run … workbay-overlay-tooling` entry point) whenever `<Makefile.d>/../../pyproject.toml` is absent — which is the case for every hoisted consumer. So the dep-complete entry point is never used in package mode.
4. Even setting `$WORKBAY_OVERLAY_PAYLOAD` to the uv-tool payload is not enough: the make target runs the full generator under the consumer's **system `python3`**, which cannot `import workbay_protocol` (`ImportError: cannot import name 'BRAND_SLUG'`). The generator's deps live only inside the uv-tool venv.

## Current consumer workaround (please obsolete)

`context-alt-text-monorepo` carries a local hand-patch in `scripts/generate_agent_workflows.py`: a `_installed_workbay_tool()` helper that locates `$(uv tool dir)/workbay/.../workbay_system/payload/scripts/generate_agent_workflows.py` and runs it with the **uv-tool's own python** (deps satisfied). This restores both make targets.

Because `scripts/generate_agent_workflows.py` is a bootstrap-managed **shared** surface, every `workbay update` / `install` re-clobbers the patch, so it must be re-applied after each upgrade. This is the churn we want removed.

## Ask

Make the overlay tooling package-mode-aware in `workbay-system` so consumers need no local patch. Any one of:

- **(preferred)** `generate_agent_workflows.py` gains a package-mode fallback: when `.workbay/remote` is absent, locate the installed uv-tool payload and invoke it with the uv-tool interpreter (the consumer's patch, upstreamed).
- OR `overlay_payload_root()` resolves the installed distribution's payload directly, **and** the shim execs it with an interpreter carrying the workbay deps (not bare system `python3`).
- OR `Makefile.d/workflows.mk` detects package mode and routes through the dep-complete `uv run … workbay-overlay-tooling generate-agent-workflows` entry point instead of the bare-python shim.

## Acceptance

On a fresh package-mode consumer (no `.workbay/remote`, no local patch), immediately after `workbay install`:

```
make generate-agent-workflows   # exit 0, writes adapters
make check-agent-workflows      # exit 0, facade + codex-router checks pass
```
