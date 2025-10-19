# Validation Logic Contract

This document defines the shared validation rules that MUST be synchronized between the frontend (TypeScript) and backend (PHP) codebases.

## Overview

To prevent validation drift and ensure consistent behavior across the stack, all validation constants and logic are centralized in shared constant files:

- **TypeScript**: `apps/wp-context-alt-text/js/admin/constants/validation.ts`
- **PHP**: `apps/wp-context-alt-text/src/Shared/Constants/ValidationConstants.php`

## Validation Rules

### 1. Recognition Service Timeout

**Purpose**: Validate and sanitize timeout values for recognition API requests.

| Constant             | Value    | Description                                       |
| -------------------- | -------- | ------------------------------------------------- |
| `MIN_TIMEOUT_MS`     | `1000`   | Minimum allowed timeout (1 second)                |
| `MAX_TIMEOUT_MS`     | `120000` | Maximum allowed timeout (2 minutes)               |
| `DEFAULT_TIMEOUT_MS` | `15000`  | Default timeout when invalid/missing (15 seconds) |

**Validation Logic**:

1. Convert input to integer
2. If value <= 0, use `DEFAULT_TIMEOUT_MS`
3. Clamp value between `MIN_TIMEOUT_MS` and `MAX_TIMEOUT_MS`
4. Return sanitized value

**TypeScript Implementation**:

```typescript
// js/admin/constants/validation.ts
export const TIMEOUT_MS = {
  MIN: 1_000,
  MAX: 120_000,
  DEFAULT: 15_000,
} as const;

// js/admin/settings/RecognitionSettingsPanel.tsx
const clampTimeout = (value: number): number => {
  if (!Number.isFinite(value) || value <= 0) {
    return VALIDATION.TIMEOUT_MS.DEFAULT;
  }

  return Math.min(
    VALIDATION.TIMEOUT_MS.MAX,
    Math.max(VALIDATION.TIMEOUT_MS.MIN, Math.trunc(value))
  );
};
```

**PHP Implementation**:

```php
// src/Shared/Constants/ValidationConstants.php
final class ValidationConstants
{
    public const MIN_TIMEOUT_MS = 1000;
    public const MAX_TIMEOUT_MS = 120000;
    public const DEFAULT_TIMEOUT_MS = 15000;
}

// src/Shared/Config/SettingsRepository.php
private function sanitizeTimeout($value): int
{
    if (is_string($value)) {
        $value = trim($value);
    }

    $timeout = (int) $value;

    if ($timeout <= 0) {
        $timeout = ValidationConstants::DEFAULT_TIMEOUT_MS;
    }

    return ValidationHelpers::sanitizeTimeout(
        $timeout,
        ValidationConstants::MIN_TIMEOUT_MS,
        ValidationConstants::MAX_TIMEOUT_MS
    );
}
```

### 2. Recognition Service URL

**Purpose**: Validate and sanitize the base URL for the recognition service endpoint.

| Constant              | Value               | Description                                 |
| --------------------- | ------------------- | ------------------------------------------- |
| `URL_SCHEME_PATTERN`  | `/^(https?:)\/\//i` | RegExp pattern matching http:// or https:// |
| `ALLOWED_URL_SCHEMES` | `['http', 'https']` | List of valid URL schemes                   |

**Validation Logic**:

1. Trim whitespace from input
2. If empty string, allow (URL is optional)
3. Check if URL starts with http:// or https:// using pattern
4. Validate full URL using native URL parsing
5. Return sanitized URL or empty string if invalid

**TypeScript Implementation**:

```typescript
// js/admin/constants/validation.ts
export const URL_VALIDATION = {
  PATTERN: /^(https?:)\/\//i,
  REQUIRED_SCHEMES: ["http", "https"] as const,
} as const;

// js/admin/settings/RecognitionSettingsPanel.tsx
const isValidUrl = (value: string): boolean => {
  const trimmed = value.trim();

  if (trimmed === "") {
    return true; // Empty URL is valid (optional field)
  }

  if (!VALIDATION.URL.PATTERN.test(trimmed)) {
    return false;
  }

  try {
    new URL(trimmed);
    return true;
  } catch {
    return false;
  }
};
```

**PHP Implementation**:

```php
// src/Shared/Constants/ValidationConstants.php
final class ValidationConstants
{
    public const ALLOWED_URL_SCHEMES = ['http', 'https'];
    public const URL_SCHEME_PATTERN = '/^(https?:)\/\//i';
}

// src/Shared/Utils/ValidationHelpers.php
public static function sanitizeUrl(string $url, bool $stripTrailingSlash = false): string
{
    $url = trim($url);

    if ($url === '' || filter_var($url, FILTER_VALIDATE_URL) === false) {
        return '';
    }

    return $stripTrailingSlash ? rtrim($url, '/') : $url;
}
```

## Testing Contract Alignment

### Manual Testing Checklist

When making changes to validation logic, verify alignment by testing these scenarios in both frontend and backend:

**Timeout Validation**:

- [ ] Valid timeout (15000) → accepted
- [ ] Below minimum (500) → clamped to 1000
- [ ] Above maximum (200000) → clamped to 120000
- [ ] Zero or negative (-100) → defaults to 15000
- [ ] Non-numeric ("abc") → defaults to 15000
- [ ] Missing/undefined → defaults to 15000

**URL Validation**:

- [ ] Valid HTTP URL (http://localhost:8000) → accepted
- [ ] Valid HTTPS URL (https://api.example.com) → accepted
- [ ] Empty string → accepted (optional field)
- [ ] Missing scheme (example.com) → rejected
- [ ] Invalid scheme (ftp://example.com) → rejected
- [ ] Malformed URL (http://) → rejected

### Automated Contract Tests

TODO: Add contract tests in Phase 8, Task 8.3 that verify:

1. TypeScript constants match PHP constants
2. Validation logic produces identical results for same inputs
3. Edge cases handled consistently

## Maintenance Guidelines

1. **Never change validation constants independently** - Always update both TypeScript and PHP files in the same commit
2. **Update this contract document** when adding or modifying validation rules
3. **Run both frontend and PHP test suites** after validation changes
4. **Document breaking changes** if validation becomes more strict

## Related Files

**TypeScript**:

- `js/admin/constants/validation.ts` - Validation constants
- `js/admin/settings/RecognitionSettingsPanel.tsx` - Frontend validation usage

**PHP**:

- `src/Shared/Constants/ValidationConstants.php` - Validation constants
- `src/Shared/Utils/ValidationHelpers.php` - Validation helper functions
- `src/Shared/Config/SettingsRepository.php` - Settings validation usage

## Change Log

### 2025-10-18 - Initial Contract

- Created shared validation constants
- Aligned timeout validation (1000-120000ms, default 15000ms)
- Aligned URL scheme validation (http/https only)
- Migrated RecognitionSettingsPanel.tsx to use constants
- Migrated SettingsRepository.php to use constants
