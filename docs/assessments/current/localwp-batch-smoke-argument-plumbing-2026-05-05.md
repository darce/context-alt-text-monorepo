# LocalWP Batch Smoke Argument Plumbing Assessment

Date: 2026-05-05
Status: actionable finding
Scope: `make localwp-batch-run-smoke` and `scripts/localwp/batch-run-smoke.php`

## Summary

`make localwp-batch-run-smoke` currently passes a literal `--` before the positional arguments sent to WP-CLI `eval-file`. WP-CLI exposes that separator to the evaluated PHP script as `$args[0]`, so every smoke harness argument shifts one slot to the right.

The visible symptom is that a command such as:

```bash
make localwp-batch-run-smoke WP_PATH="$HOME/Development/wp-context-alt-text/app/public" SMOKE_LIMIT=10 BATCH_SIZE=5
```

can report a successful smoke with `submitted_total: 1` instead of exercising 10 attachments. The smoke is not proving the operator-requested batch size or timeout settings.

## Evidence

The Makefile expands the final WP-CLI call as:

```bash
_run_wp --path=".../app/public" eval-file ".../scripts/localwp/batch-run-smoke.php" -- "10" "5" "60" "500"
```

The PHP smoke script reads raw positional arguments directly:

```php
$limit = isset( $args[0] ) ? max( 1, (int) $args[0] ) : 100;
$batch_size = isset( $args[1] ) ? max( 1, (int) $args[1] ) : 5;
$timeout_seconds = isset( $args[2] ) ? max( 1, (int) $args[2] ) : 240;
$poll_interval_ms = isset( $args[3] ) ? max( 100, (int) $args[3] ) : 1000;
```

The previously captured successful payload from an invocation with `SMOKE_LIMIT=10 BATCH_SIZE=5` showed this shifted mapping:

| Intended field | Intended value | Actual parsed value | Why |
| --- | ---: | ---: | --- |
| `limit` | `10` | `1` | `(int) "--"` becomes `0`, then `max(1, 0)` |
| `batch_size` | `5` | `10` | receives intended limit |
| `timeout_seconds` | default `240` | `5` | receives intended batch size |
| `poll_interval_ms` | default `1000` | `240` | receives intended timeout |

This matches the runtime JSON observed after activation repair: `submitted_total: 1`, `timeout_seconds: 5`, and `poll_interval_ms: 240`.

## Impact

- The smoke harness can produce false confidence by scanning one image while the operator believes it scanned 10, 100, or another requested count.
- Timeout and polling controls are also shifted, so smoke failures can be artificially fast or oddly timed.
- Batch behavior is under-tested because `BATCH_SIZE` becomes the intended limit, and the actual batch size is not currently emitted in the JSON payload.
- Documentation examples that include `SMOKE_LIMIT` and `BATCH_SIZE` are misleading until the plumbing is fixed.

## Recommended Fix

Remove the literal `--` from the Makefile `eval-file` invocation:

```make
_run_wp --path="$(WP_PATH)" eval-file "$(CURDIR)/scripts/localwp/batch-run-smoke.php" "$(if $(SMOKE_LIMIT),$(SMOKE_LIMIT),100)" "$(if $(BATCH_SIZE),$(BATCH_SIZE),5)" "$(if $(TIMEOUT_SECONDS),$(TIMEOUT_SECONDS),240)" "$(if $(POLL_INTERVAL_MS),$(POLL_INTERVAL_MS),1000)"
```

Then harden the PHP script so future wrapper changes fail loudly instead of silently coercing invalid arguments:

- Reject `--` if it appears in `$args`.
- Validate each numeric argument with `ctype_digit()` or `filter_var(..., FILTER_VALIDATE_INT)` before coercion.
- Include `limit` and `batch_size` in the final JSON payload for operator-visible confirmation.

## Suggested Regression Coverage

Add a repo-local test that exercises the Makefile target with a fake `scripts/localwp-wp.sh` wrapper or a fixture-controlled `PATH`, and asserts the final `eval-file` command does not include `--` before smoke script arguments.

Add a PHP-level smoke parser test or script extraction that proves these inputs map directly:

```text
args: 10 5 60 500
limit: 10
batch_size: 5
timeout_seconds: 60
poll_interval_ms: 500
```

## Verification After Fix

Run:

```bash
make localwp-batch-run-smoke WP_PATH="$HOME/Development/wp-context-alt-text/app/public" SMOKE_LIMIT=10 BATCH_SIZE=5 TIMEOUT_SECONDS=60 POLL_INTERVAL_MS=500
```

Expected payload properties:

- `submitted_total: 10`
- `accepted_total: 10`
- `terminal_state: true`
- `reconciled: true`
- `timeout_seconds: 60`
- `poll_interval_ms: 500`

If the local site has fewer than 10 image attachments, the script should fail with `Need at least 10 image attachments`, not silently scan one item.
