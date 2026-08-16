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
      members: overrides.members ?? [member()],
      // null is a valid unlabeled-card state — only fall back when the override is omitted.
      editableClusterId:
        overrides.editableClusterId !== undefined ? overrides.editableClusterId : 'editable',
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

    expect(mutations.merge).toHaveBeenCalledWith(
      'other-bob',
      'Bob',
      expect.any(AbortSignal),
      undefined,
    );
    expect(cancelEditing).not.toHaveBeenCalled();
    expect(queueSaveStatus).toHaveBeenCalled();
  });

  it('same-label different-target-id must NOT no-op (BR-42)', async () => {
    // BR-42: bail is cluster-id equality, not label. Bob→other-bob must merge.
    // Predicted first failure (pre-fix label bail): cancelEditing; merge not called
    const { result, mutations, cancelEditing, queueSaveStatus } = renderConfirm({
      editableClusterId: 'editable',
      members: [member({ cluster_label: 'Bob' })],
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

    expect(mutations.merge).toHaveBeenCalledWith(
      'other-bob',
      'Bob',
      expect.any(AbortSignal),
      undefined,
    );
    expect(cancelEditing).not.toHaveBeenCalled();
    expect(queueSaveStatus).toHaveBeenCalled();
  });

  it('confirm of already-editable cluster id still no-ops (BR-42)', async () => {
    const { result, mutations, cancelEditing } = renderConfirm({
      editableClusterId: 'editable',
      members: [member({ cluster_label: 'Bob' })],
    });

    await act(async () => {
      await result.current.handleConfirmSuggestion('editable', 'Bob');
    });

    expect(cancelEditing).toHaveBeenCalled();
    expect(mutations.merge).not.toHaveBeenCalled();
  });

  it('confirm with a genuinely different label still merges', async () => {
    const { result, mutations, cancelEditing } = renderConfirm({
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

    expect(mutations.merge).toHaveBeenCalledWith(
      'other-bob',
      'Bob',
      expect.any(AbortSignal),
      undefined,
    );
    expect(cancelEditing).not.toHaveBeenCalled();
  });

  it('threads suggestionId into merge so confirm resolves the pending row by id (BR-16 / L1R-01)', async () => {
    // Predicted first failure on f54f7c87 production: merge called without suggestionId
    // (handleConfirmSuggestion dropped the third arg → runMatchedAction never carried it).
    const { result, mutations } = renderConfirm({
      editableClusterId: 'editable',
      members: [member()],
      options: [
        {
          value: 'cluster:other-bob',
          label: 'Bob',
          source: 'cluster',
          group: 'Suggested',
          identityCount: 2,
          suggestion_id: 'sug-confirm-1',
        },
      ],
    });

    await act(async () => {
      await result.current.handleConfirmSuggestion('other-bob', 'Bob', 'sug-confirm-1');
    });

    expect(mutations.merge).toHaveBeenCalledWith(
      'other-bob',
      'Bob',
      expect.any(AbortSignal),
      'sug-confirm-1',
    );
  });

  it('threads suggestionId into assignToCluster for unlabeled confirm (BR-16 / L1R-01)', async () => {
    // Predicted first failure: assignToCluster called without the fourth suggestionId arg.
    // Small known count skips requestConfirm so the call is deterministic.
    const assignToCluster = vi.fn();
    const merge = vi.fn();
    const members = [member({ cluster_id: 'unlabeled' })];
    const { result, requestConfirm } = renderConfirm({
      editableClusterId: null,
      canEdit: false,
      canSearchForMatch: true,
      members,
      mutations: { isPending: false, merge, assignToCluster },
      options: [
        {
          value: 'cluster:alice',
          label: 'Alice',
          source: 'cluster',
          group: 'Suggested',
          identityCount: 1,
        },
      ],
    });

    await act(async () => {
      await result.current.handleConfirmSuggestion('alice', 'Alice', 'sug-assign-1');
    });

    expect(requestConfirm).not.toHaveBeenCalled();
    expect(merge).not.toHaveBeenCalled();
    expect(assignToCluster).toHaveBeenCalledTimes(1);
    expect(assignToCluster).toHaveBeenCalledWith(
      members[0].identity_id,
      'alice',
      expect.any(AbortSignal),
      'sug-assign-1',
    );
  });
});
