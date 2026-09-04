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

acx_is_trusted_describe_profile() {
    is_trusted_describe_profile "$1"
}
