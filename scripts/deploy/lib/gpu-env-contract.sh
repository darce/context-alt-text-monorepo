#!/usr/bin/env bash
# Repository-side adapter for the GPU env preflight. The VM-self-contained
# describe gate is the single definition site for trusted profiles. A staged
# preflight package places it beside this file; repository runs find the same
# source from the repository-relative fallback.

contract_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
describe_gate_contract="${contract_dir}/describe-gate.sh"
if [[ ! -r "$describe_gate_contract" ]]; then
    describe_gate_contract="${contract_dir}/../../../infra/oci/demo/lib/describe-gate.sh"
fi
if [[ ! -r "$describe_gate_contract" ]]; then
    echo "ERROR: trusted description profile contract is missing: describe-gate.sh" >&2
    return 1
fi
# shellcheck source=../../../infra/oci/demo/lib/describe-gate.sh
source "$describe_gate_contract"

# The shared demo helper intentionally has a very small sed grammar, but the
# deployment preflight also needs to distinguish executable PHP from comments.
# Keep the accepted define('NAME','value') shape unchanged while removing PHP
# line/block comments with a quote-aware scanner before looking for constants.
php_define_value() {
    local name="$1" src="$2"
    [ -n "$name" ] || { printf '%s' ""; return; }
    printf '%s' "$src" | python3 -c '
import re
import sys

name = sys.argv[1]
source = sys.stdin.read()
out = []
i = 0
quote = None
while i < len(source):
    char = source[i]
    following = source[i + 1] if i + 1 < len(source) else ""
    if quote is not None:
        out.append(char)
        if char == "\\" and following:
            out.append(following)
            i += 2
            continue
        if char == quote:
            quote = None
        i += 1
        continue
    if char in ("\"", "\x27"):
        quote = char
        out.append(char)
        i += 1
        continue
    if char == "/" and following == "*":
        end = source.find("*/", i + 2)
        i = len(source) if end < 0 else end + 2
        out.append(" ")
        continue
    if char == "/" and following == "/":
        end = source.find("\n", i + 2)
        i = len(source) if end < 0 else end
        out.append("\n")
        continue
    if char == "#":
        end = source.find("\n", i + 1)
        i = len(source) if end < 0 else end
        out.append("\n")
        continue
    out.append(char)
    i += 1

code = "".join(out)
pattern = re.compile(
    r"define\(([\x27\"])" + re.escape(name) + r"\1,([\x27\"])([^\x27\"]*)\2\)"
)
match = pattern.search(code)
if match:
    sys.stdout.write(match.group(3))
' "$name" 2>/dev/null
}

acx_is_trusted_describe_profile() {
    is_trusted_describe_profile "$1"
}
