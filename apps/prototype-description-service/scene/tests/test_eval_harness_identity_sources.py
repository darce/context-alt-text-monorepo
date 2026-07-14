"""VLM-6 S1: identity-source readers (celeb filenames + XMP face regions)."""

import os

import pytest

from scripts.eval_harness.identity_sources import (
    celeb_identity_from_filename,
    extract_face_regions,
    named_identities,
)

_UPLOADS = os.path.expanduser("~/Development/wp-context-alt-text/app/public/wp-content/uploads")

# A real plugin-written region image (Tory Guzman) discovered during S1 recon.
_REAL_XMP_IMG = os.path.join(_UPLOADS, "2025/12/28514407_10156297712651133_2186204419637901683_o.jpg")


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("clint_eastwood_8.jpg", "Clint Eastwood"),
        ("rihanna_17.jpg", "Rihanna"),
        ("robert_downey_jr._5.jpg", "Robert Downey Jr."),
        ("robert_de_niro_37.jpg", "Robert De Niro"),
        ("dali_3.jpg", "Dali"),
        ("emma_watson_14.jpeg", "Emma Watson"),
        ("queen_elizabeth_13.jpg", "Queen Elizabeth"),
        ("madonna.png", "Madonna"),  # no trailing index
    ],
)
def test_celeb_identity_from_filename(filename, expected):
    assert celeb_identity_from_filename(filename) == expected


def test_celeb_identity_handles_path_and_empty():
    assert celeb_identity_from_filename("just_5.jpg") == "Just"
    assert celeb_identity_from_filename("5.jpg") is None
    assert celeb_identity_from_filename("_.jpg") is None


def _jpeg_with_xmp(xmp: str) -> bytes:
    # Minimal JPEG SOI + an APP1 XMP-ish blob; the parser only needs the packet.
    return b"\xff\xd8\xff\xe1" + xmp.encode("utf-8") + b"\xff\xd9"


_IPTC_XMP = """<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about="">
   <Iptc4xmpExt:ImageRegion><rdf:Bag>
    <rdf:li xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/">
     <Iptc4xmpExt:RegionBoundary>
      <Iptc4xmpExt:rbShape>rectangle</Iptc4xmpExt:rbShape>
      <Iptc4xmpExt:rbX>0.636976</Iptc4xmpExt:rbX>
      <Iptc4xmpExt:rbY>0.193</Iptc4xmpExt:rbY>
      <Iptc4xmpExt:rbW>0.178144</Iptc4xmpExt:rbW>
      <Iptc4xmpExt:rbH>0.154</Iptc4xmpExt:rbH>
      <Iptc4xmpExt:rbUnit>relative</Iptc4xmpExt:rbUnit>
     </Iptc4xmpExt:RegionBoundary>
     <Iptc4xmpExt:Name xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/">Tory Guzman</Iptc4xmpExt:Name>
    </rdf:li>
   </rdf:Bag></Iptc4xmpExt:ImageRegion>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>"""

_MWG_XMP = """<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description xmlns:mwg-rs="http://www.metadataworkinggroup.com/schemas/regions/">
   <mwg-rs:Regions><mwg-rs:RegionList><rdf:Seq>
    <rdf:li>
     <mwg-rs:Area xmlns:stArea="http://ns.adobe.com/xmp/sType/Area#">
      <stArea:x>0.5115</stArea:x><stArea:y>0.4855</stArea:y>
      <stArea:w>0.113</stArea:w><stArea:h>0.151</stArea:h>
     </mwg-rs:Area>
     <mwg-rs:Type>Face</mwg-rs:Type>
    </rdf:li>
   </rdf:Seq></mwg-rs:RegionList></mwg-rs:Regions>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>"""


def test_iptc_region_name_and_box_parsed():
    regions = extract_face_regions(_jpeg_with_xmp(_IPTC_XMP))
    assert len(regions) == 1
    r = regions[0]
    assert r.name == "Tory Guzman" and r.source == "iptc"
    assert (round(r.x, 3), round(r.y, 3), round(r.w, 3), round(r.h, 3)) == (0.637, 0.193, 0.178, 0.154)


def test_mwg_region_box_only_no_name():
    regions = extract_face_regions(_jpeg_with_xmp(_MWG_XMP))
    assert len(regions) == 1
    assert regions[0].name is None and regions[0].source == "mwg"
    assert regions[0].x == 0.5115


def test_no_xmp_returns_empty():
    assert extract_face_regions(b"\xff\xd8\xff\xd9") == []


def test_named_identities_dedup_and_order():
    regions = extract_face_regions(_jpeg_with_xmp(_IPTC_XMP))
    assert named_identities(regions) == ["Tory Guzman"]
    assert named_identities([]) == []


@pytest.mark.skipif(not os.path.isfile(_REAL_XMP_IMG), reason="real LocalWP XMP fixture not present")
def test_real_localwp_image_yields_named_region():
    regions = extract_face_regions(open(_REAL_XMP_IMG, "rb").read())
    named = named_identities(regions)
    assert "Tory Guzman" in named
    iptc = [r for r in regions if r.source == "iptc" and r.name]
    assert iptc and all(0.0 <= r.x <= 1.0 and 0.0 <= r.w <= 1.0 for r in iptc)
