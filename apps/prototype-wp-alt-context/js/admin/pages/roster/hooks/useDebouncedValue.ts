import { useEffect, useState } from 'react';

/**
 * Return `value` only after it has stayed unchanged for `delayMs`.
 * Used so role=status copy can settle while the live query stays immediate.
 *
 * `null` flushes synchronously (no timer) so a status region can drop stale
 * "Showing N matching …" copy the moment the list empties or search clears.
 * Non-null rewrites keep the delay [E21-19-REV1-01].
 */
export const useDebouncedValue = <T,>(value: T, delayMs: number): T => {
  const [debounced, setDebounced] = useState(value);

  if (value === null && debounced !== null) {
    setDebounced(value);
  }

  useEffect(() => {
    if (value === null) {
      return;
    }
    const timer = window.setTimeout(() => {
      setDebounced(value);
    }, delayMs);
    return () => {
      window.clearTimeout(timer);
    };
  }, [value, delayMs]);

  return value === null ? value : debounced;
};
