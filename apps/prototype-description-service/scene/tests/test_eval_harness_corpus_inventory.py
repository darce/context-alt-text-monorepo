"""VLM-6 S1: corpus inventory + cheap stratification features."""

import hashlib
import json

from PIL import Image

from scripts.eval_harness.corpus_inventory import (
    BW_SATURATION_THRESHOLD,
    ImageRecord,
    _main,
    dedupe_by_sha256,
    inventory_dir,
    inventory_image,
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
    b"Maria Correonero</Iptc4xmpExt:Name></rdf:li></rdf:Bag></Iptc4xmpExt:ImageRegion>"
    b"</rdf:Description></rdf:RDF></x:xmpmeta>"
)


def _save(path, color, size=(40, 30), xmp: bytes | None = None):
    Image.new("RGB", size, color).save(path, "JPEG")
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
    assert rec.xmp_names == ["Maria Correonero"] and rec.xmp_face_count == 1


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


def test_dedupe_by_sha256(tmp_path):
    _save(tmp_path / "a.jpg", (5, 5, 5))
    _save(tmp_path / "b.jpg", (5, 5, 5))  # identical bytes => same sha
    _save(tmp_path / "c.jpg", (9, 9, 9))
    records = inventory_dir(tmp_path)
    assert len(records) == 3
    deduped = dedupe_by_sha256(records)
    assert len(deduped) == 2


def test_cli_writes_json(tmp_path, capsys):
    _save(tmp_path / "julia_roberts_2.jpg", (200, 30, 30))
    out = tmp_path / "inv.json"
    rc = _main([str(tmp_path), "--out", str(out)])
    assert rc == 0
    data = json.loads(out.read_text())
    assert data[0]["celeb_name"] == "Julia Roberts"
    assert "images ->" in capsys.readouterr().out


def test_record_is_frozen():
    rec = ImageRecord("p", "s", 1, 1, 0.0, 1.0, None, [], 0, True)
    try:
        rec.path = "y"  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("ImageRecord should be frozen")
