"""S1: deterministic cache-key hashing primitives (pure, no HTTP/DB/model)."""

from scene.application.hashing import compute_context_hash, compute_image_hash


def test_image_hash_stable_for_identical_bytes():
    data = b"\x89PNG\r\n fake image bytes"
    assert compute_image_hash(data) == compute_image_hash(data)


def test_image_hash_differs_for_different_bytes():
    assert compute_image_hash(b"a") != compute_image_hash(b"b")


def test_image_hash_is_hex_sha256():
    digest = compute_image_hash(b"x")
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_context_hash_insensitive_to_key_order():
    a = {"title": "Cat", "caption": "A cat", "tags": ["a", "b"]}
    b = {"caption": "A cat", "tags": ["a", "b"], "title": "Cat"}
    assert compute_context_hash(a) == compute_context_hash(b)


def test_context_hash_insensitive_to_nested_key_order():
    a = {"wp": {"title": "Cat", "caption": "x"}}
    b = {"wp": {"caption": "x", "title": "Cat"}}
    assert compute_context_hash(a) == compute_context_hash(b)


def test_context_hash_differs_on_value_change():
    assert compute_context_hash({"title": "Cat"}) != compute_context_hash({"title": "Dog"})


def test_context_hash_empty_and_none_are_equivalent_and_stable():
    assert compute_context_hash(None) == compute_context_hash({})
    assert len(compute_context_hash(None)) == 64
