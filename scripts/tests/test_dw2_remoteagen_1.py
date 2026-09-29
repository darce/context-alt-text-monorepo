from scripts.tests import test_remote_agent_origin_guard as origin_guard


def test_origin_guard_fragments_are_available_without_operator_overlay() -> None:
    guard = origin_guard._origin_guard_block()
    attestation = origin_guard._phase_attestation_block()

    assert "_assert_lane_venv_origin" in guard
    assert "skipped_no_guarded_roots" in guard
    assert "venv_origin_shadow" in guard
    assert "origin_ok" in attestation
    assert "origin_guard" in attestation
