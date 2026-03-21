import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi, afterEach } from 'vitest';
import { useLocation } from 'react-router-dom';
import { useScrollRestoration } from '../useScrollRestoration';

vi.mock('react-router-dom', () => ({
  useLocation: vi.fn(),
}));

describe('useScrollRestoration', () => {
  const originalScrollY = window.scrollY;
  const buildLocation = (
    overrides: Partial<ReturnType<typeof useLocation>> = {}
  ): ReturnType<typeof useLocation> =>
    ({
      pathname: '/test-route',
      search: '?tab=scan',
      hash: '',
      state: null,
      key: 'test-key',
      ...overrides,
    }) as ReturnType<typeof useLocation>;

  beforeEach(() => {
    sessionStorage.clear();
    vi.clearAllMocks();

    Object.defineProperty(window, 'scrollY', {
      value: 0,
      writable: true,
    });

    window.scrollTo = vi.fn((...args: unknown[]) => {
      const x = args[0];
      const y = args[1];
      if (typeof x === 'object' && x !== null) {
        window.scrollY = (x as ScrollToOptions).top ?? 0;
      } else {
        window.scrollY = typeof y === 'number' ? y : 0;
      }
    }) as unknown as typeof window.scrollTo;

    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb: FrameRequestCallback) => {
      cb(performance.now());
      return 1;
    });

    vi.mocked(useLocation).mockReturnValue(buildLocation());
  });

  afterEach(() => {
    Object.defineProperty(window, 'scrollY', {
      value: originalScrollY,
      writable: true,
    });
  });

  it('scrolls to top on mount if no saved position exists', () => {
    renderHook(() => useScrollRestoration('my-key'));
    expect(window.scrollTo).toHaveBeenCalledWith(0, 0);
  });

  it('restores scroll position from sessionStorage on mount', () => {
    sessionStorage.setItem('scroll_pos_/test-route?tab=scan_my-key', '450');
    renderHook(() => useScrollRestoration('my-key'));
    // Delay is needed in actual implementation (e.g. useLayoutEffect or setTimeout)
    // to allow paints, but we test the immediate call here based on standard behavior pattern
    expect(window.scrollTo).toHaveBeenCalledWith(0, 450);
  });

  it('saves scroll position on unmount', () => {
    const { unmount } = renderHook(() => useScrollRestoration('my-key'));

    // Simulate scrolling down
    window.scrollY = 300;

    unmount();

    expect(sessionStorage.getItem('scroll_pos_/test-route?tab=scan_my-key')).toBe('300');
  });

  it('updates saved position when the route/key change', () => {
    const { rerender } = renderHook(() => useScrollRestoration('my-key'));

    window.scrollY = 200;

    // Change location simulate
    vi.mocked(useLocation).mockReturnValue(
      buildLocation({
        pathname: '/new-route',
        search: '',
        key: 'test-key-2',
      })
    );

    // Re-render
    rerender();

    // The previous route's scroll should have been saved during the cleanup phase
    expect(sessionStorage.getItem('scroll_pos_/test-route?tab=scan_my-key')).toBe('200');
  });
});
