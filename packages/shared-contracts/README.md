# Shared Contracts

Store JSON schemas, OpenAPI fragments, and generated DTOs consumed by both the WordPress plugin and the recognition service.

Recommended structure:

```
json/
  alt-text/
  recognition/
php/
  src/Contracts/
  composer.json
typescript/
  src/contracts/
  package.json
```

When an API changes:

1. Update the canonical schema in this package.
2. Regenerate language-specific DTOs (e.g., PHP classes, TS types).
3. Bump the package version and update both apps to consume the new build.
