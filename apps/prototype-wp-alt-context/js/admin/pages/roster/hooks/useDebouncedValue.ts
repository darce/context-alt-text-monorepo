import { useEffect, useState } from 'react';

/**
 * Return `value` only after it has stayed unchanged for `delayMs`.
 * Used so role=status copy can settle while the live query stays immediate.
 */
export const useDebouncedValue = <T,>(value: T, delayMs: number): T => {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebounced(value);
    }, delayMs);
    return () => {
      window.clearTimeout(timer);
    };
  }, [value, delayMs]);

  return debounced;
};
