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

const renderSaveAction = ({
  mutations = baseMutations(),
  cancelEditing = vi.fn(),
  queueSaveStatus = vi.fn(),
  resetSaveStatus = vi.fn(),
  findClusterByLabel = vi.fn().mockResolvedValue(null),
  requestConfirm = vi.fn().mockResolvedValue(true),
  setError = vi.fn(),
  ...rest
}: Partial<Parameters<typeof useClusterSaveAction>[0]> & {
  mutations?: ReturnType<typeof baseMutations>;
  cancelEditing?: ReturnType<typeof vi.fn>;
  queueSaveStatus?: ReturnType<typeof vi.fn>;
  resetSaveStatus?: ReturnType<typeof vi.fn>;
  findClusterByLabel?: ReturnType<typeof vi.fn>;
  requestConfirm?: ReturnType<typeof vi.fn>;
  setError?: ReturnType<typeof vi.fn>;
} = {}) => {
  const saveAbortRef = { current: null as AbortController | null };

  const { result } = renderHook(() =>
    useClusterSaveAction({
      clusterLabel: 'Old',
      members: [member()],
      editableClusterId: 'editable',
      canEdit: true,
      canSearchForMatch: false,
      labelInput: '',
      matchedCluster: null,
      options: [],
      saveStatus: 'idle',
      mutations,
      findClusterByLabel,
      requestConfirm,
      cancelEditing,
      setError,
      queueSaveStatus,
      resetSaveStatus,
      saveAbortRef,
      ...rest,
    }),
  );

  return { result, mutations, cancelEditing, queueSaveStatus, resetSaveStatus, findClusterByLabel };
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
 * Characterization (TEST-03 / B6): pin today's case-insensitive dirty-check bails
 * before the exact-compare fix. These assert actual current behavior; Slice 2 flips them.
 */
describe('useClusterSaveAction casing characterization (B6 / TEST-03)', () => {
  it('TODAY: case-only rename bob→Bob bails via cancelEditing without rename', async () => {
    // Actual current: dirty check lowercases both sides → silent no-op
    const { result, mutations, cancelEditing, queueSaveStatus, findClusterByLabel } = renderSaveAction({
      clusterLabel: 'bob',
      labelInput: 'Bob',
      members: [member({ cluster_label: 'bob' })],
    });

    await act(async () => {
      await result.current.handleSave();
    });

    expect(cancelEditing).toHaveBeenCalled();
    expect(mutations.rename).not.toHaveBeenCalled();
    expect(mutations.merge).not.toHaveBeenCalled();
    expect(queueSaveStatus).not.toHaveBeenCalled();
    expect(findClusterByLabel).not.toHaveBeenCalled();
  });

  it('TODAY: exact same label Bob→Bob bails via cancelEditing without rename', async () => {
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

  it('TODAY: merge path preserved when typed label differs from current (Alice→bob matching Bob)', async () => {
    // Actual current: dirty check passes; case-insensitive match still merges
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

    expect(mutations.merge).toHaveBeenCalledWith('other-bob', 'Bob', expect.any(AbortSignal));
    expect(mutations.rename).not.toHaveBeenCalled();
    expect(cancelEditing).not.toHaveBeenCalled();
  });

  it('TODAY: handlePersonSelect case-only bob→Bob also bails without rename', () => {
    const { result, mutations, cancelEditing, queueSaveStatus } = renderSaveAction({
      clusterLabel: 'bob',
      members: [member({ cluster_label: 'bob' })],
    });

    act(() => {
      result.current.handlePersonSelect('Bob');
    });

    expect(cancelEditing).toHaveBeenCalled();
    expect(mutations.rename).not.toHaveBeenCalled();
    expect(queueSaveStatus).not.toHaveBeenCalled();
  });
});
