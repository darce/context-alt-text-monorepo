import '@testing-library/jest-dom';

class TestResizeObserver {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    callback: ResizeObserverCallback | ((entries: any[]) => void);

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    constructor(callback: ResizeObserverCallback | ((entries: any[]) => void)) {
        this.callback = callback;
    }

    observe(): void {
        // no-op for test environment
    }

    unobserve(): void {
        // no-op for test environment
    }

    disconnect(): void {
        // no-op for test environment
    }
}

if (!globalThis.ResizeObserver) {
    // @ts-expect-error - assign test polyfill
    globalThis.ResizeObserver = TestResizeObserver;
}
