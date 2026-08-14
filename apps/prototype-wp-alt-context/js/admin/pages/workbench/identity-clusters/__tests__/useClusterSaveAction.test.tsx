import { renderHook, act } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { namingOptionValue } from '../buildNamingOptions';
import type { ClusterGroup } from '../types';
import { useClusterSaveAction } from '../useClusterSaveAction';

const baseMutations = () => ({
  isPending: false,
  merge: vi.fn(),
  assignToCluster: vi.fn(),
  rename: vi.fn(),
  createClusterForIdentity: vi.fn(),
});

const member = (overrides: Partial<ClusterGroup['members'][number]> = {}): ClusterGroup['members'][number] => ({
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
  ...overrides,
});

type SaveOpts = Parameters<typeof useClusterSaveAction>[0];

type SaveActionOverrides = Partial<
  Omit<
    SaveOpts,
    | 'mutations'
    | 'cancelEditing'
    | 'queueSaveStatus'
    | 'resetSaveStatus'
    | 'findClusterByLabel'
    | 'requestConfirm'
    | 'setError'
    | 'saveAbortRef'
  >
> & {
  mutations?: ReturnType<typeof baseMutations>;
  cancelEditing?: ReturnType<typeof vi.fn>;
  queueSaveStatus?: ReturnType<typeof vi.fn>;
  resetSaveStatus?: ReturnType<typeof vi.fn>;
  findClusterByLabel?: ReturnType<typeof vi.fn>;
  requestConfirm?: ReturnType<typeof vi.fn>;
  setError?: ReturnType<typeof vi.fn>;
};

const renderSaveAction = (overrides: SaveActionOverrides = {}) => {
  const mutations = overrides.mutations ?? baseMutations();
  const cancelEditing = overrides.cancelEditing ?? vi.fn();
  const queueSaveStatus = overrides.queueSaveStatus ?? vi.fn();
  const resetSaveStatus = overrides.resetSaveStatus ?? vi.fn();
  const findClusterByLabel = overrides.findClusterByLabel ?? vi.fn().mockResolvedValue(null);
  const requestConfirm = overrides.requestConfirm ?? vi.fn().mockResolvedValue(true);
  const setError = overrides.setError ?? vi.fn();
  const saveAbortRef = { current: null as AbortController | null };

  const { result } = renderHook(() =>
    useClusterSaveAction({
      clusterLabel: overrides.clusterLabel ?? 'Old',
      members: overrides.members ?? [member()],
      editableClusterId: overrides.editableClusterId ?? 'editable',
      anchorIdentityId: overrides.anchorIdentityId,
      canEdit: overrides.canEdit ?? true,
      canSearchForMatch: overrides.canSearchForMatch ?? false,
      labelInput: overrides.labelInput ?? '',
      matchedCluster: overrides.matchedCluster ?? null,
      options: overrides.options ?? [],
      saveStatus: overrides.saveStatus ?? 'idle',
      mutations,
      findClusterByLabel: findClusterByLabel as unknown as SaveOpts['findClusterByLabel'],
      requestConfirm: requestConfirm as unknown as SaveOpts['requestConfirm'],
      cancelEditing: cancelEditing as unknown as SaveOpts['cancelEditing'],
      setError: setError as unknown as SaveOpts['setError'],
      queueSaveStatus: queueSaveStatus as unknown as SaveOpts['queueSaveStatus'],
      resetSaveStatus: resetSaveStatus as unknown as SaveOpts['resetSaveStatus'],
      saveAbortRef,
    }),
  );

  return {
    result,
    mutations,
    cancelEditing,
    queueSaveStatus,
    resetSaveStatus,
    findClusterByLabel,
    setError,
  };
};

describe('useClusterSaveAction person path (FIX-1)', () => {
  it('person+cluster same name: handlePersonSelect renames with canonical casing and never merges', () => {
    // Predicted first failure: handleSave path re-resolves via findClusterByLabel → merge
    const findClusterByLabel = vi.fn().mockResolvedValue({
      id: 'cluster-alice',
      label: 'Alice',
      identityCount: 12,
    });
    const { result, mutations } = renderSaveAction({
      clusterLabel: 'Old',
      labelInput: 'alice',
      findClusterByLabel,
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
    });

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
    const findClusterByLabel = vi.fn().mockResolvedValue({
      id: 'cluster-alice',
      label: 'Alice',
      identityCount: 9,
    });
    const { result, mutations } = renderSaveAction({
      clusterLabel: 'Old',
      labelInput: 'alice',
      findClusterByLabel,
      options: [
        {
          value: namingOptionValue('person', 1),
          label: 'Alice',
          source: 'person',
          group: 'All Labels',
        },
      ],
    });

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mutations.rename).toHaveBeenCalledWith('Alice', expect.any(AbortSignal));
    expect(mutations.merge).not.toHaveBeenCalled();
    expect(findClusterByLabel).not.toHaveBeenCalled();
  });
});

/**
 * Five-case grid (B6): exact dirty check; case-only rename mutates; merge preserved.
 * Flipped from characterization (TEST-03 → desired). Predicted failures noted (TEST-06).
 */
describe('useClusterSaveAction casing grid (B6)', () => {
  it('1. bob→Bob mutates: exact dirty check proceeds to rename and queues save status', async () => {
    // Predicted first failure: cancelEditing called; rename not called (case-insensitive bail)
    const { result, mutations, cancelEditing, queueSaveStatus, findClusterByLabel } = renderSaveAction({
      clusterLabel: 'bob',
      labelInput: 'Bob',
      members: [member({ cluster_label: 'bob' })],
    });

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mutations.rename).toHaveBeenCalledWith('Bob', expect.any(AbortSignal));
    expect(mutations.merge).not.toHaveBeenCalled();
    expect(cancelEditing).not.toHaveBeenCalled();
    expect(queueSaveStatus).toHaveBeenCalled();
    // Null lookup — rename path, not merge
    expect(findClusterByLabel).toHaveBeenCalledWith('Bob', expect.any(AbortSignal));
  });

  it('1b. bob→Bob with self-match from findClusterByLabel still renames (filterEditableClusterMatch)', async () => {
    // UXP-3-BR-41: grid 1 only mocked null; pin self-id filter → rename, not merge/cancel
    const findClusterByLabel = vi.fn().mockResolvedValue({
      id: 'editable',
      label: 'bob',
      identityCount: 1,
    });
    const { result, mutations, cancelEditing, queueSaveStatus } = renderSaveAction({
      clusterLabel: 'bob',
      labelInput: 'Bob',
      members: [member({ cluster_label: 'bob' })],
      findClusterByLabel,
    });

    await act(async () => {
      await result.current.handleSave();
    });

    expect(findClusterByLabel).toHaveBeenCalledWith('Bob', expect.any(AbortSignal));
    expect(mutations.rename).toHaveBeenCalledWith('Bob', expect.any(AbortSignal));
    expect(mutations.merge).not.toHaveBeenCalled();
    expect(cancelEditing).not.toHaveBeenCalled();
    expect(queueSaveStatus).toHaveBeenCalled();
  });

  it('1c. bob→BOB with different exact-duplicate "bob" cluster renames typed casing (not cancel/merge)', async () => {
    // UXP-3-BR-40: post-lookup match.label === currentLabel after self-filter is a remote dupe;
    // case-only edit intent is rename of OUR cluster, never silent cancelEditing.
    const findClusterByLabel = vi.fn().mockResolvedValue({
      id: 'dupe-bob',
      label: 'bob',
      identityCount: 3,
    });
    const { result, mutations, cancelEditing, queueSaveStatus } = renderSaveAction({
      clusterLabel: 'bob',
      labelInput: 'BOB',
      members: [member({ cluster_label: 'bob' })],
      findClusterByLabel,
    });

    await act(async () => {
      await result.current.handleSave();
    });

    expect(findClusterByLabel).toHaveBeenCalledWith('BOB', expect.any(AbortSignal));
    expect(mutations.rename).toHaveBeenCalledWith('BOB', expect.any(AbortSignal));
    expect(mutations.merge).not.toHaveBeenCalled();
    expect(cancelEditing).not.toHaveBeenCalled();
    expect(queueSaveStatus).toHaveBeenCalled();
  });

  it('2. Bob→Bob no-ops: exact same label still cancels without mutation', async () => {
    // Predicted first failure: none expected if exact compare lands; stays green as no-op
    const { result, mutations, cancelEditing, queueSaveStatus } = renderSaveAction({
      clusterLabel: 'Bob',
      labelInput: 'Bob',
      members: [member({ cluster_label: 'Bob' })],
    });

    await act(async () => {
      await result.current.handleSave();
    });

    expect(cancelEditing).toHaveBeenCalled();
    expect(mutations.rename).not.toHaveBeenCalled();
    expect(queueSaveStatus).not.toHaveBeenCalled();
  });

  it('3. bob typed with a different existing Bob cluster routes to merge', async () => {
    // Predicted first failure: none if current≠bob (Alice); regression guard for merge path
    const findClusterByLabel = vi.fn().mockResolvedValue({
      id: 'other-bob',
      label: 'Bob',
      identityCount: 2,
    });
    const { result, mutations, cancelEditing } = renderSaveAction({
      clusterLabel: 'Alice',
      labelInput: 'bob',
      members: [member({ cluster_label: 'Alice' })],
      findClusterByLabel,
    });

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mutations.merge).toHaveBeenCalledWith(
      'other-bob',
      'Bob',
      expect.any(AbortSignal),
      undefined,
    );
    expect(mutations.rename).not.toHaveBeenCalled();
    expect(cancelEditing).not.toHaveBeenCalled();
  });

  it('4. bob→Bob with different Bob cluster merges (post-findClusterByLabel exact, not silent bail)', async () => {
    // Predicted first failure: cancelEditing + no merge when match.label lowercases to current
    // (dirty check already exact; this pins the second case-insensitive bail)
    const findClusterByLabel = vi.fn().mockResolvedValue({
      id: 'other-bob',
      label: 'Bob',
      identityCount: 2,
    });
    const { result, mutations, cancelEditing, queueSaveStatus } = renderSaveAction({
      clusterLabel: 'bob',
      labelInput: 'Bob',
      members: [member({ cluster_label: 'bob' })],
      findClusterByLabel,
    });

    await act(async () => {
      await result.current.handleSave();
    });

    // Different cluster with case-variant label → merge (exact post-bail lets it through)
    expect(mutations.merge).toHaveBeenCalledWith(
      'other-bob',
      'Bob',
      expect.any(AbortSignal),
      undefined,
    );
    expect(mutations.rename).not.toHaveBeenCalled();
    expect(cancelEditing).not.toHaveBeenCalled();
    expect(queueSaveStatus).toHaveBeenCalled();
  });

  it('4b. free-typed suggested label threads suggestionId into merge (L1V-01 → acceptSuggestion)', async () => {
    // Free-type path: findClusterByLabel (options resolver) returns suggestionId; merge must
    // receive the 4th arg so mutationFn can call acceptSuggestion. Predicted first failure:
    // merge(..., undefined) when resolveClusterMatchFromOptions drops suggestion_id.
    const findClusterByLabel = vi.fn().mockResolvedValue({
      id: 'cluster-alice',
      label: 'Alice',
      identityCount: 4,
      suggestionId: 'sug-free-type-1',
    });
    const { result, mutations } = renderSaveAction({
      clusterLabel: 'Old',
      labelInput: 'Alice',
      members: [member({ cluster_label: 'Old' })],
      findClusterByLabel,
    });

    await act(async () => {
      await result.current.handleSave();
    });

    expect(findClusterByLabel).toHaveBeenCalledWith('Alice', expect.any(AbortSignal));
    expect(mutations.merge).toHaveBeenCalledWith(
      'cluster-alice',
      'Alice',
      expect.any(AbortSignal),
      'sug-free-type-1',
    );
    expect(mutations.rename).not.toHaveBeenCalled();
  });

  it('5. handlePersonSelect case-only bob→Bob renames (exact dirty check on person path)', () => {
    // Predicted first failure: cancelEditing; rename not called
    const { result, mutations, cancelEditing, queueSaveStatus } = renderSaveAction({
      clusterLabel: 'bob',
      members: [member({ cluster_label: 'bob' })],
    });

    act(() => {
      result.current.handlePersonSelect('Bob');
    });

    expect(mutations.rename).toHaveBeenCalledWith('Bob', expect.any(AbortSignal));
    expect(cancelEditing).not.toHaveBeenCalled();
    expect(queueSaveStatus).toHaveBeenCalled();
  });

  it('6. free-typed case-only edit no-ops when person canonical already matches current label (UXP-3-BR-43)', async () => {
    // Cluster "bob" + person option "bob"; user types "Bob". Dirty check passes, person path
    // would applyPersonLabel("bob") → rename to the label already held (false "Saved!").
    const { result, mutations, cancelEditing, findClusterByLabel } = renderSaveAction({
      clusterLabel: 'bob',
      labelInput: 'Bob',
      members: [member({ cluster_label: 'bob' })],
      options: [
        {
          value: namingOptionValue('person', 1),
          label: 'bob',
          source: 'person',
          group: 'All Labels',
        },
      ],
    });

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mutations.rename).not.toHaveBeenCalled();
    expect(mutations.merge).not.toHaveBeenCalled();
    expect(mutations.createClusterForIdentity).not.toHaveBeenCalled();
    expect(findClusterByLabel).not.toHaveBeenCalled();
    expect(cancelEditing).toHaveBeenCalled();
  });

  it('7. free-typed person match still renames when person canonical casing differs from current (UXP-3-BR-43)', async () => {
    // Cluster "bob" + person option "Bob"; free-type that passes dirty check ("BOB" / "Bob")
    // must still rename to person casing. Exact "bob" is the dirty-check no-op (test 2).
    const personOption = {
      value: namingOptionValue('person', 1),
      label: 'Bob',
      source: 'person' as const,
      group: 'All Labels',
    };

    for (const labelInput of ['BOB', 'Bob'] as const) {
      const { result, mutations, cancelEditing } = renderSaveAction({
        clusterLabel: 'bob',
        labelInput,
        members: [member({ cluster_label: 'bob' })],
        options: [personOption],
      });

      await act(async () => {
        await result.current.handleSave();
      });

      expect(mutations.rename).toHaveBeenCalledWith('Bob', expect.any(AbortSignal));
      expect(mutations.merge).not.toHaveBeenCalled();
      expect(cancelEditing).not.toHaveBeenCalled();
    }
  });

  it('8. padded person label trims before BR-43 guard (UXP-3-BR-46)', async () => {
    // Person option "Bob " must normalize to "Bob" so cluster "Bob" + typed "bob" no-ops
    // instead of applyPersonLabel("Bob ") → trim → rename("Bob") (false "Saved!").
    const { result, mutations, cancelEditing, findClusterByLabel } = renderSaveAction({
      clusterLabel: 'Bob',
      labelInput: 'bob',
      members: [member({ cluster_label: 'Bob' })],
      options: [
        {
          value: namingOptionValue('person', 1),
          label: 'Bob ',
          source: 'person',
          group: 'All Labels',
        },
      ],
    });

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mutations.rename).not.toHaveBeenCalled();
    expect(mutations.merge).not.toHaveBeenCalled();
    expect(mutations.createClusterForIdentity).not.toHaveBeenCalled();
    expect(findClusterByLabel).not.toHaveBeenCalled();
    expect(cancelEditing).toHaveBeenCalled();
  });
});

const RESERVED_LABEL_MSG =
  'This label format is reserved for automatic cluster IDs. Choose a descriptive name.';

describe('useClusterSaveAction reserved-label gate (BR-49)', () => {
  it('handleSave(cluster-7) rejects reserved machine label without lookup or mutation', async () => {
    const { result, mutations, findClusterByLabel, setError, queueSaveStatus } = renderSaveAction({
      clusterLabel: 'Old',
      labelInput: 'cluster-7',
    });

    await act(async () => {
      await result.current.handleSave('cluster-7');
    });

    expect(setError).toHaveBeenCalledWith(RESERVED_LABEL_MSG);
    expect(findClusterByLabel).not.toHaveBeenCalled();
    expect(mutations.rename).not.toHaveBeenCalled();
    expect(mutations.createClusterForIdentity).not.toHaveBeenCalled();
    expect(mutations.merge).not.toHaveBeenCalled();
    expect(queueSaveStatus).not.toHaveBeenCalled();
  });

  it('handleSave(cluster-auto-1) rejects reserved machine label without lookup or mutation', async () => {
    const { result, mutations, findClusterByLabel, setError, queueSaveStatus } = renderSaveAction({
      clusterLabel: 'Old',
      labelInput: 'cluster-auto-1',
    });

    await act(async () => {
      await result.current.handleSave('cluster-auto-1');
    });

    expect(setError).toHaveBeenCalledWith(RESERVED_LABEL_MSG);
    expect(findClusterByLabel).not.toHaveBeenCalled();
    expect(mutations.rename).not.toHaveBeenCalled();
    expect(mutations.createClusterForIdentity).not.toHaveBeenCalled();
    expect(mutations.merge).not.toHaveBeenCalled();
    expect(queueSaveStatus).not.toHaveBeenCalled();
  });

  it('handleSave(Cluster-Dad) proceeds past the reserved gate on the normal path', async () => {
    const { result, mutations, findClusterByLabel, setError } = renderSaveAction({
      clusterLabel: 'Old',
      labelInput: 'Cluster-Dad',
    });

    await act(async () => {
      await result.current.handleSave('Cluster-Dad');
    });

    expect(setError).not.toHaveBeenCalledWith(RESERVED_LABEL_MSG);
    expect(findClusterByLabel).toHaveBeenCalledWith('Cluster-Dad', expect.any(AbortSignal));
    expect(mutations.rename).toHaveBeenCalledWith('Cluster-Dad', expect.any(AbortSignal));
  });
});

describe('useClusterSaveAction person-confirm reserved-label gate (BR-55)', () => {
  // Tests 1–2: layered reject (gate 1 + sink). Red-proof A removes gate 1 only — these
  // still pass via applyPersonLabel. queueSaveStatus early-bail is asserted separately
  // (gate 1 property; fails under sink-only).
  it('handlePersonSelect(cluster-7) rejects reserved label without rename/create mutation', () => {
    const { result, mutations, setError } = renderSaveAction({
      clusterLabel: 'Old',
    });

    act(() => {
      result.current.handlePersonSelect('cluster-7');
    });

    expect(setError).toHaveBeenCalledWith(RESERVED_LABEL_MSG);
    expect(mutations.rename).not.toHaveBeenCalled();
    expect(mutations.createClusterForIdentity).not.toHaveBeenCalled();
    expect(mutations.merge).not.toHaveBeenCalled();
  });

  it('handlePersonSelect(cluster-auto-1) rejects reserved label without rename/create mutation', () => {
    const { result, mutations, setError } = renderSaveAction({
      clusterLabel: 'Old',
    });

    act(() => {
      result.current.handlePersonSelect('cluster-auto-1');
    });

    expect(setError).toHaveBeenCalledWith(RESERVED_LABEL_MSG);
    expect(mutations.rename).not.toHaveBeenCalled();
    expect(mutations.createClusterForIdentity).not.toHaveBeenCalled();
    expect(mutations.merge).not.toHaveBeenCalled();
  });

  it('handlePersonSelect reserved label short-circuits before queueSaveStatus (gate 1)', () => {
    const { result, queueSaveStatus, setError } = renderSaveAction({
      clusterLabel: 'Old',
    });

    act(() => {
      result.current.handlePersonSelect('cluster-7');
    });

    expect(setError).toHaveBeenCalledWith(RESERVED_LABEL_MSG);
    expect(queueSaveStatus).not.toHaveBeenCalled();
  });

  it('handlePersonSelect(Pat Rivera) proceeds to rename (control)', () => {
    const { result, mutations, setError, queueSaveStatus } = renderSaveAction({
      clusterLabel: 'Old',
    });

    act(() => {
      result.current.handlePersonSelect('Pat Rivera');
    });

    expect(setError).not.toHaveBeenCalledWith(RESERVED_LABEL_MSG);
    expect(mutations.rename).toHaveBeenCalledWith('Pat Rivera', expect.any(AbortSignal));
    expect(queueSaveStatus).toHaveBeenCalled();
  });
});
