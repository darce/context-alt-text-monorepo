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

type ConfirmOpts = Parameters<typeof useClusterConfirmSuggestion>[0];

type ConfirmOverrides = Partial<
  Omit<
    ConfirmOpts,
    | 'mutations'
    | 'cancelEditing'
    | 'queueSaveStatus'
    | 'resetSaveStatus'
    | 'requestConfirm'
    | 'setError'
    | 'saveAbortRef'
  >
> & {
  mutations?: ReturnType<typeof baseMutations>;
  cancelEditing?: ReturnType<typeof vi.fn>;
  queueSaveStatus?: ReturnType<typeof vi.fn>;
  resetSaveStatus?: ReturnType<typeof vi.fn>;
  requestConfirm?: ReturnType<typeof vi.fn>;
  setError?: ReturnType<typeof vi.fn>;
};

const renderConfirm = (overrides: ConfirmOverrides = {}) => {
  const mutations = overrides.mutations ?? baseMutations();
  const cancelEditing = overrides.cancelEditing ?? vi.fn();
  const queueSaveStatus = overrides.queueSaveStatus ?? vi.fn();
  const resetSaveStatus = overrides.resetSaveStatus ?? vi.fn();
  const requestConfirm = overrides.requestConfirm ?? vi.fn().mockResolvedValue(true);
  const setError = overrides.setError ?? vi.fn();
  const saveAbortRef = { current: null as AbortController | null };

  const { result } = renderHook(() =>
    useClusterConfirmSuggestion({
      clusterLabel: overrides.clusterLabel ?? 'bob',
      members: overrides.members ?? [member()],
      editableClusterId: overrides.editableClusterId ?? 'editable',
      canEdit: overrides.canEdit ?? true,
      canSearchForMatch: overrides.canSearchForMatch ?? false,
      options: overrides.options ?? [],
      saveStatus: overrides.saveStatus ?? 'idle',
      mutations,
      requestConfirm: requestConfirm as unknown as ConfirmOpts['requestConfirm'],
      cancelEditing: cancelEditing as unknown as ConfirmOpts['cancelEditing'],
      setError: setError as unknown as ConfirmOpts['setError'],
      queueSaveStatus: queueSaveStatus as unknown as ConfirmOpts['queueSaveStatus'],
      resetSaveStatus: resetSaveStatus as unknown as ConfirmOpts['resetSaveStatus'],
      saveAbortRef,
    }),
  );

  return { result, mutations, cancelEditing, queueSaveStatus, resetSaveStatus, requestConfirm };
};

/**
 * Confirm-path casing (B6 / PR-09): exact compare so case-only confirm applies.
 * Flipped from characterization (TEST-03 → desired). Predicted failures noted (TEST-06).
 */
describe('useClusterConfirmSuggestion casing grid (B6)', () => {
  it('case-only confirm bob→Bob applies merge (exact no-op before runMatchedAction)', async () => {
    // Predicted first failure: cancelEditing; merge not called (case-insensitive bail)
    const { result, mutations, cancelEditing, queueSaveStatus } = renderConfirm({
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

    expect(mutations.merge).toHaveBeenCalledWith('other-bob', 'Bob', expect.any(AbortSignal));
    expect(cancelEditing).not.toHaveBeenCalled();
    expect(queueSaveStatus).toHaveBeenCalled();
  });

  it('exact same confirm Bob→Bob still no-ops without merge', async () => {
    // Predicted first failure: none if exact compare lands; stays green as no-op
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

  it('confirm with a genuinely different label still merges', async () => {
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
