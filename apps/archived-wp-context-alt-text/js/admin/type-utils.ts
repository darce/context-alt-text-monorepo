/**
 * Type utility functions
 *
 * Common type guards and type checking utilities.
 */

/**
 * Type guard to check if a value is a non-null object (Record).
 *
 * @param value - The value to check
 * @returns True if the value is a non-null object
 */
export const isRecord = (value: unknown): value is Record<string, unknown> => {
    return value !== null && typeof value === "object";
};
