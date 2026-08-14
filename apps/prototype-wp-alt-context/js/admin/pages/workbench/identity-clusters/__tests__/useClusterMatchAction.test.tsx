import { renderHook, act } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { namingOptionValue } from '../buildNamingOptions';
import { requiresMergeConfirm, resolveMatchMemberCount, useClusterMatchAction } from '../useClusterMatchAction';

describe('useClusterMatchAction merge confirm (FIX-3)', () => {
  it('resolveMatchMemberCount prefers match.identityCount then options', () => {
    expect(
      resolveMatchMemberCount({ id: 'c1', label: 'Bob', identityCount: 7 }, [
        { value: namingOptionValue('cluster', 'c1'), label: 'Bob', identityCount: 2 },
      ]),
    ).toBe(7);

    expect(
      resolveMatchMemberCount({ id: 'c1', label: 'Bob' }, [
        { value: namingOptionValue('cluster', 'c1'), label: 'Bob', identityCount: 3 },
      ]),
    ).toBe(3);

    expect(resolveMatchMemberCount({ id: 'remote-only', label: 'Bob' }, [])).toBeUndefined();
  });

  it('requires confirm when member count is unknown or ≥5', () => {
    expect(requiresMergeConfirm(undefined)).toBe(true);
    expect(requiresMergeConfirm(5)).toBe(true);
    expect(requiresMergeConfirm(12)).toBe(true);
    expect(requiresMergeConfirm(0)).toBe(false);
    expect(requiresMergeConfirm(4)).toBe(false);
  });

  it('remote-only match with no options entry calls requestConfirm; decline aborts merge', async () => {
    // Predicted first failure: identityCount 0 from missing options → no confirm → merge fires
    const merge = vi.fn();
    const requestConfirm = vi.fn().mockResolvedValue(false);

    const { result } = renderHook(() =>
      useClusterMatchAction({
        members: [
          {
            identity_id: 'id-1',
            representative_id: 'rep-1',
            media_id: 1,
            cluster_id: 'editable',
            cluster_label: 'Src',
            is_auto_label: false,
            is_pinned: false,
            bbox: { x: 0, y: 0, width: 1, height: 1 },
            confidence: 1,
            similarity: 1,
            detected_at: '',
          },
        ],
        editableClusterId: 'editable',
        canSearchForMatch: false,
        options: [],
        mutations: { merge, assignToCluster: vi.fn() },
        requestConfirm,
      }),
    );

    const abortController = new AbortController();
    let started = true;
    await act(async () => {
      started = await result.current.runMatchedAction({ id: 'remote-only', label: 'Big Cluster' }, abortController);
    });

    expect(requestConfirm).toHaveBeenCalledWith('merge', 'Big Cluster');
    expect(started).toBe(false);
    expect(merge).not.toHaveBeenCalled();
  });

  it('remote-only match with identityCount uses real count for threshold', async () => {
    const merge = vi.fn();
    const requestConfirm = vi.fn().mockResolvedValue(true);

    const { result } = renderHook(() =>
      useClusterMatchAction({
        members: [
          {
            identity_id: 'id-1',
            representative_id: 'rep-1',
            media_id: 1,
            cluster_id: 'editable',
            cluster_label: 'Src',
            is_auto_label: false,
            is_pinned: false,
            bbox: { x: 0, y: 0, width: 1, height: 1 },
            confidence: 1,
            similarity: 1,
            detected_at: '',
          },
        ],
        editableClusterId: 'editable',
        canSearchForMatch: false,
        options: [],
        mutations: { merge, assignToCluster: vi.fn() },
        requestConfirm,
      }),
    );

    const abortController = new AbortController();
    await act(async () => {
      await result.current.runMatchedAction({ id: 'remote-big', label: 'Big', identityCount: 12 }, abortController);
    });

    expect(requestConfirm).toHaveBeenCalled();
    expect(merge).toHaveBeenCalledWith('remote-big', 'Big', expect.any(AbortSignal), undefined);
  });

  it('threads match.suggestionId into merge (BR-16 / L1R-01)', async () => {
    // Predicted first failure: merge called without fourth suggestionId arg
    const merge = vi.fn();
    const { result } = renderHook(() =>
      useClusterMatchAction({
        members: [
          {
            identity_id: 'id-1',
            representative_id: 'rep-1',
            media_id: 1,
            cluster_id: 'editable',
            cluster_label: 'Src',
            is_auto_label: false,
            is_pinned: false,
            bbox: { x: 0, y: 0, width: 1, height: 1 },
            confidence: 1,
            similarity: 1,
            detected_at: '',
          },
        ],
        editableClusterId: 'editable',
        canSearchForMatch: false,
        options: [{ value: namingOptionValue('cluster', 'c-small'), label: 'Small', identityCount: 2 }],
        mutations: { merge, assignToCluster: vi.fn() },
        requestConfirm: vi.fn().mockResolvedValue(true),
      }),
    );

    const abortController = new AbortController();
    await act(async () => {
      await result.current.runMatchedAction(
        { id: 'c-small', label: 'Small', suggestionId: 'sug-match-1' },
        abortController,
      );
    });

    expect(merge).toHaveBeenCalledWith('c-small', 'Small', expect.any(AbortSignal), 'sug-match-1');
  });

  it('small known count skips confirm', async () => {
    const merge = vi.fn();
    const requestConfirm = vi.fn().mockResolvedValue(true);

    const { result } = renderHook(() =>
      useClusterMatchAction({
        members: [
          {
            identity_id: 'id-1',
            representative_id: 'rep-1',
            media_id: 1,
            cluster_id: 'editable',
            cluster_label: 'Src',
            is_auto_label: false,
            is_pinned: false,
            bbox: { x: 0, y: 0, width: 1, height: 1 },
            confidence: 1,
            similarity: 1,
            detected_at: '',
          },
        ],
        editableClusterId: 'editable',
        canSearchForMatch: false,
        options: [{ value: namingOptionValue('cluster', 'c-small'), label: 'Small', identityCount: 2 }],
        mutations: { merge, assignToCluster: vi.fn() },
        requestConfirm,
      }),
    );

    const abortController = new AbortController();
    await act(async () => {
      await result.current.runMatchedAction({ id: 'c-small', label: 'Small' }, abortController);
    });

    expect(requestConfirm).not.toHaveBeenCalled();
    expect(merge).toHaveBeenCalledWith('c-small', 'Small', expect.any(AbortSignal), undefined);
  });
});
