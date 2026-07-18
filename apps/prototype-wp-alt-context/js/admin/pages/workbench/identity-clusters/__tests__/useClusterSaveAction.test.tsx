import { renderHook, act } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { namingOptionValue } from '../buildNamingOptions';
import { useClusterSaveAction } from '../useClusterSaveAction';

const baseMutations = () => ({
  isPending: false,
  merge: vi.fn(),
  assignToCluster: vi.fn(),
  rename: vi.fn(),
  createClusterForIdentity: vi.fn(),
});

describe('useClusterSaveAction person path (FIX-1)', () => {
  it('person+cluster same name: handlePersonSelect renames with canonical casing and never merges', () => {
    // Predicted first failure: handleSave path re-resolves via findClusterByLabel → merge
    const mutations = baseMutations();
    const findClusterByLabel = vi.fn().mockResolvedValue({
      id: 'cluster-alice',
      label: 'Alice',
      identityCount: 12,
    });
    const saveAbortRef = { current: null as AbortController | null };

    const { result } = renderHook(() =>
      useClusterSaveAction({
        clusterLabel: 'Old',
        members: [
          {
            identity_id: 'id-1',
            representative_id: 'rep-1',
            media_id: 1,
            cluster_id: 'editable',
            cluster_label: 'Old',
            is_auto_label: false,
            is_pinned: false,
            bbox: { x: 0, y: 0, width: 1, height: 1 },
            confidence: 1,
            similarity: 1,
            detected_at: '',
          },
        ],
        editableClusterId: 'editable',
        canEdit: true,
        canSearchForMatch: false,
        labelInput: 'alice',
        matchedCluster: null,
        options: [
          {
            value: namingOptionValue('person', 1),
            label: 'Alice',
            source: 'person',
            group: 'All Labels',
          },
          {
            value: namingOptionValue('cluster', 'cluster-alice'),
            label: 'Alice',
            source: 'cluster',
            group: 'Suggested',
            identityCount: 12,
          },
        ],
        saveStatus: 'idle',
        mutations,
        findClusterByLabel,
        requestConfirm: vi.fn().mockResolvedValue(true),
        cancelEditing: vi.fn(),
        setError: vi.fn(),
        queueSaveStatus: vi.fn(),
        resetSaveStatus: vi.fn(),
        saveAbortRef,
      }),
    );

    act(() => {
      result.current.handlePersonSelect('Alice');
    });

    expect(mutations.rename).toHaveBeenCalledWith('Alice', expect.any(AbortSignal));
    expect(mutations.merge).not.toHaveBeenCalled();
    expect(mutations.assignToCluster).not.toHaveBeenCalled();
    expect(findClusterByLabel).not.toHaveBeenCalled();
  });

  it('free-typed person match prefers rename with canonical person casing (never merge)', async () => {
    // Predicted first failure: findClusterByLabel returns cluster → merge
    const mutations = baseMutations();
    const findClusterByLabel = vi.fn().mockResolvedValue({
      id: 'cluster-alice',
      label: 'Alice',
      identityCount: 9,
    });
    const saveAbortRef = { current: null as AbortController | null };

    const { result } = renderHook(() =>
      useClusterSaveAction({
        clusterLabel: 'Old',
        members: [
          {
            identity_id: 'id-1',
            representative_id: 'rep-1',
            media_id: 1,
            cluster_id: 'editable',
            cluster_label: 'Old',
            is_auto_label: false,
            is_pinned: false,
            bbox: { x: 0, y: 0, width: 1, height: 1 },
            confidence: 1,
            similarity: 1,
            detected_at: '',
          },
        ],
        editableClusterId: 'editable',
        canEdit: true,
        canSearchForMatch: false,
        labelInput: 'alice',
        matchedCluster: null,
        options: [
          {
            value: namingOptionValue('person', 1),
            label: 'Alice',
            source: 'person',
            group: 'All Labels',
          },
        ],
        saveStatus: 'idle',
        mutations,
        findClusterByLabel,
        requestConfirm: vi.fn().mockResolvedValue(true),
        cancelEditing: vi.fn(),
        setError: vi.fn(),
        queueSaveStatus: vi.fn(),
        resetSaveStatus: vi.fn(),
        saveAbortRef,
      }),
    );

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mutations.rename).toHaveBeenCalledWith('Alice', expect.any(AbortSignal));
    expect(mutations.merge).not.toHaveBeenCalled();
    expect(findClusterByLabel).not.toHaveBeenCalled();
  });
});
