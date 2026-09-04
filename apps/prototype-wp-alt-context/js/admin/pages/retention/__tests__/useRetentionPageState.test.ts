import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { HTTPError } from '../../../utils/http';
import { createMockMutation, createMockQuery } from '../../../test-utils/mockHooks';
import {
  buildExportDocument,
  extractImportSnapshot,
  RetentionImportValidationError,
  useRetentionPageState,
} from '../useRetentionPageState';

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
const importMutateAsync = vi.fn();

vi.mock('../useRetentionPageMutations', () => ({
  useRetentionPageMutations: () => ({
    updatePolicy: createMockMutation({ mutateAsync: updateMutateAsync }),
    exportMutation: createMockMutation({ mutateAsync: vi.fn() }),
    purgeMutation: createMockMutation({ mutateAsync: vi.fn() }),
    importMutation: createMockMutation({ mutateAsync: importMutateAsync }),
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

/* ------------------------------------------------------------------ */
/*  FEBT1G-H-06 — export/import round trip and boundary validation     */
/* ------------------------------------------------------------------ */

const SNAPSHOT = {
  schema_version: 3,
  tenant_id: 'tenant-1',
  exported_at: '2026-01-01T00:00:00+00:00',
  retention_mode: 'retain_all',
  clusters: [{ id: 'cluster-1' }, { id: 'cluster-2' }],
  media_identities: [{ id: 'identity-1' }],
  identity_suggestions: [],
  name_suggestions: [],
  cluster_merge_suggestions: [],
  scan_jobs: [],
};

const exportFile = (document: unknown): File =>
  ({ text: () => Promise.resolve(JSON.stringify(document, null, 2)) }) as unknown as File;

const importDownloadedFile = async (document: unknown) => {
  const { result } = renderHook(() => useRetentionPageState());
  act(() => {
    result.current.dispatch({ type: 'SET_IMPORT_FILE', file: exportFile(document) });
  });
  await act(async () => {
    await result.current.actions.confirmImport();
  });
  return result;
};

describe('retention export/import round trip [FEBT1G-H-06][rg-005]', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('submits the nested snapshot, so the backend counts real collections', async () => {
    const downloaded = buildExportDocument({
      tenant_id: 'tenant-1',
      exported_at: '2026-01-01T00:00:00+00:00',
      schema_version: 3,
      payload: SNAPSHOT,
      summary: { clusters: 2, media_identities: 1 },
    });
    // The envelope wraps the snapshot under `data` and carries `counts`; the
    // backend contract (ImportRequest.data -> _extract_counts) counts top-level
    // collections, so the envelope itself would import as zero of everything.
    expect(Object.keys(downloaded)).toContain('counts');
    expect(downloaded.data).toEqual(SNAPSHOT);

    await importDownloadedFile(downloaded);

    expect(importMutateAsync).toHaveBeenCalledTimes(1);
    const submitted = importMutateAsync.mock.calls[0][0] as { data: Record<string, unknown> };
    expect(submitted.data).toEqual(SNAPSHOT);
    expect(submitted.data.clusters).toHaveLength(2);
    expect(submitted.data.media_identities).toHaveLength(1);
    // Regression pin for the defect: the whole envelope must not be submitted.
    expect(submitted.data.data).toBeUndefined();
    expect(submitted.data.counts).toBeUndefined();
    expect(toastSuccess).toHaveBeenCalledWith('Import completed.');
  });

  it('accepts a bare snapshot that was not wrapped in an envelope', async () => {
    await importDownloadedFile(SNAPSHOT);

    expect(importMutateAsync).toHaveBeenCalledTimes(1);
    expect((importMutateAsync.mock.calls[0][0] as { data: unknown }).data).toEqual(SNAPSHOT);
  });

  it.each([
    ['an array', [SNAPSHOT]],
    ['an arbitrary object', { hello: 'world' }],
    ['an envelope missing schema_version', { counts: {}, data: { clusters: [] } }],
    ['a snapshot with no exported collections', { schema_version: 3, tenant_id: 't' }],
    ['a snapshot whose collection is not an array', { schema_version: 3, clusters: { id: 'c' } }],
  ])('rejects %s before any request is issued', async (_label, document) => {
    await importDownloadedFile(document);

    expect(importMutateAsync).not.toHaveBeenCalled();
    expect(toastError).toHaveBeenCalledTimes(1);
    expect(String(toastError.mock.calls[0][0])).toContain('Invalid export file');
  });

  it('extractImportSnapshot throws the dedicated boundary error type', () => {
    expect(() => extractImportSnapshot([SNAPSHOT])).toThrow(RetentionImportValidationError);
    expect(() => extractImportSnapshot(null)).toThrow(RetentionImportValidationError);
    expect(extractImportSnapshot({ data: SNAPSHOT })).toEqual(SNAPSHOT);
  });
});

describe('array rejection is attributable to a dedicated guard [FEBT1G-H-06]', () => {
  it('names arrays specifically instead of falling through to the schema_version check', () => {
    // A JSON array can never carry a top-level `schema_version`, so without a
    // dedicated guard the array case is only incidentally rejected. Pin the
    // array-specific message so the guard is load-bearing under mutation.
    expect(() => extractImportSnapshot([SNAPSHOT])).toThrow(
      'Invalid export file: expected a JSON object, not an array.',
    );
  });
});
