"""Regression coverage for JavaScript module references in the app portal lexer."""

from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "deploy" / "app-portal.sh"
REPO_ROOT = SCRIPT.parents[2]
FAKE_LIVE_KEY = "pk_live_" + base64.b64encode(b"clerk.altcontext.com$").decode("ascii").rstrip("=")


def _write_manifest(tmp_path: Path) -> Path:
    root = tmp_path / "app-portal-test-config" / "env"
    shutil.copytree(REPO_ROOT / "config" / "env", root)
    portal_manifest = root / "manifest.d" / "60-app-portal.toml"
    portal_text = portal_manifest.read_text(encoding="utf-8")
    portal_text = re.sub(
        r'(values = \{ local = "[^"]+")\s*\}',
        rf'\1, prod = "{FAKE_LIVE_KEY}" }}',
        portal_text,
        count=1,
    )
    portal_manifest.write_text(portal_text, encoding="utf-8")
    return root


def _clerk_config_module() -> str:
    return (
        "function parsePortalConfig(env) { return {"
        "publishableKey: env.VITE_CLERK_PUBLISHABLE_KEY, "
        "fapiOrigin: env.VITE_CLERK_FAPI }; }\n"
        f'const env = {{ VITE_CLERK_PUBLISHABLE_KEY: "{FAKE_LIVE_KEY}", '
        'VITE_CLERK_FAPI: "https://clerk.altcontext.com", VITE_PORTAL_ENABLED: "true" };\n'
        "parsePortalConfig(env);\n"
    )


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


def _validate(
    tmp_path: Path, source: str, target: str | None,
) -> subprocess.CompletedProcess[str]:
    assets = tmp_path / "assets"
    assets.mkdir()
    (tmp_path / "index.html").write_text(
        '<script type="module" src="/assets/index.js"></script>', encoding="utf-8",
    )
    (assets / "index.js").write_text(source + _clerk_config_module(), encoding="utf-8")
    if target is not None:
        (assets / target).write_text("export const a=1;", encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")
    start = script.index("frontend_asset_references() {")
    end = script.index("\nsync_path() {", start)
    return subprocess.run(
        ["bash", "-c", f'{script[start:end]}\nvalidate_frontend "$1"',
         "module-validation", str(tmp_path)],
        text=True, capture_output=True, check=False,
        env={
            **os.environ,
            "APP_PORTAL_ENV_ROOT": str(_write_manifest(tmp_path)),
            "REPO_ROOT": str(REPO_ROOT),
        },
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


@pytest.mark.parametrize(
    "source",
    [
        'export const load = () => import("./target.js");',
        'export const load=()=>import("./target.js");',
        'export default () => import("./target.js");',
        'export default()=>import("./target.js");',
        'const label = `${import("./target.js")}`;',
        'const label=`text ${({load:()=>import("./target.js")}).load()}`;',
        'export const label=`outer ${`inner ${import("./target.js")}`}`;',
        'export{a as b}from"./target.js";',
        'export*from"./target.js";',
    ],
)
@pytest.mark.parametrize("target_exists", [False, True])
def test_validate_frontend_checks_export_and_template_imports(
    tmp_path: Path, source: str, target_exists: bool,
) -> None:
    result = _validate(tmp_path, source, "target.js" if target_exists else None)

    if target_exists:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
        assert "missing module dependency ./target.js" in result.stderr


@pytest.mark.parametrize(
    "source",
    [
        'const value={} / 2; import("./present.js");',
        'const value={nested:{}}/2;import("./present.js");',
        'const value=({})/2;import("./present.js");',
        'const value=[{} / 2];import("./present.js");',
        'function load(){return {} / 2} import("./present.js");',
    ],
)
def test_division_after_object_keeps_later_import(tmp_path: Path, source: str) -> None:
    result = _scan(tmp_path, source)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["./present.js"]

    validation = _validate(tmp_path, source, "present.js")
    assert validation.returncode == 0, validation.stderr


def test_template_text_is_opaque_but_all_interpolations_are_scanned(tmp_path: Path) -> None:
    result = _scan(
        tmp_path,
        r'const text=`import("./bogus.js") \${import("./escaped.js")} '
        r'${/import "bogus.js"[}]/.test("}") ? import("./one.js") : "}"} '
        r'${(()=>{ /* } */ return import("./two.js") })()}`/2;'
        'import("./after.js");',
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["./one.js", "./two.js", "./after.js"]


@pytest.mark.parametrize("source", ['`unfinished', '`text ${import("./x.js")', '`outer ${`inner`'])
def test_unterminated_template_still_fails(tmp_path: Path, source: str) -> None:
    result = _scan(tmp_path, source)

    assert result.returncode != 0
    assert "unterminated JavaScript template string" in result.stderr


@pytest.mark.parametrize("block", ["if(ok){}", "function run(){}", "const run=()=>{};"])
def test_regex_after_block_remains_opaque(tmp_path: Path, block: str) -> None:
    result = _scan(tmp_path, f'{block}/import "bogus.js"/.test(s);import("./x.js");')

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["./x.js"]
