"""FB1-S4-01: synthetic, independently labelled path evidence; no real observations.

Canon v0.26.2 GRPH-18 (Never trust the transitive closure of a raw similarity
threshold, Introduction to Information Retrieval, § 17.2) asks for held-out
verified-different path links, not a hierarchical clustering method.
"""

from __future__ import annotations

from fractions import Fraction
from itertools import combinations, permutations

import numpy as np
import pytest

from scripts.eval_harness import firbench_clusters as fcl
from scripts.eval_harness import firbench_contract as fc


def _face(face_id, identity, *, status=fc.IdentityStatus.named, verified=True, fold=0):
    return fcl.LegFace(face_id, identity, status, fold, f"fake-independent-qc:{face_id}" if verified else None)


def _input(pairs=(("a", "b"),)):
    return fcl.ChainingInput("fake-held-out-frame", 0, "predeclared fake GT pairs", pairs)


def _graph_vectors(count, edges):
    # Strictly diagonally dominant Gram matrix: real cosine geometry for any
    # small graph, independent of the producer's traversal implementation.
    gram = np.eye(count)
    for left, right in edges:
        gram[left, right] = gram[right, left] = 0.1
    return np.linalg.cholesky(gram)


def _check(faces, edges, *, chaining=None, order=None):
    vectors = _graph_vectors(len(faces), edges)
    if order is not None:
        faces = tuple(faces[index] for index in order)
        vectors = vectors[list(order)]
    return fcl.chaining_check(
        vectors, faces, similarity_threshold=0.05, chaining=_input() if chaining is None else chaining
    )


def _inspect(data, faces, edges):
    by_id = {face.face_id: face for face in faces}
    vectors = _graph_vectors(len(faces), edges)
    similarity = vectors @ vectors.T
    row = {face.face_id: index for index, face in enumerate(faces)}
    for record in data["pairs"]:
        path = record["path"]
        if path is None:
            assert not record["path_linked"]
            assert record["edges"] == []
            continue
        ids = [node["face_id"] for node in path]
        assert ids[0] == record["left"]["face_id"]
        assert ids[-1] == record["right"]["face_id"]
        assert len(ids) == len(set(ids))  # No detours out and back masquerading as a path.
        for node in path:
            face = by_id[node["face_id"]]
            assert node == {
                "face_id": face.face_id,
                "identity_id": face.identity_id,
                "identity_status": face.identity_status.value,
                "verification_ref": face.verification_ref,
            }
        assert len(record["edges"]) == len(path) - 1
        for edge, left, right in zip(record["edges"], ids, ids[1:], strict=False):
            assert (edge["source_face_id"], edge["target_face_id"]) == (left, right)
            assert edge["cosine_similarity"] == pytest.approx(similarity[row[left], row[right]], abs=1e-12)
            assert edge["cosine_similarity"] >= 0.05
        if record["through_third_identity"]:
            third = record["third_identity_id"]
            assert third not in (record["left"]["identity_id"], record["right"]["identity_id"])
            assert any(
                node["identity_id"] == third and node["identity_status"] == "named" and node["verification_ref"]
                for node in path[1:-1]
            )


@pytest.mark.parametrize(
    ("identity", "status", "verified", "expected_c"),
    [
        ("C", fc.IdentityStatus.named, False, 0),
        (None, fc.IdentityStatus.unknown, False, 0),
        (None, fc.IdentityStatus.unresolved, False, 0),
        (None, fc.IdentityStatus.unknown, True, 0),
        (None, fc.IdentityStatus.unresolved, True, 0),
        ("A", fc.IdentityStatus.named, True, 0),
        ("B", fc.IdentityStatus.named, True, 0),
        ("C", fc.IdentityStatus.named, True, 1),
    ],
)
def test_middle_needs_its_own_verified_third_identity(identity, status, verified, expected_c):
    faces = (_face("a", "A"), _face("b", "B"), _face("c", identity, status=status, verified=verified))
    edges = ((0, 2), (2, 1))
    result = _check(faces, edges)
    assert result.status == "available"
    data = result.data
    assert (data["input_pairs"], data["eligible_pairs"], data["path_linked_pairs"]) == (1, 1, 1)
    assert data["third_identity_linked_pairs"] == expected_c
    assert data["D"].data == 1.0
    assert data["C"].data == float(Fraction(expected_c, 1))
    assert data["pairs"][0]["third_identity_id"] == ("C" if expected_c else None)
    _inspect(data, faces, edges)


@pytest.mark.parametrize("direct", [False, True])
def test_alternative_verified_path_counts_even_when_shortest_bypasses_it(direct):
    faces = (_face("a", "A"), _face("b", "B"), _face("c", "A"), _face("d", "D"))
    edges = ((0, 2), (2, 1), (0, 3), (3, 1)) + (((0, 1),) if direct else ())
    data = _check(faces, edges).data
    assert (data["eligible_pairs"], data["path_linked_pairs"], data["third_identity_linked_pairs"]) == (1, 1, 1)
    assert data["pairs"][0]["third_identity_id"] == "D"
    _inspect(data, faces, edges)


def test_third_in_dangling_branch_does_not_establish_a_simple_endpoint_path():
    faces = (_face("a", "A"), _face("b", "B"), _face("c", "A"), _face("d", "D"))
    edges = ((0, 2), (2, 1), (2, 3))
    data = _check(faces, edges).data
    assert (data["path_linked_pairs"], data["third_identity_linked_pairs"]) == (1, 0)
    _inspect(data, faces, edges)


@pytest.mark.parametrize("verified", [False, True])
def test_stable_ids_determine_witness_and_geometry_under_every_row_permutation(verified):
    faces = (
        _face("a", "A"),
        _face("b", "B"),
        _face("c", "C", verified=verified),
        _face("d", "D", verified=verified),
    )
    edges = ((0, 2), (2, 1), (0, 3), (3, 1))
    expected = _check(faces, edges).to_json()
    assert expected["data"]["pairs"][0]["third_identity_id"] == ("C" if verified else None)
    for order in permutations(range(4)):
        result = _check(faces, edges, order=order)
        assert result.to_json() == expected
        _inspect(result.data, faces, edges)


def test_all_five_node_graphs_match_independent_simple_path_oracle():
    faces = (_face("a", "A"), _face("b", "B"), _face("c", "A"), _face("d", "D"), _face("e", "E"))
    possible = tuple(combinations(range(5), 2))
    for mask in range(1 << len(possible)):
        edges = tuple(edge for bit, edge in enumerate(possible) if mask & (1 << bit))
        paths = []
        for length in range(4):
            for middle in permutations((2, 3, 4), length):
                path = (0, *middle, 1)
                if all(tuple(sorted(edge)) in edges for edge in zip(path, path[1:], strict=False)):
                    paths.append(path)
        expected_c = int(any(3 in path or 4 in path for path in paths))
        data = _check(faces, edges).data
        assert (data["eligible_pairs"], data["path_linked_pairs"], data["third_identity_linked_pairs"]) == (
            1,
            int(bool(paths)),
            expected_c,
        ), (mask, paths, data)
        _inspect(data, faces, edges)


@pytest.mark.parametrize("pairs", [(("a", "b"), ("a", "b")), (("a", "b"), ("b", "a"))])
def test_duplicate_unordered_declared_pairs_are_refused(pairs):
    with pytest.raises(fc.FrameContractError):
        _input(pairs)


@pytest.mark.parametrize(
    "pairs",
    [
        None,
        7,
        "ab",
        {"a": "b"},
        {("a", "b")},
        (None,),
        (7,),
        ("ab",),
        (("a",),),
        (("a", "b", "c"),),
        (("a", 7),),
        (("a", " "),),
        (("a", "a"),),
    ],
)
def test_malformed_pair_declarations_raise_contract_error(pairs):
    with pytest.raises(fc.FrameContractError):
        _input(pairs)


def test_pair_declaration_is_frozen_and_canonical_after_validation():
    pairs = [["b", "a"]]
    chaining = _input(pairs)
    pairs.append(["a", "b"])
    assert chaining.candidate_pairs == (("a", "b"),)


@pytest.mark.parametrize("chaining", [None, {}, "bad", 7])
def test_standalone_check_requires_chaining_input(chaining):
    with pytest.raises(fc.FrameContractError):
        fcl.chaining_check(np.eye(2), (_face("a", "A"), _face("b", "B")), similarity_threshold=0.5, chaining=chaining)


@pytest.mark.parametrize("faces", [None, 7, "ab", {}, (None, None), ({}, {}), (_face("a", "A"),)])
def test_malformed_standalone_faces_raise_contract_error(faces):
    with pytest.raises(fc.FrameContractError):
        fcl.chaining_check(np.eye(2), faces, similarity_threshold=0.5, chaining=_input())


def test_duplicate_face_id_cannot_overwrite_verification_or_vector_lookup():
    faces = (_face("a", "A", verified=False), _face("b", "B"), _face("a", "C"))
    with pytest.raises(fc.FrameContractError):
        _check(faces, ((0, 1), (1, 2)))


def test_fixed_eligible_denominator_and_exclusions_do_not_depend_on_geometry():
    faces = (
        _face("a", "A"),
        _face("b", "B"),
        _face("c", "C"),
        _face("same", "A"),
        _face("unverified", "X", verified=False),
        _face("fit", "F", fold=1),
        _face("unknown", None, status=fc.IdentityStatus.unknown),
        _face("unresolved", None, status=fc.IdentityStatus.unresolved),
    )
    pairs = tuple(("a", other) for other in ("b", "c", "same", "unverified", "fit", "unknown", "unresolved", "missing"))
    chaining = _input(pairs)
    for edges, expected_d in [((), 0), (tuple(combinations(range(len(faces)), 2)), 2)]:
        data = _check(faces, edges, chaining=chaining).data
        assert (data["input_pairs"], data["eligible_pairs"], data["path_linked_pairs"]) == (8, 2, expected_d)
        assert data["D"].data == float(Fraction(expected_d, 2))
        assert data["exclusions"] == [
            {"reason": reason, "count": 1}
            for reason in (
                "same_verified_identity",
                "unknown_identity",
                "unresolved_identity",
                "unverified_endpoint",
                "not_held_out",
                "missing_vector",
            )
        ]


@pytest.mark.parametrize("pairs", [(), (("a", "missing"),), (("a", "c"),)])
def test_zero_eligible_is_absence_of_rate_never_zero_risk(pairs):
    faces = (_face("a", "A"), _face("b", "B"), _face("c", "C", verified=False))
    data = _check(faces, ((0, 1), (1, 2)), chaining=_input(pairs)).data
    assert (data["eligible_pairs"], data["path_linked_pairs"], data["third_identity_linked_pairs"]) == (0, 0, 0)
    assert data["pairs"] == []
    for rate in ("D", "C"):
        assert data[rate].to_json() == {"status": "unavailable", "reason": "no eligible pairs", "data": None}
