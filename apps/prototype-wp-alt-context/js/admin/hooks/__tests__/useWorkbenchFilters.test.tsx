import type { ChangeEvent } from 'react';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
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
});
