import pytest

from conftest import load_module


_CREDENTIAL_VALUES = [
    "-https://h/x?token=fake",
    "x-https://h/x?token=fake",
    ".https://h/x#access_token=fake",
    "+https://h/x?api_key=fake",
    "1https://h/x?sig=fake",
    "ahttps://h/x?token=fake",
]


@pytest.mark.parametrize("value", _CREDENTIAL_VALUES)
def test_prefixed_url_query_credentials_are_detected(value):
    assert load_module("manifest")._url_query_credential(value)


@pytest.mark.parametrize("value", _CREDENTIAL_VALUES)
def test_harvest_withholds_prefixed_url_credentials(value):
    assert load_module("harvest_extract").secret_looking("CONFIG_NAME", value)


@pytest.mark.parametrize("value", _CREDENTIAL_VALUES)
def test_public_build_rejects_prefixed_url_credentials(write_manifest, value):
    module = load_module("manifest")
    root = write_manifest('''version = 1
[targets.t]
audience = "public_build"
envs = ["prod"]
sections = ["Runtime"]
''', **{"10-url": f'''version = 1
[[var]]
name = "VITE_SERVICE_URL"
class = "public"
targets = ["t"]
section = "Runtime"
example = "{value}"
values = {{ prod = "safe-value" }}
'''})

    with pytest.raises(module.ManifestError, match="URL credentials") as exc:
        module.load_manifest(root)
    assert "VITE_SERVICE_URL" in str(exc.value)
    assert value not in str(exc.value)


@pytest.mark.parametrize("value", ["-https://h/x?q=1", "https://h/x?q=1"])
def test_benign_prefixed_urls_remain_unflagged(value):
    assert not load_module("manifest")._url_query_credential(value)
    assert not load_module("harvest_extract").secret_looking("CONFIG_NAME", value)
