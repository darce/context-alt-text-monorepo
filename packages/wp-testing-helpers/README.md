# WordPress Testing Helpers

Centralise PHPUnit fixtures, WordPress factory wrappers, and custom assertions that are shared across Context Alt Text services.

Possible contents:

- `Factories/AttachmentFactory.php`
- `Assertions/CapabilityAssertions.php`
- `bootstrap.php` for registering the helpers in test suites

Keep this package framework-agnostic so both the plugin (PHPUnit) and backend (Pytest/MSW via generated fixtures) can reuse data builders.
