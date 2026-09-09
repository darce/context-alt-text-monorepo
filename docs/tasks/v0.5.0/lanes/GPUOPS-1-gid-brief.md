# GPUOPS-1 · lane `gpuops-1-gid` · GPUOPS-1-GID-01

Branch `feature/gpuops-1-gid`, based on `feature/gpuops-1` @ `a3ffcff64`.
Test command: `python3 -m pytest scripts/deploy/tests -q`.

This is the **last open finding** on GPUOPS-1. When it closes, `feature/gpuops-1`
lands and twelve retained lane branches become reapable. Keep the lane tight.

## Finding GPUOPS-1-GID-01 (medium)

`scripts/deploy/gpu-lifecycle-install.sh` ·
`scripts/deploy/tests/test_gpu_lifecycle_contract_ownership.py`

`de76ffc43` introduced

```sh
ACX_API_GID="${ACX_API_GID:-10001}"      # :463
ACX_API_GROUP="${ACX_API_GROUP:-acxapi}" # :464
```

and threaded `${ACX_API_GID}` through the tmpfiles template (`:491`, `:960`) and
the chowns (`:948`, `:950`). Four of the eight tests in
`test_gpu_lifecycle_contract_ownership.py` now fail on this branch. They are all
green on `main`.

**First, understand what is NOT broken.** The tmpfiles heredoc at `:958` is
`<<'TMPF'` — quoted, no expansion — but it is nested inside an *outer, unquoted*
heredoc that composes the remote script, so `${ACX_API_GID}` is already expanded
to `10001` by the composing shell before anything reaches the host. The default
deployment path is correct. Verify this yourself before you change a line of the
installer; if you conclude otherwise, say so and show the evidence rather than
silently "fixing" a bug that is not there.

**What IS broken is the guard, and behind it a real gap.**

`_provisioned()` regex-parses the `d <path> <mode> <user> <group>` tmpfiles lines
straight out of the installer *source*. It now reads the group as the literal
string `${ACX_API_GID}`. So:

- `test_load_dir_group_matches_the_gid_the_api_image_pins` compares
  `'${ACX_API_GID}' == '10001'` — a spelling against a value.
- `test_installer_template_group_is_not_hardcoded_away_from_the_image` greps for
  the decimal literal `10001` in the template line.
- `test_contract_states_each_distinct_ownership_tuple` demands the contract state
  ``root:${ACX_API_GID} 0775``.
- `test_each_registered_deployment_uses_api_writable_tmpfiles_template` greps for
  the same literal.

That is the same drift class as GPUOPS-1-HV-01: a guard asserting on how a value
is *spelled in source* rather than on the value the deployment *resolves*. A
rename broke it, which means it was never guarding the invariant.

And the invariant is now genuinely unguarded. Read the comment block the tests
carry themselves (WBUX6-MRG-01, above `DOCKERFILE = ...`): the group grant on
`/run/acx-write/<env>` only works if the container's runtime gid really is the gid
the host granted. An operator who exports `ACX_API_GID=2000` gets
`/run/acx-write` group 2000 while the api image still runs as gid 10001; the
container falls through to `other` on a `0775` directory, loses write, and
silently stops publishing `describe-load.json`. Nothing compares the two. The
override introduced a way to break the exact invariant these tests exist to
protect, and simultaneously blinded them to it.

## Required fix — two parts

### 1. Make the override safe, or remove it

Decide explicitly and justify it in the commit body:

- **Keep it** and have the installer resolve the gid the api image pins
  (`apps/prototype-description-service/Dockerfile`, `groupadd -r -g <gid>`) and
  **fail fast, non-zero, naming both numbers**, when an operator-supplied
  `ACX_API_GID` disagrees. A wrong gid here is silent data loss, not a warning —
  it must not be a log line the deploy scrolls past.
- **Remove it** and go back to the literal, if nothing actually needs the
  override. `ACX_API_GROUP` is a *name*, not an id, and NSS-resolvable names are a
  real portability need; the numeric gid is not the same kind of thing.

Either is defensible. Pick one, implement it once, do not half-do both.

### 2. Make the guard assert on values, not spellings

`_provisioned()` must resolve the installer's effective values before comparing.
The installer states its own defaults in `VAR="${VAR:-default}"` form, so a small
helper that extracts those defaults from the source and substitutes them into the
parsed tmpfiles lines is enough — and it keeps working through the next rename.

Constraints on that helper:

- It must **fail loudly** on a `${VAR}` reference it cannot resolve to a default.
  A silent fall-through to the raw spelling recreates exactly the vacuous
  assertion this finding is about. The existing
  `assert {"/run/acx", "/run/acx-write"} <= set(found)` guard in `_provisioned()`
  exists for the same reason — follow that precedent.
- Do not weaken any assertion to make it pass. If an assertion is right and the
  installer is wrong, fix the installer.
- The four currently-red tests must go green *because the values agree*, not
  because the comparison got looser.

Add one test that would have caught the real gap: an installer whose resolved
`ACX_API_GID` differs from the Dockerfile's pinned gid must fail. Write it
failing-first against the current code.

## Boundaries

- Touch only `scripts/deploy/gpu-lifecycle-install.sh`,
  `scripts/deploy/tests/test_gpu_lifecycle_contract_ownership.py`, and
  `docs/workbay/contracts/gpu-lifecycle.md` **only if** part 1 changes what the
  installer provisions.
- Do **not** touch `infra/oci/gpu_lifecycle/**`. The intent/journal work on this
  branch is finished and its findings are closed; reopening it is out of scope.
- Do **not** touch `docs/workbay/contracts/gpu-lifecycle.md`'s
  `### Durable intent state` section — another lane owns that prose and it is
  settled.
- Do not touch `apps/**`. If the Dockerfile is wrong, report it; do not edit it.
- No AI attribution trailers in the commit message.

## Sandbox reality

Your sandbox has no network. `python3 -m pytest scripts/deploy/tests -q` is pure
Python and should run — use it. If a suite that shells out stalls, it is the known
macOS/`bash 3.2` locale issue on the coordinator side, not yours.

Some of what this brief describes may already be fixed. Verify against the file
before changing it and report `ALREADY-FIXED:` for anything that is.

## Done

`python3 -m pytest scripts/deploy/tests -q` green, all 8 ownership tests passing
because the resolved gid matches the image-pinned gid; a mismatched
`ACX_API_GID` now fails the deploy (or the override is gone); one new
failing-first test covers the mismatch. Committed on `feature/gpuops-1-gid`.
