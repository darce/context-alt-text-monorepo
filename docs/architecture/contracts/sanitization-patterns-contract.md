# Sanitization Patterns Contract

This document defines the shared sanitization patterns that MUST be synchronized between the frontend (TypeScript) and backend (PHP) codebases.

## Overview

To ensure consistent data handling and prevent type drift, all primitive type sanitization functions are centralized in dedicated helper files:

- **TypeScript**: `apps/wp-context-alt-text/js/admin/utils/normalization/primitives.ts`
- **PHP**: `apps/wp-context-alt-text/src/Shared/Utils/SanitizationHelpers.php`

## Design Principles

1. **Mirror behavior**: TypeScript and PHP functions MUST produce identical results for identical inputs
2. **Predictable nullability**: Functions return `null` when conversion is invalid, not empty strings or zero
3. **Safe type coercion**: Use strict checks to avoid unexpected conversions
4. **WordPress compatibility**: PHP functions use `sanitize_text_field()` for string sanitization

## Sanitization Functions

### 1. toFiniteNumber / toFiniteNumber

**Purpose**: Convert unknown values to finite numbers with a fallback.

**TypeScript Signature**:

```typescript
toFiniteNumber(value: unknown, fallback = 0): number
```

**PHP Signature**:

```php
public static function toFiniteNumber($value, $fallback = 0): int|float
```

**Behavior**:

- If value is numeric and finite → return as number
- If value is non-numeric or infinite/NaN → return fallback
- Default fallback: `0`

**Examples**:

| Input      | TypeScript Output | PHP Output     | Match |
| ---------- | ----------------- | -------------- | ----- |
| `42`       | `42`              | `42`           | ✅    |
| `"3.14"`   | `3.14`            | `3.14`         | ✅    |
| `"abc"`    | `0` (fallback)    | `0` (fallback) | ✅    |
| `null`     | `0` (fallback)    | `0` (fallback) | ✅    |
| `Infinity` | `0` (fallback)    | `0` (fallback) | ✅    |

---

### 2. toNumberOrNull / toNumberOrNull

**Purpose**: Convert unknown values to numbers, returning null for invalid inputs.

**TypeScript Signature**:

```typescript
toNumberOrNull(value: unknown): number | null
```

**PHP Signature**:

```php
public static function toNumberOrNull($value): int|float|null
```

**Behavior**:

- If value is numeric and finite → return as number
- Otherwise → return `null`

**Examples**:

| Input       | TypeScript Output | PHP Output | Match |
| ----------- | ----------------- | ---------- | ----- |
| `100`       | `100`             | `100`      | ✅    |
| `"50.5"`    | `50.5`            | `50.5`     | ✅    |
| `"invalid"` | `null`            | `null`     | ✅    |
| `null`      | `null`            | `null`     | ✅    |
| `undefined` | `null`            | `null`     | ✅    |

---

### 3. toNullableTimestamp / toNullableTimestamp

**Purpose**: Convert unknown values to positive timestamps (Unix time).

**TypeScript Signature**:

```typescript
toNullableTimestamp(value: unknown): number | null
```

**PHP Signature**:

```php
public static function toNullableTimestamp($value): ?int
```

**Behavior**:

- If value is numeric, finite, and > 0 → return as positive number
- Otherwise → return `null`

**Examples**:

| Input        | TypeScript Output | PHP Output   | Match |
| ------------ | ----------------- | ------------ | ----- |
| `1697673600` | `1697673600`      | `1697673600` | ✅    |
| `0`          | `null`            | `null`       | ✅    |
| `-100`       | `null`            | `null`       | ✅    |
| `"abc"`      | `null`            | `null`       | ✅    |

---

### 4. toStringOrNull / toStringOrNull

**Purpose**: Convert unknown values to non-empty strings, returning null for invalid inputs.

**TypeScript Signature**:

```typescript
toStringOrNull(value: unknown): string | null
```

**PHP Signature**:

```php
public static function toStringOrNull($value): ?string
```

**Behavior**:

- If value is string → trim and return (or null if empty after trim)
- If value is number or boolean → convert to string
- If value is null/undefined → return `null`
- PHP uses `sanitize_text_field()` for XSS protection

**Examples**:

| Input         | TypeScript Output | PHP Output | Match                        |
| ------------- | ----------------- | ---------- | ---------------------------- |
| `"hello"`     | `"hello"`         | `"hello"`  | ✅                           |
| `"  world  "` | `"world"`         | `"world"`  | ✅                           |
| `""`          | `null`            | `null`     | ✅                           |
| `"   "`       | `null`            | `null`     | ✅                           |
| `42`          | `"42"`            | `"42"`     | ✅                           |
| `true`        | `"true"`          | `"1"`      | ⚠️ (PHP bool→string differs) |
| `null`        | `null`            | `null`     | ✅                           |

**Note**: PHP converts `true` to `"1"` and `false` to `"0"` when casting to string, while TypeScript converts to `"true"`/`"false"`. This is acceptable as both are non-empty strings.

---

### 5. ensureString / ensureString

**Purpose**: Convert unknown values to strings, never returning null.

**TypeScript Signature**:

```typescript
ensureString(value: unknown): string
```

**PHP Signature**:

```php
public static function ensureString($value): string
```

**Behavior**:

- If value is string → return as-is (trimmed in TS, sanitized in PHP)
- If value is null/undefined → return empty string
- If value is number/boolean → convert to string
- TypeScript handles Date objects → ISO string
- PHP uses `sanitize_text_field()` for XSS protection

**Examples**:

| Input       | TypeScript Output | PHP Output | Match               |
| ----------- | ----------------- | ---------- | ------------------- |
| `"hello"`   | `"hello"`         | `"hello"`  | ✅                  |
| `null`      | `""`              | `""`       | ✅                  |
| `undefined` | `""`              | `""`       | ✅                  |
| `123`       | `"123"`           | `"123"`    | ✅                  |
| `false`     | `"false"`         | `"0"`      | ⚠️ (See note above) |

---

### 6. toBooleanOrNull / toBooleanOrNull

**Purpose**: Convert unknown values to booleans, returning null for ambiguous inputs.

**TypeScript Signature**:

```typescript
toBooleanOrNull(value: unknown): boolean | null
```

**PHP Signature**:

```php
public static function toBooleanOrNull($value): ?bool
```

**Behavior**:

- If value is boolean → return as-is
- If value is null/undefined → return `null`
- If value is number → `true` if non-zero, `false` if zero
- If value is string:
  - `"true"`, `"1"`, `"yes"` → `true`
  - `"false"`, `"0"`, `"no"`, `""` → `false`
  - Other strings → `null` (ambiguous)
- Case-insensitive string matching

**Examples**:

| Input     | TypeScript Output | PHP Output | Match |
| --------- | ----------------- | ---------- | ----- |
| `true`    | `true`            | `true`     | ✅    |
| `false`   | `false`           | `false`    | ✅    |
| `1`       | `true`            | `true`     | ✅    |
| `0`       | `false`           | `false`    | ✅    |
| `"true"`  | `true`            | `true`     | ✅    |
| `"false"` | `false`           | `false`    | ✅    |
| `"yes"`   | `true`            | `true`     | ✅    |
| `"no"`    | `false`           | `false`    | ✅    |
| `"maybe"` | `null`            | `null`     | ✅    |
| `null`    | `null`            | `null`     | ✅    |

---

### 7. toUniqueNumericIds / toUniqueNumericIds

**Purpose**: Convert array of mixed IDs to unique positive numeric IDs.

**TypeScript Signature**:

```typescript
toUniqueNumericIds(ids: (number | string)[]): number[]
```

**PHP Signature**:

```php
public static function toUniqueNumericIds(array $ids): array
```

**Behavior**:

- Convert each value to number
- Filter out non-numeric values
- Filter out zero and negative values
- Remove duplicates
- Return re-indexed array

**Examples**:

| Input             | TypeScript Output | PHP Output  | Match |
| ----------------- | ----------------- | ----------- | ----- |
| `[1, 2, 3]`       | `[1, 2, 3]`       | `[1, 2, 3]` | ✅    |
| `["1", "2", "3"]` | `[1, 2, 3]`       | `[1, 2, 3]` | ✅    |
| `[1, 1, 2, 2]`    | `[1, 2]`          | `[1, 2]`    | ✅    |
| `[1, 0, -5, 2]`   | `[1, 2]`          | `[1, 2]`    | ✅    |
| `[1, "abc", 2]`   | `[1, 2]`          | `[1, 2]`    | ✅    |
| `[]`              | `[]`              | `[]`        | ✅    |

---

## Testing Contract Alignment

### Manual Testing Checklist

When making changes to sanitization logic, verify alignment by testing these scenarios:

**toStringOrNull**:

- [ ] Non-empty string → returns trimmed string
- [ ] Empty string → returns null
- [ ] Whitespace-only string → returns null
- [ ] Number → converts to string
- [ ] null/undefined → returns null

**toNumberOrNull**:

- [ ] Valid number → returns number
- [ ] Numeric string → converts to number
- [ ] Non-numeric string → returns null
- [ ] null/undefined → returns null
- [ ] Infinity/NaN → returns null

**toBooleanOrNull**:

- [ ] Boolean → returns as-is
- [ ] "true"/"1"/"yes" → returns true
- [ ] "false"/"0"/"no" → returns false
- [ ] Ambiguous string → returns null
- [ ] Numbers → 0 is false, non-zero is true

**toUniqueNumericIds**:

- [ ] Numeric array → returns deduplicated
- [ ] String numbers → converts to numbers
- [ ] Filters out zero and negatives
- [ ] Filters out non-numeric values

### Automated Contract Tests

TODO: Add contract tests in Phase 10 that verify:

1. TypeScript and PHP functions produce identical results
2. Edge cases handled consistently
3. Null handling is predictable

## Usage Guidelines

### When to Use Each Function

**toStringOrNull**:

- API response fields that may be empty
- Optional text fields from forms
- When you need to distinguish between "not provided" (null) and "provided but empty" (null after trim)

**ensureString**:

- When you always need a string (never null)
- Display values that should show empty string instead of "null"
- Concatenation where null would cause issues

**toNumberOrNull**:

- API response fields with numeric IDs
- Optional numeric form inputs
- When you need to validate "is this a valid number?"

**toFiniteNumber**:

- Required numeric fields with a fallback
- Calculations where you need a guaranteed number
- Pagination values (e.g., page number defaults to 1)

**toBooleanOrNull**:

- Optional boolean settings
- Three-state toggles (true/false/unset)
- Form checkboxes that may not be submitted

**toUniqueNumericIds**:

- Attachment IDs from API
- User-selected item IDs
- Any list of database IDs that should be unique and positive

## Maintenance Guidelines

1. **Always update both codebases** - Changes to sanitization logic MUST be synchronized
2. **Update this contract** when adding or modifying sanitization functions
3. **Run both test suites** after sanitization changes
4. **Document edge cases** if TypeScript/PHP behavior differs (e.g., boolean→string conversion)
5. **Use sanitize_text_field()** in PHP for all user-provided strings

## Related Files

**TypeScript**:

- `js/admin/utils/normalization/primitives.ts` - Sanitization functions
- `js/admin/utils/normalization/recognition.ts` - Recognition-specific normalization
- `js/admin/utils/normalization/roster.ts` - Roster-specific normalization

**PHP**:

- `src/Shared/Utils/SanitizationHelpers.php` - Sanitization functions
- `src/Shared/Utils/ValidationHelpers.php` - Validation-specific helpers
- `src/Shared/Constants/ValidationConstants.php` - Validation constants

## Change Log

### 2025-10-18 - Initial Contract

- Created SanitizationHelpers.php mirroring primitives.ts
- Implemented 7 core sanitization functions
- Aligned TypeScript/PHP behavior for primitive type coercion
- Documented known differences (boolean→string conversion)
- Deprecated ValidationHelpers::sanitizeBool() in favor of SanitizationHelpers
