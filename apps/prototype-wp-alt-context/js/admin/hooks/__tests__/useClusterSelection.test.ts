import { act, renderHook } from '@testing-library/react';

import { useClusterSelection } from '../useClusterSelection';

describe('useClusterSelection', () => {
  it('toggles ids in and out of selection', () => {
    const { result } = renderHook(() => useClusterSelection());

    expect(result.current.count).toBe(0);
    act(() => {
      result.current.toggle('cluster-1');
    });
    expect(result.current.isSelected('cluster-1')).toBe(true);
    expect(result.current.count).toBe(1);

    act(() => {
      result.current.toggle('cluster-1');
    });
    expect(result.current.isSelected('cluster-1')).toBe(false);
    expect(result.current.count).toBe(0);
  });

  it('adds range selections without dropping existing picks', () => {
    const { result } = renderHook(() => useClusterSelection());

    act(() => {
      result.current.toggle('cluster-1');
      result.current.selectRange(['cluster-2', 'cluster-3']);
    });

    expect(result.current.isSelected('cluster-1')).toBe(true);
    expect(result.current.isSelected('cluster-2')).toBe(true);
    expect(result.current.isSelected('cluster-3')).toBe(true);
    expect(result.current.count).toBe(3);
  });

  it('clears all selected ids', () => {
    const { result } = renderHook(() => useClusterSelection());

    act(() => {
      result.current.selectRange(['cluster-1', 'cluster-2']);
    });
    expect(result.current.count).toBe(2);

    act(() => {
      result.current.clear();
    });

    expect(result.current.count).toBe(0);
    expect(result.current.selectedIds.size).toBe(0);
  });

  it('supports selecting all ids and checking all-selected state', () => {
    const { result } = renderHook(() => useClusterSelection());
    const allIds = ['cluster-1', 'cluster-2', 'cluster-3'];

    expect(result.current.isAllSelected(allIds)).toBe(false);

    act(() => {
      result.current.selectAll(allIds);
    });

    expect(result.current.count).toBe(3);
    expect(result.current.isAllSelected(allIds)).toBe(true);

    act(() => {
      result.current.toggle('cluster-2');
    });

    expect(result.current.isAllSelected(allIds)).toBe(false);
  });

  it('retains only the currently visible ids', () => {
    const { result } = renderHook(() => useClusterSelection());

    act(() => {
      result.current.selectAll(['cluster-1', 'cluster-2', 'cluster-3']);
    });

    act(() => {
      result.current.retainVisible(['cluster-2']);
    });

    expect(Array.from(result.current.selectedIds)).toEqual(['cluster-2']);
    expect(result.current.count).toBe(1);
    expect(result.current.isSelected('cluster-1')).toBe(false);
    expect(result.current.isSelected('cluster-2')).toBe(true);
  });
});
