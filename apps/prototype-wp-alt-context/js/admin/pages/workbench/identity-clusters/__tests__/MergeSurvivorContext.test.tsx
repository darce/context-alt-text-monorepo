import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it } from 'vitest';

import { MergeSurvivorProvider, useMergeSurvivors } from '../MergeSurvivorContext';

describe('MergeSurvivorContext', () => {
  it('records and resolves a survivor mapping', () => {
    const wrapper = ({ children }: { children: ReactNode }) => (
      <MergeSurvivorProvider>{children}</MergeSurvivorProvider>
    );
    const { result } = renderHook(() => useMergeSurvivors(), { wrapper });

    act(() => {
      result.current.recordMergeSurvivor('retired-1', 'survivor-1');
    });
    expect(result.current.resolveSurvivor('retired-1')).toBe('survivor-1');
    expect(result.current.resolveSurvivor('missing')).toBeNull();
  });

  it('evicts oldest entries beyond cap', () => {
    const wrapper = ({ children }: { children: ReactNode }) => (
      <MergeSurvivorProvider cap={2}>{children}</MergeSurvivorProvider>
    );
    const { result } = renderHook(() => useMergeSurvivors(), { wrapper });

    act(() => {
      result.current.recordMergeSurvivor('r1', 's1');
      result.current.recordMergeSurvivor('r2', 's2');
      result.current.recordMergeSurvivor('r3', 's3');
    });
    expect(result.current.resolveSurvivor('r1')).toBeNull();
    expect(result.current.resolveSurvivor('r2')).toBe('s2');
    expect(result.current.resolveSurvivor('r3')).toBe('s3');
  });

  it('expires entries past TTL', () => {
    let now = 1_000_000;
    const wrapper = ({ children }: { children: ReactNode }) => (
      <MergeSurvivorProvider ttlMs={1_000} now={() => now}>
        {children}
      </MergeSurvivorProvider>
    );
    const { result } = renderHook(() => useMergeSurvivors(), { wrapper });

    act(() => {
      result.current.recordMergeSurvivor('r1', 's1');
    });
    expect(result.current.resolveSurvivor('r1')).toBe('s1');

    now += 1_001;
    expect(result.current.resolveSurvivor('r1')).toBeNull();
  });
});
