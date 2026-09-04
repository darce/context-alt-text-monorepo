# Public demo describe

The `[acx_demo_describe]` shortcode is a deliberately narrow public adapter over the same asynchronous describe-run pipeline used by the authenticated Workbench. It accepts one configured WordPress attachment ID; it has no upload field and no URL input.

## Screen and state map

```text
+-- Describe an image ------------------------------------------------------+
| Choose an image to describe                                              |
|                                                                          |
|  ( ) +-------------+   ( ) +-------------+   ( ) +-------------+        |
|      |             |       |             |       |             |        |
|      | demo image  |       | demo image  |       | demo image  |        |
|      |             |       |             |       |             |        |
|      +-------------+       +-------------+       +-------------+        |
|      Garden                Lake                   Street                  |
|                                                                          |
|  [ Describe selected image ]                                             |
|                                                                          |
|  ● Select an image, then choose Describe.                  IDLE           |
|  ! Too many requests. Please wait and try again.           LIMITED       |
|  ◌ The description service is warming up…                 WARMING         |
|  ◌ Describing the image… 50%                              DESCRIBING      |
|  ✓ Description complete.                                  COMPLETED       |
|    | A person walking beside a lake under a cloudy sky. |                 |
|  × The image could not be described. Please try later.    ERROR          |
+--------------------------------------------------------------------------+
```

The status is an `aria-live="polite"` region. Every state combines an icon with token-based color, so meaning does not depend on color alone. Completion moves focus to the result. While a request is active, picker controls are disabled; terminal and error states restore them.

Polling begins at 500 ms, doubles to a maximum interval of 5 seconds, and stops at the deadline returned by the server. That deadline combines the configured GPU warm-up budget (`ACX_GPU_WARMUP_TIMEOUT_SECONDS`, default 510 seconds) with the 180-second inference budget. Each submit/status fetch is independently aborted at its remaining deadline or when the page navigates away. The hard stop does not claim that backend work was cancelled: it tells the visitor to wait and refresh, avoiding an automatic retry that could duplicate paid work.

## Safety boundaries

- The feature flag `acx_public_demo_enabled` defaults off. Both REST routes validate the page's `X-WP-Nonce` and the flag; neither uses `__return_true`.
- `acx_public_demo_media_ids` is the complete input authority. Requests carry a single integer ID and the controller passes that ID to `DescribeController::submit_describe_run()`; browser-provided bytes and URLs are impossible in this contract.
- A per-peer-IP token bucket admits three requests per minute. Only the direct `REMOTE_ADDR` is used; forwarded headers are not trusted at this boundary.
- `acx_public_demo_daily_cap` defaults to 50. A lock-held, non-autoloaded daily usage option reserves capacity before pipeline submission.
- An atomic `add_option` lock admits one public run at a time. Terminal polling releases it. Before replacing an expired lease, the controller reconciles its fenced `run_id` with the backend: a live or indeterminate run renews the lease and rejects admission, while only a terminal or unknown run permits replacement. Lock/rate/counter storage ambiguity fails closed.
- The public status adapter authorizes only the currently recorded public run. It rebuilds responses from the public field allowlist, maps upstream failures to stable public codes, and never forwards tenant identifiers or raw service errors. At completion it obtains the existing pipeline's item result and exposes only the selected attachment's draft description.

This follows the read-only heuristics canon's Release It! stability vocabulary: **RES-09** asks what throttles a high-fan-in front tier when the back tier saturates (the rate and daily limits); **RES-13** requires an explicit containment boundary and tested failure modes (the one-run bulkhead and fail-closed storage paths); **RES-02/RES-03** require bounded waits and fast failure (the browser polling deadline); and **RES-07** requires a steady-state reclaimer (daily usage is one date-stamped option rather than one accumulating option per day). Principle 14 / **SECD-02** grounds the smallest-grant input contract: anonymous authority reaches only operator-selected attachment IDs.

## Operator setup

The default is disabled. Configure it with WP-CLI, replacing the example IDs with image attachments already in the Media Library:

```sh
wp option update acx_public_demo_media_ids '[41,42,43]' --format=json
wp option update acx_public_demo_daily_cap 50
wp option update acx_public_demo_enabled 1
```

Add `[acx_demo_describe]` to the public demo page. Disable the trigger immediately without changing the page:

```sh
wp option update acx_public_demo_enabled 0
```

If a visitor abandons a run, the bulkhead remains until status observes a terminal state. Once its ten-minute lease ages, the next submission checks the recorded run against the backend before either renewing or replacing the lease. Operators investigating a known-stale run can inspect `wp option get acx_public_demo_inflight --format=json`; normal operation should not require manual deletion.
