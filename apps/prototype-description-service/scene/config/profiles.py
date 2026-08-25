"""Operator-facing description profiles (E19-1 S11).

One switch — ``ACX_DESCRIPTION_ADAPTER`` — selects a *profile*, and the registry
below resolves each profile to a concrete adapter spec (provenance kind, model
id/revision/version, decode params). Profiles are the deployment knob; the wire
``adapter`` provenance kind stays the coarse vocabulary (``seeded``/``local_cpu``/
``gpu``) while ``model_id``/``model_version`` distinguish the Florence size.

Benchmarked winners (OCI A1 CPU, see
``docs/tasks/19.0/E19-1-local-cpu-vlm-benchmark-decision-memo.md``):
  - ``florence_small`` (Florence-2-base-ft) ~14s mean — under the 20s inline bar.
  - ``florence_large`` (Florence-2-large-ft) ~39s — quality ceiling, **async-worker
    only**, shipped here as a fail-closed stub (deferred; see impl notes).
  - ``gpu_phi4`` (Phi-4-multimodal-instruct) ~900s on A1 CPU — **GPU-only**, stub.

Deferred-work design notes:
``docs/tasks/19.0/E19-1-florence-large-async-worker-impl-notes.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from scene.domain.description import DescriptionAdapterKind

_ASYNC_NOTES = "docs/tasks/19.0/E19-1-florence-large-async-worker-impl-notes.md"


class DescriptionProfile(StrEnum):
    """The operator-selectable description backends."""

    SEEDED = "seeded"
    FLORENCE_SMALL = "florence_small"
    FLORENCE_LARGE = "florence_large"
    GPU_PHI4 = "gpu_phi4"
    GPU_QWEN30B = "gpu_qwen30b"
    GPU_QWEN30B_ENSEMBLE = "gpu_qwen30b_ensemble"
    HOSTED_GPT4O = "hosted_gpt4o"


@dataclass(frozen=True)
class ProfileSpec:
    """How one profile maps to an adapter. ``available=False`` => fail-closed stub."""

    profile: DescriptionProfile
    adapter_kind: DescriptionAdapterKind
    available: bool
    model_id: str | None = None
    model_revision: str | None = None
    model_version: str = "1"
    num_beams: int | None = None
    max_new_tokens: int | None = None
    unavailable_reason: str | None = None


PROFILE_SPECS: dict[DescriptionProfile, ProfileSpec] = {
    DescriptionProfile.SEEDED: ProfileSpec(
        profile=DescriptionProfile.SEEDED,
        adapter_kind=DescriptionAdapterKind.SEEDED,
        available=True,
        model_id=None,
    ),
    DescriptionProfile.FLORENCE_SMALL: ProfileSpec(
        profile=DescriptionProfile.FLORENCE_SMALL,
        adapter_kind=DescriptionAdapterKind.LOCAL_CPU,
        available=True,
        model_id="microsoft/Florence-2-base-ft",
        # Pin the trust_remote_code model + remote code to the benchmarked commit.
        model_revision="f6c1a25888ffc1d945ee8a1a77ac833c7303d46e",
        model_version="florence-2-base-ft",
        num_beams=3,
        max_new_tokens=512,
    ),
    DescriptionProfile.FLORENCE_LARGE: ProfileSpec(
        profile=DescriptionProfile.FLORENCE_LARGE,
        adapter_kind=DescriptionAdapterKind.LOCAL_CPU,
        available=False,
        model_id="microsoft/Florence-2-large-ft",
        model_revision=None,  # pin on enablement; see impl notes
        model_version="florence-2-large-ft",
        num_beams=3,
        max_new_tokens=512,
        unavailable_reason=(
            "florence_large (~39s/image on OCI A1 CPU) exceeds the 20s inline budget; "
            f"enable only behind the async describe worker (deferred). See {_ASYNC_NOTES}."
        ),
    ),
    DescriptionProfile.GPU_PHI4: ProfileSpec(
        profile=DescriptionProfile.GPU_PHI4,
        adapter_kind=DescriptionAdapterKind.GPU,
        available=False,
        model_id="microsoft/Phi-4-multimodal-instruct",
        model_revision=None,
        model_version="phi-4-multimodal-instruct",
        unavailable_reason=(
            "gpu_phi4 (~900s/image on A1 CPU, ~60x Florence) requires a GPU host; "
            f"stub pending GPU deployment. See {_ASYNC_NOTES}."
        ),
    ),
    DescriptionProfile.GPU_QWEN30B: ProfileSpec(
        profile=DescriptionProfile.GPU_QWEN30B,
        adapter_kind=DescriptionAdapterKind.GPU,
        available=True,
        model_id="Qwen3-VL-30B-A3B-Instruct",
        # Served artifact is the Q4_K_M GGUF, not the unquantized transformers
        # snapshot. Pin the hub revision of unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF
        # (SEC-10). Resolved live via huggingface_hub.HfApi().model_info.
        model_revision="0af19e7479857aa7f3246466a4ad16c7e7299639",
        model_version="Q4_K_M",
    ),
    # VLM-4 Slice 2b: same endpoint/model as GPU_QWEN30B. Only the ASYNC
    # GPU-final resolver (get_async_gpu_description_adapter) wraps this profile
    # in EnsembleDescriptionAdapter; the sync route stays raw (VLM4-RA-BR-02).
    DescriptionProfile.GPU_QWEN30B_ENSEMBLE: ProfileSpec(
        profile=DescriptionProfile.GPU_QWEN30B_ENSEMBLE,
        adapter_kind=DescriptionAdapterKind.GPU,
        available=True,
        model_id="Qwen3-VL-30B-A3B-Instruct",
        model_revision="0af19e7479857aa7f3246466a4ad16c7e7299639",
        model_version="Q4_K_M",
    ),
    DescriptionProfile.HOSTED_GPT4O: ProfileSpec(
        profile=DescriptionProfile.HOSTED_GPT4O,
        adapter_kind=DescriptionAdapterKind.HOSTED_PROVIDER,
        available=False,  # fail-closed: image bytes leave the service boundary (E20-11)
        model_id="gpt-4o-mini",
        model_revision=None,
        model_version="gpt-4o-mini",
        unavailable_reason=(
            "hosted_gpt4o sends image bytes to a third-party provider; opt in explicitly "
            "with ACX_HOSTED_PROVIDER_OPTIN=1 (server-side, eval/benchmark use only)."
        ),
    ),
}


def get_profile_spec(profile: DescriptionProfile) -> ProfileSpec:
    """Return the registry spec for ``profile`` (total over the enum)."""
    return PROFILE_SPECS[profile]
