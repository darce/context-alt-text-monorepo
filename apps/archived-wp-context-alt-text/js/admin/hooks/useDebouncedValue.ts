import React from "react";

/**
 * Debounces a value by delaying updates until after the specified delay.
 *
 * Useful for throttling expensive operations like API calls or search queries.
 * In test environments (NODE_ENV === "test"), the debounce is bypassed for immediate updates.
 *
 * @template T - The type of value to debounce
 * @param {T} value - The value to debounce
 * @param {number} delay - Delay in milliseconds before updating the debounced value
 * @returns {T} The debounced value
 *
 * @example
 * ```tsx
 * const [searchInput, setSearchInput] = useState("");
 * const debouncedSearch = useDebouncedValue(searchInput, 400);
 *
 * useEffect(() => {
 *   // Only runs 400ms after user stops typing
 *   performSearch(debouncedSearch);
 * }, [debouncedSearch]);
 * ```
 */
export const useDebouncedValue = <T>(value: T, delay: number): T => {
    const [debouncedValue, setDebouncedValue] = React.useState(value);

    React.useEffect(() => {
        // Bypass debounce in test environment for immediate updates
        if (delay <= 0) {
            setDebouncedValue(value);
            return;
        }

        const timer = window.setTimeout(() => {
            setDebouncedValue(value);
        }, delay);

        return () => {
            window.clearTimeout(timer);
        };
    }, [value, delay]);

    return debouncedValue;
};
