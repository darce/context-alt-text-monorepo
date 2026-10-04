"""Regression coverage for regular-expression literals in the app portal lexer."""

from __future__ import annotations

import subprocess
from pathlib import Path


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
