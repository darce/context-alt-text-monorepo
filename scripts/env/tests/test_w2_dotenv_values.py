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
        ("#", "#"),
        (" # comment", ""),
        ('"#quoted"', "#quoted"),
        (r"\#escaped", "#escaped"),
    ],
)
def test_leading_hash_values_keep_assignment_whitespace(write_manifest, raw, expected):
    render = load_module("render_env")
    module = load_module("harvest_extract")
    root = _manifest(write_manifest, "NAME")

    text = f"NAME={raw}\n"
    assignments = render.shell_assignments(text)
    result = _extract(module, root, text)

    assert set(assignments) == {"NAME"}
    assert render.shell_words(assignments["NAME"][0]) == ([] if expected == "" else [expected])
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


@pytest.mark.parametrize(
    "text",
    [
        "NOTICE=\\\n$(printf first\nLOG_LEVEL=private-fragment\nlast)\nAFTER=visible\n",
        "NOTICE=\\\n`printf first\nLOG_LEVEL=private-fragment\nlast`\nAFTER=visible\n",
        "NOTICE=\\\n<(printf first\nLOG_LEVEL=private-fragment\nlast\n)\nAFTER=visible\n",
        "NOTICE=\\\n>(printf first\nLOG_LEVEL=private-fragment\nlast\n)\nAFTER=visible\n",
    ],
    ids=("continued-dollar-paren", "continued-backtick", "continued-input-process", "continued-output-process"),
)
def test_continuation_before_substitution_does_not_expose_inner_assignment(write_manifest, text):
    render = load_module("render_env")
    module = load_module("harvest_extract")
    root = _manifest(write_manifest, "NOTICE", "LOG_LEVEL", "AFTER")

    assignments = render.shell_assignments(text)
    result = _extract(module, root, text)

    assert set(assignments) == {"NOTICE", "AFTER"}
    assert assignments["NOTICE"][0].startswith("\\\n")
    assert result["values"] == {"AFTER": "visible"}
    assert result["withheld"]["missing"] == ["LOG_LEVEL"]
    assert result["withheld"]["unparsed"] == ["NOTICE"]


@pytest.mark.parametrize(
    "text",
    [
        "NOTICE=$\\\n(printf first\nLOG_LEVEL=private-fragment\nlast)\nAFTER=visible\n",
        "NOTICE=<\\\n(printf first\nLOG_LEVEL=private-fragment\nlast\n)\nAFTER=visible\n",
        "NOTICE=>\\\n(printf first\nLOG_LEVEL=private-fragment\nlast\n)\nAFTER=visible\n",
    ],
    ids=("split-dollar-paren-opener", "split-input-process-opener", "split-output-process-opener"),
)
def test_substitution_openers_split_by_continuation_are_recognized(write_manifest, text):
    render = load_module("render_env")
    module = load_module("harvest_extract")
    root = _manifest(write_manifest, "NOTICE", "LOG_LEVEL", "AFTER")

    assignments = render.shell_assignments(text)
    result = _extract(module, root, text)

    assert set(assignments) == {"NOTICE", "AFTER"}
    assert result["values"] == {"AFTER": "visible"}
    assert result["withheld"]["missing"] == ["LOG_LEVEL"]
    assert result["withheld"]["unparsed"] == ["NOTICE"]


def test_braced_command_boundary_preserves_case_context(write_manifest):
    render = load_module("render_env")
    module = load_module("harvest_extract")
    root = _manifest(write_manifest, "NOTICE", "LOG_LEVEL", "AFTER")
    text = (
        "NOTICE=$({ case fake in\n"
        "foo)\n"
        "LOG_LEVEL=private-fragment\n"
        ";;\n"
        "esac\n"
        "})\n"
        "AFTER=visible\n"
    )

    assignments = render.shell_assignments(text)
    result = _extract(module, root, text)

    assert set(assignments) == {"NOTICE", "AFTER"}
    assert result["values"] == {"AFTER": "visible"}
    assert result["withheld"]["missing"] == ["LOG_LEVEL"]
    assert result["withheld"]["unparsed"] == ["NOTICE"]


def test_ordinary_keyword_arguments_do_not_create_case_context(write_manifest):
    render = load_module("render_env")
    module = load_module("harvest_extract")
    root = _manifest(write_manifest, "NOTICE", "AFTER")
    text = "NOTICE=$(printf then case)\nAFTER=visible\n"

    assignments = render.shell_assignments(text)
    result = _extract(module, root, text)

    assert set(assignments) == {"NOTICE", "AFTER"}
    assert result["values"] == {"AFTER": "visible"}
    assert result["withheld"]["unparsed"] == ["NOTICE"]


@pytest.mark.parametrize(
    "pattern_line",
    ["foo)", "(foo|bar)"],
    ids=("case-pattern", "parenthesized-case-pattern"),
)
def test_case_pattern_parenthesis_does_not_end_command_substitution(write_manifest, pattern_line):
    render = load_module("render_env")
    module = load_module("harvest_extract")
    root = _manifest(write_manifest, "NOTICE", "LOG_LEVEL", "AFTER")
    text = (
        'NOTICE=$(case "$x" in\n'
        f"{pattern_line}\n"
        "LOG_LEVEL=private-fragment\n"
        ";;\n"
        "esac\n"
        ")\n"
        "AFTER=visible\n"
    )

    assignments = render.shell_assignments(text)
    result = _extract(module, root, text)

    assert set(assignments) == {"NOTICE", "AFTER"}
    assert result["values"] == {"AFTER": "visible"}
    assert result["withheld"]["missing"] == ["LOG_LEVEL"]
    assert result["withheld"]["unparsed"] == ["NOTICE"]


@pytest.mark.parametrize(
    "command",
    [
        'echo "first\nsecond" esac',
        "echo first \\\nsecond esac",
    ],
    ids=("quoted-newline", "escaped-line-continuation"),
)
def test_case_argument_esac_does_not_close_multiline_word(write_manifest, command):
    render = load_module("render_env")
    module = load_module("harvest_extract")
    root = _manifest(write_manifest, "NOTICE", "LOG_LEVEL", "AFTER")
    text = (
        'NOTICE=$(case "$x" in\n'
        "foo)\n"
        f"{command}\n"
        ";;\n"
        "bar)\n"
        "LOG_LEVEL=private-fragment\n"
        ";;\n"
        "esac\n"
        ")\n"
        "AFTER=visible\n"
    )

    assignments = render.shell_assignments(text)
    result = _extract(module, root, text)

    assert set(assignments) == {"NOTICE", "AFTER"}
    assert result["values"] == {"AFTER": "visible"}
    assert result["withheld"]["missing"] == ["LOG_LEVEL"]
    assert result["withheld"]["unparsed"] == ["NOTICE"]


def test_unclosed_case_construct_withholds_ambiguous_tail(write_manifest):
    render = load_module("render_env")
    module = load_module("harvest_extract")
    root = _manifest(write_manifest, "NOTICE", "LOG_LEVEL", "AFTER")
    text = (
        'NOTICE=$(case "$x" in\n'
        "foo)\n"
        "LOG_LEVEL=private-fragment\n"
        ")\n"
        "AFTER=also-private\n"
    )

    assignments = render.shell_assignments(text)
    result = _extract(module, root, text)

    assert set(assignments) == {"NOTICE"}
    assert result["values"] == {}
    assert result["withheld"]["missing"] == ["AFTER", "LOG_LEVEL"]
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


def test_same_line_empty_case_closes_substitution_and_resumes_assignments(write_manifest):
    render = load_module("render_env")
    module = load_module("harvest_extract")
    root = _manifest(write_manifest, "NOTICE", "AFTER")
    text = 'NOTICE=$(case "$x" in esac)\nAFTER=visible\n'

    assignments = render.shell_assignments(text)
    result = _extract(module, root, text)

    assert set(assignments) == {"NOTICE", "AFTER"}
    assert result["values"] == {"AFTER": "visible"}
    assert result["withheld"]["unparsed"] == ["NOTICE"]


@pytest.mark.parametrize(
    "pattern",
    ["(esac", '"esac"', r"\esac"],
    ids=("parenthesized-literal", "quoted-literal", "escaped-literal"),
)
def test_literal_esac_case_patterns_remain_patterns(write_manifest, pattern):
    render = load_module("render_env")
    module = load_module("harvest_extract")
    root = _manifest(write_manifest, "NOTICE", "LOG_LEVEL", "AFTER")
    text = (
        'NOTICE=$(case "$x" in\n'
        f"{pattern})\n"
        "LOG_LEVEL=private-fragment\n"
        ";;\n"
        "esac\n"
        ")\n"
        "AFTER=visible\n"
    )

    assignments = render.shell_assignments(text)
    result = _extract(module, root, text)

    assert set(assignments) == {"NOTICE", "AFTER"}
    assert result["values"] == {"AFTER": "visible"}
    assert result["withheld"]["unparsed"] == ["NOTICE"]


@pytest.mark.parametrize(
    "operator",
    ["<", ">"],
    ids=("input-process-substitution", "output-process-substitution"),
)
def test_multiline_process_substitutions_are_withheld_and_resume(write_manifest, operator):
    render = load_module("render_env")
    module = load_module("harvest_extract")
    root = _manifest(write_manifest, "NOTICE", "LOG_LEVEL", "AFTER")
    text = (
        f"NOTICE={operator}(printf first\n"
        "LOG_LEVEL=private-fragment\n"
        "last\n"
        ")\n"
        "AFTER=visible\n"
    )

    assignments = render.shell_assignments(text)
    result = _extract(module, root, text)

    assert set(assignments) == {"NOTICE", "AFTER"}
    assert result["values"] == {"AFTER": "visible"}
    assert result["withheld"]["missing"] == ["LOG_LEVEL"]
    assert result["withheld"]["unparsed"] == ["NOTICE"]


@pytest.mark.parametrize("operator", ["<", ">"], ids=("input", "output"))
def test_process_substitution_literals_are_not_scanned_as_executable(operator):
    render = load_module("render_env")

    assert render.shell_words(f"{operator}(printf literal)") is None
    assert render.shell_words(f"'{operator}(printf literal)'") == [
        f"{operator}(printf literal)"
    ]
    assert render.shell_words(f"\\{operator}\\(printf\\ literal\\)") == [
        f"{operator}(printf literal)"
    ]


@pytest.mark.parametrize(
    "text",
    [
        'NOTICE="$(cat <<EOF\n\'")\nLOG_LEVEL=private-fragment\nEOF\n)"\nAFTER=visible\n',
        'NOTICE="$(cat <<EOF\n\'\nEOF\n)"\nAFTER=visible\n',
        "NOTICE=$(cat <<EOF\n)\nLOG_LEVEL=private-fragment\nEOF\n)\nAFTER=visible\n",
    ],
    ids=("quoted-body-quote-and-close-paren", "quoted-body-single-quote", "body-close-paren"),
)
def test_heredoc_bodies_are_opaque_inside_substitutions(write_manifest, text):
    render = load_module("render_env")
    module = load_module("harvest_extract")
    root = _manifest(write_manifest, "NOTICE", "LOG_LEVEL", "AFTER")

    assignments = render.shell_assignments(text)
    result = _extract(module, root, text)

    assert set(assignments) == {"NOTICE", "AFTER"}
    assert result["values"] == {"AFTER": "visible"}
    assert result["withheld"]["missing"] == ["LOG_LEVEL"]
    assert result["withheld"]["unparsed"] == ["NOTICE"]


@pytest.mark.parametrize(
    ("operator", "terminator", "body_prefix"),
    [
        ("<<'END'", "END", ""),
        ('<<"END"', "END", ""),
        ("<<-END", "\tEND", "\t"),
    ],
    ids=("single-quoted-delimiter", "double-quoted-delimiter", "tab-stripped-delimiter"),
)
def test_bounded_heredoc_delimiters_resume_after_the_opaque_body(
    write_manifest, operator, terminator, body_prefix
):
    render = load_module("render_env")
    module = load_module("harvest_extract")
    root = _manifest(write_manifest, "NOTICE", "LOG_LEVEL", "AFTER")
    text = (
        f"NOTICE=$(cat {operator}\n"
        f"{body_prefix})\n"
        f"{body_prefix}LOG_LEVEL=private-fragment\n"
        f"{terminator}\n"
        ")\n"
        "AFTER=visible\n"
    )

    assignments = render.shell_assignments(text)
    result = _extract(module, root, text)

    assert set(assignments) == {"NOTICE", "AFTER"}
    assert result["values"] == {"AFTER": "visible"}
    assert result["withheld"]["missing"] == ["LOG_LEVEL"]
    assert result["withheld"]["unparsed"] == ["NOTICE"]


@pytest.mark.parametrize(
    "text",
    [
        "NOTICE=$(cat <<$DELIM\n)\nLOG_LEVEL=private-fragment\nEOF\n)\nAFTER=also-private\n",
        "NOTICE=$(cat <<EOF\n)\nLOG_LEVEL=private-fragment\nAFTER=also-private\n",
    ],
    ids=("unsupported-expanded-delimiter", "unterminated-delimiter"),
)
def test_ambiguous_heredocs_quarantine_the_remaining_input(write_manifest, text):
    render = load_module("render_env")
    module = load_module("harvest_extract")
    root = _manifest(write_manifest, "NOTICE", "LOG_LEVEL", "AFTER")

    assignments = render.shell_assignments(text)
    result = _extract(module, root, text)

    assert set(assignments) == {"NOTICE"}
    assert result["values"] == {}
    assert result["withheld"]["missing"] == ["AFTER", "LOG_LEVEL"]
    assert result["withheld"]["unparsed"] == ["NOTICE"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("NOTICE='<<EOF'\n", "<<EOF"),
        (r"NOTICE=\<\<EOF" + "\n", "<<EOF"),
    ],
    ids=("quoted-literal", "escaped-literal"),
)
def test_heredoc_operators_in_literal_text_remain_values(write_manifest, text, expected):
    module = load_module("harvest_extract")
    root = _manifest(write_manifest, "NOTICE")

    result = _extract(module, root, text)

    assert result["values"] == {"NOTICE": expected}
    assert result["withheld"]["unparsed"] == []
