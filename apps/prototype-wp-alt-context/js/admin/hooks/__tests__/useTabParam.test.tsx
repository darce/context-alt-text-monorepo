import type { ReactNode } from 'react';
import { act, renderHook } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { useTabParam } from '../useTabParam';

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
});
