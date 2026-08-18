import React from 'react';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { useWorkbenchFilters } from '../useWorkbenchFilters';

const wrapperForUrl = (url: string) => ({ children }: { children: ReactNode }) => (
  <MemoryRouter initialEntries={[url]}>
    <Routes><Route path="/" element={<>{children}</>} /></Routes>
  </MemoryRouter>
);

describe('rq= double-write in one tick (ReviewQueue.handleFilterClick → onKindChange + onIndexChange)', () => {
  it('kind chip click from default: second setQueueState({index:0}) must not clobber kind', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), { wrapper: wrapperForUrl('/') });
    act(() => {
      // ScanTabContent.handleKindChange
      result.current.setQueueState({ kind: 'assignment', index: 0 });
      // ReviewQueue.handleFilterClick then calls onIndexChange(0) → handleIndexChange
      result.current.setQueueState({ index: 0 });
    });
    expect(result.current.queueState.kind).toBe('assignment');
  });
  it('kind chip click at index 3: kind must survive the same-tick index reset', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), { wrapper: wrapperForUrl('/?rq=all.all.3') });
    act(() => {
      result.current.setQueueState({ kind: 'assignment', index: 0 });
      result.current.setQueueState({ index: 0 });
    });
    expect(result.current.queueState.kind).toBe('assignment');
  });
  it('Clear filters button (onKindChange + onBandChange same tick) clears kind AND band', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), { wrapper: wrapperForUrl('/?rq=assignment.strong.2') });
    act(() => {
      result.current.setQueueState({ kind: 'all', index: 0 });
      result.current.setQueueState({ band: 'all', index: 0 });
    });
    expect(result.current.queueState).toEqual({ kind: 'all', band: 'all', index: 0 });
  });
  it('control: single merged write works', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), { wrapper: wrapperForUrl('/?rq=all.all.3') });
    act(() => { result.current.setQueueState({ kind: 'assignment', index: 0 }); });
    expect(result.current.queueState).toEqual({ kind: 'assignment', band: 'all', index: 0 });
  });
});
