import type { ReactNode } from 'react';
import { act, renderHook } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useSearchParams } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';
import { useTabParam } from '../useTabParam';
import {
  queuePendingQueueState,
  resetPendingSearchWritesForTests,
} from '../pendingSearchWrites';

const wrapper = ({ children }: { children: ReactNode }) => (
  <MemoryRouter initialEntries={['/']}>
    <Routes>
      <Route path="/" element={children} />
    </Routes>
  </MemoryRouter>
);

describe('useTabParam', () => {
  const validTabs = ['scan', 'batch', 'confirm'] as const;
  type Tab = (typeof validTabs)[number];

  beforeEach(() => {
    resetPendingSearchWritesForTests();
  });

  it('reads param from URL', () => {
    const { result } = renderHook(() => useTabParam<Tab>('tab', 'scan', validTabs), {
      wrapper: ({ children }) => (
        <MemoryRouter initialEntries={['/?tab=batch']}>
          <Routes>
            <Route path="/" element={children} />
          </Routes>
        </MemoryRouter>
      ),
    });

    expect(result.current[0]).toBe('batch');
  });

  it('defaults when missing or invalid', () => {
    // Missing
    const { result: missingResult } = renderHook(() => useTabParam<Tab>('tab', 'scan', validTabs), {
      wrapper,
    });
    expect(missingResult.current[0]).toBe('scan');

    // Invalid
    const { result: invalidResult } = renderHook(() => useTabParam<Tab>('tab', 'scan', validTabs), {
      wrapper: ({ children }) => (
        <MemoryRouter initialEntries={['/?tab=invalid']}>
          <Routes>
            <Route path="/" element={children} />
          </Routes>
        </MemoryRouter>
      ),
    });
    expect(invalidResult.current[0]).toBe('scan');
  });

  it('sets param on change', () => {
    const { result } = renderHook(() => useTabParam<Tab>('tab', 'scan', validTabs), {
      wrapper,
    });

    act(() => {
      result.current[1]('confirm');
    });

    expect(result.current[0]).toBe('confirm');
  });

  it('UXW2-1-R3-04: setTab merges a queued pending rq into the URL', () => {
    queuePendingQueueState({ kind: 'assignment', band: 'all', index: 0 }, null);

    const { result } = renderHook(
      () => {
        const [, setTab] = useTabParam<Tab>('tab', 'scan', validTabs);
        const [searchParams] = useSearchParams();
        return { setTab, search: searchParams.toString() };
      },
      { wrapper },
    );

    act(() => {
      result.current.setTab('scan');
    });

    expect(result.current.search).toContain('rq=assignment.all.0');
    expect(result.current.search).toContain('tab=scan');
  });
});
