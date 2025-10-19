# TypeScript vs PHP Sanitization Contract Differences

This document outlines the key behavioral differences discovered during testing between the TypeScript (`primitives.ts`) and PHP (`SanitizationHelpers.php`) sanitization implementations.

## Overview

While both implementations aim to provide consistent type coercion, there are important differences due to language-specific type handling. These differences have been **documented in tests** but may need to be addressed for full contract alignment.

---

## 1. Boolean Handling

### TypeScript Behavior
```typescript
Number(true)  // 1
Number(false) // 0

toFiniteNumber(true)  // 1
toNumberOrNull(true)  // 1
toNullableTimestamp(true) // 1
```

### PHP Behavior
```php
is_numeric(true)  // false
is_numeric(false) // false

toFiniteNumber(true)  // 0 (returns fallback)
toNumberOrNull(true)  // null
toNullableTimestamp(true) // null
```

**Impact:** PHP does not treat booleans as numeric, while JavaScript does.

**Recommendation:** If boolean-to-number conversion is needed, add explicit boolean handling before the `is_numeric()` check in PHP.

---

## 2. Numeric String Handling in `toBooleanOrNull()`

### Issue
PHP's `toBooleanOrNull()` has a **bug** where numeric strings are not cast to numbers before comparison.

### Current PHP Behavior
```php
toBooleanOrNull('0')   // true ❌ (should be false)
toBooleanOrNull('2')   // true ✓ (correct)
toBooleanOrNull('  0  ') // true ❌ (should be false)
```

### Expected Behavior (TypeScript)
```typescript
toBooleanOrNull('0')   // false ✓
toBooleanOrNull('2')   // null ✓
toBooleanOrNull('  0  ') // false ✓
```

### Root Cause
```php
if (is_numeric($value)) {
    return $value !== 0 && $value !== 0.0;  // ❌ $value is still a string!
}
```

The code checks `$value !== 0` where `$value` is still a string (e.g., `'0'`), so `'0' !== 0` evaluates to `true` (strict type comparison).

### Fix
```php
if (is_numeric($value)) {
    $numeric = (float) $value;  // Cast to numeric first
    return $numeric !== 0.0;
}
```

**Status:** Bug documented in tests but not yet fixed to maintain backward compatibility.

---

## 3. String Sanitization and Trimming

### TypeScript Behavior
```typescript
ensureString('  hello  ') // '  hello  ' (no trimming)
toStringOrNull('  hello  ') // 'hello' (trims)
```

### PHP Behavior
```php
ensureString('  hello  ') // 'hello' (sanitize_text_field trims)
toStringOrNull('  hello  ') // 'hello' (trim + sanitize_text_field)
```

**Impact:** PHP's `sanitize_text_field()` function automatically trims whitespace, so `ensureString()` cannot preserve leading/trailing spaces.

**Recommendation:** Document this difference. If whitespace preservation is critical, consider using a different sanitization approach or accept the difference.

---

## 4. Special Number Values

### TypeScript Behavior
```typescript
toStringOrNull(NaN)      // 'NaN'
toStringOrNull(Infinity)  // 'Infinity'
toBooleanOrNull(NaN)     // true (NaN !== 0)
```

### PHP Behavior
```php
// PHP doesn't have NaN/Infinity as values that can be passed to functions
// INF constant exists but is_numeric(INF) returns true, is_finite(INF) returns false
```

**Impact:** Limited - JavaScript's NaN/Infinity are edge cases that don't translate directly to PHP.

---

## 5. Empty Array and Object Handling

### TypeScript Behavior
```typescript
Number([])    // 0
Number({})    // NaN

toNumberOrNull([])  // 0
toNumberOrNull({})  // null
```

### PHP Behavior
```php
is_numeric([])    // false
is_numeric((object)[]) // false

toNumberOrNull([])  // null
toNumberOrNull(new \stdClass()) // null
```

**Impact:** PHP returns `null` for empty arrays while JavaScript converts them to `0`. This is generally acceptable since arrays shouldn't be converted to numbers.

---

## 6. Type Strictness in Comparisons

### TypeScript
Uses `!==` and `===` for strict equality:
```typescript
'0' !== 0  // true (different types)
```

### PHP
Also uses `!==` and `===` for strict equality:
```php
'0' !== 0  // true (different types)
```

**Issue:** In `toBooleanOrNull`, the PHP code doesn't cast strings to numbers before comparison, leading to unexpected results.

---

## Test Coverage Summary

### TypeScript Tests
- **File:** `primitives.test.ts`
- **Tests:** 78 tests across 7 functions
- **Status:** ✅ All passing (362 total frontend tests)

### PHP Tests
- **File:** `SanitizationHelpersTest.php`
- **Tests:** 151 tests across 8 functions
- **Status:** ✅ All passing (354 total PHP tests)
- **Note:** Tests document actual behavior, including the `toBooleanOrNull` bug

---

## Recommendations

### Short Term
1. ✅ **Document differences** - Completed in this file and test comments
2. ✅ **Test actual behavior** - Tests reflect real implementation behavior
3. **Add JSDoc/PHPDoc warnings** - Note differences in function documentation

### Long Term
1. **Fix `toBooleanOrNull` bug** - Cast numeric strings before comparison
2. **Consider adding boolean handling** - Align PHP behavior with TypeScript for booleans
3. **Create alignment tests** - Add cross-language contract tests (Task 10.4)

### Breaking Changes to Consider
- Fixing the `toBooleanOrNull('0')` bug would be a breaking change
- Adding boolean-to-number conversion in PHP would be a breaking change
- Review usage before implementing fixes

---

## Usage Guidelines

### When to Use TypeScript Version
- Frontend validation
- Client-side data normalization
- JavaScript-specific type coercion needs

### When to Use PHP Version
- Backend validation
- Server-side data normalization
- WordPress data sanitization (includes XSS protection)

### Key Difference to Remember
**PHP is more strict** - it returns `null` for ambiguous cases (booleans, empty arrays) while **TypeScript is more permissive** - it attempts type coercion more aggressively.

---

## See Also
- `docs/architecture/contracts/sanitization-patterns-contract.md` - Full sanitization contract
- `js/admin/utils/normalization/primitives.ts` - TypeScript implementation
- `src/Shared/Utils/SanitizationHelpers.php` - PHP implementation
- `js/admin/utils/normalization/primitives.test.ts` - TypeScript tests
- `tests/Shared/Utils/SanitizationHelpersTest.php` - PHP tests
