"""DEFWAVE-2 regression tests for recursive weight-exclusion patterns."""

from __future__ import annotations

from recognition.tests.deploy import test_dockerignore_weight_exclusions as weight_exclusions


def test_rsync_double_star_patterns_are_recursive() -> None:
    assert weight_exclusions._is_rsync_depth_recursive_pattern("**/*.bin")
    assert weight_exclusions._is_rsync_depth_recursive_pattern("**/models--*/")


def test_rsync_double_star_patterns_cover_weight_classes() -> None:
    script = (
        "rsync -az --exclude='**/*.bin' "
        "--exclude='**/models--*/' src/ dst/\n"
    )

    assert weight_exclusions.rsync_weight_classes(script) == {"bin", "models--"}


def test_uncertain_positive_docker_pattern_does_not_claim_weight_coverage() -> None:
    assert weight_exclusions.docker_weight_classes("[a-z].bin\n") == set()


def test_uncertain_docker_negation_still_fails_closed_for_weight_coverage() -> None:
    body = "**/*.bin\n![a-z].bin\n"

    assert weight_exclusions.docker_weight_classes(body) == set()


def test_filename_specific_docker_exclude_does_not_claim_bin_class() -> None:
    assert weight_exclusions.docker_weight_classes("**/pytorch_model.bin\n") == set()


def test_bin_class_requires_all_representatives_after_last_match_wins() -> None:
    body = "**/pytorch_model.bin\n**/adapter_model.bin\n"

    assert weight_exclusions.docker_weight_classes(body) == {"bin"}


def test_reincluding_one_bin_representative_unprotects_the_class() -> None:
    body = "**/*.bin\n!**/pytorch_model.bin\n"

    assert "bin" not in weight_exclusions.docker_weight_classes(body)
