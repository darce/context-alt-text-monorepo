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

describe('useWorkbenchFilters', () => {
  it('defaults to page 1, empty search, and all status', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), { wrapper });

    expect(result.current.currentPage).toBe(1);
    expect(result.current.searchQuery).toBe('');
    expect(result.current.statusFilter).toBe('all');
    expect(result.current.normalizedSearch).toBe('');
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
});
