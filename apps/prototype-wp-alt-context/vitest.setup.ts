import '@testing-library/jest-dom';
import { act, configure } from '@testing-library/react';
import { notifyManager } from '@tanstack/react-query';

notifyManager.setNotifyFunction((fn) => {
  act(fn);
});
notifyManager.setBatchNotifyFunction((fn) => {
  act(fn);
});
notifyManager.setScheduler((fn) => {
  act(fn);
});

configure({
  asyncWrapper: async (callback) => {
    let result: unknown;
    await act(async () => {
      result = await callback();
    });
    return result;
  },
  eventWrapper: (callback) => {
    let result: unknown;
    act(() => {
      result = callback();
    });
    return result;
  },
});

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
  globalThis.ResizeObserver = TestResizeObserver as typeof ResizeObserver;
}

/**
 * Default IntersectionObserver for jsdom: auto-intersect on observe so existing
 * IdentityThumbnail / ClusterDrawerPanel tests that expect canvas crop (or the
 * post-intersect sourceUrl fallback) stay green without per-file stubs.
 * Lazy-crop tests replace this with a controlled observer that does not fire.
 */
class TestIntersectionObserver implements IntersectionObserver {
  readonly root: Element | Document | null = null;
  readonly rootMargin: string = '0px';
  readonly thresholds: ReadonlyArray<number> = [0];
  private readonly callback: IntersectionObserverCallback;

  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback;
  }

  observe(target: Element): void {
    const entry = {
      isIntersecting: true,
      target,
      intersectionRatio: 1,
      time: 0,
      boundingClientRect: target.getBoundingClientRect(),
      intersectionRect: target.getBoundingClientRect(),
      rootBounds: null,
    } as IntersectionObserverEntry;
    this.callback([entry], this);
  }

  unobserve(): void {
    // no-op for test environment
  }

  disconnect(): void {
    // no-op for test environment
  }

  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
}

if (!globalThis.IntersectionObserver) {
  globalThis.IntersectionObserver = TestIntersectionObserver as typeof IntersectionObserver;
}

if (typeof window !== 'undefined') {
  Object.defineProperty(window, 'scrollTo', { value: () => {}, writable: true });
}

// jsdom does not implement Element.prototype.scrollIntoView. cmdk (used by the
// Combobox component) calls it in a layout effect when the highlighted item
// changes, which crashes any test that opens the command list.
if (typeof Element !== 'undefined' && typeof Element.prototype.scrollIntoView !== 'function') {
  Element.prototype.scrollIntoView = function scrollIntoView(): void {
    // no-op for test environment
  };
}
