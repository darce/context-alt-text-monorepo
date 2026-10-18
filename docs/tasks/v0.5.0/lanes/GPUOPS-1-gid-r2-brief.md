# GPUOPS-1 · lane `gpuops-1-gid` round 2 · GPUOPS-1-GID-02

Branch `feature/gpuops-1-gid`, currently at `d0495a61c` (your round-1 checkpoint).
Test command: `python3 -m pytest scripts/deploy/tests -q`.

Round 1 landed. I verified it locally, because your self-verify never ran
(exit 70, zero tests executed — not a red suite, an unrun gate).

**What I confirmed is good, so do not redo it:**

- `test_gpu_lifecycle_contract_ownership.py` is now 9 passed, up from 4 failed /
  4 passed. `_installer_defaults` + `_resolve_installer_value` resolve values
  instead of comparing spellings, and they assert loudly on an unresolvable
  `${VAR}` rather than silently falling through. That is the right shape.
- `resolve_api_image_gid` plus the `exit 2` on disagreement is the right call on
  part 1, and the new `test_installer_rejects_a_gid_override_that_differs_from_the_api_image`
  actually invokes the installer instead of grepping it.
- Your rewrite of `ensure_acx_api_group` (groupadd, then fall back to
  `acxgid<gid>`) brings the function into parity with the inline remote block
  and is an improvement. Keep it.

## GPUOPS-1-GID-02 (high) — the one thing left

`scripts/deploy/tests/test_gpu_lifecycle_install.py::test_installer_provisions_every_supplementary_group_it_references`
fails. It fails on `feature/gpuops-1` too and passes on `main`, so it is a
pre-existing branch regression, not something you caused — but it is the last
red test between GPUOPS-1 and merge, and it is the same drift class you just
fixed one layer down.

The branch redesigned the units to reference the api group by **name**, not by
number. The comment the branch added at `:211` explains why: systemd resolves
`SupplementaryGroups` through NSS before it forks `ExecStart`, a bare numeric
chown creates no group entry, and both lifecycle units died at `216/GROUP`
until the gid also had a resolvable *name*. The installer emits
`SupplementaryGroups=${ACX_API_GROUP_NAME}`, which the host resolves to
`acxapi`.

The test still asserts the pre-redesign spelling:

```python
assert "SupplementaryGroups=10001" in rendered
```

I executed the installer through the test's own fake-transport shim on your
branch. It returns 0, the fake NSS db contains `acxapi:x:10001:`, and the
rendered `acx-gpu-start.service` contains `SupplementaryGroups=acxapi`. Every
substantive assertion in that test already passes — `groupadd -r -g 10001
acxapi` is called, `getent` brackets it before and after, the group db resolves
10001. Only the final render assertion fails, and it checks the representation
rather than the invariant.

**Do not "fix" this by making the installer emit the number.** That would
re-assert the exact bug the branch fixed. Fix the assertion: the rendered
`SupplementaryGroups` value must be a group name that the fake NSS database
maps to the **image-pinned** gid (read it via the same `_api_runtime_ids()`
style source of truth, not a literal `10001`). Verify the mapping; do not
verify the spelling.

If after reading the code you conclude the installer is wrong and the test is
right, say so and show the evidence — do not silently pick one.

## One question to answer in the commit body

Round 1 changed two unrelated lines:

```sh
IDLE_SECONDS="${IDLE_SECONDS-300}"     # was ${IDLE_SECONDS:-300}
REAP_INTERVAL="${REAP_INTERVAL-2min}"  # was ${REAP_INTERVAL:-2min}
```

`main` uses the `-` form for both, so this restores main. But `START_INTERVAL`
was left at `:-`, so the three siblings now disagree, and nothing in the commit
message explains it. I checked: the ownership tests pass either way, so this was
not needed to make anything green.

It is not cosmetic. With `-`, an exported-but-empty `IDLE_SECONDS=` propagates
empty into the rendered unit instead of defaulting to 300. Either make all three
consistent and say which form is correct and why, or revert these two and leave
the interval defaults alone. Do not leave them split.

## Boundaries

- `scripts/deploy/tests/test_gpu_lifecycle_install.py`,
  `scripts/deploy/tests/test_gpu_lifecycle_contract_ownership.py`,
  `scripts/deploy/gpu-lifecycle-install.sh`.
- Do **not** touch `infra/oci/gpu_lifecycle/**` or `apps/**`.
- Do not weaken any assertion to make it pass.
- No AI attribution trailers in the commit message.

## Sandbox reality

No network. `python3 -m pytest scripts/deploy/tests -q` is pure Python but takes
about 12 minutes and spawns shell shims; run at least
`scripts/deploy/tests/test_gpu_lifecycle_install.py` and
`scripts/deploy/tests/test_gpu_lifecycle_contract_ownership.py` before you
finish, and say which you ran.

## Done

Both of those files green, `SupplementaryGroups` asserted by resolved mapping
rather than by literal, the interval-default split resolved and explained, and a
real commit (not a `wip(offload)` checkpoint) on `feature/gpuops-1-gid`.
