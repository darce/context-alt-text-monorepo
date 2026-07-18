import { renderHook, act } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ClusterGroup } from '../types';
import { useClusterConfirmSuggestion } from '../useClusterConfirmSuggestion';

const member = (overrides: Partial<ClusterGroup['members'][number]> = {}): ClusterGroup['members'][number] => ({
  identity_id: 'id-1',
  representative_id: 'rep-1',
  media_id: 1,
  cluster_id: 'editable',
  cluster_label: 'bob',
  is_auto_label: false,
  is_pinned: false,
  bbox: { x: 0, y: 0, width: 1, height: 1 },
  confidence: 1,
  similarity: 1,
  detected_at: '',
  ...overrides,
});

const baseMutations = () => ({
  isPending: false,
  merge: vi.fn(),
  assignToCluster: vi.fn(),
});

const renderConfirm = ({
  mutations = baseMutations(),
  cancelEditing = vi.fn(),
  queueSaveStatus = vi.fn(),
  resetSaveStatus = vi.fn(),
  requestConfirm = vi.fn().mockResolvedValue(true),
  setError = vi.fn(),
  ...rest
}: Partial<Parameters<typeof useClusterConfirmSuggestion>[0]> & {
  mutations?: ReturnType<typeof baseMutations>;
  cancelEditing?: ReturnType<typeof vi.fn>;
  queueSaveStatus?: ReturnType<typeof vi.fn>;
  resetSaveStatus?: ReturnType<typeof vi.fn>;
  requestConfirm?: ReturnType<typeof vi.fn>;
  setError?: ReturnType<typeof vi.fn>;
} = {}) => {
  const saveAbortRef = { current: null as AbortController | null };

  const { result } = renderHook(() =>
    useClusterConfirmSuggestion({
      clusterLabel: 'bob',
      members: [member()],
      editableClusterId: 'editable',
      canEdit: true,
      canSearchForMatch: false,
      options: [],
      saveStatus: 'idle',
      mutations,
      requestConfirm,
      cancelEditing,
      setError,
      queueSaveStatus,
      resetSaveStatus,
      saveAbortRef,
      ...rest,
    }),
  );

  return { result, mutations, cancelEditing, queueSaveStatus, resetSaveStatus, requestConfirm };
};

/**
 * Characterization (TEST-03 / B6): pin today's case-insensitive confirm no-op
 * before the exact-compare fix. Slice 2 flips this to apply the suggestion.
 */
describe('useClusterConfirmSuggestion casing characterization (B6 / TEST-03)', () => {
  it('TODAY: case-only confirm bob→Bob bails via cancelEditing without merge', async () => {
    // Actual current: label.toLowerCase() === currentLabel.toLowerCase() → silent no-op
    const { result, mutations, cancelEditing, resetSaveStatus } = renderConfirm({
      clusterLabel: 'bob',
      options: [
        {
          value: 'cluster:other-bob',
          label: 'Bob',
          source: 'cluster',
          group: 'Suggested',
          identityCount: 2,
        },
      ],
    });

    await act(async () => {
      await result.current.handleConfirmSuggestion('other-bob', 'Bob');
    });

    expect(cancelEditing).toHaveBeenCalled();
    expect(resetSaveStatus).toHaveBeenCalled();
    expect(mutations.merge).not.toHaveBeenCalled();
    expect(mutations.assignToCluster).not.toHaveBeenCalled();
  });

  it('TODAY: exact same confirm Bob→Bob also bails without merge', async () => {
    const { result, mutations, cancelEditing } = renderConfirm({
      clusterLabel: 'Bob',
      members: [member({ cluster_label: 'Bob' })],
    });

    await act(async () => {
      await result.current.handleConfirmSuggestion('other-bob', 'Bob');
    });

    expect(cancelEditing).toHaveBeenCalled();
    expect(mutations.merge).not.toHaveBeenCalled();
  });

  it('TODAY: confirm with a genuinely different label still merges', async () => {
    const { result, mutations, cancelEditing } = renderConfirm({
      clusterLabel: 'Alice',
      members: [member({ cluster_label: 'Alice' })],
      options: [
        {
          value: 'cluster:other-bob',
          label: 'Bob',
          source: 'cluster',
          group: 'Suggested',
          identityCount: 2,
        },
      ],
    });

    await act(async () => {
      await result.current.handleConfirmSuggestion('other-bob', 'Bob');
    });

    expect(mutations.merge).toHaveBeenCalledWith('other-bob', 'Bob', expect.any(AbortSignal));
    expect(cancelEditing).not.toHaveBeenCalled();
  });
});
