"""Artifact lock for the E15-28 demo-walkthrough Playwright proof pipeline.

`make demo-walkthrough-proof` -> evidence spec -> screenshots + manifest + a
smoke-log fragment rendered by a pure, unit-tested TS helper. This test pins the
wiring so the pipeline cannot silently lose a stage (renderer, spec, make target,
vitest discovery, runbook cross-reference).
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP = REPO_ROOT / "apps/prototype-wp-alt-context"
RENDERER = APP / "tests/e2e/fixtures/demo-smoke-log.ts"
RENDERER_TEST = APP / "tests/e2e/fixtures/demo-smoke-log.test.ts"
SPEC = APP / "tests/e2e/evidence/demo-walkthrough.spec.ts"
VITE_CONFIG = APP / "vite.config.ts"
DEPLOY_MK = REPO_ROOT / "mk/deploy.mk"
WALKTHROUGH_RUNBOOK = REPO_ROOT / "infra/oci/demo/walkthrough-runbook.md"

FRAGMENT_FILENAME = "demo-walkthrough-smoke-log-fragment.md"


def test_renderer_exports_pure_fragment_surface() -> None:
    text = RENDERER.read_text()
    assert "export const DEMO_WALKTHROUGH_FRAGMENT_FILENAME" in text
    assert f"'{FRAGMENT_FILENAME}'" in text
    assert "export const renderDemoSmokeLogFragment" in text
    assert "export interface DemoWalkthroughManifest" in text
    # Honest verdict axis: provenance gating is explicit in the contract.
    assert "constant_provenance_required" in text
    # Purity guard: the renderer must not read the clock or filesystem.
    assert "new Date(" not in text
    assert "node:fs" not in text


def test_renderer_has_unit_test() -> None:
    text = RENDERER_TEST.read_text()
    assert "renderDemoSmokeLogFragment" in text
    assert "Public demo walkthrough verdict" in text


def test_vitest_discovers_e2e_unit_tests() -> None:
    text = VITE_CONFIG.read_text()
    assert "tests/e2e/**/*.test.ts" in text


def test_spec_drives_walkthrough_and_emits_manifest_plus_fragment() -> None:
    text = SPEC.read_text()
    # Consumes the pure renderer + filename constant.
    assert "from '../fixtures/demo-smoke-log'" in text
    assert "renderDemoSmokeLogFragment" in text
    assert "DEMO_WALKTHROUGH_FRAGMENT_FILENAME" in text
    # Reuses the shared pairing probe rather than re-implementing it.
    assert "probeAcxConnection" in text
    # Emits both artifacts.
    assert "evidence-manifest.json" in text
    assert "demo-settings-provenance.png" in text
    # LocalWP opt-out for the provenance verdict axis is wired.
    assert "ACX_E2E_REQUIRE_CONSTANT_PROVENANCE" in text
    # The dead failure-string copied from the older spec must not regress back in.
    assert "Client could not submit this batch" not in text


def _phony_block(makefile_text: str) -> str:
    """Return the full ``.PHONY`` declaration, honoring backslash line continuations."""
    lines: list[str] = []
    capturing = False
    for line in makefile_text.splitlines():
        if line.lstrip().startswith(".PHONY"):
            capturing = True
        if capturing:
            lines.append(line)
            if not line.rstrip().endswith("\\"):
                break
    return "\n".join(lines)


def test_make_target_runs_evidence_project_against_demo_spec() -> None:
    text = DEPLOY_MK.read_text()
    assert "demo-walkthrough-proof:" in text
    assert "--project=evidence" in text
    assert "tests/e2e/evidence/demo-walkthrough.spec.ts" in text
    assert "demo-walkthrough-proof" in _phony_block(text)
    # Fresh-checkout runnability: the target guards missing deps and ensures the browser
    # rather than dying at exit 127 / a headless Chromium launch with no message.
    assert "node_modules" in text
    assert "npm run e2e:install" in text


def test_runbook_points_operators_at_the_make_target() -> None:
    text = WALKTHROUGH_RUNBOOK.read_text()
    assert "make demo-walkthrough-proof" in text
