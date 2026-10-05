#!/usr/bin/env python3
"""Read-only validator for production Clerk values in the environment manifest."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
from env.manifest import Manifest, ManifestError, effective_var, load_manifest  # noqa: E402

DEFAULT_AUTHORIZED_PARTY = "https://app.altcontext.com"
APP_PORTAL_TARGET = "app-portal-build"
BACKEND_TARGET = "svc-vm"
JWKS_PATH = "/.well-known/jwks.json"
CHECK_TIMEOUT_S = 2.0
CHECK_MAX_BYTES = 256 * 1024
CHECK_READ_CHUNK = 4096
MAX_FRONTEND_MODULES = 512
MAX_FRONTEND_MODULE_BYTES = 16 * 1024 * 1024
MAX_FRONTEND_TOTAL_BYTES = 128 * 1024 * 1024
MAX_FRONTEND_TOKENS = 2_000_000
_CLERK_KEY_FIELD = "VITE_CLERK_PUBLISHABLE_KEY"
_CLERK_FAPI_FIELD = "VITE_CLERK_FAPI"
_PORTAL_ENABLED_FIELD = "VITE_PORTAL_ENABLED"
_FRONTEND_CONFIG_FIELDS = frozenset({_CLERK_KEY_FIELD, _CLERK_FAPI_FIELD, _PORTAL_ENABLED_FIELD})
_HOSTNAME_RE = re.compile(
    r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)
_DEV_HOST_SUFFIXES = (".accounts.dev", ".lcl.dev", ".lclclerk.com")


class ClerkConfigError(Exception):
    """Manifest validation failure with no configuration values in the message."""


@dataclass(frozen=True, slots=True)
class DerivedClerkConfig:
    publishable_key: str
    frontend_api: str
    issuer: str
    jwks_url: str
    audience: str
    authorized_parties: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _JSToken:
    kind: str
    value: str | None
    raw: str
    line_break_before: bool = False


def decode_publishable_key(raw: str) -> str:
    """Return the Clerk FAPI hostname encoded in a ``pk_live_`` key."""
    key = _single_line_value(raw)
    if key.startswith("pk_test_"):
        raise ClerkConfigError("development key refused; production requires pk_live_")
    if not key.startswith("pk_live_"):
        raise ClerkConfigError("key must start with pk_live_")
    payload = key.removeprefix("pk_live_")
    if not payload:
        raise ClerkConfigError("key is missing the encoded frontend API host")
    padded = payload + "=" * (-len(payload) % 4)
    try:
        decoded = base64.b64decode(padded, validate=False)
    except (ValueError, binascii.Error):
        try:
            decoded = base64.urlsafe_b64decode(padded)
        except (ValueError, binascii.Error) as exc:
            raise ClerkConfigError("key is not valid base64") from exc
    try:
        text = decoded.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ClerkConfigError("decoded host is not ASCII") from exc
    if not text.endswith("$"):
        raise ClerkConfigError("decoded host must end with '$'")
    host = text[:-1]
    if not host or "/" in host or ":" in host or "@" in host or " " in host:
        raise ClerkConfigError("malformed frontend API host")
    lowered = host.lower()
    if lowered == "localhost" or any(lowered.endswith(suffix) for suffix in _DEV_HOST_SUFFIXES):
        raise ClerkConfigError("development frontend API host refused")
    if not _HOSTNAME_RE.fullmatch(host):
        raise ClerkConfigError("malformed frontend API host")
    return host


def load_production_config(manifest_root: Path) -> DerivedClerkConfig:
    try:
        manifest = load_manifest(manifest_root)
    except (ManifestError, OSError, ValueError):
        raise ClerkConfigError("config/env manifest is invalid") from None

    publishable_key = _manifest_value(manifest, APP_PORTAL_TARGET, "VITE_CLERK_PUBLISHABLE_KEY")
    try:
        host = decode_publishable_key(publishable_key)
    except ClerkConfigError as exc:
        raise ClerkConfigError(f"VITE_CLERK_PUBLISHABLE_KEY: {exc}") from None

    frontend_api = f"https://{host}"
    fapi_value = _manifest_value(manifest, APP_PORTAL_TARGET, "VITE_CLERK_FAPI")
    if _https_origin(fapi_value, "VITE_CLERK_FAPI") != frontend_api:
        raise ClerkConfigError("VITE_CLERK_FAPI: must match the host encoded in VITE_CLERK_PUBLISHABLE_KEY")

    issuer = _manifest_value(manifest, BACKEND_TARGET, "ACX_CLERK_ISSUER")
    if issuer != frontend_api:
        raise ClerkConfigError("ACX_CLERK_ISSUER: must match VITE_CLERK_PUBLISHABLE_KEY")

    jwks_url = _manifest_value(manifest, BACKEND_TARGET, "ACX_CLERK_JWKS_URL")
    expected_jwks_url = f"{frontend_api}{JWKS_PATH}"
    if jwks_url != expected_jwks_url:
        raise ClerkConfigError("ACX_CLERK_JWKS_URL: must match ACX_CLERK_ISSUER")

    audience = _manifest_value(manifest, BACKEND_TARGET, "ACX_CLERK_AUDIENCE")
    if not audience or any(char in audience for char in "\n\r\0,"):
        raise ClerkConfigError("ACX_CLERK_AUDIENCE: one non-empty value is required")

    parties_raw = _manifest_value(manifest, BACKEND_TARGET, "ACX_CLERK_AUTHORIZED_PARTIES")
    parties = tuple(part.strip() for part in parties_raw.split(",") if part.strip())
    if parties != (DEFAULT_AUTHORIZED_PARTY,):
        raise ClerkConfigError("ACX_CLERK_AUTHORIZED_PARTIES: must contain only https://app.altcontext.com")

    return DerivedClerkConfig(
        publishable_key=publishable_key,
        frontend_api=frontend_api,
        issuer=issuer,
        jwks_url=jwks_url,
        audience=audience,
        authorized_parties=parties,
    )


def _manifest_value(manifest: Manifest, target_name: str, name: str) -> str:
    target = manifest.targets.get(target_name)
    if target is None or "prod" not in target.envs:
        raise ClerkConfigError(f"{name}: production target is unavailable")
    variable = next((item for item in manifest.vars if item.name == name), None)
    if variable is None or target_name not in variable.targets:
        raise ClerkConfigError(f"{name}: production manifest value is unavailable")
    value = effective_var(manifest, variable, target_name).values.get("prod")
    if not isinstance(value, str) or not value.strip():
        raise ClerkConfigError(f"{name}: production manifest value is required")
    return value.strip()


def _https_origin(raw: str, name: str) -> str:
    try:
        parsed = urlparse(raw)
        valid = (
            parsed.scheme == "https"
            and bool(parsed.netloc)
            and parsed.path in {"", "/"}
            and not parsed.params
            and not parsed.query
            and not parsed.fragment
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        valid = False
    if not valid:
        raise ClerkConfigError(f"{name}: exact https origin is required")
    return f"https://{parsed.netloc}"


def _single_line_value(raw: str) -> str:
    if "\0" in raw:
        raise ClerkConfigError("value contains a NUL")
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) != 1 or any(char in lines[0] for char in " \t"):
        raise ClerkConfigError("value must be a single line without whitespace")
    return lines[0]


def _skip_quoted_javascript(source: str, start: int) -> tuple[int, str, str | None]:
    quote = source[start]
    index = start + 1
    value_start = index
    escaped = False
    while index < len(source):
        char = source[index]
        if char == quote:
            raw = source[value_start:index]
            return index + 1, raw, None if escaped else raw
        if char in "\r\n" and quote != "`":
            raise ClerkConfigError("reachable JavaScript module has an unterminated string")
        if char == "\\":
            escaped = True
            index += 2
            continue
        index += 1
    raise ClerkConfigError("reachable JavaScript module has an unterminated string")


def _template_regex_can_start(source: str, expression_start: int, index: int) -> bool:
    prefix = source[expression_start:index].rstrip()
    return bool(prefix) and (
        prefix[-1] in "=(:,[!&|?{};" or prefix.endswith(("return", "throw", "case", "yield", "await"))
    )


def _skip_template_expression(source: str, start: int) -> int:
    depth = 0
    index = start
    while index < len(source):
        char = source[index]
        if char in "'\"":
            index, _, _ = _skip_quoted_javascript(source, index)
            continue
        if char == "`":
            index = _skip_template_javascript(source, index)
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            if newline < 0:
                raise ClerkConfigError("reachable JavaScript module has an unterminated template expression")
            index = newline + 1
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0:
                raise ClerkConfigError("reachable JavaScript module has an unterminated comment")
            index = end + 2
            continue
        if char == "/" and _template_regex_can_start(source, start, index):
            index = _skip_regex_javascript(source, index)
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            if depth == 0:
                return index + 1
            depth -= 1
        index += 1
    raise ClerkConfigError("reachable JavaScript module has an unterminated template expression")


def _skip_template_javascript(source: str, start: int) -> int:
    index = start + 1
    while index < len(source):
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if char == "`":
            return index + 1
        if source.startswith("${", index):
            index = _skip_template_expression(source, index + 2)
            continue
        index += 1
    raise ClerkConfigError("reachable JavaScript module has an unterminated template")


def _regex_can_start(tokens: Sequence[_JSToken]) -> bool:
    if not tokens:
        return True
    previous = tokens[-1]
    return previous.kind == "punct" and previous.value in {
        "=", "(", "[", "{", ",", ":", ";", "!", "?", "=>", "&&", "||", "??"
    } or previous.kind == "identifier" and previous.value in {"return", "throw", "case", "yield", "await"}


def _skip_regex_javascript(source: str, start: int) -> int:
    index = start + 1
    in_class = False
    escaped = False
    while index < len(source):
        char = source[index]
        if char in "\r\n":
            break
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif char == "/" and not in_class:
            index += 1
            while index < len(source) and (source[index].isalpha() or source[index] == "$"):
                index += 1
            return index
        index += 1
    raise ClerkConfigError("reachable JavaScript module has an unterminated regular expression")


def _tokenize_javascript(source: str) -> list[_JSToken]:
    tokens: list[_JSToken] = []
    index = 0
    last_token_end = 0
    operators = ("===", "!==", "=>", "==", "!=", "<=", ">=", "++", "--", "+=", "-=", "*=", "/=", "&&", "||", "??", "...", "?.")
    while index < len(source):
        char = source[index]
        if char.isspace():
            index += 1
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            index = len(source) if newline < 0 else newline + 1
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0:
                raise ClerkConfigError("reachable JavaScript module has an unterminated comment")
            index = end + 2
            continue
        token_start = index
        line_break_before = any(char in source[last_token_end:token_start] for char in "\r\n")
        if char in "'\"":
            index, raw, value = _skip_quoted_javascript(source, index)
            tokens.append(_JSToken("string", value, raw, line_break_before))
        elif char == "`":
            end = _skip_template_javascript(source, index)
            tokens.append(_JSToken("template", None, source[index + 1 : end - 1], line_break_before))
            index = end
        elif char == "/" and _regex_can_start(tokens):
            end = _skip_regex_javascript(source, index)
            tokens.append(_JSToken("regex", None, source[index:end], line_break_before))
            index = end
        elif char.isascii() and (char.isalpha() or char in "_$"):
            end = index + 1
            while end < len(source) and source[end].isascii() and (source[end].isalnum() or source[end] in "_$"):
                end += 1
            tokens.append(_JSToken("identifier", source[index:end], source[index:end], line_break_before))
            index = end
        else:
            operator = next((item for item in operators if source.startswith(item, index)), None)
            if operator is not None:
                tokens.append(_JSToken("punct", operator, operator, line_break_before))
                index += len(operator)
            else:
                tokens.append(_JSToken("punct", char, char, line_break_before))
                index += 1
        last_token_end = index
        if len(tokens) > MAX_FRONTEND_TOKENS:
            raise ClerkConfigError("reachable JavaScript module exceeds the static inspection limit")
    return tokens


def _javascript_delimiters(tokens: Sequence[_JSToken]) -> tuple[dict[int, int], list[tuple[int, ...]]]:
    closing = {"{": "}", "[": "]", "(": ")"}
    reverse = {value: key for key, value in closing.items()}
    stack: list[tuple[str, int]] = []
    pairs: dict[int, int] = {}
    scopes: list[tuple[int, ...]] = []
    for index, token in enumerate(tokens):
        value = token.value
        scopes.append(tuple(position for opener, position in stack if opener == "{"))
        if value in closing:
            stack.append((value, index))
        elif value in reverse:
            if not stack or stack[-1][0] != reverse[value]:
                raise ClerkConfigError("reachable JavaScript module has unsupported delimiters")
            _, opener = stack.pop()
            pairs[opener] = index
            pairs[index] = opener
    if stack:
        raise ClerkConfigError("reachable JavaScript module has unsupported delimiters")
    return pairs, scopes


def _object_fields(
    tokens: Sequence[_JSToken], pairs: dict[int, int], open_index: int
) -> tuple[dict[str, tuple[_JSToken, int]], bool]:
    close_index = pairs[open_index]
    fields: dict[str, tuple[_JSToken, int]] = {}
    has_spread = False
    index = open_index + 1
    while index < close_index:
        token = tokens[index]
        if token.value == ",":
            index += 1
            continue
        if token.value == "...":
            has_spread = True
        if token.kind in {"identifier", "string"} and index + 1 < close_index and tokens[index + 1].value == ":":
            name = token.value
            if name in _FRONTEND_CONFIG_FIELDS:
                if name in fields:
                    raise ClerkConfigError(f"{name}: portal configuration binding is ambiguous")
                value_start = index + 2
                value_end = value_start
                while value_end < close_index:
                    value_token = tokens[value_end]
                    if value_token.value in {"{", "[", "("}:
                        value_end = pairs[value_end] + 1
                    elif value_token.value == ",":
                        break
                    else:
                        value_end += 1
                if value_end - value_start != 1:
                    fields[name] = (_JSToken("unsupported", None, ""), value_start)
                else:
                    fields[name] = (tokens[value_start], value_start)
                index = value_end + 1
                continue
        if token.value in {"{", "[", "("}:
            index = pairs[index] + 1
        else:
            index += 1
    return fields, has_spread


_INITIALIZER_CONTINUATIONS = frozenset(
    {
        "(", "[", ".", "?.", "+", "-", "*", "/", "%", "**", "<", ">", "<=", ">=", "==", "===", "!=", "!==",
        "&&", "||", "??", "?", ":", "=", "+=", "-=", "*=", "/=", "=>", "&", "|", "^", "in", "instanceof", "of",
        "as", "satisfies",
    }
)


def _initializer_ends_here(tokens: Sequence[_JSToken], next_index: int) -> bool:
    if next_index == len(tokens):
        return True
    following = tokens[next_index]
    if following.value in {";", ",", "}"}:
        return True
    if not following.line_break_before:
        return False
    return following.kind != "template" and following.value not in _INITIALIZER_CONTINUATIONS


def _resolve_static_alias(
    name: str,
    tokens: Sequence[_JSToken],
    scopes: Sequence[tuple[int, ...]],
    use_scope: tuple[int, ...],
    before_index: int,
    seen: frozenset[tuple[str, tuple[int, ...], int]] = frozenset(),
) -> str:
    declarations: list[tuple[int, tuple[int, ...], _JSToken]] = []
    index = 0
    while index + 3 < before_index:
        if (
            tokens[index].value == "const"
            and tokens[index + 1].kind == "identifier"
            and tokens[index + 1].value == name
            and tokens[index + 2].value == "="
        ):
            initializer = tokens[index + 3]
            declarations.append((index, scopes[index], initializer))
        index += 1
    visible = [item for item in declarations if len(item[1]) <= len(use_scope) and use_scope[: len(item[1])] == item[1]]
    if not visible:
        raise ClerkConfigError("VITE_CLERK_FAPI: configuration alias is unsupported")
    max_scope = max(len(item[1]) for item in visible)
    nearest = [item for item in visible if len(item[1]) == max_scope]
    if len(nearest) != 1:
        raise ClerkConfigError("VITE_CLERK_FAPI: configuration alias is ambiguous")
    declaration_index, declaration_scope, initializer = nearest[0]
    identity = (name, declaration_scope, declaration_index)
    if identity in seen:
        raise ClerkConfigError("VITE_CLERK_FAPI: configuration alias is cyclic")
    if len(seen) >= 16:
        raise ClerkConfigError("VITE_CLERK_FAPI: configuration alias chain is too deep")
    if initializer.kind not in {"string", "identifier"} or not _initializer_ends_here(tokens, declaration_index + 4):
        raise ClerkConfigError("VITE_CLERK_FAPI: configuration alias initializer is unsupported")
    if initializer.kind == "string":
        if initializer.value is None:
            raise ClerkConfigError("VITE_CLERK_FAPI: escaped configuration aliases are unsupported")
        return initializer.value
    assert initializer.value is not None
    return _resolve_static_alias(
        initializer.value,
        tokens,
        scopes,
        declaration_scope,
        declaration_index,
        seen | {identity},
    )


def _static_field_value(
    name: str,
    field: tuple[_JSToken, int],
    tokens: Sequence[_JSToken],
    scopes: Sequence[tuple[int, ...]],
    use_scope: tuple[int, ...],
) -> str:
    token, value_index = field
    if token.kind == "string" and token.value is not None:
        return token.value
    if token.kind == "identifier" and token.value is not None:
        try:
            return _resolve_static_alias(token.value, tokens, scopes, use_scope, value_index)
        except ClerkConfigError as exc:
            message = str(exc)
            if message.startswith("VITE_CLERK_FAPI:"):
                raise ClerkConfigError(message.replace("VITE_CLERK_FAPI:", f"{name}:", 1)) from None
            raise
    raise ClerkConfigError(f"{name}: configuration value is not a supported static string")


def _function_parameter_consumers(tokens: Sequence[_JSToken], pairs: dict[int, int]) -> dict[str, str]:
    consumers: dict[str, str] = {}

    def add_consumer(name: str | None, params_open: int, body_open: int) -> None:
        if name is None or body_open not in pairs or params_open >= len(tokens):
            return
        if tokens[params_open].value == "(":
            first_param = tokens[params_open + 1] if params_open + 1 < pairs[params_open] else None
        else:
            first_param = tokens[params_open]
        if first_param is None or first_param.kind != "identifier":
            return
        body_close = pairs[body_open]
        fields = {
            tokens[index + 2].value
            for index in range(body_open + 1, body_close - 2)
            if tokens[index].value == first_param.value
            and tokens[index + 1].value == "."
            and tokens[index + 2].kind == "identifier"
        }
        if {_CLERK_KEY_FIELD, _CLERK_FAPI_FIELD}.issubset(fields):
            consumers[name] = first_param.value

    for index, token in enumerate(tokens):
        if token.value == "function":
            name_index = index + 1
            if name_index < len(tokens) and tokens[name_index].value == "*":
                name_index += 1
            if name_index >= len(tokens) or tokens[name_index].kind != "identifier":
                continue
            params_open = name_index + 1
            if params_open >= len(tokens) or tokens[params_open].value != "(":
                continue
            body_open = pairs.get(params_open, -1) + 1
            if body_open < len(tokens) and tokens[body_open].value == "{":
                add_consumer(tokens[name_index].value, params_open, body_open)
        if (
            token.value == "const"
            and index + 3 < len(tokens)
            and tokens[index + 1].kind == "identifier"
            and tokens[index + 2].value == "="
            and tokens[index + 3].value == "function"
        ):
            params_open = index + 4
            if params_open < len(tokens) and tokens[params_open].value == "(":
                body_open = pairs.get(params_open, -1) + 1
                if body_open < len(tokens) and tokens[body_open].value == "{":
                    add_consumer(tokens[index + 1].value, params_open, body_open)
        if token.value == "const" and index + 4 < len(tokens) and tokens[index + 1].kind == "identifier" and tokens[index + 2].value == "=":
            name = tokens[index + 1].value
            params_open = index + 3
            if tokens[params_open].value == "(":
                params_close = pairs.get(params_open, -1)
                arrow = params_close + 1
            elif tokens[params_open].kind == "identifier":
                params_close = params_open
                arrow = params_open + 1
            else:
                continue
            body_open = arrow + 1
            if arrow < len(tokens) and tokens[arrow].value == "=>" and body_open < len(tokens) and tokens[body_open].value == "{":
                add_consumer(name, params_open, body_open)
    return consumers


def _resolve_config_object(
    name: str,
    tokens: Sequence[_JSToken],
    scopes: Sequence[tuple[int, ...]],
    use_scope: tuple[int, ...],
    before_index: int,
    config_objects: set[int],
    pairs: dict[int, int],
    seen: frozenset[tuple[str, tuple[int, ...], int]] = frozenset(),
) -> int:
    declarations: list[tuple[int, tuple[int, ...], int]] = []
    for index in range(before_index - 3):
        if (
            tokens[index].value == "const"
            and tokens[index + 1].kind == "identifier"
            and tokens[index + 1].value == name
            and tokens[index + 2].value == "="
        ):
            declarations.append((index, scopes[index], index + 3))
    visible = [item for item in declarations if len(item[1]) <= len(use_scope) and use_scope[: len(item[1])] == item[1]]
    if not visible:
        raise ClerkConfigError("VITE_CLERK_FAPI: portal config object alias is unsupported")
    max_scope = max(len(item[1]) for item in visible)
    nearest = [item for item in visible if len(item[1]) == max_scope]
    if len(nearest) != 1:
        raise ClerkConfigError("VITE_CLERK_FAPI: portal config object alias is ambiguous")
    declaration_index, declaration_scope, initializer_index = nearest[0]
    identity = (name, declaration_scope, declaration_index)
    if identity in seen or len(seen) >= 16:
        raise ClerkConfigError("VITE_CLERK_FAPI: portal config object alias is cyclic or too deep")
    initializer = tokens[initializer_index]
    if initializer.value == "{":
        close_index = pairs.get(initializer_index)
        if (
            initializer_index not in config_objects
            or close_index is None
            or not _initializer_ends_here(tokens, close_index + 1)
        ):
            raise ClerkConfigError("VITE_CLERK_FAPI: portal config object alias has no supported binding")
        return initializer_index
    if initializer.kind != "identifier" or not _initializer_ends_here(tokens, initializer_index + 1):
        raise ClerkConfigError("VITE_CLERK_FAPI: portal config object alias initializer is unsupported")
    assert initializer.value is not None
    return _resolve_config_object(
        initializer.value,
        tokens,
        scopes,
        declaration_scope,
        declaration_index,
        config_objects,
        pairs,
        seen | {identity},
    )


def _portal_config_records(tokens: Sequence[_JSToken]) -> tuple[list[dict[str, str]], set[str]]:
    pairs, scopes = _javascript_delimiters(tokens)
    consumer_functions = _function_parameter_consumers(tokens, pairs)
    object_records: dict[int, dict[str, str]] = {}
    for open_index, token in enumerate(tokens):
        if token.value != "{" or open_index not in pairs:
            continue
        previous = tokens[open_index - 1] if open_index else None
        if previous is not None and previous.value not in {"=", "(", "[", ",", ":", "return", "=>"}:
            continue
        fields, has_spread = _object_fields(tokens, pairs, open_index)
        if not (_FRONTEND_CONFIG_FIELDS & fields.keys()):
            continue
        if has_spread or not _FRONTEND_CONFIG_FIELDS.issubset(fields):
            raise ClerkConfigError("VITE_CLERK_FAPI: portal configuration record is incomplete or unsupported")
        use_scope = scopes[open_index]
        object_records[open_index] = {
            name: _static_field_value(name, fields[name], tokens, scopes, use_scope)
            for name in _FRONTEND_CONFIG_FIELDS
        }

    consumed_objects: set[int] = set()
    for call_index, token in enumerate(tokens):
        if token.value not in consumer_functions or call_index + 1 >= len(tokens) or tokens[call_index + 1].value != "(":
            continue
        if call_index and tokens[call_index - 1].value in {"function", ".", "?."}:
            continue
        call_open = call_index + 1
        if call_open not in pairs:
            continue
        call_close = pairs[call_open]
        argument_start = call_open + 1
        argument_end = argument_start
        while argument_end < call_close:
            value = tokens[argument_end].value
            if value in {"{", "[", "("}:
                argument_end = pairs[argument_end] + 1
            elif value == ",":
                break
            else:
                argument_end += 1
        if argument_end == argument_start:
            continue
        if (
            tokens[argument_start].value == "{"
            and argument_start in pairs
            and pairs[argument_start] + 1 == argument_end
        ):
            object_index = argument_start
        elif argument_end - argument_start == 1 and tokens[argument_start].kind == "identifier":
            object_index = _resolve_config_object(
                tokens[argument_start].value or "",
                tokens,
                scopes,
                scopes[call_index],
                call_index,
                set(object_records),
                pairs,
            )
        else:
            continue
        if object_index in object_records:
            consumed_objects.add(object_index)

    if object_records.keys() != consumed_objects:
        raise ClerkConfigError("VITE_CLERK_FAPI: portal configuration record is not consumed by the Clerk config parser")
    return list(object_records.values()), {_CLERK_KEY_FIELD, _CLERK_FAPI_FIELD} if consumer_functions else set()


def validate_frontend_modules(config: DerivedClerkConfig, module_paths: Sequence[Path]) -> None:
    if not module_paths:
        raise ClerkConfigError("reachable JavaScript module assets are required")
    if len(module_paths) > MAX_FRONTEND_MODULES:
        raise ClerkConfigError("reachable JavaScript module count exceeds the static inspection limit")
    total_bytes = 0
    total_tokens = 0
    records: list[dict[str, str]] = []
    consumers: set[str] = set()
    has_expected_key = False
    for path in module_paths:
        try:
            raw_contents = path.read_bytes()
        except OSError:
            raise ClerkConfigError("reachable JavaScript module asset cannot be read") from None
        total_bytes += len(raw_contents)
        if len(raw_contents) > MAX_FRONTEND_MODULE_BYTES or total_bytes > MAX_FRONTEND_TOTAL_BYTES:
            raise ClerkConfigError("reachable JavaScript modules exceed the static inspection limit")
        try:
            contents = raw_contents.decode("utf-8")
        except UnicodeError:
            raise ClerkConfigError("reachable JavaScript module asset cannot be read") from None
        tokens = _tokenize_javascript(contents)
        total_tokens += len(tokens)
        if total_tokens > MAX_FRONTEND_TOKENS:
            raise ClerkConfigError("reachable JavaScript modules exceed the static inspection limit")
        key_tokens = [
            key
            for token in tokens
            if token.kind in {"string", "template"}
            for key in re.findall(r"\bpk_(?:live|test)_[A-Za-z0-9_+/=-]+", token.raw)
        ]
        if any(token != config.publishable_key for token in key_tokens):
            raise ClerkConfigError("VITE_CLERK_PUBLISHABLE_KEY: reachable module contains a different Clerk key")
        has_expected_key = has_expected_key or any(config.publishable_key in token.raw for token in tokens if token.kind in {"string", "template"})
        module_records, module_consumers = _portal_config_records(tokens)
        records.extend(module_records)
        consumers.update(module_consumers)
    if not has_expected_key:
        raise ClerkConfigError("VITE_CLERK_PUBLISHABLE_KEY is absent from reachable JavaScript modules")
    if consumers != {_CLERK_KEY_FIELD, _CLERK_FAPI_FIELD}:
        raise ClerkConfigError("VITE_CLERK_FAPI: no supported Clerk configuration consumer was found")
    if not records:
        raise ClerkConfigError("VITE_CLERK_FAPI: supported portal configuration record is absent")
    if len(records) != 1:
        raise ClerkConfigError("VITE_CLERK_FAPI: reachable portal configuration is ambiguous")
    record = records[0]
    if record[_CLERK_KEY_FIELD] != config.publishable_key:
        raise ClerkConfigError("VITE_CLERK_PUBLISHABLE_KEY: portal configuration does not match the manifest")
    try:
        configured_fapi = _https_origin(record[_CLERK_FAPI_FIELD], _CLERK_FAPI_FIELD)
    except ClerkConfigError as exc:
        raise ClerkConfigError(str(exc)) from None
    if configured_fapi != config.frontend_api:
        raise ClerkConfigError("VITE_CLERK_FAPI: portal configuration does not match the manifest/key host")


def fetch_jwks(
    url: str,
    *,
    timeout_s: float = CHECK_TIMEOUT_S,
    clock: Callable[[], float] | None = None,
) -> dict[str, object]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ClerkConfigError("JWKS URL must be https")
    request = Request(
        url, method="GET", headers={"Accept": "application/json", "User-Agent": "acx-configure-clerk-production"}
    )
    now = time.monotonic if clock is None else clock
    deadline = now() + timeout_s
    remaining = deadline - now()
    if remaining <= 0:
        raise ClerkConfigError("JWKS check exceeded timeout")
    try:
        with urlopen(request, timeout=remaining) as response:  # noqa: S310 — scheme pinned to https above
            raw = _read_jwks_body(response, max_bytes=CHECK_MAX_BYTES, deadline=deadline, clock=now)
    except HTTPError as exc:
        raise ClerkConfigError(f"JWKS check HTTP {exc.code}") from exc
    except ClerkConfigError:
        raise
    except TimeoutError as exc:
        raise ClerkConfigError("JWKS check exceeded timeout") from exc
    except (URLError, OSError) as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, TimeoutError):
            raise ClerkConfigError("JWKS check exceeded timeout") from exc
        raise ClerkConfigError("JWKS check failed") from exc
    if len(raw) > CHECK_MAX_BYTES:
        raise ClerkConfigError("JWKS response exceeded bounded size")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClerkConfigError("JWKS response is not JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list) or not payload["keys"]:
        raise ClerkConfigError("JWKS response is missing keys")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="configure_clerk_production",
        description="Validate production Clerk settings from the environment manifest.",
    )
    parser.add_argument(
        "--root", type=Path, default=_REPO_ROOT / "config" / "env", help="environment manifest root"
    )
    parser.add_argument("--check", action="store_true", help="opt in to a bounded HTTPS JWKS check")
    parser.add_argument(
        "--verify-assets",
        action="store_true",
        help="read reachable JavaScript module paths from stdin and verify the production build values",
    )
    return parser


def execute(
    args: argparse.Namespace,
    *,
    stdin: TextIO | None = None,
    stderr: TextIO | None = None,
    jwks_get: Callable[[str], dict[str, object]] | None = None,
) -> int:
    stdin = sys.stdin if stdin is None else stdin
    stderr = sys.stderr if stderr is None else stderr
    try:
        config = load_production_config(args.root)
        if args.verify_assets:
            paths = [Path(line) for line in stdin.read().splitlines() if line]
            validate_frontend_modules(config, paths)
        if args.check:
            (fetch_jwks if jwks_get is None else jwks_get)(config.jwks_url)
        return 0
    except ClerkConfigError as exc:
        stderr.write(f"error: {exc}\n")
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    return execute(args)


def _read_jwks_body(
    response: object,
    *,
    max_bytes: int,
    deadline: float,
    clock: Callable[[], float],
    chunk_size: int = CHECK_READ_CHUNK,
) -> bytes:
    buf = bytearray()
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            raise ClerkConfigError("JWKS check exceeded timeout")
        _apply_socket_timeout(response, remaining)
        to_read = min(chunk_size, max_bytes + 1 - len(buf))
        if to_read <= 0:
            break
        try:
            chunk = response.read(to_read)  # type: ignore[attr-defined]
        except TimeoutError as exc:
            raise ClerkConfigError("JWKS check exceeded timeout") from exc
        if not chunk:
            break
        if not isinstance(chunk, (bytes, bytearray)):
            raise ClerkConfigError("JWKS response is not JSON")
        buf.extend(chunk)
        if len(buf) > max_bytes:
            break
    return bytes(buf)


def _apply_socket_timeout(response: object, timeout_s: float) -> None:
    bounded = max(timeout_s, 0.001)
    targets: list[object] = [response]
    fp = getattr(response, "fp", None)
    if fp is not None:
        targets.append(fp)
        raw = getattr(fp, "raw", None)
        if raw is not None:
            targets.append(raw)
            sock = getattr(raw, "_sock", None)
            if sock is not None:
                targets.append(sock)
    for target in targets:
        setter = getattr(target, "settimeout", None)
        if not callable(setter):
            continue
        try:
            setter(bounded)
        except (OSError, TypeError, ValueError):
            continue


if __name__ == "__main__":
    sys.exit(main())
