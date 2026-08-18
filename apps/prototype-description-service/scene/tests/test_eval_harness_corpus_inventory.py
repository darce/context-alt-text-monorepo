"""VLM-6 S1: corpus inventory + cheap stratification features."""

import hashlib
import json
from dataclasses import asdict

from PIL import Image

from scripts.eval_harness.corpus_inventory import (
    BW_SATURATION_THRESHOLD,
    FLAT_COLOR_COVERAGE_THRESHOLD,
    LOW_LIGHT_VALUE_THRESHOLD,
    ImageRecord,
    _main,
    dedupe_by_sha256,
    inventory_dir,
    inventory_image,
    iter_new_images,
    load_records,
    write_records,
)

_IPTC_XMP = (
    b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
    b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description>'
    b"<Iptc4xmpExt:ImageRegion><rdf:Bag>"
    b'<rdf:li xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/">'
    b"<Iptc4xmpExt:RegionBoundary><Iptc4xmpExt:rbX>0.5</Iptc4xmpExt:rbX>"
    b"<Iptc4xmpExt:rbY>0.5</Iptc4xmpExt:rbY><Iptc4xmpExt:rbW>0.2</Iptc4xmpExt:rbW>"
    b"<Iptc4xmpExt:rbH>0.2</Iptc4xmpExt:rbH></Iptc4xmpExt:RegionBoundary>"
    b'<Iptc4xmpExt:Name xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/">'
    b"Slate Willow</Iptc4xmpExt:Name></rdf:li></rdf:Bag></Iptc4xmpExt:ImageRegion>"
    b"</rdf:Description></rdf:RDF></x:xmpmeta>"
)


def _save(path, color, size=(40, 30), xmp: bytes | None = None, image: Image.Image | None = None):
    (image if image is not None else Image.new("RGB", size, color)).save(path, "JPEG")
    if xmp is not None:
        # extract_face_regions scans raw bytes for the packet; appending after
        # EOI is enough for the reader and Pillow still decodes the image.
        with open(path, "ab") as handle:
            handle.write(xmp)


def test_grayscale_flags_bw_candidate(tmp_path):
    p = tmp_path / "clint_eastwood_3.jpg"
    _save(p, (128, 128, 128))  # gray => ~0 saturation
    rec = inventory_image(p, tmp_path)
    assert rec.mean_saturation is not None and rec.mean_saturation < BW_SATURATION_THRESHOLD
    assert rec.bw_candidate is True
    assert rec.width == 40 and rec.height == 30 and rec.aspect_ratio == round(40 / 30, 4)


def test_saturated_image_not_bw(tmp_path):
    p = tmp_path / "photo.jpg"
    _save(p, (220, 10, 10))  # vivid red => high saturation
    rec = inventory_image(p, tmp_path)
    assert rec.mean_saturation > BW_SATURATION_THRESHOLD and rec.bw_candidate is False


def test_celeb_name_from_filename(tmp_path):
    p = tmp_path / "robert_de_niro_37.jpg"
    _save(p, (50, 80, 120))
    assert inventory_image(p, tmp_path).celeb_name == "Robert De Niro"


def test_sha256_matches_file_bytes(tmp_path):
    p = tmp_path / "x.jpg"
    _save(p, (10, 20, 30))
    assert inventory_image(p, tmp_path).sha256 == hashlib.sha256(p.read_bytes()).hexdigest()


def test_xmp_names_and_face_count(tmp_path):
    p = tmp_path / "family.jpg"
    _save(p, (90, 90, 90), xmp=_IPTC_XMP)
    rec = inventory_image(p, tmp_path)
    assert rec.xmp_names == ["Slate Willow"] and rec.xmp_face_count == 1


def test_unreadable_image_degrades_to_metadata(tmp_path):
    p = tmp_path / "broken.jpg"
    p.write_bytes(b"not a real jpeg")
    rec = inventory_image(p, tmp_path)
    assert rec.width is None and rec.mean_saturation is None and rec.bw_candidate is False
    assert rec.sha256 == hashlib.sha256(b"not a real jpeg").hexdigest()


def test_inventory_dir_skips_wp_thumbnails(tmp_path):
    _save(tmp_path / "hero.jpg", (10, 200, 10))
    _save(tmp_path / "hero-150x150.jpg", (10, 200, 10))  # WP thumbnail, must be skipped
    (tmp_path / "notes.txt").write_text("ignore me")
    records = inventory_dir(tmp_path)
    assert [r.path for r in records] == ["hero.jpg"]


def test_inventory_dir_skips_scaled_copy_when_the_original_is_present(tmp_path):
    # WP re-encodes big uploads to `-scaled`; the bytes differ from the original so
    # sha256 dedupe cannot catch the pair (398 such pairs in the real uploads tree).
    _save(tmp_path / "IMG_2957.jpg", (10, 200, 10), size=(64, 48))
    _save(tmp_path / "IMG_2957-scaled.jpg", (10, 200, 10), size=(32, 24))
    assert [r.path for r in inventory_dir(tmp_path)] == ["IMG_2957.jpg"]


def test_inventory_dir_keeps_a_scaled_only_upload(tmp_path):
    # Some uploads exist ONLY as `-scaled`; dropping those loses the image itself.
    _save(tmp_path / "IMG_0216-scaled.jpg", (10, 200, 10))
    assert [r.path for r in inventory_dir(tmp_path)] == ["IMG_0216-scaled.jpg"]


def test_dedupe_by_sha256(tmp_path):
    _save(tmp_path / "a.jpg", (5, 5, 5))
    _save(tmp_path / "b.jpg", (5, 5, 5))  # identical bytes => same sha
    _save(tmp_path / "c.jpg", (9, 9, 9))
    records = inventory_dir(tmp_path)
    assert len(records) == 3
    deduped = dedupe_by_sha256(records)
    assert len(deduped) == 2


def test_dark_image_flags_low_light(tmp_path):
    p = tmp_path / "night.jpg"
    _save(p, (8, 8, 10))
    rec = inventory_image(p, tmp_path)
    assert rec.mean_value is not None and rec.mean_value < LOW_LIGHT_VALUE_THRESHOLD
    assert rec.low_light_candidate is True


def test_bright_image_not_low_light(tmp_path):
    p = tmp_path / "day.jpg"
    _save(p, (200, 190, 180))
    rec = inventory_image(p, tmp_path)
    assert rec.mean_value > LOW_LIGHT_VALUE_THRESHOLD and rec.low_light_candidate is False


def test_flat_color_image_flags_chart_candidate(tmp_path):
    # Two flat blocks == a screenshot/chart-like image: a couple of colors cover everything.
    image = Image.new("RGB", (64, 64), (255, 255, 255))
    image.paste(Image.new("RGB", (32, 64), (20, 60, 200)), (0, 0))
    p = tmp_path / "chart.jpg"
    _save(p, None, image=image)
    rec = inventory_image(p, tmp_path)
    assert rec.flat_color_coverage > FLAT_COLOR_COVERAGE_THRESHOLD
    assert rec.flat_color_candidate is True


def test_photo_like_noise_not_flat_color(tmp_path):
    # Per-pixel varied content: no small set of colors covers the frame.
    image = Image.new("RGB", (64, 64))
    image.putdata([((x * 7) % 256, (y * 11) % 256, (x * y) % 256) for y in range(64) for x in range(64)])
    p = tmp_path / "noise.jpg"
    _save(p, None, image=image)
    rec = inventory_image(p, tmp_path)
    assert rec.flat_color_candidate is False
    assert rec.edge_density > 0.0


def test_flat_image_has_lower_edge_density_than_busy_image(tmp_path):
    _save(tmp_path / "flat.jpg", (120, 120, 120), size=(64, 64))
    busy = Image.new("RGB", (64, 64))
    busy.putdata([(255, 255, 255) if (x + y) % 2 else (0, 0, 0) for y in range(64) for x in range(64)])
    _save(tmp_path / "busy.jpg", None, image=busy)
    flat = inventory_image(tmp_path / "flat.jpg", tmp_path)
    dense = inventory_image(tmp_path / "busy.jpg", tmp_path)
    assert dense.edge_density > flat.edge_density


def test_large_image_features_use_bounded_thumbnail(tmp_path):
    # Features are computed on a downscaled copy, but the RECORDED dims stay original.
    p = tmp_path / "big.jpg"
    _save(p, (30, 140, 60), size=(1200, 900))
    rec = inventory_image(p, tmp_path)
    assert rec.width == 1200 and rec.height == 900
    assert rec.mean_saturation is not None and rec.bw_candidate is False


def test_write_and_load_records_roundtrip_jsonl(tmp_path):
    _save(tmp_path / "julia_roberts_2.jpg", (200, 30, 30))
    out = tmp_path / "inv.jsonl"
    records = inventory_dir(tmp_path)
    write_records(out, records)
    loaded = load_records(out)
    assert loaded == records


def test_load_records_skips_truncated_trailing_line(tmp_path):
    # A checkpointed scan killed mid-write leaves a partial last line; resume must
    # drop it rather than crash, and re-inventory that image.
    out = tmp_path / "inv.jsonl"
    good = json.dumps(asdict(inventory_image_stub()))
    out.write_text(f"{good}\n{good[:40]}")
    assert [r.path for r in load_records(out)] == ["p"]


def test_load_records_skips_row_from_an_older_field_schema(tmp_path):
    out = tmp_path / "inv.jsonl"
    stale = asdict(inventory_image_stub())
    del stale["edge_density"]
    out.write_text(json.dumps(stale) + "\n")
    assert load_records(out) == []


def test_iter_new_images_skips_already_inventoried(tmp_path):
    _save(tmp_path / "a.jpg", (10, 20, 30))
    _save(tmp_path / "b.jpg", (40, 50, 60))
    assert [p.name for p in iter_new_images(tmp_path, done={"a.jpg"})] == ["b.jpg"]


def test_cli_writes_jsonl_and_resumes(tmp_path, capsys):
    _save(tmp_path / "julia_roberts_2.jpg", (200, 30, 30))
    out = tmp_path / "inv.jsonl"
    assert _main([str(tmp_path), "--out", str(out)]) == 0
    first = json.loads(out.read_text().splitlines()[0])
    assert first["celeb_name"] == "Julia Roberts"

    _save(tmp_path / "second.jpg", (30, 200, 30))
    assert _main([str(tmp_path), "--out", str(out), "--resume"]) == 0
    lines = [json.loads(line) for line in out.read_text().splitlines()]
    assert [r["path"] for r in lines] == ["julia_roberts_2.jpg", "second.jpg"]
    assert "resumed" in capsys.readouterr().out


def test_cli_without_resume_restarts_the_scan(tmp_path):
    _save(tmp_path / "a.jpg", (10, 20, 30))
    out = tmp_path / "inv.jsonl"
    _main([str(tmp_path), "--out", str(out)])
    _main([str(tmp_path), "--out", str(out)])
    assert len(out.read_text().splitlines()) == 1


def test_record_is_frozen():
    rec = inventory_image_stub()
    try:
        rec.path = "y"  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("ImageRecord should be frozen")


def inventory_image_stub() -> ImageRecord:
    return ImageRecord(
        path="p",
        sha256="s",
        width=1,
        height=1,
        mean_saturation=0.0,
        mean_value=0.5,
        aspect_ratio=1.0,
        celeb_name=None,
        xmp_names=[],
        xmp_face_count=0,
        bw_candidate=True,
        low_light_candidate=False,
        flat_color_coverage=0.1,
        flat_color_candidate=False,
        edge_density=0.2,
    )


def test_scan_exits_nonzero_when_a_file_raises_and_nothing_else_inventoried(tmp_path, monkeypatch, capsys):
    # A file whose inventory raises is SKIPPED (never aborts the scan); when it is the only
    # file, _main reports it on stderr and returns 1 — a bounded no-progress signal (A-01, rg-007).
    _save(tmp_path / "bad.jpg", (10, 20, 30))

    def boom(path, root):
        raise RuntimeError(f"boom on {path.name}")

    monkeypatch.setattr("scripts.eval_harness.corpus_inventory.inventory_image", boom)
    out = tmp_path / "inv.jsonl"
    assert _main([str(tmp_path), "--out", str(out)]) == 1
    err = capsys.readouterr().err
    assert "skipping" in err and "bad.jpg" in err


def test_scan_continues_past_a_raising_file_and_exits_zero_with_progress(tmp_path, monkeypatch, capsys):
    # One bad file must not halt the scan: the good file is still inventoried and _main
    # returns 0 because progress was made (A-01, rg-007).
    import scripts.eval_harness.corpus_inventory as ci

    _save(tmp_path / "aaa_good.jpg", (10, 200, 10))
    _save(tmp_path / "zzz_bad.jpg", (10, 20, 30))
    real = ci.inventory_image

    def maybe_boom(path, root):
        if path.name == "zzz_bad.jpg":
            raise RuntimeError("boom")
        return real(path, root)

    monkeypatch.setattr(ci, "inventory_image", maybe_boom)
    out = tmp_path / "inv.jsonl"
    assert _main([str(tmp_path), "--out", str(out)]) == 0
    assert [r.path for r in load_records(out)] == ["aaa_good.jpg"]
    assert "skipping" in capsys.readouterr().err


def test_load_records_warns_on_schema_drop_distinct_from_truncated_tail(tmp_path, capsys):
    # A schema-mismatched checkpoint row is dropped WITH a stderr warning so a silent re-scan
    # is visible, while a truncated tail line stays silent and uncounted (A-06).
    out = tmp_path / "inv.jsonl"
    stale = asdict(inventory_image_stub())
    del stale["edge_density"]  # schema mismatch -> counted + warned
    out.write_text(json.dumps(stale) + "\n" + '{"path": "trunc",')  # + truncated tail -> silent
    assert load_records(out) == []
    err = capsys.readouterr().err
    assert "dropped 1 checkpoint row" in err
    assert "trunc" not in err
