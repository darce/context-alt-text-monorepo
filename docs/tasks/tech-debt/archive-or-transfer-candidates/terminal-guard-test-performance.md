# Investigation: terminal-guard test performance

**Date**: 2026-03-30
**File**: `.github/hooks/test_terminal_guard.py`
**Symptom**: 85 tests take ~3.3s wall time for a pure-logic hook with no I/O dependencies

## Root Cause

Every test spawns a fresh Python subprocess via `subprocess.run([sys.executable, str(HOOK_SCRIPT)], ...)`. That's 85 Python interpreter startups at ~30-40ms each, accounting for essentially all execution time. The hook itself is pure synchronous logic (regex matching + JSON) that completes in microseconds.

### Evidence

```
$ time python -m pytest .github/hooks/test_terminal_guard.py -q
85 passed in 3.60s
real 3.325s  (user 2.07s + sys 0.68s = 82% CPU)
```

Slowest test: `find . -name '*.py'` at 0.42s — a single subprocess spawn + regex classification.

### Test breakdown

| Category | Tests | Needs subprocess? | Why |
|---|---|---|---|
| Tier 1 allowlist (`test_allowlisted_commands_pass_through`) | 38 | No | Tests `_check_command` returns `None` |
| Tier 2 hard block (`test_hard_block_violations`) | 18 | No | Tests `_check_command` returns `("block", ...)` |
| Tier 3 default deny (`test_default_deny_unknown_commands`) | 7 | No | Tests `_check_command` returns `("ask", ...)` |
| Boundary tests (git status, tail) | 4 | No | Tests `_check_command` classification |
| Telemetry tests | 3 | Yes | Tests file I/O side effects in subprocess |
| Schema/robustness tests | 5 | Yes | Tests stdin parsing, camelCase, empty input |
| **Total** | **85** | **8 yes / 77 no** |

77 of 85 tests (91%) only verify the return value of `_check_command()` — a pure function. They don't need subprocess isolation.

## Recommended Fix

Import `_check_command` directly and call it in-process for the 77 classification tests. Keep `_run_hook` (subprocess) only for the 8 tests that genuinely need it (telemetry file writes, stdin/stdout/exit-code contract, camelCase schema handling).

```python
# Direct import for classification tests
from terminal_guard import _check_command

def test_hard_block_cat():
    result = _check_command("cat README.md")
    assert result is not None
    decision, tool, _ = result
    assert decision == "block"
    assert tool == "read_file"

def test_allowlisted_make():
    assert _check_command("make test-handoff") is None
```

### Expected improvement

- 77 tests become in-process function calls: ~0ms each (vs ~35ms per subprocess)
- 8 tests remain subprocess-based: ~0.3s total
- Estimated total: **<0.5s** (down from 3.3s, ~85% reduction)

### Implementation notes

- `sys.path.insert(0, str(Path(__file__).parent))` at the top of the test file, then `from terminal_guard import _check_command, _strip_env_prefix, _base_command`
- The `terminal-guard.py` filename with a hyphen requires either renaming the file or using `importlib`. Renaming to `terminal_guard.py` is cleaner but changes the hook path in settings.
- Alternative: add `terminal_guard.py` as a symlink, or use `importlib.util.spec_from_file_location`.
