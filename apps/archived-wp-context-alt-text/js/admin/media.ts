/**
 * WordPress Media Library utilities
 *
 * Provides type-safe access to the WordPress media library (wp.media).
 */

export interface MediaFrameState {
    get: (key: string) => unknown;
}

export interface MediaFrame {
    on: (event: string, callback: () => void) => void;
    off?: (event: string) => void;
    open: () => void;
    state: () => { get: (key: string) => unknown } | MediaFrameState | undefined;
}

/**
 * Get the WordPress media library factory function if available.
 * Returns undefined if wp.media is not loaded (e.g., in test environment).
 *
 * @returns The wp.media factory function or undefined
 */
export const getWpMedia = (): ((options: Record<string, unknown>) => MediaFrame) | undefined => {
    const root =
        typeof window !== "undefined"
            ? window
            : typeof globalThis !== "undefined"
              ? (globalThis as typeof globalThis & { wp?: { media?: unknown } })
              : undefined;

    const mediaFactory = root?.wp && typeof root.wp === "object" ? (root.wp as { media?: unknown }).media : undefined;

    // Type assertion is safe here because we're checking at runtime
    return typeof mediaFactory === "function"
        ? (mediaFactory as (options: Record<string, unknown>) => MediaFrame)
        : undefined;
};
