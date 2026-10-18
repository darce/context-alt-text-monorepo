"""Adversarial DAG-ingest regressions ([TEST-15])."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.bench import corpus as corpus_mod
from scripts.bench import driver as driver_mod
from scripts.bench.corpus import ItemOutcomeStore, resolve_media_bytes
from scripts.bench.driver import init_run_dir, run_leg
from scripts.bench.stack_pair import BenchError, load_stack_pair
from scripts.bench.tests.conftest import FakeClient, minimal_entry, png_bytes, valid_pair_dict, write_pair
from scripts.eval_harness.manifest import GoldenEntry, ManifestError, resolve_image_path


def _write_manifest(path: Path, entry: dict) -> Path:
    path.write_text(
        json.dumps(
            {
                "manifest_version": 3,
                "annotation_mode": "exhaustive",
                "roster": [],
                "entries": [entry],
            }
        ),
        encoding="utf-8",
    )
    return path


def _entry(*, path: str, sha256: str, url: str | None = None) -> dict:
    entry = minimal_entry(1, path=path, sha256=sha256, face_count=0, present_identities=[], face_boxes=[])
    if url is not None:
        entry["provenance"]["url"] = url
    return entry


def _run_ingest_case(
    tmp_path: Path,
    entry: dict,
    *,
    images_dir: Path,
    item_max_attempts: int = 1,
    url_map_path: Path | None = None,
    resolver=None,
    fetcher=None,
    monkeypatch: pytest.MonkeyPatch | None = None,
) -> tuple[FakeClient, list[dict]]:
    manifest_path = _write_manifest(tmp_path / "manifest.json", entry)
    pair = load_stack_pair(
        write_pair(
            tmp_path / "pair.yaml",
            valid_pair_dict(item_max_attempts=item_max_attempts, media_url_map_path=str(url_map_path) if url_map_path else None),
        )
    )
    run_dir = init_run_dir(tmp_path / "run", pair, manifest_path)
    client = FakeClient()
    if monkeypatch is not None and (resolver is not None or fetcher is not None):
        def resolve_with_test_transport(entry, images_dir, **kwargs):
            return corpus_mod.resolve_media_bytes(
                entry,
                images_dir,
                resolver=resolver,
                fetcher=fetcher,
                **kwargs,
            )

        monkeypatch.setattr(driver_mod, "resolve_media_bytes", resolve_with_test_transport)
    run_leg(
        pair.endpoint("acx-dev-insightface"),
        pair,
        manifest_path=manifest_path,
        images_dir=images_dir,
        run_dir=run_dir,
        client=client,
    )
    records = ItemOutcomeStore(run_dir / "legs" / "acx-dev-insightface" / "items.jsonl").read_all()
    return client, records


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "/outside.jpg",
        "../outside.jpg",
        "nested/../../outside.jpg",
        r"\outside.jpg",
        r"C:\outside.jpg",
        r"C:outside.jpg",
        r"..\outside.jpg",
        r"\\server\share\outside.jpg",
    ],
)
def test_unsafe_path_spellings_fail_before_missing_root_fallback(tmp_path: Path, unsafe_path: str) -> None:
    """A missing local root may signal remote fallback, never path escape."""
    with pytest.raises(ManifestError, match="relative") as exc:
        resolve_image_path(tmp_path / "missing-images", unsafe_path)
    assert exc.value.invariant == "image_path_containment"


def test_nested_file_and_in_root_symlink_resolve(tmp_path: Path) -> None:
    payload = png_bytes(9, 7)
    images = tmp_path / "images"
    real = images / "nested" / "real.jpg"
    real.parent.mkdir(parents=True)
    real.write_bytes(payload)
    link = real.parent / "link.jpg"
    link.symlink_to(real)

    entry = GoldenEntry(**_entry(path="nested/link.jpg", sha256=hashlib.sha256(payload).hexdigest()))
    assert resolve_image_path(images, "nested/real.jpg") == real.resolve()
    assert resolve_image_path(images, "nested/link.jpg") == real.resolve()
    assert resolve_media_bytes(entry, images) == payload


def test_local_hash_mismatch_fails_before_client_upload(tmp_path: Path) -> None:
    images = tmp_path / "images"
    actual = png_bytes(8, 8)
    local = images / "nested" / "bad.jpg"
    local.parent.mkdir(parents=True)
    local.write_bytes(actual)
    expected = hashlib.sha256(b"different-content").hexdigest()

    client, records = _run_ingest_case(
        tmp_path,
        _entry(path="nested/bad.jpg", sha256=expected),
        images_dir=images,
    )

    assert client.analyze_calls == []
    failed = [record for record in records if record.get("phase") == "ingest"][-1]
    assert failed["outcome"] == "failed"
    assert failed["error_code"] == "media_unresolvable"
    assert failed["terminal_ingest_outcome"] != "success"


def test_symlink_escape_fails_before_client_upload(tmp_path: Path) -> None:
    payload = png_bytes(8, 8)
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(payload)
    images = tmp_path / "images"
    images.mkdir()
    (images / "nested").mkdir()
    (images / "nested" / "escape.jpg").symlink_to(outside)

    client, records = _run_ingest_case(
        tmp_path,
        _entry(path="nested/escape.jpg", sha256=hashlib.sha256(payload).hexdigest()),
        images_dir=images,
    )

    assert client.analyze_calls == []
    failed = [record for record in records if record.get("phase") == "ingest"][-1]
    assert failed["error_code"] == "media_unresolvable"
    assert failed["manifest_path"] == "nested/escape.jpg"


def test_remote_hash_mismatch_fails_before_client_upload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    corpus_mod.reset_media_host_pins()
    wrong = b"remote-but-wrong"
    expected = hashlib.sha256(b"remote-expected").hexdigest()

    def resolver(_host: str) -> list[str]:
        return ["93.184.216.34"]

    def fetcher(_url: str, _addresses: set[str]) -> bytes:
        return wrong

    client, records = _run_ingest_case(
        tmp_path,
        _entry(path="remote.jpg", sha256=expected, url="https://remote-hash.example/media.jpg"),
        images_dir=tmp_path / "missing-images",
        resolver=resolver,
        fetcher=fetcher,
        monkeypatch=monkeypatch,
    )

    assert client.analyze_calls == []
    failed = [record for record in records if record.get("phase") == "ingest"][-1]
    assert failed["error_code"] == "media_unresolvable"
    assert failed["terminal_ingest_outcome"] != "success"


def test_malformed_media_map_fails_before_dns_or_client_upload(tmp_path: Path) -> None:
    media_map = tmp_path / "media-map.json"
    media_map.write_text("[]", encoding="utf-8")

    client, records = _run_ingest_case(
        tmp_path,
        _entry(path="mapped.jpg", sha256=hashlib.sha256(b"expected").hexdigest()),
        images_dir=tmp_path / "missing-images",
        url_map_path=media_map,
    )

    assert client.analyze_calls == []
    failed = [record for record in records if record.get("phase") == "ingest"][-1]
    assert failed["error_code"] == "media_resource_failed"
    assert failed["terminal_ingest_outcome"] != "success"


def test_missing_media_map_file_is_terminal_ingest_failure(tmp_path: Path) -> None:
    missing_map = tmp_path / "missing-media-map.json"
    client, records = _run_ingest_case(
        tmp_path,
        _entry(path="mapped.jpg", sha256=hashlib.sha256(b"expected").hexdigest()),
        images_dir=tmp_path / "missing-images",
        url_map_path=missing_map,
    )

    assert client.analyze_calls == []
    failed = [record for record in records if record.get("phase") == "ingest"][-1]
    assert failed["error_code"] == "media_resource_failed"
    assert failed["terminal_ingest_outcome"] != "success"


def test_remote_dns_failure_is_terminal_ingest_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    corpus_mod.reset_media_host_pins()

    def resolver(_host: str) -> list[str]:
        raise OSError("DNS unavailable")

    client, records = _run_ingest_case(
        tmp_path,
        _entry(path="dns.jpg", sha256=hashlib.sha256(b"expected").hexdigest(), url="https://dns-failure.example/media.jpg"),
        images_dir=tmp_path / "missing-images",
        resolver=resolver,
        monkeypatch=monkeypatch,
    )

    assert client.analyze_calls == []
    failed = [record for record in records if record.get("phase") == "ingest"][-1]
    assert failed["error_code"] == "media_resource_failed"
    assert failed["terminal_ingest_outcome"] != "success"


def test_remote_fetch_failure_is_terminal_ingest_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    corpus_mod.reset_media_host_pins()

    def fetcher(_url: str, _addresses: set[str]) -> bytes:
        raise TimeoutError("socket read timed out")

    client, records = _run_ingest_case(
        tmp_path,
        _entry(path="socket.jpg", sha256=hashlib.sha256(b"expected").hexdigest(), url="https://fetch-failure.example/media.jpg"),
        images_dir=tmp_path / "missing-images",
        resolver=lambda _host: ["93.184.216.34"],
        fetcher=fetcher,
        monkeypatch=monkeypatch,
    )

    assert client.analyze_calls == []
    failed = [record for record in records if record.get("phase") == "ingest"][-1]
    assert failed["error_code"] == "media_resource_failed"
    assert failed["terminal_ingest_outcome"] != "success"


def test_ingest_retry_budget_comes_from_durable_ingest_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_entry = _entry(path="never.jpg", sha256=hashlib.sha256(b"expected").hexdigest())
    manifest_path = _write_manifest(tmp_path / "manifest.json", manifest_entry)
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml", valid_pair_dict(item_max_attempts=2)))
    run_dir = init_run_dir(tmp_path / "run", pair, manifest_path)

    def unavailable(*_args, **_kwargs):
        raise BenchError("media_resource_failed", "resource unavailable")

    monkeypatch.setattr(driver_mod, "resolve_media_bytes", unavailable)
    for _ in range(3):
        run_leg(
            pair.endpoint("acx-dev-insightface"),
            pair,
            manifest_path=manifest_path,
            images_dir=tmp_path / "missing-images",
            run_dir=run_dir,
            client=FakeClient(),
        )

    records = ItemOutcomeStore(run_dir / "legs" / "acx-dev-insightface" / "items.jsonl").read_all()
    failed = [record for record in records if record.get("phase") == "ingest" and record.get("outcome") == "failed"]
    assert [record["attempt"] for record in failed] == [1, 2]
    assert failed[-1]["terminal_ingest_outcome"] == "media_resource_failed"
