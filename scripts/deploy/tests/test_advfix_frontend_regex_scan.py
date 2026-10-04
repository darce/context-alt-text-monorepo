"""Regression coverage for regular-expression literals in the app portal lexer."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "deploy" / "app-portal.sh"


def _scan(tmp_path: Path, source: str) -> subprocess.CompletedProcess[str]:
    module = tmp_path / "module.js"
    module.write_text(source, encoding="utf-8")

    script = SCRIPT.read_text(encoding="utf-8")
    start = script.index("frontend_module_references() {")
    end = script.index("\nresolve_frontend_asset_reference() {", start)
    scanner_function = script[start:end].rstrip()
    return subprocess.run(
        [
            "bash",
            "-c",
            f'{scanner_function}\nfrontend_module_references "$1"',
            "regex-scan",
            str(module),
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def test_regex_literals_with_quotes_are_skipped_and_later_import_is_found(
    tmp_path: Path,
) -> None:
    result = _scan(
        tmp_path,
        '/"/;\n'
        'const pattern = /"/; export const ready = true;\n'
        "const re = /'[/]/g;\n"
        r'const escaped = /[\/\]]/;' + "\n"
        'const hidden = /import "bogus.js"/;\n'
        'const contexts = (typeof /"/) ? ! /"/ : [ /"/, /"/ ];\n'
        'const logical = ready && /"/ || /"/;\n'
        'function read() { return /"/; }\n'
        'const quotient = ready / 2;\n'
        'import "./after-regex.js";\n',
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["./after-regex.js"]


def test_unterminated_javascript_string_still_fails(tmp_path: Path) -> None:
    result = _scan(tmp_path, 'const broken = "unterminated;\n')

    assert result.returncode != 0
    assert "unterminated JavaScript string" in result.stderr


@pytest.mark.parametrize(
    "expression",
    [
        "counter++ / 2", "counter-- / 2", "counter++/2", "counter--/2",
        "(counter) / 2", "values[0] / 2", "42 / 2", "1.5e+2 / 2",
        "++counter / 2", "--counter / 2", "obj.throw / 2", "obj.if(ok) / 2",
        '"value" / 2', "`value` / 2", "/x/ / 2",
    ],
)
def test_division_after_expression_keeps_later_import(
    tmp_path: Path, expression: str,
) -> None:
    result = _scan(tmp_path, f'a = {expression}; import("./x.js");\n')

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["./x.js"]


@pytest.mark.parametrize(
    "prefix",
    [
        "throw", "return", "typeof", "case", "delete", "void", "new",
        "in", "of", "instanceof", "yield", "await",
    ],
)
def test_regex_after_expression_keyword_is_skipped(tmp_path: Path, prefix: str) -> None:
    result = _scan(tmp_path, f'{prefix} /import "bogus.js"/; import("./x.js");\n')

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["./x.js"]


@pytest.mark.parametrize(
    "header",
    [
        "if (ok)", "if(b)", "if (check(ok))", "while (ok)",
        "for (;;)", "for (const item of items)", "with (scope)",
        "if /* comment */ ((ok))", "if (ok) if (other)",
    ],
)
def test_regex_after_control_header_is_skipped(tmp_path: Path, header: str) -> None:
    result = _scan(tmp_path, f'{header}/import "bogus.js"/.test(s); import("./x.js");\n')

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["./x.js"]


@pytest.mark.parametrize("source", ['throw /x"y/;', 'if (ok) /"/.test(s);'])
def test_regex_after_keyword_or_header_does_not_open_string(
    tmp_path: Path, source: str,
) -> None:
    result = _scan(tmp_path, source)

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_unterminated_regex_still_fails(tmp_path: Path) -> None:
    result = _scan(tmp_path, "throw /unterminated;\n")

    assert result.returncode != 0
    assert "unterminated JavaScript regular expression" in result.stderr
