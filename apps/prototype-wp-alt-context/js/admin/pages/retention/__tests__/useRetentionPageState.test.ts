import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { HTTPError } from '../../../utils/http';
import { createMockMutation, createMockQuery } from '../../../test-utils/mockHooks';
import { useRetentionPageState } from '../useRetentionPageState';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

const toastError = vi.fn();
const toastSuccess = vi.fn();

vi.mock('../../../context/ToastContext', () => ({
  useToast: () => ({
    success: toastSuccess,
    error: toastError,
  }),
}));

const updateMutateAsync = vi.fn();

vi.mock('../useRetentionPageMutations', () => ({
  useRetentionPageMutations: () => ({
    updatePolicy: createMockMutation({ mutateAsync: updateMutateAsync }),
    exportMutation: createMockMutation({ mutateAsync: vi.fn() }),
    purgeMutation: createMockMutation({ mutateAsync: vi.fn() }),
    importMutation: createMockMutation({ mutateAsync: vi.fn() }),
    applyPreset: createMockMutation({ mutateAsync: vi.fn() }),
    downloadJobData: createMockMutation({ mutateAsync: vi.fn() }),
  }),
}));

vi.mock('../useRetentionPageQueries', () => ({
  useRetentionPageQueries: () => ({
    retentionQuery: createMockQuery({
      data: {
        available: true,
        policy: {
          retention_mode: 'dispose_after_ack',
          last_export_at: null,
          last_purge_at: null,
          retention_updated_at: null,
        },
        recent_audit_events: [],
      },
    }),
    exportJobStatusQuery: createMockQuery({ data: undefined }),
    auditQuery: createMockQuery({ data: { items: [], total: 0, limit: 20, offset: 0 } }),
  }),
}));

const leakingHttpError = (): HTTPError =>
  new HTTPError({
    status: 500,
    retryAfterSeconds: undefined,
    endpoint: '/wp-json/acx/v1/retention/policy',
    bodyPreview: 'SECRET_BODY_LEAK_XYZ_42',
    message: 'Request to /wp-json/acx/v1/retention/policy failed (500): SECRET_BODY_LEAK_XYZ_42',
  });

describe('useRetentionPageState user-facing errors [O-03][W2-L5]', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('savePolicy toasts the fallback, never HTTPError.message [O-03][TEST-15]', async () => {
    const error = leakingHttpError();
    updateMutateAsync.mockRejectedValue(error);

    const { result } = renderHook(() => useRetentionPageState());
    act(() => {
      result.current.dispatch({ type: 'SET_DRAFT_MODE', mode: 'retain_all' });
    });
    await act(async () => {
      await result.current.actions.savePolicy();
    });

    expect(toastError).toHaveBeenCalledTimes(1);
    expect(toastError).toHaveBeenCalledWith('Unable to update retention policy.');
    expect(String(toastError.mock.calls[0][0])).not.toContain('SECRET_BODY_LEAK_XYZ_42');
    expect(String(toastError.mock.calls[0][0])).not.toBe(error.message);
  });
});
