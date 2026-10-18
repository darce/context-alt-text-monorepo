import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ClusterGroup } from '../types';
import { useClusterConfirmDialog } from '../useClusterConfirmDialog';
import { useClusterConfirmSuggestion } from '../useClusterConfirmSuggestion';
import type { SuggestionProvenance } from '../useClusterMatchAction';

const SOURCE = 'source-cluster';
const TARGET = 'target-cluster';
const FACE = 'selected-second-face';
const LABEL = 'Target person';
const SUGGESTION = 'identity-suggestion';
type AssignToCluster = Parameters<typeof useClusterConfirmSuggestion>[0]['mutations']['assignToCluster'];

const member = (identityId: string): ClusterGroup['members'][number] => ({
  identity_id: identityId,
  representative_id: `rep-${identityId}`,
  media_id: 115,
  cluster_id: SOURCE,
  cluster_label: null,
  is_auto_label: false,
  is_pinned: false,
  bbox: { x: 0, y: 0, width: 1, height: 1 },
  confidence: 1,
  similarity: 0.49,
  detected_at: '',
});

const renderConfirm = (accepted: boolean) => {
  const mutations = { isPending: false, merge: vi.fn(), assignToCluster: vi.fn<AssignToCluster>() };
  const requestConfirm = vi.fn().mockResolvedValue(accepted);
  const hook = renderHook(() =>
    useClusterConfirmSuggestion({
      members: [member('first-face'), member(FACE)],
      editableClusterId: SOURCE,
      canEdit: true,
      canSearchForMatch: false,
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
  const confirm = async (suggestionId?: string, provenance?: SuggestionProvenance) => {
    await act(async () => {
      await hook.result.current.handleConfirmSuggestion(TARGET, LABEL, suggestionId, provenance);
    });
  };
  return { mutations, requestConfirm, confirm };
};

describe('explicit identity confirmation scope on an editable cluster', () => {
  it.each([true, false])('requests assign confirmation; accepted=%s', async (accepted) => {
    const { mutations, requestConfirm, confirm } = renderConfirm(accepted);

    await confirm(SUGGESTION, { kind: 'identity', identityId: FACE });

    expect(requestConfirm).toHaveBeenCalledExactlyOnceWith('assign', LABEL);
    expect(mutations.merge).not.toHaveBeenCalled();
    if (accepted) {
      expect(mutations.assignToCluster).toHaveBeenCalledExactlyOnceWith(
        FACE, TARGET, expect.any(AbortSignal), SUGGESTION,
      );
      expect(mutations.assignToCluster.mock.calls[0]?.[2]?.aborted).toBe(false);
    } else {
      expect(mutations.assignToCluster).not.toHaveBeenCalled();
    }
  });

  it('uses the existing assign dialog copy and cancel resolves without writing', async () => {
    const mutations = { isPending: false, merge: vi.fn(), assignToCluster: vi.fn<AssignToCluster>() };
    const { result } = renderHook(() => {
      const dialog = useClusterConfirmDialog();
      const confirm = useClusterConfirmSuggestion({
        members: [member('first-face'), member(FACE)],
        editableClusterId: SOURCE,
        canEdit: true,
        canSearchForMatch: false,
        options: [],
        saveStatus: 'idle',
        mutations,
        requestConfirm: dialog.requestConfirm,
        cancelEditing: vi.fn(),
        setError: vi.fn(),
        queueSaveStatus: vi.fn(),
        resetSaveStatus: vi.fn(),
        saveAbortRef: { current: null },
      });
      return { ...dialog, ...confirm };
    });
    let pending: Promise<void> | undefined;
    act(() => {
      pending = result.current.handleConfirmSuggestion(TARGET, LABEL, SUGGESTION, {
        kind: 'identity', identityId: FACE,
      });
    });

    const copy = result.current.confirmDialogCopy;
    await act(async () => {
      result.current.handleCancel();
      await pending;
    });

    expect(copy).toEqual({
      title: 'Assign identity',
      description: `Assign this identity to "${LABEL}"?`,
      confirmLabel: 'Assign',
    });
    expect(result.current.confirmDialog).toBeNull();
    expect(mutations.merge).not.toHaveBeenCalled();
    expect(mutations.assignToCluster).not.toHaveBeenCalled();
  });
});

describe('existing whole-cluster confirmation controls', () => {
  it.each([true, false])('preserves genuine cluster_merge confirmation and atomicity; accepted=%s', async (accepted) => {
    const { mutations, requestConfirm, confirm } = renderConfirm(accepted);

    await confirm('merge-suggestion', { kind: 'cluster_merge' });

    expect(requestConfirm).toHaveBeenCalledExactlyOnceWith('merge', LABEL);
    expect(mutations.assignToCluster).not.toHaveBeenCalled();
    if (accepted) {
      expect(mutations.merge).toHaveBeenCalledExactlyOnceWith(
        TARGET, LABEL, expect.any(AbortSignal), 'merge-suggestion',
      );
    } else {
      expect(mutations.merge).not.toHaveBeenCalled();
    }
  });

  it.each([true, false])('preserves manual legacy merge confirmation; accepted=%s', async (accepted) => {
    const { mutations, requestConfirm, confirm } = renderConfirm(accepted);

    await confirm();

    expect(requestConfirm).toHaveBeenCalledExactlyOnceWith('merge', LABEL);
    expect(mutations.assignToCluster).not.toHaveBeenCalled();
    if (accepted) {
      expect(mutations.merge).toHaveBeenCalledExactlyOnceWith(TARGET, LABEL, expect.any(AbortSignal), undefined);
    } else {
      expect(mutations.merge).not.toHaveBeenCalled();
    }
  });
});
