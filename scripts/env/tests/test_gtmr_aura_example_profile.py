"""GTMR RED: semantic contract for the AuraFace example profile (P2M-AURA-EXAMPLE-01).

The committed apps/prototype-description-service/.env.auraface.example is the template an
operator copies for each AuraFace label. Its RECOGNITION_FACE_PIPELINE_PROFILE must select
the AuraFace model space, not the generic face_pipeline (SFace) space, and it must pair that
profile with PGVECTOR_DIM=512.

check_example equality cannot catch this defect: the example and the generated comparison
both derive from the same shared var default, so a wrong value still matches the render.
The oracle here is the runtime behaviour instead: runtime_factory branches on
ModelSpace(profile) is ModelSpace.AURAFACE, and the leaf enum is loaded by path so the
application package import graph is not pulled in.

The RED test fails against unchanged source (the example renders face_pipeline beside 512).
The two controls must pass before and after the repair: they prove the oracle accepts the
runtime AuraFace values and that the generic FIR example keeps its SFace 128 selection.
Environment labels and resource names are proposed configuration, not observed resources.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from conftest import load_module

manifest_api = load_module("manifest")
render_api = load_module("render_env")

REPO = Path(__file__).resolve().parents[3]
MANIFEST_ROOT = REPO / "config" / "env"
APP = REPO / "apps" / "prototype-description-service"
AURA_EXAMPLE = APP / ".env.auraface.example"
FIR_EXAMPLE = APP / ".env.fir.example"
MODEL_SPACE_LEAF = APP / "recognition" / "infrastructure" / "face_pipeline" / "model_space.py"

AURA_LABELS = ("dev-auraface", "staging-auraface", "prod-auraface")
PROFILE = "RECOGNITION_FACE_PIPELINE_PROFILE"
DIMENSION = "PGVECTOR_DIM"


def _model_space():
    """Return the runtime ModelSpace enum, loaded from its stdlib-only leaf module by path."""
    spec = importlib.util.spec_from_file_location("gtmr_aura_example_model_space", MODEL_SPACE_LEAF)
    assert spec is not None and spec.loader is not None, f"cannot load {MODEL_SPACE_LEAF}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ModelSpace


def _assignments(text: str) -> dict[str, str]:
    """Effective dotenv values: the last assignment of each name wins, as the loader applies it."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip("'\"")
    return values


def _selection_gaps(label: str, profile: str | None, dimension: str | None) -> list[str]:
    """Judge a (profile, dimension) pair by what the runtime does with it.

    runtime_factory selects the AuraFace embedder only when ModelSpace(profile) is AURAFACE;
    any other profile lands on the SFace face_pipeline space, which is 128-dimensional.
    """
    space_enum = _model_space()
    if profile is None:
        return [f"{label}: {PROFILE} is absent"]
    try:
        space = space_enum(profile)
    except ValueError:
        return [f"{label}: {PROFILE}={profile!r} selects no model space"]
    gaps: list[str] = []
    if space is not space_enum.AURAFACE:
        gaps.append(f"{label}: {PROFILE}={profile!r} selects {space.value}, not auraface")
    if dimension != "512":
        gaps.append(f"{label}: {DIMENSION}={dimension!r} is not 512")
    return gaps


def _real_manifest():
    return manifest_api.load_manifest(MANIFEST_ROOT)


def _aura_target(manifest) -> str:
    names = sorted(name for name, target in manifest.targets.items() if set(target.envs) & set(AURA_LABELS))
    assert len(names) == 1, f"expected exactly one Aura target, found {names or 'none'}"
    return names[0]


def _runtime_values(manifest, target: str, label: str) -> dict[str, str]:
    """Values the runtime file for one Aura label receives from the manifest render."""
    text = render_api.render_target(
        manifest,
        target,
        label,
        resolve=lambda name, reference: f"fake({name})",
        missing_host_keys=set(),
    )
    return _assignments(text)


# ---------------------------------------------------------------------------
# RED: the committed AuraFace example must select the AuraFace space (real files)
# ---------------------------------------------------------------------------


def test_auraface_example_profile_selects_auraface_space_for_every_label():
    manifest = _real_manifest()
    target = _aura_target(manifest)
    example = _assignments(AURA_EXAMPLE.read_text(encoding="utf-8"))
    gaps = _selection_gaps("svc-auraface example", example.get(PROFILE), example.get(DIMENSION))
    for label in AURA_LABELS:
        runtime_profile = _runtime_values(manifest, target, label).get(PROFILE)
        if example.get(PROFILE) != runtime_profile:
            gaps.append(
                f"example {PROFILE}={example.get(PROFILE)!r} differs from {label} runtime {runtime_profile!r}"
            )
    assert not gaps, "\n".join(gaps)


# ---------------------------------------------------------------------------
# Healthy controls: must pass against unchanged source and after the repair
# ---------------------------------------------------------------------------


def test_runtime_render_of_each_aura_label_selects_auraface_at_512():
    manifest = _real_manifest()
    target = _aura_target(manifest)
    gaps: list[str] = []
    for label in AURA_LABELS:
        runtime = _runtime_values(manifest, target, label)
        gaps += _selection_gaps(label, runtime.get(PROFILE), runtime.get(DIMENSION))
    assert not gaps, "\n".join(gaps)


def test_generic_fir_example_keeps_its_sface_128_selection():
    example = _assignments(FIR_EXAMPLE.read_text(encoding="utf-8"))
    space_enum = _model_space()
    assert example.get(PROFILE) == "face_pipeline", example.get(PROFILE)
    assert space_enum(example[PROFILE]) is space_enum.FACE_PIPELINE
    assert example.get(DIMENSION) == "128", example.get(DIMENSION)
    assert "RECOGNITION_AURAFACE_MODELS_DIR" not in example
