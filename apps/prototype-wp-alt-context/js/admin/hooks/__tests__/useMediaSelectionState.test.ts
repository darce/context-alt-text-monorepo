import { act, renderHook } from '@testing-library/react';

import { useMediaSelectionState } from '../useMediaSelectionState';
import type { WorkbenchMediaItem } from '../useWorkbenchMedia';

const buildItem = (overrides: Partial<WorkbenchMediaItem> = {}): WorkbenchMediaItem => ({
  id: overrides.id ?? 1,
  title: overrides.title ?? 'Sample image',
  altText: overrides.altText ?? null,
  isDecorative: overrides.isDecorative ?? false,
  status: overrides.status ?? 'missing',
  thumbnailUrl: overrides.thumbnailUrl ?? null,
  mimeType: overrides.mimeType ?? 'image/jpeg',
  editUrl: overrides.editUrl ?? '/wp-admin/post.php?post=1&action=edit',
  updatedAt: overrides.updatedAt ?? '2025-01-01T00:00:00Z',
  dimensions: overrides.dimensions ?? { width: 1200, height: 800 },
  tags: overrides.tags ?? [],
});

describe('useMediaSelectionState', () => {
  it('adds and removes individual selections', () => {
    const { result } = renderHook(() => useMediaSelectionState());
    const item = buildItem();

    act(() => {
      result.current.toggleRow(item, true);
    });

    expect(result.current.selection[item.id.toString()]).toBe(true);
    expect(result.current.selectedMedia).toHaveLength(1);

    act(() => {
      result.current.toggleRow(item, false);
    });

    expect(result.current.selection[item.id.toString()]).toBeUndefined();
    expect(result.current.selectedMedia).toHaveLength(0);
  });

  it('toggles entire pages at once', () => {
    const { result } = renderHook(() => useMediaSelectionState());
    const items = [buildItem({ id: 1 }), buildItem({ id: 2 })];

    act(() => {
      result.current.toggleAll(items, true);
    });

    expect(result.current.isPageFullySelected(items)).toBe(true);

    act(() => {
      result.current.toggleAll(items, false);
    });

    expect(result.current.isPageFullySelected(items)).toBe(false);
  });
});
