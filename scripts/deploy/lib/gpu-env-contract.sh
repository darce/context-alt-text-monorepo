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

# Decode a strict single-line Compose dotenv subset. Reject escapes rather than
# guessing whether Compose would interpolate/decode them. A quote envelope may
# not contain its own delimiter (e.g. single-quoted PHP inside single quotes).
acx_env_literal_value() {
    local value="${1%$'\r'}"
    case "$value" in
        *\\*|*'$'*|*$'\n'*|*$'\r'*)
            echo "ERROR: unsupported dotenv escape, interpolation or multiline value (redacted)." >&2
            return 1 ;;
    esac
    case "$value" in
        \"*|\'*)
            local delimiter="${value:0:1}"
            if [[ ${#value} -lt 2 || "${value: -1}" != "$delimiter" ]]; then
                echo "ERROR: unterminated dotenv quote (redacted)." >&2
                return 1
            fi
            value="${value:1:${#value}-2}"
            if [[ "$value" == *"$delimiter"* ]]; then
                echo "ERROR: embedded dotenv quote delimiter (redacted)." >&2
                return 1
            fi
            ;;
    esac
    printf '%s' "$value"
}

# Accepted PHP is deliberately restricted to unconditional, literal define
# statements and comments. Unsupported code fails closed; env input is never
# evaluated. Bootstrap sources this same helper for credential parity.
php_define_value() {
    local name="$1" src="$2"
    printf '%s' "$src" | python3 -c '
import re
import sys

source = sys.stdin.read()
name = sys.argv[1]
# Single-quoted values have PHP literal semantics; reject escapes and double
# quotes (which could interpolate PHP variables) rather than guessing values.
statement = re.compile(r"define\([ \t\r\n]*\x27([A-Z][A-Z0-9_]*)\x27[ \t\r\n]*,[ \t\r\n]*(?:\x27([^\x27\\]*)\x27|true|false|0|[1-9][0-9]*)[ \t\r\n]*\)[ \t\r\n]*;")
comment = re.compile(r"/\*.*?\*/|//[^\n]*(?:\n|$)|\#[^\n]*(?:\n|$)", re.S)
values = {}
i = 0
while i < len(source):
    if source[i] in " \t\r\n":
        i += 1
        continue
    match = comment.match(source, i)
    if match:
        i = match.end()
        continue
    match = statement.match(source, i)
    if not match or match.group(1) in values:
        raise SystemExit(0)  # No value: caller reports missing config, redacted.
    values[match.group(1)] = match.group(2)
    i = match.end()
sys.stdout.write(values.get(name) or "")
' "$name" 2>/dev/null
}

acx_is_trusted_describe_profile() {
    is_trusted_describe_profile "$1"
}
