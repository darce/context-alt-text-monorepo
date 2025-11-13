import { act, renderHook } from '@testing-library/react';

import { useClusterDragDrop } from '../useClusterDragDrop';

describe('useClusterDragDrop', () => {
  it('tracks drag payload and drop target state', () => {
    const { result } = renderHook(() => useClusterDragDrop());

    expect(result.current.dragPayload).toBeNull();
    expect(result.current.dropTarget).toBeNull();
    expect(result.current.isDragging).toBe(false);

    act(() => result.current.handleFaceDragStart('cluster-a', 'face-1'));
    expect(result.current.dragPayload).toEqual({ fromClusterId: 'cluster-a', faceId: 'face-1' });
    expect(result.current.isDragging).toBe(true);

    act(() => result.current.handleDropTargetChange('cluster-b'));
    expect(result.current.dropTarget).toBe('cluster-b');

    act(() => result.current.handleFaceDragEnd());
    expect(result.current.dragPayload).toBeNull();
    expect(result.current.dropTarget).toBeNull();
  });
});
