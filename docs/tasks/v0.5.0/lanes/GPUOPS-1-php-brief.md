# GPUOPS-1 lane L4 — WordPress REST pass-through for GPU control

Branch `feature/gpuops-1-php`, worktree `context-alt-text-monorepo-gpuops-1-php`. Owns `apps/prototype-wp-alt-context/src/api/class-gpu-control-controller.php`, the registration lines in `apps/prototype-wp-alt-context/src/api/class-api.php`, and `apps/prototype-wp-alt-context/tests/Unit/GpuControlControllerTest.php`.

## Goal

Implement contract C4: `GET acx/v1/recognition/gpu/status` and `POST acx/v1/recognition/gpu/intent`, verbatim pass-through to the description service (rg-015), `manage_options` only.

## Current anchors

- `src/api/class-api.php` :94-97 instantiates and registers controllers (`RecognitionController`, `PublicDemoDescribeController`, `MediaDetailController`, `SettingsController`). Add `GpuControlController` there.
- `src/api/class-settings-controller.php`: `can_manage_settings` (manage_options) and the `/settings/test` route show how the plugin builds the service base URL and API key headers. Reuse the same HTTP helper and error shape; do not write a second client.
- `src/api/class-public-demo-describe-controller.php` :821-859 validates `gpu_state` pass-through; copy its stance: forward unknown fields, never invent them.

## Deliverables

1. `GpuControlController` with the two routes. GET forwards to `GET <service>/scene/gpu/status`. POST validates `action ∈ {start, stop, auto}` and optional integer `ttl_seconds`, adds `requested_by = wp_get_current_user()->user_login`, forwards to `POST <service>/scene/gpu/intent`. Response body and HTTP status are returned exactly as the service sent them. Request timeout 10 s (RES-02). Transport failure → 502 `gpu_status_unavailable` with the WP_Error message.
2. Class filename must be autoloadable per rg-016: either add the `require_once` where sibling controllers are required, or use a PSR-4 filename. Verify with `php -r "require 'vendor/autoload.php'; var_export(class_exists('AltContext\\Api\\GpuControlController'));"` (adjust namespace to match siblings).
3. Unit tests: permission denied for non-admin (403), GET pass-through of a fixture body, POST adds `requested_by` and forwards status 202, invalid action → 400 before any HTTP call, transport error → 502. Mock the HTTP layer the way the existing controller tests do.

## Tests

`cd apps/prototype-wp-alt-context && vendor/bin/phpunit --filter GpuControlController` and `composer run lint` if present (phpcs findings do not block; report them).

## Non-goals

Settings controller changes (L6), SPA (L5), any service-side code.
