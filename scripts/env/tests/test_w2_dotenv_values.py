from __future__ import annotations

from pathlib import Path

import pytest

from conftest import load_module


def _manifest(write_manifest, *names: str) -> Path:
    targets = '''version = 1

[targets.t]
audience = "backend"
envs = ["prod"]
sections = ["Runtime"]
'''
    variables = "\n".join(
        f'''[[var]]
name = "{name}"
class = "config"
targets = ["t"]
section = "Runtime"
example = "safe-example"
values = {{ prod = "safe-example" }}
'''
        for name in names
    )
    return write_manifest(targets, **{"10-values": "version = 1\n" + variables})


def _extract(module, root: Path, text: str) -> dict[str, object]:
    return module.extract(module.load_manifest(root), "t", "prod", text)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("#foo", "#foo"),
        (" # comment", ""),
        ('"#quoted"', "#quoted"),
        (r"\#escaped", "#escaped"),
    ],
)
def test_leading_hash_values_keep_assignment_whitespace(write_manifest, raw, expected):
    module = load_module("harvest_extract")
    root = _manifest(write_manifest, "NAME")

    result = _extract(module, root, f"NAME={raw}\n")

    assert result["values"] == {"NAME": expected}
    assert result["withheld"]["unparsed"] == []


@pytest.mark.parametrize(
    "text",
    [
        'NOTICE="$(printf "first\nLOG_LEVEL=private-fragment\nlast")"\nAFTER=visible\n',
        'NOTICE="`printf "first\nLOG_LEVEL=private-fragment\nlast"`"\nAFTER=visible\n',
        'NOTICE=$(printf first \\\nLOG_LEVEL=private-fragment\nlast)\nAFTER=visible\n',
    ],
    ids=("nested-quotes-in-dollar-parens", "nested-quotes-in-backticks", "continued-command"),
)
def test_command_substitutions_are_withheld_as_one_assignment(write_manifest, text):
    module = load_module("harvest_extract")
    root = _manifest(write_manifest, "NOTICE", "LOG_LEVEL", "AFTER")

    result = _extract(module, root, text)

    assert result["values"] == {"AFTER": "visible"}
    assert result["withheld"]["missing"] == ["LOG_LEVEL"]
    assert result["withheld"]["unparsed"] == ["NOTICE"]


def test_malformed_command_substitution_consumes_the_ambiguous_tail(write_manifest):
    module = load_module("harvest_extract")
    root = _manifest(write_manifest, "NOTICE", "LOG_LEVEL", "AFTER")
    text = 'NOTICE="$(printf "first\nLOG_LEVEL=private-fragment\nAFTER=also-private\n'

    result = _extract(module, root, text)

    assert result["values"] == {}
    assert result["withheld"]["missing"] == ["AFTER", "LOG_LEVEL"]
    assert result["withheld"]["unparsed"] == ["NOTICE"]


@pytest.mark.parametrize("raw", ["$(printf fake)", "`printf fake`"], ids=("dollar-paren", "backtick"))
def test_single_line_executable_substitutions_are_withheld(write_manifest, raw):
    module = load_module("harvest_extract")
    root = _manifest(write_manifest, "NAME")

    result = _extract(module, root, f"NAME={raw}\n")

    assert result["values"] == {}
    assert result["withheld"]["unparsed"] == ["NAME"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("NAME='$(echo literal)'\n", "$(echo literal)"),
        (r"NAME=\$(echo)" + "\n", "$(echo)"),
        (r"NAME=\`echo\`" + "\n", "`echo`"),
    ],
    ids=("single-quoted", "escaped-dollar-paren", "escaped-backticks"),
)
def test_literal_command_substitution_text_remains_a_value(write_manifest, text, expected):
    module = load_module("harvest_extract")
    root = _manifest(write_manifest, "NAME")

    result = _extract(module, root, text)

    assert result["values"] == {"NAME": expected}
    assert result["withheld"]["unparsed"] == []
