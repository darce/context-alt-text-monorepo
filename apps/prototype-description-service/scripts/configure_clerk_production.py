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
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple, TextIO
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
MAX_FRONTEND_TEMPLATE_DEPTH = 32
_CLERK_KEY_FIELD = "VITE_CLERK_PUBLISHABLE_KEY"
_CLERK_FAPI_FIELD = "VITE_CLERK_FAPI"
_PORTAL_ENABLED_FIELD = "VITE_PORTAL_ENABLED"
_FRONTEND_CONFIG_FIELDS = frozenset({_CLERK_KEY_FIELD, _CLERK_FAPI_FIELD, _PORTAL_ENABLED_FIELD})
_OPTIONAL_FRONTEND_CONFIG_FIELDS = frozenset({"VITE_PAYMENTS_ENABLED", "VITE_PUBLIC_PLAN_CODE"})
_CONSUMER_CONFIG_FIELDS = _FRONTEND_CONFIG_FIELDS | _OPTIONAL_FRONTEND_CONFIG_FIELDS
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


class _ConfigBinding(NamedTuple):
    name: str
    scope: tuple[int, ...]
    token_index: int


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
    urlsafe = "-" in payload or "_" in payload
    alphabet = r"[A-Za-z0-9_-]*={0,2}" if urlsafe else r"[A-Za-z0-9+/]*={0,2}"
    unpadded = payload.rstrip("=")
    padding = payload[len(unpadded) :]
    required_padding = "=" * (-len(unpadded) % 4)
    if (
        not re.fullmatch(alphabet, payload)
        or (urlsafe and any(char in payload for char in "+/"))
        or len(unpadded) % 4 == 1
        or (padding and (len(payload) % 4 != 0 or padding != required_padding))
    ):
        raise ClerkConfigError("key is not valid base64")
    padded = unpadded + required_padding
    try:
        decoded = base64.b64decode(padded, altchars=b"-_" if urlsafe else None, validate=True)
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


_CONTROL_PAREN_KEYWORDS = frozenset({"catch", "for", "if", "switch", "while", "with"})
_REGEX_PREFIX_KEYWORDS = frozenset({"await", "case", "delete", "return", "throw", "typeof", "void", "yield"})


def _control_header_precedes_paren(tokens: Sequence[_JSToken]) -> bool:
    previous_index = len(tokens) - 2
    if (
        previous_index < 0
        or tokens[previous_index].kind != "identifier"
        or tokens[previous_index].value not in _CONTROL_PAREN_KEYWORDS
    ):
        if previous_index < 1 or tokens[previous_index].kind != "identifier" or tokens[previous_index].value != "await":
            return False
        if tokens[previous_index - 1].kind != "identifier" or tokens[previous_index - 1].value != "for":
            return False
        keyword_index = previous_index - 1
    else:
        keyword_index = previous_index
    return keyword_index == 0 or not (
        tokens[keyword_index - 1].kind == "punct" and tokens[keyword_index - 1].value in {".", "?."}
    )


def _template_regex_can_start(source: str, expression_start: int, index: int) -> bool:
    prefix = source[expression_start:index].rstrip()
    if not prefix:
        return True
    if prefix[-1] in "=(:,[!&|?{};+-*/%^~<>":
        return True
    keyword = re.search(r"\b(" + "|".join(sorted(_REGEX_PREFIX_KEYWORDS)) + r")\s*$", prefix)
    if keyword and not prefix[: keyword.start()].rstrip().endswith((".", "?.")):
        return True
    if not prefix.endswith(")"):
        return False
    depth = 0
    for open_index in range(len(prefix) - 1, -1, -1):
        if prefix[open_index] == ")":
            depth += 1
        elif prefix[open_index] == "(":
            depth -= 1
            if depth == 0:
                keyword = re.search(r"([A-Za-z_$][A-Za-z0-9_$]*)\s*$", prefix[:open_index])
                if keyword is None:
                    return False
                word = keyword.group(1)
                if word == "await":
                    return bool(re.search(r"\bfor\s+$", prefix[: keyword.start()]))
                before_keyword = prefix[: keyword.start()].rstrip()
                return word in _CONTROL_PAREN_KEYWORDS and not before_keyword.endswith((".", "?."))
    return False


def _skip_template_expression(source: str, start: int, depth: int = 0) -> int:
    depth = 0
    index = start
    while index < len(source):
        char = source[index]
        if char in "'\"":
            index, _, _ = _skip_quoted_javascript(source, index)
            continue
        if char == "`":
            index = _skip_template_javascript(source, index, depth + 1)
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


def _template_interpolations(source: str, start: int, depth: int = 0) -> tuple[int, list[str]]:
    if depth > MAX_FRONTEND_TEMPLATE_DEPTH:
        raise ClerkConfigError("reachable JavaScript template nesting exceeds the static inspection limit")
    index = start + 1
    expressions: list[str] = []
    while index < len(source):
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if char == "`":
            return index + 1, expressions
        if source.startswith("${", index):
            expression_start = index + 2
            expression_end = _skip_template_expression(source, expression_start, depth + 1)
            expressions.append(source[expression_start : expression_end - 1])
            index = expression_end
            continue
        index += 1
    raise ClerkConfigError("reachable JavaScript module has an unterminated template")


def _skip_template_javascript(source: str, start: int, depth: int = 0) -> int:
    end, _ = _template_interpolations(source, start, depth)
    return end


def _regex_can_start(tokens: Sequence[_JSToken]) -> bool:
    if not tokens:
        return True
    previous = tokens[-1]
    return (
        previous.kind == "punct"
        and previous.value
        in {
            "=",
            "(",
            "[",
            "{",
            ",",
            ":",
            ";",
            "!",
            "?",
            "=>",
            "&&",
            "||",
            "??",
            "+",
            "-",
            "*",
            "/",
            "%",
            "^",
            "~",
            "<",
            ">",
            "<=",
            ">=",
            "==",
            "===",
            "!=",
            "!==",
            "&",
            "|",
        }
        or previous.kind == "identifier"
        and previous.value in _REGEX_PREFIX_KEYWORDS
        and not (len(tokens) > 1 and tokens[-2].kind == "punct" and tokens[-2].value in {".", "?."})
    )


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


def _tokenize_javascript(source: str, template_depth: int = 0) -> list[_JSToken]:
    tokens: list[_JSToken] = []
    index = 0
    last_token_end = 0
    paren_context: list[bool] = []
    regex_after_control_header = False
    operators = (
        ">>>=",
        "&&=",
        "||=",
        "??=",
        "<<=",
        ">>=",
        "**=",
        "===",
        "!==",
        "=>",
        "==",
        "!=",
        "<=",
        ">=",
        "++",
        "--",
        "+=",
        "-=",
        "*=",
        "/=",
        "%=",
        "&=",
        "|=",
        "^=",
        "&&",
        "||",
        "??",
        "...",
        "?.",
    )
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
        first_token_index = len(tokens)
        if char in "'\"":
            index, raw, value = _skip_quoted_javascript(source, index)
            tokens.append(_JSToken("string", value, raw, line_break_before))
        elif char == "`":
            end, expressions = _template_interpolations(source, index, template_depth + 1)
            tokens.append(_JSToken("template", None, source[index + 1 : end - 1], line_break_before))
            for expression in expressions:
                tokens.append(_JSToken("template_expr_start", None, ""))
                tokens.extend(_tokenize_javascript(expression, template_depth + 1))
                tokens.append(_JSToken("template_expr_end", None, ""))
                if len(tokens) > MAX_FRONTEND_TOKENS:
                    raise ClerkConfigError("reachable JavaScript module exceeds the static inspection limit")
            index = end
        elif char == "/" and (regex_after_control_header or _regex_can_start(tokens)):
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
        token = tokens[first_token_index]
        if _is_punct(token, "("):
            paren_context.append(_control_header_precedes_paren(tokens))
            regex_after_control_header = False
        elif _is_punct(token, ")"):
            regex_after_control_header = paren_context.pop() if paren_context else False
        else:
            regex_after_control_header = False
        last_token_end = index
        if len(tokens) > MAX_FRONTEND_TOKENS:
            raise ClerkConfigError("reachable JavaScript module exceeds the static inspection limit")
    return tokens


def _is_punct(token: _JSToken, value: str) -> bool:
    return token.kind == "punct" and token.value == value


def _skip_template_expression_tokens(tokens: Sequence[_JSToken], start: int) -> int:
    depth = 0
    for index in range(start, len(tokens)):
        if tokens[index].kind == "template_expr_start":
            depth += 1
        elif tokens[index].kind == "template_expr_end":
            depth -= 1
            if depth == 0:
                return index + 1
    raise ClerkConfigError("reachable JavaScript module has an unterminated template expression")


def _javascript_delimiters(tokens: Sequence[_JSToken]) -> tuple[dict[int, int], list[tuple[int, ...]]]:
    closing = {"{": "}", "[": "]", "(": ")"}
    reverse = {value: key for key, value in closing.items()}
    stack: list[tuple[str, int]] = []
    pairs: dict[int, int] = {}
    scopes: list[tuple[int, ...]] = []
    for index, token in enumerate(tokens):
        value = token.value if token.kind == "punct" else None
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
) -> tuple[dict[str, tuple[int, int]], bool]:
    close_index = pairs[open_index]
    fields: dict[str, tuple[int, int]] = {}
    has_spread = False
    has_computed = False
    has_accessor = False
    has_unsupported_member = False
    supported_names: set[str] = set()
    members: list[tuple[int, int]] = []
    index = open_index + 1
    while index < close_index:
        member_start = index
        while index < close_index:
            if tokens[index].kind == "template_expr_start":
                index = _skip_template_expression_tokens(tokens, index)
            elif tokens[index].kind == "punct" and tokens[index].value in {"{", "[", "("}:
                index = pairs[index] + 1
            elif _is_punct(tokens[index], ","):
                break
            else:
                index += 1
        if index > member_start:
            members.append((member_start, index))
        if index < close_index and _is_punct(tokens[index], ","):
            index += 1

    def note_supported_name(name: str | None) -> None:
        if name not in _FRONTEND_CONFIG_FIELDS:
            return
        if name in supported_names:
            raise ClerkConfigError(f"{name}: portal configuration binding is ambiguous")
        supported_names.add(name)

    for member_start, member_end in members:
        token = tokens[member_start]
        if _is_punct(token, "..."):
            has_spread = True
            continue
        if _is_punct(token, "["):
            has_computed = True
            if member_start + 2 < member_end and _is_punct(tokens[member_start + 2], "]"):
                note_supported_name(tokens[member_start + 1].value)
            continue

        property_index = member_start
        accessor = False
        if (
            token.kind == "identifier"
            and token.value in {"get", "set"}
            and member_start + 2 < member_end
            and not _is_punct(tokens[member_start + 1], ":")
        ):
            accessor = True
            property_index = member_start + 1
            if _is_punct(tokens[property_index], "["):
                has_computed = True
                continue
        property_token = tokens[property_index]
        name = property_token.value if property_token.kind in {"identifier", "string"} else None
        if accessor:
            has_accessor = True
            note_supported_name(name)
            continue
        if property_index + 1 < member_end and _is_punct(tokens[property_index + 1], "("):
            has_accessor = True
            note_supported_name(name)
            continue
        if property_index + 1 < member_end and _is_punct(tokens[property_index + 1], ":"):
            if name in _FRONTEND_CONFIG_FIELDS:
                note_supported_name(name)
                fields[name] = (property_index + 2, member_end)
            elif name is None:
                has_unsupported_member = True
            continue
        if name in _FRONTEND_CONFIG_FIELDS:
            note_supported_name(name)
            has_unsupported_member = True
        elif property_index != member_start or member_end - member_start != 1:
            has_unsupported_member = True

    is_candidate = bool(supported_names or fields)
    if is_candidate and (has_spread or has_computed or has_accessor or has_unsupported_member):
        raise ClerkConfigError("VITE_CLERK_FAPI: portal configuration record contains unsupported members")
    return fields, has_spread


_INITIALIZER_CONTINUATIONS = frozenset(
    {
        "(",
        "[",
        ".",
        "?.",
        "+",
        "-",
        "*",
        "/",
        "%",
        "**",
        "<",
        ">",
        "<=",
        ">=",
        "==",
        "===",
        "!=",
        "!==",
        "&&",
        "||",
        "??",
        "?",
        ":",
        "=",
        "+=",
        "-=",
        "*=",
        "/=",
        "=>",
        "&",
        "|",
        "^",
        "in",
        "instanceof",
        "of",
        "as",
        "satisfies",
    }
)
_INITIALIZER_WORD_CONTINUATIONS = frozenset({"in", "instanceof", "of", "as", "satisfies"})


def _initializer_ends_here(tokens: Sequence[_JSToken], next_index: int) -> bool:
    if next_index == len(tokens):
        return True
    following = tokens[next_index]
    if following.kind == "punct" and following.value in {";", ",", "}"}:
        return True
    if not following.line_break_before:
        return False
    if following.kind == "template":
        return False
    return not (
        (following.kind == "punct" and following.value in _INITIALIZER_CONTINUATIONS)
        or (following.kind == "identifier" and following.value in _INITIALIZER_WORD_CONTINUATIONS)
    )


def _nearest_lexical_binding(
    name: str,
    tokens: Sequence[_JSToken],
    scopes: Sequence[tuple[int, ...]],
    use_scope: tuple[int, ...],
    pairs: dict[int, int],
) -> tuple[str, tuple[int, ...], int]:
    bindings, _ = _config_binding_shadows(tokens, scopes, pairs)
    visible = [
        binding
        for binding in bindings
        if binding[0] == name and len(binding[1]) <= len(use_scope) and use_scope[: len(binding[1])] == binding[1]
    ]
    if not visible:
        raise ClerkConfigError("VITE_CLERK_FAPI: configuration alias is unsupported")
    nearest_scope_size = max(len(binding[1]) for binding in visible)
    nearest = [binding for binding in visible if len(binding[1]) == nearest_scope_size]
    if len(nearest) != 1:
        raise ClerkConfigError("VITE_CLERK_FAPI: configuration alias is ambiguous")
    return nearest[0]


def _resolve_static_alias(
    name: str,
    tokens: Sequence[_JSToken],
    scopes: Sequence[tuple[int, ...]],
    use_scope: tuple[int, ...],
    before_index: int,
    pairs: dict[int, int],
    seen: frozenset[tuple[str, tuple[int, ...], int]] = frozenset(),
) -> str:
    _, declaration_scope, name_index = _nearest_lexical_binding(name, tokens, scopes, use_scope, pairs)
    declaration_index = name_index - 1
    if (
        name_index >= before_index
        or declaration_index < 0
        or tokens[declaration_index].kind != "identifier"
        or tokens[declaration_index].value != "const"
        or name_index + 2 >= len(tokens)
        or not _is_punct(tokens[name_index + 1], "=")
    ):
        raise ClerkConfigError("VITE_CLERK_FAPI: configuration alias binding is not a supported const")
    initializer = tokens[name_index + 2]
    identity = (name, declaration_scope, name_index)
    if identity in seen:
        raise ClerkConfigError("VITE_CLERK_FAPI: configuration alias is cyclic")
    if len(seen) >= 16:
        raise ClerkConfigError("VITE_CLERK_FAPI: configuration alias chain is too deep")
    if initializer.kind not in {"string", "identifier"} or not _initializer_ends_here(tokens, name_index + 3):
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
        pairs,
        seen | {identity},
    )


def _static_field_value(
    name: str,
    field: tuple[int, int],
    tokens: Sequence[_JSToken],
    scopes: Sequence[tuple[int, ...]],
    use_scope: tuple[int, ...],
    object_fields: dict[int, dict[str, tuple[int, int]]],
    pairs: dict[int, int],
    seen_objects: frozenset[int] = frozenset(),
) -> tuple[str, set[int], set[int]]:
    value_start, value_end = field
    expression_size = value_end - value_start
    token = tokens[value_start] if expression_size else None
    if expression_size == 1 and token is not None and token.kind == "string" and token.value is not None:
        return token.value, set(), set()
    if expression_size == 1 and token is not None and token.kind == "identifier" and token.value is not None:
        try:
            value = _resolve_static_alias(token.value, tokens, scopes, use_scope, value_start, pairs)
            return value, set(), set()
        except ClerkConfigError as exc:
            message = str(exc)
            if message.startswith("VITE_CLERK_FAPI:"):
                raise ClerkConfigError(message.replace("VITE_CLERK_FAPI:", f"{name}:", 1)) from None
            raise
    if (
        expression_size == 3
        and token is not None
        and token.kind == "identifier"
        and _is_punct(tokens[value_start + 1], ".")
        and tokens[value_start + 2].kind == "identifier"
    ):
        try:
            object_index = _resolve_config_object(
                token.value or "",
                tokens,
                scopes,
                use_scope,
                value_start,
                set(object_fields),
                pairs,
            )
            if object_index in seen_objects or len(seen_objects) >= 16:
                raise ClerkConfigError("VITE_CLERK_FAPI: portal config object property chain is cyclic or too deep")
            property_name = tokens[value_start + 2].value
            object_field = object_fields[object_index].get(property_name or "")
            if object_field is None:
                raise ClerkConfigError("VITE_CLERK_FAPI: portal config object property is unsupported")
            resolved, supporting_objects, member_uses = _static_field_value(
                name,
                object_field,
                tokens,
                scopes,
                scopes[object_index],
                object_fields,
                pairs,
                seen_objects | {object_index},
            )
            return resolved, supporting_objects | {object_index}, member_uses | {value_start}
        except ClerkConfigError as exc:
            message = str(exc)
            if message.startswith("VITE_CLERK_FAPI:"):
                raise ClerkConfigError(message.replace("VITE_CLERK_FAPI:", f"{name}:", 1)) from None
            raise
    raise ClerkConfigError(f"{name}: configuration value is not a supported static string")


def _function_parameter_consumers(
    tokens: Sequence[_JSToken],
    pairs: dict[int, int],
    scopes: Sequence[tuple[int, ...]],
) -> dict[tuple[str, tuple[int, ...], int], tuple[str, int, int]]:
    consumers: dict[tuple[str, tuple[int, ...], int], tuple[str, int, int]] = {}

    def add_consumer(
        name: str | None,
        binding_scope: tuple[int, ...],
        binding_index: int,
        params_open: int,
        body_open: int,
    ) -> None:
        if name is None or body_open not in pairs or params_open >= len(tokens):
            return
        if _is_punct(tokens[params_open], "("):
            first_param = tokens[params_open + 1] if params_open + 1 < pairs[params_open] else None
        else:
            first_param = tokens[params_open]
        if first_param is None or first_param.kind != "identifier":
            return
        body_close = pairs[body_open]
        fields = set()
        for index in range(body_open + 1, body_close - 2):
            if (
                tokens[index].kind == "identifier"
                and tokens[index].value == first_param.value
                and _is_punct(tokens[index + 1], ".")
                and tokens[index + 2].kind == "identifier"
            ):
                fields.add(tokens[index + 2].value)
        if {_CLERK_KEY_FIELD, _CLERK_FAPI_FIELD}.issubset(fields):
            consumers[(name, binding_scope, binding_index)] = (first_param.value, body_open, body_close)

    for index, token in enumerate(tokens):
        if token.kind == "identifier" and token.value == "function":
            name_index = index + 1
            if name_index < len(tokens) and _is_punct(tokens[name_index], "*"):
                name_index += 1
            if name_index >= len(tokens) or tokens[name_index].kind != "identifier":
                continue
            params_open = name_index + 1
            if params_open >= len(tokens) or not _is_punct(tokens[params_open], "("):
                continue
            body_open = pairs.get(params_open, -1) + 1
            if body_open < len(tokens) and _is_punct(tokens[body_open], "{"):
                add_consumer(tokens[name_index].value, scopes[name_index], name_index, params_open, body_open)
        if (
            token.kind == "identifier"
            and token.value == "const"
            and index + 3 < len(tokens)
            and tokens[index + 1].kind == "identifier"
            and _is_punct(tokens[index + 2], "=")
            and tokens[index + 3].kind == "identifier"
            and tokens[index + 3].value == "function"
        ):
            params_open = index + 4
            if params_open < len(tokens) and _is_punct(tokens[params_open], "("):
                body_open = pairs.get(params_open, -1) + 1
                if body_open < len(tokens) and _is_punct(tokens[body_open], "{"):
                    add_consumer(
                        tokens[index + 1].value,
                        scopes[index],
                        index + 1,
                        params_open,
                        body_open,
                    )
        if (
            token.kind == "identifier"
            and token.value == "const"
            and index + 4 < len(tokens)
            and tokens[index + 1].kind == "identifier"
            and _is_punct(tokens[index + 2], "=")
        ):
            name = tokens[index + 1].value
            params_open = index + 3
            if _is_punct(tokens[params_open], "("):
                params_close = pairs.get(params_open, -1)
                arrow = params_close + 1
            elif tokens[params_open].kind == "identifier":
                params_close = params_open
                arrow = params_open + 1
            else:
                continue
            body_open = arrow + 1
            if (
                arrow < len(tokens)
                and _is_punct(tokens[arrow], "=>")
                and body_open < len(tokens)
                and _is_punct(tokens[body_open], "{")
            ):
                add_consumer(name, scopes[index], index + 1, params_open, body_open)
    return consumers


def _validate_consumer_binding(
    identity: tuple[str, tuple[int, ...], int],
    tokens: Sequence[_JSToken],
    scopes: Sequence[tuple[int, ...]],
    pairs: dict[int, int],
) -> None:
    name, _, declaration_index = identity
    for index, token in enumerate(tokens):
        if token.kind != "identifier" or token.value != name or index == declaration_index:
            continue
        if index and _is_punct(tokens[index - 1], "."):
            continue
        if index and _is_punct(tokens[index - 1], "?."):
            continue
        if index + 1 < len(tokens) and _is_punct(tokens[index + 1], ":"):
            continue
        try:
            reference_identity = _nearest_lexical_binding(name, tokens, scopes, scopes[index], pairs)
        except ClerkConfigError as exc:
            if "configuration alias is ambiguous" in str(exc):
                raise ClerkConfigError("VITE_CLERK_FAPI: portal config consumer binding is ambiguous") from None
            continue
        if reference_identity != identity:
            continue
        if index + 1 >= len(tokens) or not _is_punct(tokens[index + 1], "("):
            raise ClerkConfigError("VITE_CLERK_FAPI: portal config consumer binding is reassigned or escapes")
        if index + 1 not in pairs:
            raise ClerkConfigError("VITE_CLERK_FAPI: portal config consumer call is unsupported")


def _validate_consumer_parameter(
    tokens: Sequence[_JSToken], parameter: str, body_open: int, body_close: int, pairs: dict[int, int]
) -> None:
    reads: set[str] = set()
    for index in range(body_open + 1, body_close):
        if tokens[index].kind != "identifier" or tokens[index].value != parameter:
            continue
        if (
            index >= body_open + 9
            and [token.value for token in tokens[index - 8 : index]]
            == ["Object", ".", "prototype", ".", "hasOwnProperty", ".", "call", "("]
            and index + 3 < body_close
            and _is_punct(tokens[index + 1], ",")
            and tokens[index + 2].kind == "string"
            and tokens[index + 2].value in _OPTIONAL_FRONTEND_CONFIG_FIELDS
            and _is_punct(tokens[index + 3], ")")
        ):
            continue
        field_index = index + 2
        if (
            field_index >= body_close
            or not _is_punct(tokens[index + 1], ".")
            or tokens[field_index].kind != "identifier"
            or tokens[field_index].value not in _CONSUMER_CONFIG_FIELDS
        ):
            raise ClerkConfigError("VITE_CLERK_FAPI: portal config consumer parameter is mutated or escapes")
        previous, following = _member_access_mutation_neighbors(
            tokens, index, field_index, body_open + 1, body_close, pairs
        )
        if (
            (previous is not None and previous.kind == "identifier" and previous.value == "delete")
            or (previous is not None and previous.kind == "punct" and previous.value in {"++", "--"})
            or (following is not None and following.kind == "punct" and following.value in _JS_ASSIGNMENT_OPERATORS)
            or (following is not None and following.kind == "punct" and following.value in {"++", "--"})
        ):
            raise ClerkConfigError("VITE_CLERK_FAPI: portal config consumer parameter is mutated or escapes")
        reads.add(tokens[field_index].value or "")
    if not {_CLERK_KEY_FIELD, _CLERK_FAPI_FIELD}.issubset(reads):
        raise ClerkConfigError("VITE_CLERK_FAPI: portal config consumer does not read the required fields")


_RETURNED_CLERK_FIELDS = frozenset({"publishableKey", "fapiOrigin"})
_RETURNED_CONFIG_MEMBERS = frozenset(
    {"publishableKey", "fapiOrigin", "portalEnabled", "paymentsEnabled", "publicPlanCode"}
)
_JS_ASSIGNMENT_OPERATORS = frozenset(
    {
        "=",
        "+=",
        "-=",
        "*=",
        "/=",
        "%=",
        "**=",
        "<<=",
        ">>=",
        ">>>=",
        "&=",
        "|=",
        "^=",
        "&&=",
        "||=",
        "??=",
    }
)


def _member_access_mutation_neighbors(
    tokens: Sequence[_JSToken],
    base_index: int,
    member_index: int,
    lower_bound: int,
    upper_bound: int,
    pairs: dict[int, int],
) -> tuple[_JSToken | None, _JSToken | None]:
    parenthesis_opens: set[int] = set()
    expression_start = base_index
    while expression_start > lower_bound and _is_punct(tokens[expression_start - 1], "("):
        opener = expression_start - 1
        if pairs.get(opener, -1) < member_index:
            break
        parenthesis_opens.add(opener)
        expression_start = opener
    closing_indexes = {pairs[opener] for opener in parenthesis_opens}
    following_index = member_index + 1
    while following_index in closing_indexes and following_index < upper_bound:
        following_index += 1
    previous = tokens[expression_start - 1] if expression_start > lower_bound else None
    following = tokens[following_index] if following_index < upper_bound else None
    return previous, following


def _expression_end(tokens: Sequence[_JSToken], start: int, limit: int, pairs: dict[int, int]) -> int:
    index = start
    while index < limit:
        if _is_punct(tokens[index], ";") or _is_punct(tokens[index], ",") or _is_punct(tokens[index], "}"):
            return index
        if _is_punct(tokens[index], "{") or _is_punct(tokens[index], "[") or _is_punct(tokens[index], "("):
            close_index = pairs.get(index)
            if close_index is None:
                raise ClerkConfigError("VITE_CLERK_FAPI: portal configuration expression is unsupported")
            index = close_index + 1
            continue
        if _initializer_ends_here(tokens, index + 1):
            return index + 1
        index += 1
    return limit


def _return_comma_expression_segments(
    tokens: Sequence[_JSToken], start: int, body_close: int, pairs: dict[int, int]
) -> list[tuple[int, int]]:
    segments: list[tuple[int, int]] = []
    cursor = start
    while cursor < body_close:
        end = _expression_end(tokens, cursor, body_close, pairs)
        if end <= cursor:
            raise ClerkConfigError("VITE_CLERK_FAPI: portal config return expression is unsupported")
        segments.append((cursor, end))
        if end < body_close and _is_punct(tokens[end], ","):
            cursor = end + 1
            continue
        if end < body_close and _is_punct(tokens[end], ";") and end + 1 == body_close:
            return segments
        if end == body_close:
            return segments
        raise ClerkConfigError("VITE_CLERK_FAPI: portal config return expression is unsupported")
    raise ClerkConfigError("VITE_CLERK_FAPI: portal config return expression is incomplete")


def _split_conditional_expression(
    tokens: Sequence[_JSToken], start: int, end: int, pairs: dict[int, int]
) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]] | None:
    question = colon = -1
    index = start
    while index < end:
        if tokens[index].kind == "template_expr_start":
            index = _skip_template_expression_tokens(tokens, index)
            continue
        if _is_punct(tokens[index], "{") or _is_punct(tokens[index], "[") or _is_punct(tokens[index], "("):
            close_index = pairs.get(index)
            if close_index is None:
                raise ClerkConfigError("VITE_CLERK_FAPI: portal configuration expression is unsupported")
            index = close_index + 1
            continue
        if _is_punct(tokens[index], "?") and question < 0:
            question = index
        elif _is_punct(tokens[index], ":") and question >= 0:
            colon = index
            break
        index += 1
    if question < 0 or colon < 0:
        return None
    return (start, question), (question + 1, colon), (colon + 1, end)


def _output_object_fields(
    tokens: Sequence[_JSToken], pairs: dict[int, int], open_index: int
) -> dict[str, tuple[int, int]]:
    close_index = pairs.get(open_index)
    if close_index is None:
        raise ClerkConfigError("VITE_CLERK_FAPI: returned portal configuration is unsupported")
    fields: dict[str, tuple[int, int]] = {}
    index = open_index + 1
    while index < close_index:
        member_start = index
        while index < close_index:
            if tokens[index].kind == "template_expr_start":
                index = _skip_template_expression_tokens(tokens, index)
            elif _is_punct(tokens[index], "{") or _is_punct(tokens[index], "[") or _is_punct(tokens[index], "("):
                pair = pairs.get(index)
                if pair is None:
                    raise ClerkConfigError("VITE_CLERK_FAPI: returned portal configuration is unsupported")
                index = pair + 1
            elif _is_punct(tokens[index], ","):
                break
            else:
                index += 1
        member_end = index
        if member_end <= member_start:
            raise ClerkConfigError("VITE_CLERK_FAPI: returned portal configuration has an empty member")
        key = tokens[member_start]
        if (
            key.kind not in {"identifier", "string"}
            or member_start + 1 >= member_end
            or not _is_punct(tokens[member_start + 1], ":")
        ):
            raise ClerkConfigError("VITE_CLERK_FAPI: returned portal configuration has unsupported members")
        name = key.value or ""
        if name in _RETURNED_CLERK_FIELDS:
            if name in fields:
                raise ClerkConfigError("VITE_CLERK_FAPI: returned portal configuration is ambiguous")
            fields[name] = (member_start + 2, member_end)
        if index < close_index:
            index += 1
    if not _RETURNED_CLERK_FIELDS.issubset(fields):
        raise ClerkConfigError("VITE_CLERK_FAPI: returned portal configuration is incomplete")
    return fields


def _const_declarator_start(
    name_index: int,
    binding_scope: tuple[int, ...],
    tokens: Sequence[_JSToken],
    scopes: Sequence[tuple[int, ...]],
    pairs: dict[int, int],
) -> int | None:
    declaration_index = name_index - 1
    if (
        declaration_index >= 0
        and tokens[declaration_index].kind == "identifier"
        and tokens[declaration_index].value == "const"
        and scopes[declaration_index] == binding_scope
    ):
        return declaration_index
    if declaration_index < 0 or not _is_punct(tokens[declaration_index], ","):
        return None
    cursor = declaration_index - 1
    while cursor >= 0:
        token = tokens[cursor]
        if token.kind == "template_expr_start":
            cursor = _skip_template_expression_tokens(tokens, cursor) - 1
            continue
        if _is_punct(token, "}") and scopes[cursor] == binding_scope:
            return None
        if _is_punct(token, ")") or _is_punct(token, "]") or _is_punct(token, "}"):
            opener = pairs.get(cursor, -1)
            if opener >= 0:
                cursor = opener - 1
                continue
        if _is_punct(token, ";"):
            return None
        if token.kind == "identifier" and token.value in {"const", "let", "var"} and scopes[cursor] == binding_scope:
            return cursor if token.value == "const" else None
        if (
            token.line_break_before
            and _initializer_ends_here(tokens, cursor)
            and token.kind == "identifier"
            and token.value in {"const", "let", "var", "return", "function"}
        ):
            return None
        cursor -= 1
    return None


def _local_const_initializer(
    name: str,
    tokens: Sequence[_JSToken],
    scopes: Sequence[tuple[int, ...]],
    use_index: int,
    body_open: int,
    body_close: int,
    pairs: dict[int, int],
) -> tuple[tuple[str, tuple[int, ...], int], int, int]:
    identity = _nearest_lexical_binding(name, tokens, scopes, scopes[use_index], pairs)
    _, binding_scope, name_index = identity
    declaration_index = _const_declarator_start(name_index, binding_scope, tokens, scopes, pairs)
    body_scope = scopes[body_open] + (body_open,)
    if (
        not (len(body_scope) <= len(binding_scope) and binding_scope[: len(body_scope)] == body_scope)
        or declaration_index is None
        or name_index + 2 >= body_close
        or not _is_punct(tokens[name_index + 1], "=")
    ):
        raise ClerkConfigError("VITE_CLERK_FAPI: portal configuration alias is not a supported const")
    start = name_index + 2
    end = _expression_end(tokens, start, body_close, pairs)
    if end <= start or end > use_index:
        raise ClerkConfigError("VITE_CLERK_FAPI: portal configuration alias is ambiguous")
    return identity, start, end


def _resolve_output_object(
    name: str,
    tokens: Sequence[_JSToken],
    scopes: Sequence[tuple[int, ...]],
    use_index: int,
    body_open: int,
    body_close: int,
    pairs: dict[int, int],
    seen: frozenset[tuple[str, tuple[int, ...], int]] = frozenset(),
) -> tuple[int, tuple[tuple[str, tuple[int, ...], int], ...]]:
    identity, start, end = _local_const_initializer(name, tokens, scopes, use_index, body_open, body_close, pairs)
    if identity in seen or len(seen) >= 16:
        raise ClerkConfigError("VITE_CLERK_FAPI: returned portal configuration alias is cyclic or too deep")
    if _is_punct(tokens[start], "{"):
        close_index = pairs.get(start)
        if close_index is None or close_index + 1 != end:
            raise ClerkConfigError("VITE_CLERK_FAPI: returned portal configuration initializer is unsupported")
        return start, (*seen, identity)
    if end - start == 1 and tokens[start].kind == "identifier" and tokens[start].value is not None:
        object_index, identities = _resolve_output_object(
            tokens[start].value,
            tokens,
            scopes,
            start,
            body_open,
            body_close,
            pairs,
            seen | {identity},
        )
        return object_index, (*identities, identity)
    raise ClerkConfigError("VITE_CLERK_FAPI: returned portal configuration alias is unsupported")


def _validate_optional_return_segment(
    segment: tuple[int, int],
    parameter: str,
    returned_name: str,
    tokens: Sequence[_JSToken],
    scopes: Sequence[tuple[int, ...]],
    pairs: dict[int, int],
) -> str:
    start, end = segment
    if end - start != 25:
        raise ClerkConfigError("VITE_CLERK_FAPI: returned portal optional-field assignment is unsupported")
    actual = [(tokens[index].kind, tokens[index].value) for index in range(start, end)]
    optional_inputs = {
        "VITE_PAYMENTS_ENABLED": "paymentsEnabled",
        "VITE_PUBLIC_PLAN_CODE": "publicPlanCode",
    }
    input_name = actual[10][1] if actual[10][0] == "string" else None
    member_name = optional_inputs.get(input_name or "")
    if member_name is None or tokens[start + 18].kind != "identifier":
        raise ClerkConfigError("VITE_CLERK_FAPI: returned portal optional-field assignment is unsupported")
    expected_prefix = [
        ("identifier", "Object"),
        ("punct", "."),
        ("identifier", "prototype"),
        ("punct", "."),
        ("identifier", "hasOwnProperty"),
        ("punct", "."),
        ("identifier", "call"),
        ("punct", "("),
        ("identifier", parameter),
        ("punct", ","),
        ("string", input_name),
        ("punct", ")"),
        ("punct", "&&"),
        ("punct", "("),
        ("identifier", returned_name),
        ("punct", "."),
        ("identifier", member_name),
        ("punct", "="),
    ]
    expected_suffix = [
        ("punct", "("),
        ("identifier", parameter),
        ("punct", "."),
        ("identifier", input_name),
        ("punct", ")"),
        ("punct", ")"),
    ]
    if actual[:18] != expected_prefix or actual[19:] != expected_suffix:
        raise ClerkConfigError("VITE_CLERK_FAPI: returned portal optional-field assignment is unsupported")
    try:
        _nearest_lexical_binding("Object", tokens, scopes, scopes[start], pairs)
    except ClerkConfigError as exc:
        if "configuration alias is unsupported" not in str(exc):
            raise ClerkConfigError("VITE_CLERK_FAPI: returned portal optional-field guard is ambiguous") from None
    else:
        raise ClerkConfigError("VITE_CLERK_FAPI: returned portal optional-field guard is shadowed")
    try:
        _nearest_lexical_binding(tokens[start + 18].value or "", tokens, scopes, scopes[start + 18], pairs)
    except ClerkConfigError:
        raise ClerkConfigError("VITE_CLERK_FAPI: returned portal optional-field normalizer is unsupported") from None
    return member_name


def _consumer_returned_object(
    parameter: str,
    tokens: Sequence[_JSToken],
    scopes: Sequence[tuple[int, ...]],
    body_open: int,
    body_close: int,
    pairs: dict[int, int],
) -> tuple[int, tuple[tuple[str, tuple[int, ...], int], ...], int | None]:
    body_scope = scopes[body_open] + (body_open,)
    nested_function_bodies = _nested_function_body_opens(tokens, body_open, body_close, pairs)
    returns = [
        index
        for index in range(body_open + 1, body_close)
        if tokens[index].kind == "identifier"
        and tokens[index].value == "return"
        and len(scopes[index]) >= len(body_scope)
        and scopes[index][: len(body_scope)] == body_scope
        and not nested_function_bodies.intersection(scopes[index])
    ]
    if len(returns) != 1 or scopes[returns[0]] != body_scope:
        raise ClerkConfigError("VITE_CLERK_FAPI: portal config consumer must have one unambiguous return")
    return_index = returns[0]
    value_index = return_index + 1
    if value_index >= body_close or tokens[value_index].line_break_before:
        raise ClerkConfigError("VITE_CLERK_FAPI: portal config consumer return is unsupported")
    if _is_punct(tokens[value_index], "{"):
        close_index = pairs.get(value_index)
        if close_index is None or not _initializer_ends_here(tokens, close_index + 1):
            raise ClerkConfigError("VITE_CLERK_FAPI: portal config consumer return is ambiguous")
        return value_index, (), None
    if tokens[value_index].kind == "identifier" and tokens[value_index].value is not None:
        expression_end = _expression_end(tokens, value_index, body_close, pairs)
        if expression_end < body_close and _is_punct(tokens[expression_end], ","):
            segments = _return_comma_expression_segments(tokens, value_index, body_close, pairs)
            final_start, final_end = segments[-1]
            if (
                final_end - final_start != 1
                or tokens[final_start].kind != "identifier"
                or tokens[final_start].value is None
            ):
                raise ClerkConfigError("VITE_CLERK_FAPI: portal config comma return has no config object")
            returned_name = tokens[final_start].value
            assigned_optional_fields: set[str] = set()
            for segment in segments[:-1]:
                member_name = _validate_optional_return_segment(
                    segment,
                    parameter=parameter,
                    returned_name=returned_name,
                    tokens=tokens,
                    scopes=scopes,
                    pairs=pairs,
                )
                if member_name in assigned_optional_fields:
                    raise ClerkConfigError("VITE_CLERK_FAPI: returned portal optional fields are ambiguous")
                assigned_optional_fields.add(member_name)
            object_index, identities = _resolve_output_object(
                returned_name,
                tokens,
                scopes,
                final_start,
                body_open,
                body_close,
                pairs,
            )
            return object_index, identities, final_start
        object_index, identities = _resolve_output_object(
            tokens[value_index].value,
            tokens,
            scopes,
            value_index,
            body_open,
            body_close,
            pairs,
        )
        return object_index, identities, value_index
    raise ClerkConfigError("VITE_CLERK_FAPI: portal config consumer does not return a configuration object")


def _nested_function_body_opens(
    tokens: Sequence[_JSToken], body_open: int, body_close: int, pairs: dict[int, int]
) -> set[int]:
    body_opens: set[int] = set()
    control_headers = {"catch", "for", "if", "switch", "while", "with"}
    for index in range(body_open + 1, body_close):
        token = tokens[index]
        candidate: int | None = None
        if token.kind == "identifier" and token.value == "function":
            cursor = index + 1
            if cursor < body_close and _is_punct(tokens[cursor], "*"):
                cursor += 1
            if cursor < body_close and tokens[cursor].kind == "identifier":
                cursor += 1
            if cursor < body_close and _is_punct(tokens[cursor], "("):
                params_close = pairs.get(cursor, -1)
                if params_close >= 0:
                    candidate = params_close + 1
        elif _is_punct(token, "=>"):
            candidate = index + 1
        elif _is_punct(token, "{") and index > body_open + 1 and _is_punct(tokens[index - 1], ")"):
            params_open = pairs.get(index - 1, -1)
            before_params = tokens[params_open - 1] if params_open > body_open + 1 else None
            if (
                before_params is not None
                and before_params.kind == "identifier"
                and before_params.value not in control_headers
            ) or (before_params is not None and _is_punct(before_params, "]")):
                candidate = index
        if (
            candidate is not None
            and body_open < candidate < body_close
            and _is_punct(tokens[candidate], "{")
            and candidate in pairs
        ):
            body_opens.add(candidate)
    return body_opens


def _function_definition(
    identity: tuple[str, tuple[int, ...], int],
    tokens: Sequence[_JSToken],
    scopes: Sequence[tuple[int, ...]],
    pairs: dict[int, int],
) -> tuple[str, int, int] | None:
    for index, token in enumerate(tokens):
        if token.kind != "identifier" or token.value != "function":
            continue
        name_index = index + 1
        if name_index < len(tokens) and _is_punct(tokens[name_index], "*"):
            name_index += 1
        if name_index >= len(tokens) or tokens[name_index].kind != "identifier":
            continue
        if (tokens[name_index].value or "", scopes[name_index], name_index) != identity:
            continue
        params_open = name_index + 1
        if params_open >= len(tokens) or not _is_punct(tokens[params_open], "("):
            return None
        params_close = pairs.get(params_open, -1)
        body_open = params_close + 1
        if (
            params_close <= params_open + 1
            or params_close != params_open + 2
            or tokens[params_open + 1].kind != "identifier"
            or body_open >= len(tokens)
            or not _is_punct(tokens[body_open], "{")
            or body_open not in pairs
        ):
            return None
        return tokens[params_open + 1].value or "", body_open, pairs[body_open]
    return None


def _single_call_argument(
    tokens: Sequence[_JSToken], start: int, end: int, pairs: dict[int, int]
) -> tuple[int, int, int] | None:
    if (
        start + 2 >= end
        or tokens[start].kind != "identifier"
        or not _is_punct(tokens[start + 1], "(")
        or pairs.get(start + 1) != end - 1
    ):
        return None
    argument_start = start + 2
    argument_end = end - 1
    index = argument_start
    while index < argument_end:
        if _is_punct(tokens[index], "{") or _is_punct(tokens[index], "[") or _is_punct(tokens[index], "("):
            close_index = pairs.get(index)
            if close_index is None:
                return None
            index = close_index + 1
        elif _is_punct(tokens[index], ","):
            return None
        else:
            index += 1
    return start, argument_start, argument_end


def _canonical_trim_normalizer(
    identity: tuple[str, tuple[int, ...], int],
    tokens: Sequence[_JSToken],
    scopes: Sequence[tuple[int, ...]],
    pairs: dict[int, int],
) -> bool:
    definition = _function_definition(identity, tokens, scopes, pairs)
    if definition is None:
        return False
    parameter, body_open, body_close = definition
    returns = [
        index
        for index in range(body_open + 1, body_close)
        if tokens[index].kind == "identifier" and tokens[index].value == "return"
    ]
    if len(returns) != 1:
        return False
    start = returns[0] + 1
    end = _expression_end(tokens, start, body_close, pairs)
    if returns[0] != body_open + 1 or not (
        end == body_close or (end + 1 == body_close and _is_punct(tokens[end], ";"))
    ):
        return False
    actual = [(tokens[index].kind, tokens[index].value) for index in range(start, end)]
    expected = [
        ("identifier", "typeof"),
        ("identifier", parameter),
        ("punct", "==="),
        ("string", "string"),
        ("punct", "?"),
        ("identifier", parameter),
        ("punct", "."),
        ("identifier", "trim"),
        ("punct", "("),
        ("punct", ")"),
        ("punct", ":"),
        ("string", ""),
    ]
    if actual == expected:
        return True
    expected[2] = ("punct", "==")
    return actual == expected


def _template_prefix_identifier(tokens: Sequence[_JSToken], start: int, end: int) -> str | None:
    if (
        end - start != 4
        or tokens[start].kind != "template"
        or tokens[start].raw.startswith("https://${") is False
        or not re.fullmatch(r"https://\$\{[A-Za-z_$][A-Za-z0-9_$]*\}", tokens[start].raw)
        or tokens[start + 1].kind != "template_expr_start"
        or tokens[start + 2].kind != "identifier"
        or tokens[start + 3].kind != "template_expr_end"
    ):
        return None
    return tokens[start + 2].value


def _https_prefix_identifier(tokens: Sequence[_JSToken], start: int, end: int) -> str | None:
    template_identifier = _template_prefix_identifier(tokens, start, end)
    if template_identifier is not None:
        return template_identifier
    if (
        end - start == 3
        and tokens[start].kind == "string"
        and tokens[start].value == "https://"
        and _is_punct(tokens[start + 1], "+")
        and tokens[start + 2].kind == "identifier"
    ):
        return tokens[start + 2].value
    return None


def _canonical_fapi_normalizer(
    identity: tuple[str, tuple[int, ...], int],
    tokens: Sequence[_JSToken],
    scopes: Sequence[tuple[int, ...]],
    pairs: dict[int, int],
) -> bool:
    definition = _function_definition(identity, tokens, scopes, pairs)
    if definition is None:
        return False
    parameter, body_open, body_close = definition

    def parse_const(cursor: int, limit: int) -> tuple[str, tuple[int, int], int] | None:
        if (
            cursor + 2 >= limit
            or tokens[cursor].value != "const"
            or tokens[cursor + 1].kind != "identifier"
            or not _is_punct(tokens[cursor + 2], "=")
        ):
            return None
        value_start = cursor + 3
        value_end = _expression_end(tokens, value_start, limit, pairs)
        if value_end <= value_start:
            return None
        next_cursor = value_end + 1 if value_end < limit and _is_punct(tokens[value_end], ";") else value_end
        return tokens[cursor + 1].value or "", (value_start, value_end), next_cursor

    def parse_null_return(cursor: int, limit: int) -> int | None:
        if cursor + 1 >= limit or tokens[cursor].value != "return" or tokens[cursor + 1].value != "null":
            return None
        end = cursor + 2
        return end + 1 if end < limit and _is_punct(tokens[end], ";") else end

    def parse_if_null(cursor: int, limit: int) -> tuple[tuple[int, int], int] | None:
        if cursor + 1 >= limit or tokens[cursor].value != "if" or not _is_punct(tokens[cursor + 1], "("):
            return None
        condition_close = pairs.get(cursor + 1)
        if condition_close is None:
            return None
        condition = (cursor + 2, condition_close)
        body_cursor = condition_close + 1
        if body_cursor < limit and _is_punct(tokens[body_cursor], "{"):
            close_index = pairs.get(body_cursor)
            if close_index is None:
                return None
            next_cursor = parse_null_return(body_cursor + 1, close_index)
            if next_cursor != close_index:
                return None
            return condition, close_index + 1
        next_cursor = parse_null_return(body_cursor, limit)
        return (condition, next_cursor) if next_cursor is not None else None

    def parse_null_conditional_return(cursor: int, limit: int) -> tuple[tuple[int, int], tuple[int, int], int] | None:
        if cursor + 1 >= limit or tokens[cursor].value != "return" or tokens[cursor + 1].line_break_before:
            return None
        expression_start = cursor + 1
        expression_end = _expression_end(tokens, expression_start, limit, pairs)
        conditional = _split_conditional_expression(tokens, expression_start, expression_end, pairs)
        if conditional is None:
            return None
        condition, consequent, alternate = conditional
        if (
            consequent[1] - consequent[0] != 1
            or tokens[consequent[0]].kind != "identifier"
            or tokens[consequent[0]].value != "null"
            or alternate[0] >= alternate[1]
        ):
            return None
        next_cursor = (
            expression_end + 1 if expression_end < limit and _is_punct(tokens[expression_end], ";") else expression_end
        )
        if next_cursor != limit:
            return None
        return condition, alternate, next_cursor

    cursor = body_open + 1
    raw_declaration = parse_const(cursor, body_close)
    if raw_declaration is None:
        return False
    raw_name, raw_value, cursor = raw_declaration
    raw_call = _single_call_argument(tokens, raw_value[0], raw_value[1], pairs)
    if raw_call is None:
        return False
    trim_index, trim_arg_start, trim_arg_end = raw_call
    if (
        trim_arg_end - trim_arg_start != 1
        or tokens[trim_arg_start].kind != "identifier"
        or tokens[trim_arg_start].value != parameter
    ):
        return False
    try:
        trim_identity = _nearest_lexical_binding(
            tokens[trim_index].value or "", tokens, scopes, scopes[trim_index], pairs
        )
    except ClerkConfigError:
        return False
    if not _canonical_trim_normalizer(trim_identity, tokens, scopes, pairs):
        return False
    _validate_consumer_binding(trim_identity, tokens, scopes, pairs)

    empty_guard = parse_if_null(cursor, body_close)
    if empty_guard is None:
        return False
    empty_condition, cursor = empty_guard
    if (
        empty_condition[1] - empty_condition[0] != 2
        or not _is_punct(tokens[empty_condition[0]], "!")
        or tokens[empty_condition[0] + 1].value != raw_name
    ):
        return False

    protocol_declaration = parse_const(cursor, body_close)
    if protocol_declaration is None:
        return False
    protocol_name, protocol_value, cursor = protocol_declaration
    conditional = _split_conditional_expression(tokens, *protocol_value, pairs)
    if conditional is None:
        if protocol_value[1] - protocol_value[0] != 1 or tokens[protocol_value[0]].value != raw_name:
            return False
    else:
        condition, consequent, alternate = conditional
        condition_tokens = [(tokens[index].kind, tokens[index].value) for index in range(*condition)]
        if (
            condition_tokens
            != [
                ("identifier", raw_name),
                ("punct", "."),
                ("identifier", "includes"),
                ("punct", "("),
                ("string", "://"),
                ("punct", ")"),
            ]
            or consequent[1] - consequent[0] != 1
            or tokens[consequent[0]].value != raw_name
        ):
            return False
        prefixed_name = _https_prefix_identifier(tokens, *alternate)
        if prefixed_name != raw_name:
            return False

    if cursor >= body_close or tokens[cursor].value != "try" or cursor + 1 not in pairs:
        return False
    try_open = cursor + 1
    try_close = pairs[try_open]
    try_cursor = try_open + 1
    url_declaration = parse_const(try_cursor, try_close)
    if url_declaration is None:
        return False
    url_name, url_value, try_cursor = url_declaration
    if (
        url_value[1] - url_value[0] != 5
        or tokens[url_value[0]].value != "new"
        or tokens[url_value[0] + 1].value != "URL"
        or not _is_punct(tokens[url_value[0] + 2], "(")
        or pairs.get(url_value[0] + 2) != url_value[1] - 1
        or tokens[url_value[0] + 3].value != protocol_name
    ):
        return False
    try:
        url_identity = _nearest_lexical_binding("URL", tokens, scopes, scopes[url_value[0] + 1], pairs)
    except ClerkConfigError:
        url_identity = None
    if url_identity is not None:
        return False

    scheme_guard = parse_if_null(try_cursor, try_close)
    if scheme_guard is None:
        conditional_return = parse_null_conditional_return(try_cursor, try_close)
        if conditional_return is None:
            return False
        scheme_condition, (result_start, result_end), try_cursor = conditional_return
    else:
        scheme_condition, try_cursor = scheme_guard
        if try_cursor + 1 >= try_close or tokens[try_cursor].value != "return":
            return False
        result_start = try_cursor + 1
        result_end = _expression_end(tokens, result_start, try_close, pairs)
        try_cursor = result_end + 1 if result_end < try_close and _is_punct(tokens[result_end], ";") else result_end
    scheme_tokens = [
        (tokens[index].kind, tokens[index].value)
        for index in range(*scheme_condition)
        if not (_is_punct(tokens[index], "(") or _is_punct(tokens[index], ")"))
    ]
    if scheme_tokens != [
        ("identifier", url_name),
        ("punct", "."),
        ("identifier", "protocol"),
        ("punct", "!=="),
        ("string", "https:"),
        ("punct", "&&"),
        ("identifier", url_name),
        ("punct", "."),
        ("identifier", "protocol"),
        ("punct", "!=="),
        ("string", "http:"),
    ]:
        return False
    if result_end - result_start != 11 or tokens[result_start].kind != "template":
        return False
    result_raw = tokens[result_start].raw
    match = re.fullmatch(
        r"\$\{([A-Za-z_$][A-Za-z0-9_$]*)\.protocol\}//\$\{([A-Za-z_$][A-Za-z0-9_$]*)\.host\}",
        result_raw,
    )
    if (
        match is None
        or match.group(1) != url_name
        or match.group(2) != url_name
        or tokens[result_start + 1].kind != "template_expr_start"
        or tokens[result_start + 2].value != url_name
        or tokens[result_start + 3].value != "."
        or tokens[result_start + 4].value != "protocol"
        or tokens[result_start + 5].kind != "template_expr_end"
        or tokens[result_start + 6].kind != "template_expr_start"
        or tokens[result_start + 7].value != url_name
        or tokens[result_start + 8].value != "."
        or tokens[result_start + 9].value != "host"
        or tokens[result_start + 10].kind != "template_expr_end"
    ):
        return False
    if try_cursor != try_close:
        return False

    cursor = try_close + 1
    if cursor >= body_close or tokens[cursor].value != "catch":
        return False
    catch_open = cursor + 1
    catch_close = pairs.get(catch_open)
    if catch_close is None:
        return False
    catch_cursor = parse_null_return(catch_open + 1, catch_close)
    if catch_cursor != catch_close or catch_close + 1 != body_close:
        return False
    _validate_consumer_binding(identity, tokens, scopes, pairs)
    return True


def _canonical_key_guard(condition: tuple[int, int], value_alias: str, tokens: Sequence[_JSToken]) -> bool:
    start, end = condition
    actual = [(tokens[index].kind, tokens[index].value) for index in range(start, end)]
    return (
        len(actual) == 17
        and actual[:8]
        == [
            ("identifier", value_alias),
            ("punct", "."),
            ("identifier", "length"),
            ("punct", ">"),
            ("punct", "0"),
            ("punct", "&&"),
            ("punct", "!"),
            ("punct", "("),
        ]
        and actual[8][0] == "identifier"
        and actual[9:]
        == [
            ("punct", "&&"),
            ("identifier", value_alias),
            ("punct", "."),
            ("identifier", "startsWith"),
            ("punct", "("),
            ("string", "pk_test_"),
            ("punct", ")"),
            ("punct", ")"),
        ]
    )


def _resolve_output_expression(
    start: int,
    end: int,
    parameter: str,
    field_name: str,
    tokens: Sequence[_JSToken],
    scopes: Sequence[tuple[int, ...]],
    body_open: int,
    body_close: int,
    pairs: dict[int, int],
    seen: frozenset[tuple[str, tuple[int, ...], int]] = frozenset(),
) -> tuple[str, str]:
    if (
        end - start == 3
        and tokens[start].kind == "identifier"
        and tokens[start].value == parameter
        and _is_punct(tokens[start + 1], ".")
        and tokens[start + 2].kind == "identifier"
        and tokens[start + 2].value in {_CLERK_KEY_FIELD, _CLERK_FAPI_FIELD}
    ):
        return "input", tokens[start + 2].value or ""
    if end - start == 1 and tokens[start].kind == "string" and tokens[start].value is not None:
        return "literal", tokens[start].value
    if end - start == 1 and tokens[start].kind == "identifier" and tokens[start].value is not None:
        identity, init_start, init_end = _local_const_initializer(
            tokens[start].value, tokens, scopes, start, body_open, body_close, pairs
        )
        if identity in seen:
            raise ClerkConfigError("VITE_CLERK_FAPI: portal configuration value alias is cyclic")
        return _resolve_output_expression(
            init_start,
            init_end,
            parameter,
            field_name,
            tokens,
            scopes,
            body_open,
            body_close,
            pairs,
            seen | {identity},
        )
    conditional = _split_conditional_expression(tokens, start, end, pairs)
    if conditional is not None and field_name == "publishableKey":
        condition, consequent, alternate = conditional
        if not (
            alternate[1] - alternate[0] == 1
            and tokens[alternate[0]].kind == "identifier"
            and tokens[alternate[0]].value == "null"
            and consequent[1] - consequent[0] == 1
        ):
            raise ClerkConfigError("VITE_CLERK_PUBLISHABLE_KEY: returned key guard is unsupported")
        alias_token = tokens[consequent[0]]
        if (
            alias_token.kind != "identifier"
            or alias_token.value is None
            or not _canonical_key_guard(condition, alias_token.value, tokens)
        ):
            raise ClerkConfigError("VITE_CLERK_PUBLISHABLE_KEY: returned key guard is unsupported")
        return _resolve_output_expression(
            consequent[0],
            consequent[1],
            parameter,
            field_name,
            tokens,
            scopes,
            body_open,
            body_close,
            pairs,
            seen,
        )
    call = _single_call_argument(tokens, start, end, pairs)
    if call is not None:
        callee_index, argument_start, argument_end = call
        callee_name = tokens[callee_index].value or ""
        identity = _nearest_lexical_binding(callee_name, tokens, scopes, scopes[callee_index], pairs)
        if field_name == "publishableKey" and _canonical_trim_normalizer(identity, tokens, scopes, pairs):
            _validate_consumer_binding(identity, tokens, scopes, pairs)
            return _resolve_output_expression(
                argument_start,
                argument_end,
                parameter,
                field_name,
                tokens,
                scopes,
                body_open,
                body_close,
                pairs,
                seen | {identity},
            )
        if field_name == "fapiOrigin" and _canonical_fapi_normalizer(identity, tokens, scopes, pairs):
            return _resolve_output_expression(
                argument_start,
                argument_end,
                parameter,
                field_name,
                tokens,
                scopes,
                body_open,
                body_close,
                pairs,
                seen | {identity},
            )
        manifest_name = _CLERK_KEY_FIELD if field_name == "publishableKey" else _CLERK_FAPI_FIELD
        raise ClerkConfigError(f"{manifest_name}: returned portal config uses an unsupported normalizer")
    manifest_name = _CLERK_KEY_FIELD if field_name == "publishableKey" else _CLERK_FAPI_FIELD
    raise ClerkConfigError(f"{manifest_name}: returned portal config value is unsupported")


def _validate_returned_object_bindings(
    identities: tuple[tuple[str, tuple[int, ...], int], ...],
    tokens: Sequence[_JSToken],
    scopes: Sequence[tuple[int, ...]],
    body_open: int,
    body_close: int,
    pairs: dict[int, int],
    allowed_return_object_use: int | None = None,
) -> None:
    aliases = {identity[0]: identity for identity in identities}
    for identity in identities:
        name, _, declaration_index = identity
        for index in range(body_open + 1, body_close):
            if index == declaration_index or tokens[index].kind != "identifier" or tokens[index].value != name:
                continue
            if index + 1 < body_close and _is_punct(tokens[index + 1], ":"):
                continue
            if index and _is_punct(tokens[index - 1], "."):
                continue
            try:
                if _nearest_lexical_binding(name, tokens, scopes, scopes[index], pairs) != identity:
                    continue
            except ClerkConfigError:
                raise ClerkConfigError("VITE_CLERK_FAPI: returned portal config binding is ambiguous") from None
            if index == allowed_return_object_use:
                continue
            if index > body_open + 1 and tokens[index - 1].kind == "identifier" and tokens[index - 1].value == "return":
                continue
            if index + 1 < body_close and _is_punct(tokens[index + 1], ".") and index + 2 < body_close:
                member = tokens[index + 2].value or ""
                if member not in _RETURNED_CONFIG_MEMBERS:
                    raise ClerkConfigError(
                        "VITE_CLERK_FAPI: returned portal config escapes through an unsupported member"
                    )
                previous, following = _member_access_mutation_neighbors(
                    tokens, index, index + 2, body_open + 1, body_close, pairs
                )
                if member in _RETURNED_CLERK_FIELDS and (
                    (
                        previous is not None
                        and (
                            (previous.kind == "identifier" and previous.value == "delete")
                            or (previous.kind == "punct" and previous.value in {"++", "--"})
                        )
                    )
                    or (
                        following is not None
                        and following.kind == "punct"
                        and (following.value in _JS_ASSIGNMENT_OPERATORS or following.value in {"++", "--"})
                    )
                ):
                    field_name = _CLERK_KEY_FIELD if member == "publishableKey" else _CLERK_FAPI_FIELD
                    raise ClerkConfigError(f"{field_name}: returned Clerk setting is overwritten")
                continue
            if (
                index >= body_open + 3
                and tokens[index - 1].kind == "punct"
                and tokens[index - 1].value == "="
                and tokens[index - 2].kind == "identifier"
                and tokens[index - 2].value in aliases
                and tokens[index - 3].kind == "identifier"
                and tokens[index - 3].value == "const"
            ):
                continue
            raise ClerkConfigError("VITE_CLERK_FAPI: returned portal config is mutated or escapes")


def _validate_consumer_output(
    parameter: str,
    body_open: int,
    body_close: int,
    input_record: dict[str, str],
    tokens: Sequence[_JSToken],
    scopes: Sequence[tuple[int, ...]],
    pairs: dict[int, int],
) -> None:
    object_index, identities, returned_object_use = _consumer_returned_object(
        parameter, tokens, scopes, body_open, body_close, pairs
    )
    fields = _output_object_fields(tokens, pairs, object_index)
    _validate_returned_object_bindings(identities, tokens, scopes, body_open, body_close, pairs, returned_object_use)
    expected_values = {
        "publishableKey": input_record[_CLERK_KEY_FIELD],
        "fapiOrigin": _https_origin(input_record[_CLERK_FAPI_FIELD], _CLERK_FAPI_FIELD),
    }
    for name, (start, end) in fields.items():
        result_kind, result_value = _resolve_output_expression(
            start,
            end,
            parameter,
            name,
            tokens,
            scopes,
            body_open,
            body_close,
            pairs,
        )
        if result_kind == "input":
            source_value = input_record.get(result_value)
            if result_value != (_CLERK_KEY_FIELD if name == "publishableKey" else _CLERK_FAPI_FIELD):
                raise ClerkConfigError(f"{name}: returned portal config forwards the wrong Clerk field")
            if name == "fapiOrigin":
                source_value = _https_origin(source_value or "", _CLERK_FAPI_FIELD)
        else:
            source_value = result_value
        if source_value != expected_values[name]:
            field_name = _CLERK_KEY_FIELD if name == "publishableKey" else _CLERK_FAPI_FIELD
            raise ClerkConfigError(f"{field_name}: returned portal configuration does not match the manifest")


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
    _, declaration_scope, name_index = _nearest_lexical_binding(name, tokens, scopes, use_scope, pairs)
    declaration_index = name_index - 1
    if (
        name_index >= before_index
        or declaration_index < 0
        or tokens[declaration_index].kind != "identifier"
        or tokens[declaration_index].value != "const"
        or name_index + 2 >= len(tokens)
        or not _is_punct(tokens[name_index + 1], "=")
    ):
        raise ClerkConfigError("VITE_CLERK_FAPI: portal config object alias binding is not a supported const")
    initializer_index = name_index + 2
    identity = (name, declaration_scope, name_index)
    if identity in seen or len(seen) >= 16:
        raise ClerkConfigError("VITE_CLERK_FAPI: portal config object alias is cyclic or too deep")
    initializer = tokens[initializer_index]
    if _is_punct(initializer, "{"):
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


def _config_object_bindings(
    tokens: Sequence[_JSToken],
    scopes: Sequence[tuple[int, ...]],
    pairs: dict[int, int],
    object_fields: dict[int, dict[str, tuple[int, int]]],
    before_index: int,
) -> tuple[list[tuple[str, tuple[int, ...], int, int]], set[int], set[int]]:
    bindings: list[tuple[str, tuple[int, ...], int, int]] = []
    alias_uses: set[int] = set()
    declaration_names: set[int] = set()

    for index in range(before_index - 3):
        if (
            tokens[index].kind != "identifier"
            or tokens[index].value != "const"
            or tokens[index + 1].kind != "identifier"
            or not _is_punct(tokens[index + 2], "=")
        ):
            continue
        name = tokens[index + 1].value
        initializer_index = index + 3
        initializer = tokens[initializer_index]
        object_index: int | None = None
        if _is_punct(initializer, "{"):
            close_index = pairs.get(initializer_index)
            if (
                initializer_index in object_fields
                and close_index is not None
                and _initializer_ends_here(tokens, close_index + 1)
            ):
                object_index = initializer_index
        elif initializer.kind == "identifier" and initializer.value is not None:
            if _initializer_ends_here(tokens, initializer_index + 1):
                visible = [
                    item
                    for item in bindings
                    if item[0] == initializer.value
                    and index > item[2]
                    and len(item[1]) <= len(scopes[initializer_index])
                    and scopes[initializer_index][: len(item[1])] == item[1]
                ]
                if visible:
                    max_scope = max(len(item[1]) for item in visible)
                    nearest = [item for item in visible if len(item[1]) == max_scope]
                    if len(nearest) != 1:
                        raise ClerkConfigError("VITE_CLERK_FAPI: portal config object alias is ambiguous")
                    object_index = nearest[0][3]
                    alias_uses.add(initializer_index)
        if object_index is not None:
            bindings.append((name or "", scopes[index], index + 1, object_index))
            declaration_names.add(index + 1)
    return bindings, alias_uses, declaration_names


@dataclass(slots=True)
class _ConfigBindingCollector:
    tokens: Sequence[_JSToken]
    bindings: list[_ConfigBinding] = field(default_factory=list)
    declaration_names: set[int] = field(default_factory=set)

    def add(self, name_index: int, scope: tuple[int, ...]) -> None:
        if 0 <= name_index < len(self.tokens) and self.tokens[name_index].kind == "identifier":
            self.bindings.append(_ConfigBinding(self.tokens[name_index].value or "", scope, name_index))
            self.declaration_names.add(name_index)


def _add_config_comma_declarators(
    first_name_index: int,
    scope: tuple[int, ...],
    tokens: Sequence[_JSToken],
    scopes: Sequence[tuple[int, ...]],
    pairs: dict[int, int],
    collector: _ConfigBindingCollector,
) -> None:
    cursor = first_name_index + 1
    while cursor < len(tokens):
        token = tokens[cursor]
        if token.kind == "template_expr_start":
            cursor = _skip_template_expression_tokens(tokens, cursor)
            continue
        if _is_punct(token, "{") or _is_punct(token, "[") or _is_punct(token, "("):
            close_index = pairs.get(cursor)
            if close_index is None:
                return
            cursor = close_index + 1
            continue
        name_index = cursor + 1
        if _is_punct(token, ",") and scopes[cursor] == scope and name_index + 1 < len(tokens):
            if tokens[name_index].kind == "identifier" and _is_punct(tokens[name_index + 1], "="):
                collector.add(name_index, scope)
                cursor = name_index + 2
                continue
        if _is_punct(token, ";") or (_is_punct(token, "}") and scopes[cursor] == scope):
            return
        if token.line_break_before and _initializer_ends_here(tokens, cursor):
            return
        cursor += 1


_CONTROL_KEYWORDS = frozenset({"function", "if", "for", "while", "switch", "catch", "with"})


def _config_method_key_index(tokens: Sequence[_JSToken], pairs: dict[int, int], params_open: int) -> int | None:
    key_index = params_open - 1
    if key_index < 0:
        return None
    key = tokens[key_index]
    if key.kind == "identifier" and key.value in _CONTROL_KEYWORDS:
        return None
    if _is_punct(key, "]"):
        key_index = pairs.get(key_index, -1)
        if key_index < 0 or not _is_punct(tokens[key_index], "["):
            return None
    elif key.kind not in {"identifier", "string"}:
        return None
    return key_index


def _config_method_has_control_prefix(tokens: Sequence[_JSToken], key_index: int) -> bool:
    prefix_start = key_index
    while prefix_start > 0:
        previous = tokens[prefix_start - 1]
        if _is_punct(previous, "#") or _is_punct(previous, "*"):
            prefix_start -= 1
        elif previous.kind == "identifier" and previous.value in {"async", "get", "set", "static"}:
            prefix_start -= 1
        else:
            break
    if prefix_start == 0:
        return False
    previous = tokens[prefix_start - 1]
    if previous.kind == "identifier" and previous.value in _CONTROL_KEYWORDS:
        return True
    return (
        previous.kind == "identifier"
        and previous.value == "await"
        and prefix_start > 1
        and tokens[prefix_start - 2].kind == "identifier"
        and tokens[prefix_start - 2].value == "for"
    )


def _config_method_signature(tokens: Sequence[_JSToken], pairs: dict[int, int], params_open: int) -> tuple[int, int] | None:
    params_close = pairs.get(params_open, -1)
    body_open = params_close + 1
    if params_close < 0 or body_open >= len(tokens) or not _is_punct(tokens[body_open], "{"):
        return None
    key_index = _config_method_key_index(tokens, pairs, params_open)
    if key_index is None or _config_method_has_control_prefix(tokens, key_index):
        return None
    return params_close, body_open


def _config_function_params_open(tokens: Sequence[_JSToken], function_index: int) -> int:
    name_index = function_index + 1
    if name_index < len(tokens) and _is_punct(tokens[name_index], "*"):
        name_index += 1
    if name_index < len(tokens) and tokens[name_index].kind == "identifier":
        return name_index + 1
    return name_index


def _config_function_body_opens(tokens: Sequence[_JSToken], pairs: dict[int, int]) -> list[int]:
    bodies: list[int] = []
    for index, token in enumerate(tokens):
        if token.kind == "identifier" and token.value == "function":
            params_open = _config_function_params_open(tokens, index)
            params_close = pairs.get(params_open, -1)
            body_open = params_close + 1
            if params_close >= 0 and body_open < len(tokens) and _is_punct(tokens[body_open], "{"):
                bodies.append(body_open)
        if _is_punct(token, "=>") and index + 1 < len(tokens) and _is_punct(tokens[index + 1], "{"):
            bodies.append(index + 1)
        if _is_punct(token, "("):
            method = _config_method_signature(tokens, pairs, index)
            if method is not None:
                bodies.append(method[1])
    return bodies


def _add_config_parameters(
    params_open: int, params_close: int, scope: tuple[int, ...], tokens: Sequence[_JSToken], collector: _ConfigBindingCollector
) -> None:
    # Treat defaults and destructuring identifiers as binders when their exact pattern is uncertain.
    for parameter_index in range(params_open + 1, params_close):
        if tokens[parameter_index].kind == "identifier":
            collector.add(parameter_index, scope)


def _add_config_variable_bindings(
    index: int,
    tokens: Sequence[_JSToken],
    scopes: Sequence[tuple[int, ...]],
    pairs: dict[int, int],
    function_bodies: Sequence[int],
    collector: _ConfigBindingCollector,
) -> None:
    if tokens[index].kind != "identifier" or tokens[index].value not in {"const", "let", "var"}:
        return
    if index + 1 >= len(tokens):
        return
    name_index = index + 1
    if tokens[name_index].kind == "identifier":
        scope = scopes[index]
        enclosing = [body for body in function_bodies if body in scopes[index]]
        if tokens[index].value == "var" and enclosing:
            function_body = max(enclosing, key=lambda body: len(scopes[body]) + 1)
            scope = scopes[function_body] + (function_body,)
        collector.add(name_index, scope)
        _add_config_comma_declarators(name_index, scope, tokens, scopes, pairs, collector)
    elif _is_punct(tokens[name_index], "{") or _is_punct(tokens[name_index], "["):
        close_index = pairs.get(name_index)
        if close_index is not None:
            for binding_index in range(name_index + 1, close_index):
                if tokens[binding_index].kind == "identifier":
                    collector.add(binding_index, scopes[index])


def _add_config_function_bindings(
    index: int, tokens: Sequence[_JSToken], scopes: Sequence[tuple[int, ...]], pairs: dict[int, int], collector: _ConfigBindingCollector
) -> None:
    if tokens[index].kind != "identifier" or tokens[index].value != "function":
        return
    name_index = index + 1
    if name_index < len(tokens) and _is_punct(tokens[name_index], "*"):
        name_index += 1
    if name_index < len(tokens) and tokens[name_index].kind == "identifier":
        collector.add(name_index, scopes[index])
        params_open = name_index + 1
    else:
        params_open = name_index
    if params_open >= len(tokens) or not _is_punct(tokens[params_open], "("):
        return
    params_close = pairs.get(params_open, -1)
    body_open = params_close + 1
    if params_close >= 0 and body_open < len(tokens) and _is_punct(tokens[body_open], "{"):
        _add_config_parameters(params_open, params_close, scopes[body_open] + (body_open,), tokens, collector)


def _add_config_method_parameters(
    index: int, tokens: Sequence[_JSToken], pairs: dict[int, int], scopes: Sequence[tuple[int, ...]], collector: _ConfigBindingCollector
) -> None:
    if not _is_punct(tokens[index], "("):
        return
    method = _config_method_signature(tokens, pairs, index)
    if method is None:
        return
    params_close, body_open = method
    _add_config_parameters(index, params_close, scopes[body_open] + (body_open,), tokens, collector)


def _add_config_arrow_parameters(
    index: int, tokens: Sequence[_JSToken], pairs: dict[int, int], scopes: Sequence[tuple[int, ...]], collector: _ConfigBindingCollector
) -> None:
    if not _is_punct(tokens[index], "=>") or index == 0:
        return
    if _is_punct(tokens[index - 1], ")"):
        params_close = index - 1
        params_open = pairs.get(params_close, -1)
        if params_open < 0:
            return
        body_open = index + 1
        scope = scopes[body_open] + (body_open,) if body_open < len(tokens) and _is_punct(tokens[body_open], "{") else scopes[index]
        _add_config_parameters(params_open, params_close, scope, tokens, collector)
    elif tokens[index - 1].kind == "identifier":
        body_open = index + 1
        scope = scopes[body_open] + (body_open,) if body_open < len(tokens) and _is_punct(tokens[body_open], "{") else scopes[index]
        collector.add(index - 1, scope)


def _add_config_catch_parameters(
    index: int, tokens: Sequence[_JSToken], pairs: dict[int, int], scopes: Sequence[tuple[int, ...]], collector: _ConfigBindingCollector
) -> None:
    if tokens[index].kind != "identifier" or tokens[index].value != "catch" or index + 1 >= len(tokens):
        return
    params_open = index + 1
    if not _is_punct(tokens[params_open], "(") or params_open not in pairs:
        return
    params_close = pairs[params_open]
    body_open = params_close + 1
    if body_open < len(tokens) and _is_punct(tokens[body_open], "{"):
        _add_config_parameters(params_open, params_close, scopes[body_open] + (body_open,), tokens, collector)


def _add_config_class_binding(
    index: int, tokens: Sequence[_JSToken], scopes: Sequence[tuple[int, ...]], collector: _ConfigBindingCollector
) -> None:
    if tokens[index].kind == "identifier" and tokens[index].value == "class" and index + 1 < len(tokens):
        collector.add(index + 1, scopes[index])


def _add_config_import_bindings(
    index: int, tokens: Sequence[_JSToken], scopes: Sequence[tuple[int, ...]], collector: _ConfigBindingCollector
) -> None:
    if tokens[index].kind != "identifier" or tokens[index].value != "import" or index + 1 >= len(tokens):
        return
    next_token = tokens[index + 1]
    if _is_punct(next_token, ".") or _is_punct(next_token, "?.") or _is_punct(next_token, "("):
        return
    cursor = index + 1
    while cursor < len(tokens) and not _is_punct(tokens[cursor], ";"):
        if tokens[cursor].kind == "string":
            break
        if tokens[cursor].kind == "identifier" and tokens[cursor].value not in {"as", "from", "type"}:
            collector.add(cursor, scopes[index])
        cursor += 1


def _config_binding_shadows(
    tokens: Sequence[_JSToken], scopes: Sequence[tuple[int, ...]], pairs: dict[int, int]
) -> tuple[list[_ConfigBinding], set[int]]:
    collector = _ConfigBindingCollector(tokens)
    function_bodies = _config_function_body_opens(tokens, pairs)
    for index in range(len(tokens)):
        _add_config_variable_bindings(index, tokens, scopes, pairs, function_bodies, collector)
        _add_config_function_bindings(index, tokens, scopes, pairs, collector)
        _add_config_method_parameters(index, tokens, pairs, scopes, collector)
        _add_config_arrow_parameters(index, tokens, pairs, scopes, collector)
        _add_config_catch_parameters(index, tokens, pairs, scopes, collector)
        _add_config_class_binding(index, tokens, scopes, collector)
        _add_config_import_bindings(index, tokens, scopes, collector)
    return collector.bindings, collector.declaration_names


def _reject_config_object_mutation_or_escape(
    tokens: Sequence[_JSToken],
    scopes: Sequence[tuple[int, ...]],
    pairs: dict[int, int],
    object_fields: dict[int, dict[str, tuple[int, int]]],
    tracked_objects: set[int],
    before_index: int,
    allowed_member_uses: set[int],
    allowed_direct_use: int | None,
) -> None:
    bindings, alias_uses, binding_declarations = _config_object_bindings(
        tokens, scopes, pairs, object_fields, before_index
    )
    shadows, shadow_declarations = _config_binding_shadows(tokens, scopes, pairs)
    for use_index in range(before_index):
        token = tokens[use_index]
        if token.kind != "identifier" or use_index in binding_declarations | shadow_declarations:
            continue
        if use_index and _is_punct(tokens[use_index - 1], "."):
            continue
        if use_index + 1 < before_index and _is_punct(tokens[use_index + 1], ":"):
            continue
        visible = [
            item
            for item in bindings
            if item[0] == token.value
            and item[3] in tracked_objects
            and item[2] < use_index
            and len(item[1]) <= len(scopes[use_index])
            and scopes[use_index][: len(item[1])] == item[1]
        ]
        if not visible:
            continue
        max_scope = max(len(item[1]) for item in visible)
        nearest = [item for item in visible if len(item[1]) == max_scope]
        if len(nearest) != 1:
            raise ClerkConfigError("VITE_CLERK_FAPI: portal config object alias is ambiguous")
        binding = nearest[0]
        visible_shadows = [
            item
            for item in shadows
            if item[0] == token.value
            and item[2] != binding[2]
            and len(item[1]) <= len(scopes[use_index])
            and scopes[use_index][: len(item[1])] == item[1]
        ]
        if visible_shadows and max(len(item[1]) for item in visible_shadows) >= max_scope:
            continue
        if use_index in alias_uses or use_index in allowed_member_uses or use_index == allowed_direct_use:
            continue
        raise ClerkConfigError("VITE_CLERK_FAPI: portal config object is mutated or escapes before consumption")


def _portal_config_records(tokens: Sequence[_JSToken]) -> tuple[list[dict[str, str]], set[str]]:
    pairs, scopes = _javascript_delimiters(tokens)
    consumer_functions = _function_parameter_consumers(tokens, pairs, scopes)
    consumer_names = {identity[0] for identity in consumer_functions}
    object_fields: dict[int, dict[str, tuple[int, int]]] = {}
    for open_index, token in enumerate(tokens):
        if not _is_punct(token, "{") or open_index not in pairs:
            continue
        previous = tokens[open_index - 1] if open_index else None
        if previous is not None and not (
            (previous.kind == "punct" and previous.value in {"=", "(", "[", ",", ":", "=>"})
            or (previous.kind == "identifier" and previous.value == "return")
        ):
            continue
        fields, has_spread = _object_fields(tokens, pairs, open_index)
        if not (_FRONTEND_CONFIG_FIELDS & fields.keys()):
            continue
        if has_spread or not _FRONTEND_CONFIG_FIELDS.issubset(fields):
            raise ClerkConfigError("VITE_CLERK_FAPI: portal configuration record is incomplete or unsupported")
        object_fields[open_index] = fields

    object_records: dict[int, dict[str, str]] = {}
    supporting_objects: dict[int, set[int]] = {}
    member_reads: dict[int, set[int]] = {}
    for open_index in sorted(object_fields):
        record: dict[str, str] = {}
        supports: set[int] = set()
        reads: set[int] = set()
        for name in _FRONTEND_CONFIG_FIELDS:
            value, property_objects, property_reads = _static_field_value(
                name,
                object_fields[open_index][name],
                tokens,
                scopes,
                scopes[open_index],
                object_fields,
                pairs,
            )
            record[name] = value
            supports.update(property_objects)
            reads.update(property_reads)
        object_records[open_index] = record
        supporting_objects[open_index] = supports
        member_reads[open_index] = reads

    consumer_calls: list[tuple[int, int, int | None, tuple[str, tuple[int, ...], int]]] = []
    for call_index, token in enumerate(tokens):
        if (
            token.kind != "identifier"
            or token.value not in consumer_names
            or call_index + 1 >= len(tokens)
            or not _is_punct(tokens[call_index + 1], "(")
        ):
            continue
        if call_index and (
            (tokens[call_index - 1].kind == "identifier" and tokens[call_index - 1].value == "function")
            or _is_punct(tokens[call_index - 1], ".")
            or _is_punct(tokens[call_index - 1], "?.")
        ):
            continue
        call_open = call_index + 1
        if call_open not in pairs:
            continue
        call_close = pairs[call_open]
        argument_start = call_open + 1
        argument_end = argument_start
        while argument_end < call_close:
            value_token = tokens[argument_end]
            if value_token.kind == "punct" and value_token.value in {"{", "[", "("}:
                argument_end = pairs[argument_end] + 1
            elif _is_punct(value_token, ","):
                break
            else:
                argument_end += 1
        if argument_end == argument_start:
            continue
        direct_use: int | None = None
        if (
            _is_punct(tokens[argument_start], "{")
            and argument_start in pairs
            and pairs[argument_start] + 1 == argument_end
        ):
            object_index = argument_start
        elif argument_end - argument_start == 1 and tokens[argument_start].kind == "identifier":
            direct_use = argument_start
            object_index = _resolve_config_object(
                tokens[argument_start].value or "",
                tokens,
                scopes,
                scopes[call_index],
                call_index,
                set(object_fields),
                pairs,
            )
        else:
            continue
        if object_index in object_records:
            consumer_name = token.value or ""
            binding_identity = _nearest_lexical_binding(
                consumer_name,
                tokens,
                scopes,
                scopes[call_index],
                pairs,
            )
            if binding_identity not in consumer_functions:
                raise ClerkConfigError("VITE_CLERK_FAPI: portal config consumer binding is shadowed or unsupported")
            consumer_calls.append((call_index, object_index, direct_use, binding_identity))

    consumed_objects = {object_index for _, object_index, _, _ in consumer_calls}
    consumed_records = [object_records[index] for index in sorted(consumed_objects)]
    if (not consumed_records and object_records) or any(
        object_records[index] not in consumed_records for index in object_records.keys() - consumed_objects
    ):
        raise ClerkConfigError(
            "VITE_CLERK_FAPI: portal configuration record is not consumed by the Clerk config parser"
        )

    validated_bindings: set[tuple[str, tuple[int, ...], int]] = set()
    for call_index, object_index, direct_use, binding_identity in consumer_calls:
        parameter, body_open, body_close = consumer_functions[binding_identity]
        if binding_identity not in validated_bindings:
            _validate_consumer_binding(binding_identity, tokens, scopes, pairs)
            validated_bindings.add(binding_identity)
        _validate_consumer_parameter(tokens, parameter, body_open, body_close, pairs)
        _validate_consumer_output(
            parameter,
            body_open,
            body_close,
            object_records[object_index],
            tokens,
            scopes,
            pairs,
        )
        _reject_config_object_mutation_or_escape(
            tokens,
            scopes,
            pairs,
            object_fields,
            supporting_objects[object_index] | {object_index},
            call_index,
            member_reads[object_index],
            direct_use,
        )

    return (
        consumed_records,
        {_CLERK_KEY_FIELD, _CLERK_FAPI_FIELD} if consumer_names else set(),
    )


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
        key_tokens: list[str] = []
        for token in tokens:
            if token.kind not in {"string", "template"}:
                continue
            for prefix in re.finditer(r"\bpk_(?:live|test)_", token.raw):
                end_index = next(
                    (
                        index
                        for index in range(prefix.end(), len(token.raw))
                        if token.raw[index].isspace() or token.raw[index] in "\"'`;,)]}"
                    ),
                    len(token.raw),
                )
                candidate = token.raw[prefix.start() : end_index]
                if candidate in {"pk_live_", "pk_test_", "pk_live_...", "pk_test_..."}:
                    continue
                key_tokens.append(candidate)
        if any(token != config.publishable_key for token in key_tokens):
            raise ClerkConfigError("VITE_CLERK_PUBLISHABLE_KEY: reachable module contains a different Clerk key")
        has_expected_key = has_expected_key or config.publishable_key in key_tokens
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
    parser.add_argument("--root", type=Path, default=_REPO_ROOT / "config" / "env", help="environment manifest root")
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
