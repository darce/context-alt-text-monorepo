import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as recognitionApi from '../../../../api/recognition';
import {
  getClusterLabelLookupFailedMessage,
  lookupClusterByLabel,
  unwrapClusterLabelLookup,
} from '../clusterLabelLookup';
import { useClusterSaveAction } from '../useClusterSaveAction';

vi.mock('../../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../../api/recognition')>(
    '../../../../api/recognition',
  );
  return { ...actual, listRecognitionClusters: vi.fn() };
});

describe('duplicate label lookup timeout', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('does not rename when the duplicate guard lookup times out', async () => {
    vi.mocked(recognitionApi.listRecognitionClusters).mockRejectedValue(
      new DOMException('The operation timed out.', 'TimeoutError'),
    );

    const mutations = {
      isPending: false,
      merge: vi.fn(),
      assignToCluster: vi.fn(),
      rename: vi.fn(),
      createClusterForIdentity: vi.fn(),
    };
    const setError = vi.fn();
    const findClusterByLabel = async (label: string, signal?: AbortSignal) =>
      unwrapClusterLabelLookup(await lookupClusterByLabel({ label, editableClusterId: 'editable', signal }));

    const { result } = renderHook(() =>
      useClusterSaveAction({
        clusterLabel: 'Old',
        members: [],
        editableClusterId: 'editable',
        canEdit: true,
        canSearchForMatch: false,
        labelInput: 'New',
        matchedCluster: null,
        options: [],
        saveStatus: 'idle',
        mutations,
        findClusterByLabel,
        requestConfirm: vi.fn().mockResolvedValue(true),
        cancelEditing: vi.fn(),
        setError,
        queueSaveStatus: vi.fn(),
        resetSaveStatus: vi.fn(),
        saveAbortRef: { current: null },
      }),
    );

    await act(async () => {
      await result.current.handleSave();
    });

    expect(mutations.rename).not.toHaveBeenCalled();
    expect(mutations.createClusterForIdentity).not.toHaveBeenCalled();
    expect(setError).toHaveBeenCalledWith(getClusterLabelLookupFailedMessage());
  });
});
