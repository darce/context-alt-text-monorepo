from urllib.parse import parse_qsl as _parse_qsl

import pytest

from conftest import load_module


def _track_parse_work(monkeypatch, value):
    module = load_module("manifest")
    parsed_lengths = []

    def tracked_parse_qsl(component, **kwargs):
        parsed_lengths.append(len(component))
        return _parse_qsl(component, **kwargs)

    monkeypatch.setattr(module, "parse_qsl", tracked_parse_qsl)
    assert not module._url_query_credential(value)
    assert len(parsed_lengths) <= 1
    assert sum(parsed_lengths) <= len(value)


def test_long_benign_scheme_prefix_has_bounded_parse_work(monkeypatch):
    value = f"{'a' * 4096}://host.invalid/path"

    _track_parse_work(monkeypatch, value)


def test_many_benign_urls_parse_no_overlapping_suffixes(monkeypatch):
    value = ",".join(
        f"https://host.invalid/{index}?mode=read" for index in range(256)
    )

    _track_parse_work(monkeypatch, value)


@pytest.mark.parametrize("value", [
    "prefix https://host.invalid/x?api%5Fkey=",
    "https://host.invalid/x#access%5Ftoken=",
    "https://host.invalid/x?q=ok,\nhttps://other.invalid/y#credential=",
])
def test_linear_scan_retains_decoded_blank_and_fragment_credentials(value):
    assert load_module("manifest")._url_query_credential(value)
