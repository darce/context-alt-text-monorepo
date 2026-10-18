"""VLM-6 S1: identity-source readers (celeb filenames + XMP face regions)."""

import os
from xml.etree import ElementTree

import pytest

from scripts.eval_harness.identity_sources import (
    celeb_identity_from_filename,
    extract_face_regions,
    named_identities,
)

_UPLOADS = os.path.expanduser("~/Development/wp-context-alt-text/app/public/wp-content/uploads")

# A real plugin-written region image (Flaxen Yarrow) discovered during S1 recon.
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


@pytest.mark.parametrize(
    "filename",
    [
        "28514407_10156297712651133_2186204419637901683_o.jpg",  # social-media upload id
        "mcm224181_6641495121_2911_n.jpg",
        "IMG_9DABF3F03B85-1.jpeg",  # camera id, no name word after index strip
        "12345678.png",
        # Scraped `<handle>_<post-id>` uploads: an unbounded trailing-index strip ate
        # the 19-digit id and yielded the fake public-figure labels "GildedCypress" /
        # "Oliviajaynelee" on 21 of the first 200 real LocalWP uploads.
        "gildedcypress_3134640125107970990.jpg",
        "oliviajaynelee_3644180080911632673.jpg",
    ],
)
def test_non_name_filenames_yield_no_celeb_label(filename):
    assert celeb_identity_from_filename(filename) is None


def test_trailing_index_strip_is_bounded_to_short_disambiguators():
    # celebs01 disambiguators run 1-2 digits; anything long is an opaque id that
    # must stay in the stem so the no-digits guard rejects the filename.
    assert celeb_identity_from_filename("madonna_7.jpg") == "Madonna"
    assert celeb_identity_from_filename("clint_eastwood_99.jpg") == "Clint Eastwood"
    assert celeb_identity_from_filename("handle_3134640125107970990.jpg") is None


@pytest.mark.parametrize("filename", ["dali_3.jpg", "drake_11.jpg", "madonna.png", "rihanna_17.jpg"])
def test_mononym_celebs_keep_their_label(filename):
    # 93 celebs01 files are single-token names; a first+last requirement would drop them.
    assert celeb_identity_from_filename(filename) is not None


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
     <Iptc4xmpExt:Name xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/">Flaxen Yarrow</Iptc4xmpExt:Name>
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

# An MWG region that DOES carry a confirmed name via the standard hyphenated prefix.
_MWG_XMP_NAMED = """<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description xmlns:mwg-rs="http://www.metadataworkinggroup.com/schemas/regions/">
   <mwg-rs:Regions><mwg-rs:RegionList><rdf:Seq>
    <rdf:li>
     <mwg-rs:Name>Grace Okafor</mwg-rs:Name>
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
    assert r.name == "Flaxen Yarrow" and r.source == "iptc"
    assert (round(r.x, 3), round(r.y, 3), round(r.w, 3), round(r.h, 3)) == (0.637, 0.193, 0.178, 0.154)


def test_mwg_region_box_only_no_name():
    regions = extract_face_regions(_jpeg_with_xmp(_MWG_XMP))
    assert len(regions) == 1
    assert regions[0].name is None and regions[0].source == "mwg"
    assert regions[0].x == 0.5115


def test_mwg_region_hyphenated_prefix_name_parsed():
    # The MWG-Regions canonical prefix is hyphenated (mwg-rs); a <mwg-rs:Name> the
    # standard tools (Lightroom/digiKam/Photos) write must parse, or a confirmed face
    # name is silently lost — the regex prefix group must allow '-' (E-03).
    regions = extract_face_regions(_jpeg_with_xmp(_MWG_XMP_NAMED))
    assert len(regions) == 1
    assert regions[0].name == "Grace Okafor" and regions[0].source == "mwg"
    assert named_identities(regions) == ["Grace Okafor"]


def test_no_xmp_returns_empty():
    assert extract_face_regions(b"\xff\xd8\xff\xd9") == []


def test_named_identities_dedup_and_order():
    regions = extract_face_regions(_jpeg_with_xmp(_IPTC_XMP))
    assert named_identities(regions) == ["Flaxen Yarrow"]
    assert named_identities([]) == []


@pytest.mark.skipif(not os.path.isfile(_REAL_XMP_IMG), reason="real LocalWP XMP fixture not present")
def test_real_localwp_image_yields_named_region():
    with open(_REAL_XMP_IMG, "rb") as fh:
        raw = fh.read()
    regions = extract_face_regions(raw)
    named = named_identities(regions)
    # The name lives in the image's own XMP, which this repo does not own and
    # cannot pseudonymize, so it must not be pinned as a literal in a tracked
    # file. A shape-only check would pass on a wrong-field, truncated, or
    # corrupted read, so compare against an oracle that re-derives the expected
    # value from the bytes at run time — via a real XML parse, which shares no
    # code with the reader's regex extraction.
    xmp = raw[raw.index(b"<x:xmpmeta") : raw.index(b"</x:xmpmeta>") + len(b"</x:xmpmeta>")]
    expected = list(
        dict.fromkeys(
            (el.text or "").strip()
            for el in ElementTree.fromstring(xmp).iter()
            if el.tag.rsplit("}", 1)[-1] == "Name" and (el.text or "").strip()
        )
    )
    assert named, "plugin-written XMP regions should yield at least one named identity"
    assert named == expected, "reader disagrees with the XMP <*:Name> elements"
    iptc = [r for r in regions if r.source == "iptc" and r.name]
    assert iptc and all(0.0 <= r.x <= 1.0 and 0.0 <= r.w <= 1.0 for r in iptc)
