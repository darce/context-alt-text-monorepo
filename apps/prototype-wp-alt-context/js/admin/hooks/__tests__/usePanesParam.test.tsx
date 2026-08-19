import type { ReactNode } from 'react';
import { act, renderHook } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useSearchParams } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';

import { useOverlayParam } from '../useOverlayParam';
import { usePanesParam } from '../usePanesParam';
import { resetPendingSearchWritesForTests } from '../pendingSearchWrites';

const wrapperForUrl =
  (url: string) =>
  ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/" element={<>{children}</>} />
      </Routes>
    </MemoryRouter>
  );

/** Live search string so setter tests can assert param presence/absence. */
const useSearchString = (): string => {
  const [searchParams] = useSearchParams();
  return searchParams.toString();
};

describe('usePanesParam', () => {
  beforeEach(() => {
    resetPendingSearchWritesForTests();
  });

  it('defaults to both when panes param is absent', () => {
    const { result } = renderHook(() => usePanesParam(), {
      wrapper: wrapperForUrl('/'),
    });
    expect(result.current[0]).toBe('both');
  });

  it('reads control-collapsed from the URL', () => {
    const { result } = renderHook(() => usePanesParam(), {
      wrapper: wrapperForUrl('/?panes=control-collapsed'),
    });
    expect(result.current[0]).toBe('control-collapsed');
  });

  it('falls back to both on garbage values', () => {
    const { result } = renderHook(() => usePanesParam(), {
      wrapper: wrapperForUrl('/?panes=nonsense'),
    });
    expect(result.current[0]).toBe('both');
  });

  it('setter writes collapsed state and clears back to both (param removed)', () => {
    const { result } = renderHook(
      () => {
        const [panes, setPanes] = usePanesParam();
        const search = useSearchString();
        return { panes, setPanes, search };
      },
      { wrapper: wrapperForUrl('/') },
    );

    act(() => {
      result.current.setPanes('library-collapsed');
    });
    expect(result.current.panes).toBe('library-collapsed');
    expect(result.current.search).toContain('panes=library-collapsed');

    act(() => {
      result.current.setPanes('both');
    });
    expect(result.current.panes).toBe('both');
    expect(result.current.search).not.toContain('panes=');
  });

  // [NAV-11] panes and panel restore independently
  it('reads panes while leaving panel untouched; clearing panes keeps panel', () => {
    const { result } = renderHook(
      () => {
        const [panes, setPanes] = usePanesParam();
        const [searchParams] = useSearchParams();
        return {
          panes,
          setPanes,
          panel: searchParams.get('panel'),
          search: searchParams.toString(),
        };
      },
      { wrapper: wrapperForUrl('/?panes=library-collapsed&panel=conflicts') },
    );

    expect(result.current.panes).toBe('library-collapsed');
    expect(result.current.panel).toBe('conflicts');

    act(() => {
      result.current.setPanes('both');
    });

    expect(result.current.panes).toBe('both');
    expect(result.current.panel).toBe('conflicts');
    expect(result.current.search).toContain('panel=conflicts');
    expect(result.current.search).not.toContain('panes=');
  });

  it('panel-only changes do not alter panes [NAV-11]', () => {
    const validPanels = ['conflicts', 'dead-letter'] as const;
    const { result } = renderHook(
      () => {
        const [panes] = usePanesParam();
        const [overlay, setOverlay] = useOverlayParam<(typeof validPanels)[number]>('panel', validPanels);
        const search = useSearchString();
        return { panes, overlay, setOverlay, search };
      },
      { wrapper: wrapperForUrl('/?panes=control-collapsed') },
    );

    expect(result.current.panes).toBe('control-collapsed');

    act(() => {
      result.current.setOverlay('conflicts');
    });

    expect(result.current.panes).toBe('control-collapsed');
    expect(result.current.overlay).toBe('conflicts');
    expect(result.current.search).toContain('panes=control-collapsed');
    expect(result.current.search).toContain('panel=conflicts');
  });

  // [NAV-11] SET branch: collapsed value preserves every non-panes sibling param
  it('setting panes to a collapsed value preserves multi-param siblings [NAV-11]', () => {
    const { result } = renderHook(
      () => {
        const [panes, setPanes] = usePanesParam();
        const [searchParams] = useSearchParams();
        return {
          panes,
          setPanes,
          search: searchParams.toString(),
        };
      },
      {
        wrapper: wrapperForUrl('/?tab=scan&panel=conflicts&status=needs_review'),
      },
    );

    act(() => {
      result.current.setPanes('library-collapsed');
    });

    expect(result.current.panes).toBe('library-collapsed');
    expect(result.current.search).toContain('tab=scan');
    expect(result.current.search).toContain('panel=conflicts');
    expect(result.current.search).toContain('status=needs_review');
    expect(result.current.search).toContain('panes=library-collapsed');
  });
});
