/**
 * operator115 identity-suggestion routing (c82 FIR115, test-only RED).
 *
 * Native fact: pending IdentitySuggestion 19697519-6950-4743-8305-8105584652f9 belongs to
 * face identity adcde572-ce74-446a-86e7-970865e533d8, which sits in editable cluster
 * 26d1cacb-351d-4e52-a007-f130764ba758, and targets cluster 0a6dbdcb-5191-4f63-9d9f-63f375149ee8.
 * The suggestion id is not in cluster_merge_suggestions, so a merge accept 404s.
 *
 * The real useClusterConfirmSuggestion -> useClusterMatchAction chain is driven. Only the
 * mutation boundary (merge / assignToCluster) is observed, so the routing decision itself is
 * never mocked.
 */

import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ClusterGroup } from '../types';
import type { SaveDialogAction } from '../useClusterConfirmDialog';
import { useClusterConfirmSuggestion } from '../useClusterConfirmSuggestion';
import type { SuggestionProvenance } from '../useClusterMatchAction';

const FACE_IDENTITY_ID = 'adcde572-ce74-446a-86e7-970865e533d8';
const EDITABLE_CLUSTER_ID = '26d1cacb-351d-4e52-a007-f130764ba758';
const TARGET_CLUSTER_ID = '0a6dbdcb-5191-4f63-9d9f-63f375149ee8';
const SUGGESTION_ID = '19697519-6950-4743-8305-8105584652f9';
const TARGET_LABEL = 'Bea Burke';

const member = (identityId: string, clusterId: string | null): ClusterGroup['members'][number] => ({
  identity_id: identityId,
  representative_id: `rep-${identityId}`,
  media_id: 115,
  cluster_id: clusterId,
  cluster_label: null,
  is_auto_label: false,
  is_pinned: false,
  bbox: { x: 0, y: 0, width: 1, height: 1 },
  confidence: 1,
  similarity: 0.49,
  detected_at: '',
});

const renderConfirm = ({
  members,
  editableClusterId,
  canSearchForMatch,
  requestConfirm = vi.fn().mockResolvedValue(true),
}: {
  members: ClusterGroup['members'];
  editableClusterId: string | null;
  canSearchForMatch: boolean;
  requestConfirm?: (action: SaveDialogAction, label: string) => Promise<boolean>;
}) => {
  const mutations = { isPending: false, merge: vi.fn(), assignToCluster: vi.fn() };
  const hook = renderHook(() =>
    useClusterConfirmSuggestion({
      members,
      editableClusterId,
      canEdit: true,
      canSearchForMatch,
      options: [],
      saveStatus: 'idle',
      mutations,
      requestConfirm,
      cancelEditing: vi.fn(),
      setError: vi.fn(),
      queueSaveStatus: vi.fn(),
      resetSaveStatus: vi.fn(),
      saveAbortRef: { current: null },
    }),
  );
  return { ...hook, mutations };
};

const confirmSuggestion = async (
  result: ReturnType<typeof renderConfirm>['result'],
  suggestionId: string | undefined,
  suggestionProvenance?: SuggestionProvenance,
) => {
  await act(async () => {
    await result.current.handleConfirmSuggestion(TARGET_CLUSTER_ID, TARGET_LABEL, suggestionId, suggestionProvenance);
  });
};

describe('operator115 identity suggestion routing (RED, editable cluster)', () => {
  it('routes a pending identity suggestion on an editable cluster to identity assignment, never merge accept', async () => {
    // Predicted first failure: useClusterMatchAction sends every editable-cluster match to
    // mutations.merge with the identity suggestion id, so assignToCluster is never called.
    const { result, mutations } = renderConfirm({
      members: [member(FACE_IDENTITY_ID, EDITABLE_CLUSTER_ID)],
      editableClusterId: EDITABLE_CLUSTER_ID,
      canSearchForMatch: false,
    });

    await confirmSuggestion(result, SUGGESTION_ID, { kind: 'identity', identityId: FACE_IDENTITY_ID });

    // Diagnostic first: on the current tree this prints the wrong merge accept args, which
    // carry the identity suggestion id into the whole-cluster merge path.
    expect(mutations.merge.mock.calls).toEqual([]);
    expect(mutations.assignToCluster).toHaveBeenCalledExactlyOnceWith(
      FACE_IDENTITY_ID,
      TARGET_CLUSTER_ID,
      expect.any(AbortSignal),
      SUGGESTION_ID,
    );
  });
});

describe('operator115 identity suggestion routing (healthy controls)', () => {
  it('keeps a manual whole-cluster merge (no suggestion id) as one atomic merge that assigns no face', async () => {
    // Healthy control: passes on the current tree and must keep passing after the fix.
    const { result, mutations } = renderConfirm({
      members: [member(FACE_IDENTITY_ID, EDITABLE_CLUSTER_ID)],
      editableClusterId: EDITABLE_CLUSTER_ID,
      canSearchForMatch: false,
    });

    await confirmSuggestion(result, undefined);

    expect(mutations.merge).toHaveBeenCalledExactlyOnceWith(
      TARGET_CLUSTER_ID,
      TARGET_LABEL,
      expect.any(AbortSignal),
      undefined,
    );
    expect(mutations.assignToCluster).not.toHaveBeenCalled();
  });

  it('assigns an unassigned single face to the target with the same suggestion tuple', async () => {
    // Healthy control: manual unassigned-face assignment already routes through assignToCluster.
    const { result, mutations } = renderConfirm({
      members: [member(FACE_IDENTITY_ID, null)],
      editableClusterId: null,
      canSearchForMatch: true,
    });

    await confirmSuggestion(result, SUGGESTION_ID);

    expect(mutations.assignToCluster).toHaveBeenCalledExactlyOnceWith(
      FACE_IDENTITY_ID,
      TARGET_CLUSTER_ID,
      expect.any(AbortSignal),
      SUGGESTION_ID,
    );
    expect(mutations.merge).not.toHaveBeenCalled();
  });

  it('commits nothing when the operator declines the confirm for an editable identity suggestion', async () => {
    // Healthy control: the confirm gate is reached before any mutation and blocks it.
    const requestConfirm = vi.fn().mockResolvedValue(false);
    const { result, mutations } = renderConfirm({
      members: [member(FACE_IDENTITY_ID, EDITABLE_CLUSTER_ID)],
      editableClusterId: EDITABLE_CLUSTER_ID,
      canSearchForMatch: false,
      requestConfirm,
    });

    await confirmSuggestion(result, SUGGESTION_ID);

    expect(requestConfirm).toHaveBeenCalledWith('merge', TARGET_LABEL);
    expect(mutations.merge).not.toHaveBeenCalled();
    expect(mutations.assignToCluster).not.toHaveBeenCalled();
  });
});
