import type { ChangeEvent } from 'react';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import {
  MemoryRouter,
  Route,
  Routes,
  UNSAFE_createMemoryHistory as createMemoryHistory,
  unstable_HistoryRouter as HistoryRouter,
} from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { useWorkbenchFilters } from '../useWorkbenchFilters';

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

/** Observable memory history — index is the discriminating replace-vs-push signal. */
const wrapperWithHistory =
  (history: ReturnType<typeof createMemoryHistory>) =>
  ({ children }: { children: ReactNode }) => (
    <HistoryRouter history={history}>
      <Routes>
        <Route path="/" element={<>{children}</>} />
      </Routes>
    </HistoryRouter>
  );

describe('useWorkbenchFilters', () => {
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
    expect(result.current.getQueueState()).toEqual({ kind: 'all', band: 'all', index: 0 });
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

  it('setQueueState merges into rq without dropping other params', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), {
      wrapper: wrapperForUrl('/?s=face&p=2&rq=all.all.1'),
    });

    act(() => {
      result.current.setQueueState({ kind: 'merge', index: 4 });
    });

    expect(result.current.queueState).toEqual({ kind: 'merge', band: 'all', index: 4 });
    expect(result.current.searchQuery).toBe('face');
    expect(result.current.currentPage).toBe(2);
  });

  // E21-10 Slice 3 — media=expanded codec via useWorkbenchFilters
  it('defaults mediaExpanded to false when media param is absent', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), { wrapper });
    expect(result.current.mediaExpanded).toBe(false);
  });

  it('hydrates mediaExpanded=true from media=expanded', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), {
      wrapper: wrapperForUrl('/?media=expanded'),
    });
    expect(result.current.mediaExpanded).toBe(true);
  });

  it('falls back to mediaExpanded=false for unknown media values', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), {
      wrapper: wrapperForUrl('/?media=garbage'),
    });
    expect(result.current.mediaExpanded).toBe(false);
  });

  it('setMediaExpanded writes and clears the media param without dropping siblings', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), {
      wrapper: wrapperForUrl('/?s=face&p=2'),
    });

    act(() => {
      result.current.setMediaExpanded(true);
    });
    expect(result.current.mediaExpanded).toBe(true);
    expect(result.current.searchQuery).toBe('face');
    expect(result.current.currentPage).toBe(2);

    act(() => {
      result.current.setMediaExpanded(false);
    });
    expect(result.current.mediaExpanded).toBe(false);
    expect(result.current.searchQuery).toBe('face');
  });

  it('setMediaExpanded uses replace-writes (history index unchanged after N toggles)', () => {
    // MemoryRouter + window.history is vacuous (RR does not mutate the real history
    // stack). Pin replace semantics on an observable createMemoryHistory index.
    const history = createMemoryHistory({ initialEntries: ['/'] });
    // Seed one push so a mistaken {replace:false} would advance index past this baseline.
    history.push('/?s=face');
    const startIndex = history.index;
    expect(startIndex).toBe(1);

    const { result } = renderHook(() => useWorkbenchFilters(), {
      wrapper: wrapperWithHistory(history),
    });

    // Separate acts so each setSearchParams functional update reads the latest location.
    act(() => {
      result.current.setMediaExpanded(true);
    });
    act(() => {
      result.current.setMediaExpanded(false);
    });
    act(() => {
      result.current.setMediaExpanded(true);
    });

    // Discriminating signal: history entry (not renderHook's possibly-stale result).
    expect(history.location.search).toContain('media=expanded');
    expect(history.location.search).toContain('s=face');
    // replace keeps index; push would yield startIndex + 3.
    expect(history.index).toBe(startIndex);
  });
});
