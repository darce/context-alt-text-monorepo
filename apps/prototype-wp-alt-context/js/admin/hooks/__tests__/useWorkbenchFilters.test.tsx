import type { ChangeEvent } from 'react';
import { act, render, renderHook, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter, Route, Routes, useLocation, useSearchParams } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';

import { useOverlayParam } from '../useOverlayParam';
import { usePanesParam } from '../usePanesParam';
import { useTabParam } from '../useTabParam';
import {
  QUEUE_ACTION,
  peekPendingSearchWritesForTests,
  resetPendingSearchWritesForTests,
  seedPendingSearchWritesForTests,
  useWorkbenchFilters,
} from '../useWorkbenchFilters';
import { useWorkbenchNav, WorkbenchNavProvider } from '../../pages/workbench/WorkbenchNavContext';

const wrapper = ({ children }: { children: ReactNode }) => (
  <MemoryRouter initialEntries={['/']}>
    <Routes>
      <Route path="/" element={<>{children}</>} />
    </Routes>
  </MemoryRouter>
);

const wrapperForUrl =
  (url: string) =>
  ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/" element={<>{children}</>} />
      </Routes>
    </MemoryRouter>
  );

describe('useWorkbenchFilters', () => {
  beforeEach(() => {
    resetPendingSearchWritesForTests();
  });

  it('defaults to page 1, empty search, and all status', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), { wrapper });

    expect(result.current.currentPage).toBe(1);
    expect(result.current.searchQuery).toBe('');
    expect(result.current.statusFilter).toBe('all');
    expect(result.current.normalizedSearch).toBe('');
    expect(result.current.perPage).toBe(10);
  });

  it('resets page to 1 when search changes and trims normalized search', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), { wrapper });

    act(() => {
      result.current.setCurrentPage(4);
    });
    expect(result.current.currentPage).toBe(4);

    act(() => {
      result.current.handleSearchChange({
        target: { value: '  face match  ' },
      } as ChangeEvent<HTMLInputElement>);
    });

    expect(result.current.searchQuery).toBe('  face match  ');
    expect(result.current.normalizedSearch).toBe('face match');
    expect(result.current.currentPage).toBe(1);
  });

  it('updates status filter and resets page to 1', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), { wrapper });

    act(() => {
      result.current.setCurrentPage(3);
      result.current.handleStatusChange('missing');
    });

    expect(result.current.statusFilter).toBe('missing');
    expect(result.current.currentPage).toBe(1);
  });

  it('hydrates missing status from the URL', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), { wrapper: wrapperForUrl('/?status=missing') });

    expect(result.current.statusFilter).toBe('missing');
  });

  it('falls back to all status for invalid URL values', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), { wrapper: wrapperForUrl('/?status=garbage') });

    expect(result.current.statusFilter).toBe('all');
  });

  it('hydrates perPage from the URL and resets page when perPage changes', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), { wrapper: wrapperForUrl('/?p=4&perPage=50') });

    expect(result.current.currentPage).toBe(4);
    expect(result.current.perPage).toBe(50);

    act(() => {
      result.current.setPerPage(100);
    });

    expect(result.current.currentPage).toBe(1);
    expect(result.current.perPage).toBe(100);
  });

  it('defaults queue state when rq is omitted', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), { wrapper });

    expect(result.current.queueState).toEqual({ kind: 'all', band: 'all', index: 0 });
  });

  it('parses rq=kind.band.index and falls back on malformed values', () => {
    const { result: ok } = renderHook(() => useWorkbenchFilters(), {
      wrapper: wrapperForUrl('/?rq=assignment.all.3'),
    });
    expect(ok.current.queueState).toEqual({ kind: 'assignment', band: 'all', index: 3 });

    const { result: bad } = renderHook(() => useWorkbenchFilters(), {
      wrapper: wrapperForUrl('/?rq=not-a-valid-value'),
    });
    expect(bad.current.queueState).toEqual({ kind: 'all', band: 'all', index: 0 });
  });

  it('dispatchQueue merges into rq without dropping other params', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), {
      wrapper: wrapperForUrl('/?s=face&p=2&rq=all.all.1'),
    });

    act(() => {
      result.current.dispatchQueue({ type: QUEUE_ACTION.SET_KIND, kind: 'merge' });
      result.current.dispatchQueue({ type: QUEUE_ACTION.SET_INDEX, index: 4 });
    });

    expect(result.current.queueState).toEqual({ kind: 'merge', band: 'all', index: 4 });
    expect(result.current.searchQuery).toBe('face');
    expect(result.current.currentPage).toBe(2);
  });

  it('dispatchQueue set_kind resets index inside the reducer (one write)', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), {
      wrapper: wrapperForUrl('/?rq=all.all.3'),
    });

    act(() => {
      result.current.dispatchQueue({ type: QUEUE_ACTION.SET_KIND, kind: 'assignment' });
    });

    expect(result.current.queueState).toEqual({ kind: 'assignment', band: 'all', index: 0 });
  });

  it('dispatchQueue set_band preserves kind and resets index', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), {
      wrapper: wrapperForUrl('/?rq=assignment.all.2'),
    });

    act(() => {
      result.current.dispatchQueue({ type: QUEUE_ACTION.SET_BAND, band: 'strong' });
    });

    expect(result.current.queueState).toEqual({ kind: 'assignment', band: 'strong', index: 0 });
  });

  it('dispatchQueue set_index preserves kind and band', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), {
      wrapper: wrapperForUrl('/?rq=merge.weaker.0'),
    });

    act(() => {
      result.current.dispatchQueue({ type: QUEUE_ACTION.SET_INDEX, index: 2 });
    });

    expect(result.current.queueState).toEqual({ kind: 'merge', band: 'weaker', index: 2 });
  });

  it('dispatchQueue clamp_index never goes below zero', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), {
      wrapper: wrapperForUrl('/?rq=assignment.all.1'),
    });

    act(() => {
      result.current.dispatchQueue({ type: QUEUE_ACTION.CLAMP_INDEX, index: -4 });
    });

    expect(result.current.queueState).toEqual({ kind: 'assignment', band: 'all', index: 0 });
  });

  it('dispatchQueue clear_filters removes rq from loc.search', () => {
    const Probe = (): React.ReactElement => {
      const { dispatchQueue, queueState } = useWorkbenchFilters();
      const loc = useLocation();
      return (
        <div>
          <button type="button" onClick={() => dispatchQueue({ type: QUEUE_ACTION.CLEAR_FILTERS })}>
            clear
          </button>
          <output data-testid="loc">{loc.search}</output>
          <output data-testid="state">{`${queueState.kind}.${queueState.band}.${queueState.index}`}</output>
        </div>
      );
    };

    render(
      <MemoryRouter initialEntries={['/?rq=assignment.strong.2']}>
        <Routes>
          <Route path="/" element={<Probe />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByTestId('loc').textContent).toContain('rq=');
    act(() => {
      screen.getByText('clear').click();
    });
    expect(screen.getByTestId('state').textContent).toBe('all.all.0');
    expect(screen.getByTestId('loc').textContent ?? '').not.toContain('rq=');
  });

  it('dispatchQueue set_index rejects NaN and negatives without dropping kind', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), {
      wrapper: wrapperForUrl('/?rq=assignment.all.1'),
    });

    act(() => {
      result.current.dispatchQueue({ type: QUEUE_ACTION.SET_INDEX, index: Number.NaN });
    });
    expect(result.current.queueState).toEqual({ kind: 'assignment', band: 'all', index: 0 });

    act(() => {
      result.current.dispatchQueue({ type: QUEUE_ACTION.SET_INDEX, index: 2 });
    });
    act(() => {
      result.current.dispatchQueue({ type: QUEUE_ACTION.SET_INDEX, index: -4 });
    });
    expect(result.current.queueState).toEqual({ kind: 'assignment', band: 'all', index: 0 });
  });

  it('two STEP_INDEX dispatches in one tick advance by 2 (RLSE-06)', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), {
      wrapper: wrapperForUrl('/?rq=assignment.all.0'),
    });

    act(() => {
      result.current.dispatchQueue({ type: QUEUE_ACTION.STEP_INDEX, delta: 1, length: 5 });
      result.current.dispatchQueue({ type: QUEUE_ACTION.STEP_INDEX, delta: 1, length: 5 });
    });

    expect(result.current.queueState).toEqual({ kind: 'assignment', band: 'all', index: 2 });
  });

  it('two dispatchQueue calls in one tick both land (RLSE-06 write-through)', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), {
      wrapper: wrapperForUrl('/?rq=all.all.3'),
    });

    act(() => {
      result.current.dispatchQueue({ type: QUEUE_ACTION.SET_KIND, kind: 'assignment' });
      result.current.dispatchQueue({ type: QUEUE_ACTION.SET_BAND, band: 'strong' });
    });

    expect(result.current.queueState).toEqual({ kind: 'assignment', band: 'strong', index: 0 });
  });

  it('external navigate after a pending rq write is not resurrected by setCurrentPage (R2-02)', () => {
    const Probe = (): React.JSX.Element => {
      const { dispatchQueue, setCurrentPage } = useWorkbenchFilters();
      const [, setSearchParams] = useSearchParams();
      const loc = useLocation();
      return (
        <div>
          <button
            type="button"
            onClick={() => {
              dispatchQueue({ type: QUEUE_ACTION.SET_KIND, kind: 'assignment' });
              setSearchParams(new URLSearchParams('rq=merge.all.0'), { replace: true });
            }}
          >
            race
          </button>
          <button type="button" onClick={() => setCurrentPage(2)}>
            page
          </button>
          <output data-testid="loc">{loc.search}</output>
        </div>
      );
    };

    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<Probe />} />
        </Routes>
      </MemoryRouter>,
    );

    act(() => {
      screen.getByText('race').click();
    });
    act(() => {
      screen.getByText('page').click();
    });
    expect(screen.getByTestId('loc').textContent).toContain('rq=merge.all.0');
    expect(screen.getByTestId('loc').textContent).not.toContain('assignment');
  });

  it('unmounting the last hook instance clears the pending search buffer (R2-02)', () => {
    const { unmount } = renderHook(() => useWorkbenchFilters(), { wrapper });
    seedPendingSearchWritesForTests({
      rq: { kind: 'assignment', band: 'all', index: 0 },
    });
    expect(peekPendingSearchWritesForTests().rq).toEqual({ kind: 'assignment', band: 'all', index: 0 });
    unmount();
    expect(peekPendingSearchWritesForTests()).toEqual({});
  });

  it('useTabParam in the same tick merges pending rq instead of ghosting it (R2-02)', () => {
    const Probe = (): React.JSX.Element => {
      const { dispatchQueue } = useWorkbenchFilters();
      const [, setTab] = useTabParam('tab', 'scan', ['scan'] as const);
      const loc = useLocation();
      return (
        <div>
          <button
            type="button"
            onClick={() => {
              dispatchQueue({ type: QUEUE_ACTION.SET_KIND, kind: 'assignment' });
              setTab('scan');
            }}
          >
            race-tab
          </button>
          <output data-testid="loc">{loc.search}</output>
        </div>
      );
    };

    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<Probe />} />
        </Routes>
      </MemoryRouter>,
    );

    act(() => {
      screen.getByText('race-tab').click();
    });
    expect(screen.getByTestId('loc').textContent).toContain('rq=assignment.all.0');
  });

  it('useOverlayParam in the same tick merges pending rq instead of ghosting it (UXW2-1-R3-04)', () => {
    const Probe = (): React.JSX.Element => {
      const { dispatchQueue } = useWorkbenchFilters();
      const [, setOverlay] = useOverlayParam('panel', ['conflicts'] as const);
      const loc = useLocation();
      return (
        <div>
          <button
            type="button"
            onClick={() => {
              dispatchQueue({ type: QUEUE_ACTION.SET_KIND, kind: 'assignment' });
              setOverlay('conflicts');
            }}
          >
            race-overlay
          </button>
          <output data-testid="loc">{loc.search}</output>
        </div>
      );
    };

    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<Probe />} />
        </Routes>
      </MemoryRouter>,
    );

    act(() => {
      screen.getByText('race-overlay').click();
    });
    expect(screen.getByTestId('loc').textContent).toContain('rq=assignment.all.0');
    expect(screen.getByTestId('loc').textContent).toContain('panel=conflicts');
  });

  it('usePanesParam in the same tick merges pending rq instead of ghosting it (UXW2-1-R3-04)', () => {
    const Probe = (): React.JSX.Element => {
      const { dispatchQueue } = useWorkbenchFilters();
      const [, setPanes] = usePanesParam();
      const loc = useLocation();
      return (
        <div>
          <button
            type="button"
            onClick={() => {
              dispatchQueue({ type: QUEUE_ACTION.SET_KIND, kind: 'assignment' });
              setPanes('control-collapsed');
            }}
          >
            race-panes
          </button>
          <output data-testid="loc">{loc.search}</output>
        </div>
      );
    };

    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<Probe />} />
        </Routes>
      </MemoryRouter>,
    );

    act(() => {
      screen.getByText('race-panes').click();
    });
    expect(screen.getByTestId('loc').textContent).toContain('rq=assignment.all.0');
    expect(screen.getByTestId('loc').textContent).toContain('panes=control-collapsed');
  });

  it('setAdvancedOpen in the same tick merges pending rq instead of ghosting it (UXW2-1-R3-04)', () => {
    window.AltContextAdmin = {
      nonce: 'test-nonce',
      ajaxUrl: '/wp-admin/admin-ajax.php',
      endpoints: {},
    };
    const Probe = (): React.JSX.Element => {
      const { dispatchQueue } = useWorkbenchFilters();
      const { setAdvancedOpen } = useWorkbenchNav();
      const loc = useLocation();
      return (
        <div>
          <button
            type="button"
            onClick={() => {
              dispatchQueue({ type: QUEUE_ACTION.SET_KIND, kind: 'assignment' });
              setAdvancedOpen(true);
            }}
          >
            race-advanced
          </button>
          <output data-testid="loc">{loc.search}</output>
        </div>
      );
    };

    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route
            path="/"
            element={
              <WorkbenchNavProvider>
                <Probe />
              </WorkbenchNavProvider>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    act(() => {
      screen.getByText('race-advanced').click();
    });
    expect(screen.getByTestId('loc').textContent).toContain('rq=assignment.all.0');
    expect(screen.getByTestId('loc').textContent).toContain('advanced=open');
  });
});
