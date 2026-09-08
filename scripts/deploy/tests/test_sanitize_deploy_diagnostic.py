"""Canaries for sanitize_deploy_diagnostic (GR-101..144)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "recognition-service.sh"


def _sanitize_deploy_diagnostic_src() -> str:
    source = SCRIPT.read_text()
    start = source.index("sanitize_deploy_diagnostic() {")
    end = source.index("\n}\n", start)
    return source[start : end + 2]


def _run_sanitizer(text: str) -> str:
    result = subprocess.run(
        ["bash", "-c", _sanitize_deploy_diagnostic_src() + "\nsanitize_deploy_diagnostic"],
        input=text,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout


SANITIZER_CASES = [
    ('{"access_token":"abc.DEF-123"}', "abc.DEF-123"),
    ('{"api_key": "abc123"}', "abc123"),
    ("SECRET=abc", "abc"),
    ('PGPASSWORD="quoted secret"', "quoted secret"),
    ("postgresql://acx:LEAK5@db/x", "LEAK5"),
    ('{"token": "json-secret"}', "json-secret"),
    ('{"refresh_token": "rt-secret"}', "rt-secret"),
    ('{"password": "pw-secret"}', "pw-secret"),
    ('{"passwd": "passwd-secret"}', "passwd-secret"),
    ('{"secret": "sec-value"}', "sec-value"),
    ('{"api-key":"hyphen-json"}', "hyphen-json"),
    ('{"db_password": "db-pass"}', "db-pass"),
    ('{"client_secret": "cli-sec"}', "cli-sec"),
    ('{"service_key": "svc-key"}', "svc-key"),
    ('{"pgpassword": "json-pg"}', "json-pg"),
    ("TOKEN=tok-secret", "tok-secret"),
    ("PASSWORD=pw2-secret", "pw2-secret"),
    ("KEY=key-secret", "key-secret"),
    ("SECRET: colon-secret", "colon-secret"),
    ("TOKEN='quoted token'", "quoted token"),
    ('PASSWORD="quoted pass"', "quoted pass"),
    ("Authorization: Bearer header-secret", "header-secret"),
    ("bearer naked-secret", "naked-secret"),
    ("ACX_API_TOKEN=another-secret", "another-secret"),
    ("HF_TOKEN=hf-secret", "hf-secret"),
    ("api-key=hyphen-secret", "hyphen-secret"),
    ("api_key=under-secret", "under-secret"),
    ("X-Api-Key: header-key-secret", "header-key-secret"),
    ("password=hunter2", "hunter2"),
    (json.dumps({"password": 'abc"SYNTHETIC_ESCAPED_CANARY'}), "SYNTHETIC_ESCAPED_CANARY"),
    ('{"api_key": "x\\"y\\"LEAKM"}', "LEAKM"),
    ('{"Authorization": "Bearer ab\\"LEAKN"}', "LEAKN"),
    ("Bearer abcdef123456", "abcdef123456"),
    ("Bearer ab.cd-ef_gh", "ab.cd-ef_gh"),
    ("Authorization: Basic ZGFuOmh1bnRlcjI=", "ZGFuOmh1bnRlcjI="),
    ("{'password': LEAKJ}", "LEAKJ"),
    ('{"HF_TOKEN": LEAKK, "x": 1}', "LEAKK"),
    ("Basic user:hunter2", "user:hunter2"),
    ("Bearer eyJ.abc:def", "eyJ.abc:def"),
    ("Basic abcdefgh:xyz", "abcdefgh:xyz"),
    ("Bearer abcdef%2Fgh", "abcdef%2Fgh"),
    ("authorization: token expired", "expired"),
    ("Authorization: Basic ab:12", "ab:12"),
    ('{"password": "supersecretvalue', "supersecretvalue"),
    ('{"password": 12345}', "12345"),
    ('{"password"=LEAKQ}', "LEAKQ"),
]


@pytest.mark.parametrize("raw,secret", SANITIZER_CASES, ids=[secret for _, secret in SANITIZER_CASES])
def test_sanitize_deploy_diagnostic_redacts_secret_shapes(raw: str, secret: str) -> None:
    """W-01: every secret shape from the sanitizer contract is absent after redaction."""
    out = _run_sanitizer(raw + "\n")
    assert secret not in out, out
    assert "[REDACTED]" in out
    assert out.startswith("diagnostic: ")


def test_sanitize_deploy_diagnostic_redacts_single_quoted_mapping_keys() -> None:
    """X-01: Python/mapping single-quoted keys must not leak token values."""
    raw = (
        "{'RECOGNITION_ADMIN_TOKEN': 'LEAKC', 'HF_TOKEN': 'LEAKD'}\n"
        "ERROR config: {'password': 'LEAKE'}\n"
    )
    out = _run_sanitizer(raw)
    assert "LEAKC" not in out, out
    assert "LEAKD" not in out, out
    assert "LEAKE" not in out, out
    assert "[REDACTED]" in out
    assert out.startswith("diagnostic: ")


def test_sanitize_deploy_diagnostic_redacts_basic_authorization() -> None:
    """X-02: Basic auth must be redacted in assignment, header, and bare forms."""
    raw = (
        "Authorization=Basic YWJjOmRlZg==\n"
        "authorization: Basic YWJjOmRlZg==\n"
        "Basic YWJjOmRlZjEyMzQ=\n"
    )
    out = _run_sanitizer(raw)
    assert "YWJjOmRlZg==" not in out, out
    assert "YWJjOmRlZjEyMzQ=" not in out, out
    assert "[REDACTED]" in out
    assert out.startswith("diagnostic: ")


def test_sanitize_deploy_diagnostic_redacts_unquoted_value_through_comma_brace() -> None:
    """X-03: unquoted SECRET/TOKEN values must not stop at comma or closing brace."""
    raw = "SECRET=abc}def TOKEN=abc,def\n"
    out = _run_sanitizer(raw)
    assert "def" not in out, out
    assert "abc" not in out, out
    assert "[REDACTED]" in out
    assert out.startswith("diagnostic: ")


def test_sanitize_deploy_diagnostic_preserves_token_file_and_header_name() -> None:
    """W-01 negative: TOKEN_FILE paths stay; X-Api-Key keeps its header name."""
    raw = (
        "RECOGNITION_ADMIN_TOKEN_FILE=/run/secrets/admin.token\n"
        "X-Api-Key: hunter2\n"
    )
    out = _run_sanitizer(raw)
    assert "RECOGNITION_ADMIN_TOKEN_FILE=/run/secrets/admin.token" in out
    assert "X-Api-Key:" in out
    assert "api-key=" not in out
    assert "hunter2" not in out
    assert "[REDACTED]" in out


def test_sanitize_deploy_diagnostic_redacts_escaped_json_quotes() -> None:
    """GR-02: escaped quote inside a JSON string value must not leak the remainder."""
    raw = json.dumps({"password": 'abc"SYNTHETIC_ESCAPED_CANARY'})
    out = _run_sanitizer(raw + "\n")
    assert "SYNTHETIC_ESCAPED_CANARY" not in out, out
    assert "[REDACTED]" in out
    assert out.startswith("diagnostic: ")

    out_key = _run_sanitizer('{"api_key": "x\\"y\\"LEAKM"}\n')
    assert "LEAKM" not in out_key, out_key
    assert "[REDACTED]" in out_key

    out_auth = _run_sanitizer('{"Authorization": "Bearer ab\\"LEAKN"}\n')
    assert "LEAKN" not in out_auth, out_auth
    assert "[REDACTED]" in out_auth


@pytest.mark.parametrize(
    "raw",
    [
        "Basic health OK",
        "token expired",
        "Invalid token format",
        "Token bucket exhausted",
        "Bearer abc1234",
    ],
)
def test_sanitize_deploy_diagnostic_preserves_prose_bearer_basic_token(raw: str) -> None:
    """LR-01/GR-08/GR-64: ordinary prose and 7-char bare tokens are not redacted."""
    out = _run_sanitizer(raw + "\n")
    assert out == f"diagnostic: {raw}\n"
    assert "[REDACTED]" not in out


def test_sanitize_deploy_diagnostic_authorization_header_redacts_short_and_expired_values() -> None:
    """GR-62: Authorization header stays greedy; short values and 'expired' redact."""
    out_expired = _run_sanitizer("authorization: token expired\n")
    assert out_expired == "diagnostic: Authorization: token [REDACTED]\n"
    assert "expired" not in out_expired

    out_short = _run_sanitizer("Authorization: Basic ab:12\n")
    assert out_short == "diagnostic: Authorization: Basic [REDACTED]\n"
    assert "ab:12" not in out_short


def test_sanitize_deploy_diagnostic_redacts_colon_percent_bare_credentials() -> None:
    """GR-61: bare Bearer/Basic values may include colon and percent."""
    cases = (
        ("Basic user:hunter2", "user:hunter2"),
        ("Bearer eyJ.abc:def", "eyJ.abc:def"),
        ("Basic abcdefgh:xyz", "abcdefgh:xyz"),
        ("Bearer abcdef%2Fgh", "abcdef%2Fgh"),
    )
    for raw, secret in cases:
        out = _run_sanitizer(raw + "\n")
        assert secret not in out, out
        assert out == f"diagnostic: {raw.split()[0]} [REDACTED]\n", out


def test_sanitize_deploy_diagnostic_fail_closed_unterminated_json_values() -> None:
    """GR-63: unterminated quoted JSON values must not leak the remainder."""
    out_escaped = _run_sanitizer('{"password": "abc\\"\n')
    assert "abc" not in out_escaped, out_escaped
    assert '{"password": "[REDACTED]' in out_escaped

    out_open = _run_sanitizer('{"password": "supersecretvalue\n')
    assert "supersecretvalue" not in out_open, out_open
    assert '{"password": "[REDACTED]' in out_open

    out_sibling = _run_sanitizer('{"password": "a\\\\", "x": "LEAKP"}\n')
    assert "LEAKP" in out_sibling, out_sibling
    assert "[REDACTED]" in out_sibling


def test_sanitize_deploy_diagnostic_preserves_json_null_true_false_literals() -> None:
    """GR-65: JSON null/true/false stay intact; numeric secret values still redact."""
    for raw in (
        '{"api_key": null}',
        '{"password": true}',
        '{"password": false}',
        '{"token_count": 5}',
    ):
        out = _run_sanitizer(raw + "\n")
        assert out == f"diagnostic: {raw}\n", out
        assert "[REDACTED]" not in out

    out_num = _run_sanitizer('{"password": 12345}\n')
    assert "12345" not in out_num, out_num
    assert '"password": [REDACTED]' in out_num

    out_leak = _run_sanitizer("{'password': LEAKJ}\n")
    assert "LEAKJ" not in out_leak, out_leak
    assert '"password": [REDACTED]' in out_leak


def test_sanitize_deploy_diagnostic_redacts_quoted_key_equals_unquoted_value() -> None:
    """GR-66: quoted secret key followed by = must redact the unquoted value."""
    out_dq = _run_sanitizer('{"password"=LEAKQ}\n')
    assert "LEAKQ" not in out_dq, out_dq
    assert '"password": [REDACTED]' in out_dq

    out_sq = _run_sanitizer("{'password'=LEAKJ}\n")
    assert "LEAKJ" not in out_sq, out_sq
    assert '"password": [REDACTED]' in out_sq


def test_sanitize_deploy_diagnostic_redacts_unquoted_mapping_values() -> None:
    """GR-09: quoted key with unquoted value redacts the secret and keeps siblings."""
    out = _run_sanitizer("{'password': LEAKJ}\n")
    assert "LEAKJ" not in out, out
    assert '"password": [REDACTED]' in out
    assert out.startswith("diagnostic: ")

    out2 = _run_sanitizer('{"HF_TOKEN": LEAKK, "x": 1}\n')
    assert "LEAKK" not in out2, out2
    assert '"x": 1' in out2
    assert '"HF_TOKEN": [REDACTED]' in out2


# GR-101..107: one _run_sanitizer canary per adjudicated input (positive and negative).
_GR101_107_CASES: list[tuple[str, str]] = [
    ('{"password": nul}', 'diagnostic: {"password": [REDACTED]}\n'),
    ('{"password": tru}', 'diagnostic: {"password": [REDACTED]}\n'),
    ('{"password": fals}', 'diagnostic: {"password": [REDACTED]}\n'),
    ('{"password":n}', 'diagnostic: {"password": [REDACTED]}\n'),
    ('{"password": NUL}', 'diagnostic: {"password": [REDACTED]}\n'),
    ('{"password": null}', 'diagnostic: {"password": null}\n'),
    ('{"password": true}', 'diagnostic: {"password": true}\n'),
    ('{"password": false}', 'diagnostic: {"password": false}\n'),
    ('{"api_key": null}', 'diagnostic: {"api_key": null}\n'),
    ('{"password": "abc\\', 'diagnostic: {"password": "[REDACTED]\n'),
    ('{"password": "abc\\\\\\', 'diagnostic: {"password": "[REDACTED]\n'),
    ('{"password": "o\'reilly"}', 'diagnostic: {"password": "[REDACTED]"}\n'),
    ('{"password": "hello\'world and more"}', 'diagnostic: {"password": "[REDACTED]"}\n'),
    ('{"password": "abc\'def', 'diagnostic: {"password": "[REDACTED]\n'),
    ("Basic us@r:hunter2", "diagnostic: Basic [REDACTED]\n"),
    ("Basic user@example.com:hunter2", "diagnostic: Basic [REDACTED]\n"),
    ("Basic user!hunter2", "diagnostic: Basic [REDACTED]\n"),
    ("Bearer abcdefg?xyz", "diagnostic: Bearer [REDACTED]\n"),
    ("Basic user:hunt,er2xxxxxxx", "diagnostic: Basic [REDACTED]\n"),
    ("Bearer abc1234", "diagnostic: Bearer abc1234\n"),
    ("token expired", "diagnostic: token expired\n"),
    ('{"password"="LEAKS"}', 'diagnostic: {"password": "[REDACTED]"}\n'),
    ('{"password" = "LEAKS"}', 'diagnostic: {"password": "[REDACTED]"}\n'),
    ("{'password'='LEAKJ'}", 'diagnostic: {"password": "[REDACTED]"}\n'),
    ('"password"=="LEAKS"', 'diagnostic: "password": "[REDACTED]"\n'),
]
_GR101_107_IDS = [
    "GR-101-prefix-nul",
    "GR-101-prefix-tru",
    "GR-101-prefix-fals",
    "GR-101-prefix-n",
    "GR-101-prefix-NUL",
    "GR-101-literal-null",
    "GR-101-literal-true",
    "GR-101-literal-false",
    "GR-101-literal-api_key-null",
    "GR-102-dangling-backslash-1",
    "GR-102-dangling-backslash-3",
    "GR-103-apostrophe-oreilly",
    "GR-103-apostrophe-hello-world",
    "GR-103-unterminated-apostrophe",
    "GR-104-basic-at",
    "GR-104-basic-email",
    "GR-104-basic-bang",
    "GR-105-bearer-question",
    "GR-105-basic-comma",
    "GR-104-bearer-7char-floor",
    "GR-104-token-expired-prose",
    "GR-106-quoted-equals",
    "GR-106-quoted-spaced-equals",
    "GR-106-single-quoted-equals",
    "GR-106-double-equals",
]


@pytest.mark.parametrize("raw,expected", _GR101_107_CASES, ids=_GR101_107_IDS)
def test_sanitize_deploy_diagnostic_gr101_107_canaries(raw: str, expected: str) -> None:
    """GR-107: byte-exact canaries for sentinel literals, quotes, dangling \\, bare class, [=:]+."""
    out = _run_sanitizer(raw + "\n")
    assert out == expected


# GR-108/141..144: one _run_sanitizer canary per adjudicated input (positive and negative).
_GR108_144_CASES: list[tuple[str, str]] = [
    ('{"password": =hunter2secret}', 'diagnostic: {"password": [REDACTED]}\n'),
    ('{"password": :hunter2secret}', 'diagnostic: {"password": [REDACTED]}\n'),
    ('{"password": = "LEAKS"}', 'diagnostic: {"password": "[REDACTED]"}\n'),
    ('{"password" = = "LEAKS"}', 'diagnostic: {"password": "[REDACTED]"}\n'),
    ('{"password" : : "xsecret"}', 'diagnostic: {"password": "[REDACTED]"}\n'),
    ('{"password": ["hunter2secret"]}', 'diagnostic: {"password": [REDACTED]\n'),
    ('{"password": {"hash": "deadbeefdeadbeef"}}', 'diagnostic: {"password": [REDACTED]\n'),
    ('{"password": NULL}', 'diagnostic: {"password": [REDACTED]}\n'),
    ('{"password": TRUE}', 'diagnostic: {"password": [REDACTED]}\n'),
    ('{"password": True}', 'diagnostic: {"password": [REDACTED]}\n'),
    ("{'password': False}", 'diagnostic: {"password": [REDACTED]}\n'),
    ('{"password": nulL}', 'diagnostic: {"password": [REDACTED]}\n'),
    ('{"password": null}', 'diagnostic: {"password": null}\n'),
    ('{"password": true}', 'diagnostic: {"password": true}\n'),
    ('{"password": false}', 'diagnostic: {"password": false}\n'),
    ("AWS_ACCESS_KEY_ID=AKIATESTLEAK123", "diagnostic: AWS_ACCESS_KEY_ID=[REDACTED]\n"),
    ("OCI_CLI_KEY_CONTENT=ociclicontent", "diagnostic: OCI_CLI_KEY_CONTENT=[REDACTED]\n"),
    ("SECRET_KEY_BASE=rails-secret-value", "diagnostic: SECRET_KEY_BASE=[REDACTED]\n"),
    ('{"aws_access_key_id": "AKIATESTJSON"}', 'diagnostic: {"aws_access_key_id": "[REDACTED]"}\n'),
    ("x-amz-security-token: amz-token-leak-value", "diagnostic: x-amz-security-token: [REDACTED]\n"),
    ("X-Auth-Token: abcdefghij", "diagnostic: X-Auth-Token: [REDACTED]\n"),
    ('{"api_key_id": "x"}', 'diagnostic: {"api_key_id": "[REDACTED]"}\n'),
    ("TOKEN_FILE=/run/secrets/tok", "diagnostic: TOKEN_FILE=/run/secrets/tok\n"),
    ("AWS_KEY_FILE=/x", "diagnostic: AWS_KEY_FILE=/x\n"),
    ("token_count: 5", "diagnostic: token_count: 5\n"),
]
_GR108_144_IDS = [
    "GR-141-leftover-eq-unquoted",
    "GR-141-leftover-colon-unquoted",
    "GR-141-leftover-eq-quoted",
    "GR-141-double-eq-quoted",
    "GR-141-double-colon-quoted",
    "GR-142-json-array-value",
    "GR-142-json-object-value",
    "GR-143-NULL",
    "GR-143-TRUE",
    "GR-143-True",
    "GR-143-False",
    "GR-143-nulL",
    "GR-143-literal-null",
    "GR-143-literal-true",
    "GR-143-literal-false",
    "GR-108-aws-access-key-id",
    "GR-108-oci-cli-key-content",
    "GR-108-secret-key-base",
    "GR-108-json-aws-access-key-id",
    "GR-108-amz-security-token",
    "GR-108-x-auth-token",
    "GR-108-api-key-id-contract-change",
    "GR-108-token-file-preserved",
    "GR-108-aws-key-file-preserved",
    "GR-108-token-count-preserved",
]


@pytest.mark.parametrize("raw,expected", _GR108_144_CASES, ids=_GR108_144_IDS)
def test_sanitize_deploy_diagnostic_gr108_141_144_canaries(raw: str, expected: str) -> None:
    """GR-144: byte-exact canaries for leftover separators, composites, case-exact literals, cloud keys."""
    out = _run_sanitizer(raw + "\n")
    assert out == expected


def test_sanitize_deploy_diagnostic_gr109_smoke_wrap_sentinel() -> None:
    """GR-109: SMOKE_WRAP unquoted heredoc + declare -f keeps sentinel semantics; no SOH byte."""
    driver = f"""
source "{SCRIPT}"
cat <<SMOKE_WRAP
$(declare -f sanitize_deploy_diagnostic)
$(cat <<'SMOKE'
printf '%s\\n' "$1" | sanitize_deploy_diagnostic
SMOKE
)
SMOKE_WRAP
"""
    rendered = subprocess.run(["bash", "-c", driver], capture_output=True, check=True)
    assert rendered.stdout, rendered.stderr

    def _run_wrap(raw: str) -> bytes:
        result = subprocess.run(
            ["bash", "-s", raw],
            input=rendered.stdout,
            capture_output=True,
            check=True,
        )
        return result.stdout

    nul_out = _run_wrap('{"password": nul}')
    null_out = _run_wrap('{"password": null}')
    assert nul_out == b'diagnostic: {"password": [REDACTED]}\n', nul_out
    assert null_out == b'diagnostic: {"password": null}\n', null_out
    assert b"\001" not in nul_out
    assert b"\001" not in null_out


def test_sanitize_deploy_diagnostic_preserves_benign_token_shapes() -> None:
    """Existing canaries: token_count and ready detail stay intact."""
    raw = (
        "token_count=5\n"
        '{"status": "ok", "token_count": 5}\n'
        '{"detail": "ready"}\n'
    )
    out = _run_sanitizer(raw)
    assert "token_count=5" in out
    assert '"status": "ok", "token_count": 5' in out
    assert '"detail": "ready"' in out
    assert "[REDACTED]" not in out


def test_sanitize_deploy_diagnostic_gr231_docker_auth_identitytoken() -> None:
    """GR-231: docker config.json auth / identitytoken values must not leak."""
    raw = (
        '{"auths":{"iad.ocir.io":{"auth":"dXNlcjpodW50ZXIy","identitytoken":"LEAKID"}}}\n'
        '{"auth":"b2Npci11c2VyOnBhc3N3b3JkLEAK"}\n'
        '{"identitytoken":"eyJleGFtcGxlIjoiaWRlbnRpdHktbGVhayJ9"}\n'
        'DOCKER_AUTH_CONFIG={"auth":"b2Npci11c2VyOnBhc3N3b3JkLEAK"}\n'
    )
    out = _run_sanitizer(raw)
    for secret in (
        "dXNlcjpodW50ZXIy",
        "LEAKID",
        "b2Npci11c2VyOnBhc3N3b3JkLEAK",
        "eyJleGFtcGxlIjoiaWRlbnRpdHktbGVhayJ9",
    ):
        assert secret not in out, out
    assert "[REDACTED]" in out
    assert out.startswith("diagnostic: ")
    assert out.count("\n") == 4


def test_sanitize_deploy_diagnostic_gr232_pretty_printed_json_composites() -> None:
    """GR-232: pretty-printed password array/object continuation lines must redact."""
    raw = (
        '{"password": [\n'
        '  "hunter2secret"\n'
        "]}\n"
        '{"password": {\n'
        '  "hash": "deadbeefdeadbeef"\n'
        "}}\n"
        '"password": [\n'
        '  "LEAKA",\n'
        '  "LEAKB"\n'
        "]\n"
    )
    out = _run_sanitizer(raw)
    for secret in ("hunter2secret", "deadbeefdeadbeef", "LEAKA", "LEAKB"):
        assert secret not in out, out
    assert "[REDACTED]" in out
    assert out.count("\n") == 10


def test_sanitize_deploy_diagnostic_gr233_pem_private_key_body() -> None:
    """GR-233: PEM private-key body lines between BEGIN/END must redact."""
    raw = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEvgIBADANBgkqhkiGLEAKPEM\n"
        "-----END RSA PRIVATE KEY-----\n"
        '{"private_key": "-----BEGIN PRIVATE KEY-----"}\n'
    )
    out = _run_sanitizer(raw)
    assert "LEAKPEM" not in out, out
    assert "MIIEvgIBADANBgkqhkiG" not in out, out
    assert "[REDACTED]" in out
    assert "BEGIN RSA PRIVATE KEY" in out
    assert "END RSA PRIVATE KEY" in out
    assert out.count("\n") == 4


def test_sanitize_deploy_diagnostic_s2b01_utf8_locale_pipeline() -> None:
    """S2B-01: UTF-8 canaries survive LC_ALL=C pipeline; later PASSWORD still redacts."""
    raw = (
        "Loading checkpoint shards: 1 ━━━━━━━━━ 100% — done 🚀\n"
        "PASSWORD=hunter2secret\n"
    )
    env = os.environ.copy()
    env["LC_ALL"] = "en_US.utf8"
    env["LANG"] = "en_US.utf8"
    env["LC_CTYPE"] = "en_US.utf8"
    result = subprocess.run(
        ["bash", "-c", _sanitize_deploy_diagnostic_src() + "\nsanitize_deploy_diagnostic"],
        input=raw,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
        env=env,
    )
    out = result.stdout
    assert "hunter2secret" not in out, out
    assert "[REDACTED]" in out
    assert out.count("\n") == 2
    assert "—" in out, out
    assert "━" in out, out
    assert "🚀" in out, out
    assert out.startswith("diagnostic: ")


def test_sanitize_deploy_diagnostic_gr234_url_userinfo() -> None:
    """GR-234: empty-user and @-in-password URL userinfo must redact."""
    raw = "https://:hunter2secret@ghcr.io/v2/\nhttps://user:p@ssword@host/path\n"
    out = _run_sanitizer(raw)
    assert "hunter2secret" not in out, out
    assert "p@ssword" not in out, out
    assert "@ssword@" not in out, out
    assert "[REDACTED]" in out
    assert "ghcr.io" in out
    assert "host/path" in out
    assert out.count("\n") == 2


def test_sanitize_deploy_diagnostic_gr235_npmrc_auth_tokens() -> None:
    """GR-235: .npmrc _authToken / _auth assignments must redact."""
    raw = (
        "//registry.npmjs.org/:_authToken=npm_LEAKTOKEN\n"
        "//registry.npmjs.org/:_auth=dXNlcjpwYXNzLEAK\n"
    )
    out = _run_sanitizer(raw)
    assert "npm_LEAKTOKEN" not in out, out
    assert "dXNlcjpwYXNzLEAK" not in out, out
    assert "[REDACTED]" in out
    assert out.count("\n") == 2


def test_sanitize_deploy_diagnostic_gr236_authorization_apikey() -> None:
    """GR-236: Authorization ApiKey / api-key schemes must redact."""
    raw = (
        "Authorization: ApiKey hf_LEAKAPIKEYVALUE\n"
        "Authorization: api-key hf_LEAKAPIKEYVALUE\n"
    )
    out = _run_sanitizer(raw)
    assert "hf_LEAKAPIKEYVALUE" not in out, out
    assert "[REDACTED]" in out
    assert out.count("\n") == 2


def test_sanitize_deploy_diagnostic_gr238_prefix_only_cloud_tokens() -> None:
    """GR-238: prefix-only ghp_ / github_pat_ / AKIA tokens must redact."""
    raw = (
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789\n"
        "github_pat_11AAAALEAKTOKENVALUE\n"
        "AKIAIOSFODNN7EXAMPLE\n"
    )
    out = _run_sanitizer(raw)
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in out, out
    assert "github_pat_11AAAALEAKTOKENVALUE" not in out, out
    assert "AKIAIOSFODNN7EXAMPLE" not in out, out
    assert "LEAKTOKENVALUE" not in out, out
    assert "[REDACTED]" in out
    assert out.count("\n") == 3


def test_sanitize_deploy_diagnostic_s2b02_double_separator_and_hash_rocket() -> None:
    """S2B-02: leftover separators and => hash rockets must not leak the value."""
    raw = (
        "PASSWORD == hunter2secret\n"
        "PASSWORD := hunter2secret\n"
        "PASSWORD = = hunter2secret\n"
        "PASSWORD:= hunter2secret\n"
        '"password" => "hunter2secret"\n'
    )
    out = _run_sanitizer(raw)
    assert "hunter2secret" not in out, out
    assert "[REDACTED]" in out
    assert out.count("\n") == 5


def test_sanitize_deploy_diagnostic_s2b03_hyphen_cli_flags() -> None:
    """S2B-03: --password= / --token= / --db-password= flags must redact."""
    raw = (
        "--password=hunter2secret\n"
        "--token=hunter2secret\n"
        "--secret=hunter2secret\n"
        "--db-password=hunter2secret\n"
        "unknown flag: --password=hunter2secret\n"
    )
    out = _run_sanitizer(raw)
    assert "hunter2secret" not in out, out
    assert "[REDACTED]" in out
    assert out.count("\n") == 5


def test_sanitize_deploy_diagnostic_s2b04_quoted_bearer_header() -> None:
    """S2B-04: quoted Bearer values in Authorization headers must redact."""
    raw = 'authorization: Bearer "hunter2secret"\nAuthorization: Bearer \'hunter2secret\'\n'
    out = _run_sanitizer(raw)
    assert "hunter2secret" not in out, out
    assert "[REDACTED]" in out
    assert out.count("\n") == 2


def test_sanitize_deploy_diagnostic_s2b05_escaped_quotes_in_env() -> None:
    """S2B-05: escaped quotes inside env values must not leak the remainder."""
    raw = 'PASSWORD="hunter2\\" secret"\n'
    out = _run_sanitizer(raw)
    assert "hunter2" not in out, out
    assert "secret" not in out, out
    assert "[REDACTED]" in out
    assert out.startswith("diagnostic: ")


def test_sanitize_deploy_diagnostic_gr239_declare_f_has_no_soh_byte() -> None:
    """GR-239: declare -f of the sanitizer must not materialize a raw SOH byte."""
    driver = f'source "{SCRIPT}"; declare -f sanitize_deploy_diagnostic'
    rendered = subprocess.run(["bash", "-c", driver], capture_output=True, check=True)
    assert rendered.stdout, rendered.stderr
    assert b"\001" not in rendered.stdout


def test_sanitize_deploy_diagnostic_s2b08_passphrase_pwd_cookie() -> None:
    """S2B-08: MYSQL_PWD / PASSPHRASE / AUTH / Cookie session values must redact."""
    raw = (
        "MYSQL_PWD=hunter2secret\n"
        "PASSPHRASE=hunter2secret\n"
        "OCI_CLI_PASSPHRASE=hunter2secret\n"
        "pass_phrase=hunter2secret\n"
        "REDISCLI_AUTH=hunter2secret\n"
        "AUTH=hunter2secret\n"
        "PASS=hunter2secret\n"
        "CREDENTIALS=hunter2secret\n"
        "Cookie: session=hunter2secret\n"
    )
    out = _run_sanitizer(raw)
    assert "hunter2secret" not in out, out
    assert "[REDACTED]" in out
    assert out.count("\n") == 9


_REV_W01_CANARIES = [
    ('{"access_token":"LEAKA"}', "LEAKA"),
    ('{"api_key": "LEAKB"}', "LEAKB"),
    ('{"password": "LEAKC"}', "LEAKC"),
    ("SECRET=LEAKD", "LEAKD"),
    ("KEY=LEAKE", "LEAKE"),
    ('PGPASSWORD="quoted LEAKF tail"', "LEAKF"),
    ("postgresql://acx:LEAKG@db/x", "LEAKG"),
    ("postgres://u:LEAKH@h:5432/d?sslmode=require", "LEAKH"),
]


@pytest.mark.parametrize(
    "raw,secret",
    _REV_W01_CANARIES,
    ids=[secret for _, secret in _REV_W01_CANARIES],
)
def test_sanitize_deploy_diagnostic_rev_w01_canaries(raw: str, secret: str) -> None:
    """REV-W-01: exact Wave G sanitizer canaries must not survive redaction."""
    out = _run_sanitizer(raw + "\n")
    assert secret not in out, out
    assert "[REDACTED]" in out
    assert out.startswith("diagnostic: ")


def test_sanitize_deploy_diagnostic_s2b09_authorization_signature_digest() -> None:
    """S2B-09: Signature / Digest / AWS4 / scheme-less Authorization must redact."""
    raw = (
        'Authorization: Signature version="1",keyId="ocid1.tenancy...",'
        'algorithm="rsa-sha256",signature="LEAKSIGNATUREBASE64=="\n'
        "Authorization: hunter2secretrawtoken\n"
        'Authorization: Digest username="u", response="leakleak"\n'
        "Authorization: AWS4-HMAC-SHA256 Credential=AKIAEXAMPLE, Signature=leakleak\n"
    )
    out = _run_sanitizer(raw)
    for secret in (
        "LEAKSIGNATUREBASE64==",
        "hunter2secretrawtoken",
        "leakleak",
        "AKIAEXAMPLE",
    ):
        assert secret not in out, out
    assert "[REDACTED]" in out
    assert out.count("\n") == 4
