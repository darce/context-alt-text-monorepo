# WordPress Plugin Literature Digest

This digest summarizes two reference texts stored in `docs/literature/` and distills the sections that are most relevant to the Context Alt Text project. Use it as a launch pad for best practices, coding recipes, and cross-references when implementing new slices of the plugin.

---

## Professional WordPress Plugin Development (2nd ed., 2020)

**Focus**: end-to-end architecture guidance for production-grade plugins. The material is organized into thematic chapters that map cleanly to the Context Alt Text roadmap.

### Chapters to revisit first
- **Ch.2 Plugin Framework** - Naming conventions, folder structure, plugin headers, activation/deactivation hooks, uninstall routines, and PSR-like coding standards. Reinforces the scaffolding now in `apps/wp-context-alt-text/src/` and why lifecycle hooks must be idempotent and version-aware.
- **Ch.3 Dashboard and Settings** - How to register admin menus, wire the Options/Settings APIs, and keep UI consistent with Core. Directly informs our dashboard status line, feature flags, and forthcoming configuration pages.
- **Ch.4 Security and Performance** - Covers capabilities, nonces, sanitization/escaping, prepared `$wpdb` queries, caching layers, and transients. Aligns with roadmap guardrails for roster management, remote calls, and background scans.
- **Ch.6 JavaScript** & **Ch.7 Blocks and Gutenberg** - Script registration/enqueue patterns, localization, data bootstrapping, and block scaffolding (including `wp-cli scaffold block`). Guides how we ship the React/Vite admin bundle and potential block surfaces for media UX.
- **Ch.8 Content** - Custom post types, metadata, metaboxes, and taxonomies. Useful if the draft alt-text workflow evolves into custom entities or we persist review queues outside the media library.
- **Ch.9 Users and User Data** - Role/capability design, `current_user_can` checks, and custom role registration. Ties into security gating for roster actions and MCP abilities.
- **Ch.10 Scheduled Tasks** - WordPress Cron fundamentals, real cron integration, and scheduling patterns. Mirrors our missing-alt-text scanner and future propagation jobs.
- **Ch.11 Internationalization** - Text domain usage, loading translations, and generating `.pot` files. Reinforces `load_plugin_textdomain` usage and string hygiene.
- **Ch.12 REST API** - Crafting controllers, using `WP_REST_Request`, authentication, and pairing with the HTTP API (`wp_remote_get`, retry patterns). Critical for bridging the plugin with the recognition service.
- **Ch.14 The Kitchen Sink** - Shortcodes, widgets, rewrite rules, Heartbeat API. Offers recipes for admin notifications and background status updates without custom polling stacks.
- **Ch.15 Debugging** - Toggling debug flags, using Query Monitor, error logging strategy--helpful for triaging cron scans and remote API failures.

### Key takeaways & best practices
- **Canonical structure**: Match plugin folder names to text domains; treat activation/deactivation as migrations; bundle all assets inside the plugin directory.
- **Lifecycle hygiene**: Activation is for provisioning (options, cron events, tables); deactivation disables timers; uninstall purges data. All flows must be re-runnable to support upgrades and multisite network activation.
- **Security discipline**: Always pair capability checks with nonces, sanitize input before storage, and escape output late. Use `prepare()` or `wpdb` helpers for SQL; prefer Core sanitizers (`sanitize_text_field`, `esc_url_raw`, etc.).
- **Performance knobs**: Cache expensive queries with transients or object cache; avoid autoloading large options; batch cron work; offload remote network calls to async queues when possible.
- **Hook strategy**: Document custom hooks, namespace callbacks, and avoid anonymous closures when removals may be needed. Wrap all hook wiring in classes and test for duplicates.
- **Script handling**: Register/enqueue with handles, versions, and dependencies. Localize configuration arrays instead of printing inline JSON. Scope admin assets to specific screens.
- **REST contracts**: Use the REST API for all inter-surface data exchanges. Validate and sanitize in `permission_callback` and `args`. Mirror remote DTOs with PHP objects for parity with the recognition service.
- **Multisite awareness**: Understand site switching (`switch_to_blog`) when future roster sync spans networks; ensure options are site-scoped unless intentionally network-wide.

### Practical cues for Context Alt Text
- Use Ch.2 & Ch.10 patterns to harden the first-run scan scheduler (cron naming, real-cron recommendations for HF deployments).
- Combine Ch.3 guidance with our roadmap to craft the settings page, including tabbed sections for recognition, AI providers, and feature flags.
- Follow Ch.4 nonce + capability rules when exposing roster AJAX/REST endpoints; implement "fail closed" defaults.
- Lean on Ch.6/7 to structure the Vite-driven admin SPA: enqueue via `admin_enqueue_scripts`, expose `wp.apiFetch` wrappers, and consider block-based enhancements to the media modal post-MVP.
- Apply Ch.12 REST API conventions when proxying recognition results through WordPress (custom routes, schema definitions, HTTP client usage).

---

## WordPress Plugin Development Cookbook (3rd ed., 2022)

**Focus**: executable recipes with "How to do it / How it works / There's more" patterns. Each chapter offers drop-in snippets that shorten implementation time.

### Chapters with high ROI
- **Ch.1 Preparing a Local Development Environment** - Docker/LocalWP setup, debug flags, and helpful CLI aliases. Reinforces our LocalWP symlink workflow.
- **Ch.2 Plugin Framework Basics** - Hands-on examples for headers, hooks, shortcodes, enqueueing assets, and OOP wrappers. Good reference when onboarding new contributors.
- **Ch.3 User Settings and Administration Pages** - Recipes for default options, multi-level menus, Settings API forms, contextual help tabs, meta boxes, and multisite-aware settings pages.
- **Ch.4 Custom Content Types and Taxonomies** - Extending CPTs, registering taxonomies, and building relationship UIs; relevant if we model draft alt-text reviews or roster tags as custom entities.
- **Ch.5 Working with the Database** - Using the Options API, custom tables via `dbDelta`, CRUD wrappers, and pagination strategies--vital when `cat_roster`/`cat_observation` tables land.
- **Ch.6 User Roles and Permissions** - Creating custom roles/caps, multi-role assignment, integrating nonces, and surfacing admin notices for permission issues.
- **Ch.7 Interacting with Posts, Pages, and Media** - Managing attachments, adding custom fields, filtering media queries, and implementing bulk actions--directly supports the media-centric workflow of Context Alt Text.
- **Ch.8 Ajax and the REST API** - WordPress AJAX endpoints, nonce protection, `wp_send_json_*` utilities, and building REST controllers with schema validation.
- **Ch.9 Multisite** - Network activation hooks, site option storage, and cross-blog queries; helps ensure cron scans and roster data behave in networks.
- **Ch.10 Enhancing the Admin Experience** - Custom columns, list table filters, notices, dashboard widgets, and the Heartbeat API--useful for presenting scan progress and roster sync states.
- **Ch.11 Enhancing the User Experience** - Front-end shortcodes, widgets, Gutenberg block integration; consider for future public display of alt-text history.
- **Ch.12 Working with External Services** - HTTP API usage, authentication, retry logic, and caching remote responses. Aligns with calling the recognition service and LLM endpoints.
- **Ch.13 Testing, Debugging, and Deployment** - Automated testing with PHPUnit/PHPCS, staging deployment tips, and release packaging.

### Cookbook patterns worth bookmarking
- **Activation defaults**: Register activation hooks that seed options arrays, with guards to avoid overwriting user-defined settings.
- **Settings forms**: Leverage Settings API sections/fields and `add_settings_error` for inline validation feedback.
- **Admin page structure**: Split admin controllers into separate classes/files to avoid loading cost on the frontend; lazy-load only when `is_admin()` matches the target screen.
- **Meta boxes & list tables**: Use `add_meta_box`/`manage_upload_columns` recipes to extend the media library while keeping auto-sanitized values.
- **AJAX security**: Pair `check_ajax_referer` with capability checks, return standardized JSON error payloads, and enqueue nonce tokens via `wp_localize_script`.
- **HTTP requests**: Use `wp_remote_post` with timeouts, retries, and response validation before decoding JSON; cache expensive remote calls with transients or options.
- **Cron helpers**: Recipes for scheduling, unscheduling, and creating real cron entries map directly to our scanner, propagation, and roster sync jobs.
- **Testing**: Examples for bootstrapping PHPUnit with WordPress, mocking globals, and using `WP_UnitTestCase` to validate database writes--essential when we add migrations and service tests.

### Applying the cookbook to Context Alt Text
- Adopt the admin Settings API recipes (Ch.3) to build the recognition service configuration UI with validation and contextual help tabs.
- Use the database chapter (Ch.5) as a reference when implementing `cat_roster` and `cat_observation` migrations, ensuring `dbDelta` files, version checks, and CRUD wrappers follow best practices.
- Lean on the Ajax/REST chapter (Ch.8) for implementing secure AJAX handlers in `RosterPage` and the companion REST routes surfaced to the Vite SPA.
- Follow the media-focused recipes (Ch.7) to extend the media modal, add custom list columns, and build batch actions for missing-alt media.
- Reuse HTTP API patterns (Ch.12) for communicating with the Hugging Face recognition service and any LLM endpoints, including header injection and error remapping.
- Incorporate testing guidelines (Ch.13) to bootstrap PHPUnit for scanner lifecycle hooks and REST contract tests as we harden the backend integration.

---

## How to use this digest
- Reference the chapter lists when planning new roadmap slices to ensure we lift canonical patterns rather than inventing one-off implementations.
- When filing tasks or PRs, link back to the chapter/recipe that influenced the solution to keep architectural intent visible.
- Future agents can expand this digest with additional notes (e.g., concrete code snippets, migration checklists) as we adopt more of the literature's guidance.

