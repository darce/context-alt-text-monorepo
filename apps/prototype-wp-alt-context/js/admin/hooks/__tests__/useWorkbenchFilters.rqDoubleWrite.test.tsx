import React from 'react';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';
import { resetPendingSearchWritesForTests } from '../pendingSearchWrites';
import { QUEUE_ACTION, useWorkbenchFilters } from '../useWorkbenchFilters';

const wrapperForUrl = (url: string) => ({ children }: { children: ReactNode }) => (
  <MemoryRouter initialEntries={[url]}>
    <Routes><Route path="/" element={<>{children}</>} /></Routes>
  </MemoryRouter>
);

describe('stray same-tick writes merge against pending state (RLSE-06 defence)', () => {
  beforeEach(() => {
    resetPendingSearchWritesForTests();
  });

  it('kind then index in one tick: second dispatchQueue must not clobber kind', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), { wrapper: wrapperForUrl('/') });
    act(() => {
      result.current.dispatchQueue({ type: QUEUE_ACTION.SET_KIND, kind: 'assignment' });
      result.current.dispatchQueue({ type: QUEUE_ACTION.SET_INDEX, index: 0 });
    });
    expect(result.current.queueState.kind).toBe('assignment');
  });

  it('kind at index 3: kind must survive the same-tick index reset', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), { wrapper: wrapperForUrl('/?rq=all.all.3') });
    act(() => {
      result.current.dispatchQueue({ type: QUEUE_ACTION.SET_KIND, kind: 'assignment' });
      result.current.dispatchQueue({ type: QUEUE_ACTION.SET_INDEX, index: 0 });
    });
    expect(result.current.queueState.kind).toBe('assignment');
  });

  it('clear_filters then stray set_band in the same tick still lands at defaults', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), { wrapper: wrapperForUrl('/?rq=assignment.strong.2') });
    act(() => {
      result.current.dispatchQueue({ type: QUEUE_ACTION.CLEAR_FILTERS });
      result.current.dispatchQueue({ type: QUEUE_ACTION.SET_BAND, band: 'all' });
    });
    expect(result.current.queueState).toEqual({ kind: 'all', band: 'all', index: 0 });
  });

  it('control: single dispatch works', () => {
    const { result } = renderHook(() => useWorkbenchFilters(), { wrapper: wrapperForUrl('/?rq=all.all.3') });
    act(() => { result.current.dispatchQueue({ type: QUEUE_ACTION.SET_KIND, kind: 'assignment' }); });
    expect(result.current.queueState).toEqual({ kind: 'assignment', band: 'all', index: 0 });
  });
});
