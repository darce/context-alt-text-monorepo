# PHP Plugin Context Map

> Quick reference for agents working on WordPress plugin PHP code.

## Critical Files (Read First)

| Priority | File                                             | Purpose                   |
| -------- | ------------------------------------------------ | ------------------------- |
| 🔥 1     | `apps/prototype-wp-alt-context/alt-context.php`  | Plugin entry point        |
| 🔥 2     | `apps/prototype-wp-alt-context/src/Api/`         | REST API controllers      |
| 🔥 3     | `apps/prototype-wp-alt-context/src/Recognition/` | Recognition service proxy |
| 🔥 4     | `apps/prototype-wp-alt-context/src/Security/`    | Nonce, capability checks  |
| 🔥 5     | `docs/agentic/contracts/clustering-api.md`       | WP REST API contract      |

## Plugin Structure

```
apps/prototype-wp-alt-context/
├── alt-context.php              # Plugin bootstrap
├── src/
│   ├── Api/                     # REST controllers
│   │   ├── RecognitionController.php    # Route registration
│   │   ├── RecognitionProxyController.php # Backend forwarding
│   │   └── MediaController.php  # WordPress media queries
│   ├── Recognition/             # Recognition service integration
│   │   ├── RecognitionClient.php        # HTTP client
│   │   └── RecognitionSettings.php      # API key, URL config
│   ├── Security/                # Auth & validation
│   │   ├── NonceVerifier.php    # Nonce validation
│   │   └── CapabilityChecker.php # User permissions
│   ├── Admin/                   # Admin pages
│   └── Database/                # Custom tables
├── js/                          # React frontend (see frontend.md)
├── tests/                       # PHPUnit tests
└── vendor/                      # Composer dependencies
```

## Test Entry Points

| Scope       | Path                 | When to Use            |
| ----------- | -------------------- | ---------------------- |
| Unit        | `tests/Unit/`        | Pure PHP logic         |
| Integration | `tests/Integration/` | WordPress hooks, DB    |
| API         | `tests/Api/`         | REST endpoint behavior |

## Security Patterns (MANDATORY)

```php
// Every state-changing endpoint MUST:

// 1. Verify nonce
check_ajax_referer('acx_nonce', 'nonce');

// 2. Check capability
if (!current_user_can('manage_options')) {
    return new WP_Error('forbidden', 'Insufficient permissions', ['status' => 403]);
}

// 3. Sanitize input
$media_id = absint($request->get_param('media_id'));

// 4. Escape output
echo esc_html($value);
```

## Key Diagrams

- [frontend-uml/proxy-boundary.mmd](../diagrams/frontend-uml/proxy-boundary.mmd) — WP → Backend proxy flow
- [frontend-uml/plugin-core-classes.mmd](../diagrams/frontend-uml/plugin-core-classes.mmd) — Class relationships

## Common Tasks

### Add a new REST endpoint

1. Create controller in `src/Api/`
2. Register route with `register_rest_route('acx/v1', ...)`
3. Add nonce + capability check
4. Write PHPUnit test in `tests/Api/`

### Proxy to recognition service

1. Use `RecognitionClient::request()`
2. Inject `tenant_id` (md5 of site URL)
3. Forward response to frontend
4. Handle errors with `WP_Error`

### Add admin setting

1. Add field to `RecognitionSettings`
2. Register with `register_setting()`
3. Sanitize with appropriate callback
4. Add to settings page UI
