import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { HTTPError } from '../../../utils/http';
import { createMockMutation, createMockQuery } from '../../../test-utils/mockHooks';
import { RetentionExportResponseError } from '../../../api/recognition/retentionApi';
import {
  buildExportDocument,
  downloadExportPayload,
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
const downloadMutateAsync = vi.fn();

vi.mock('../useRetentionPageMutations', () => ({
  useRetentionPageMutations: () => ({
    updatePolicy: createMockMutation({ mutateAsync: updateMutateAsync }),
    exportMutation: createMockMutation({ mutateAsync: vi.fn() }),
    purgeMutation: createMockMutation({ mutateAsync: vi.fn() }),
    importMutation: createMockMutation({ mutateAsync: importMutateAsync }),
    applyPreset: createMockMutation({ mutateAsync: vi.fn() }),
    downloadJobData: createMockMutation({ mutateAsync: downloadMutateAsync }),
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
    // backend contract (ImportRequest.data -> _validate_collections) counts top-level
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

/* ------------------------------------------------------------------ */
/*  FEBT1-LE-02 — the download resource-release path                   */
/* ------------------------------------------------------------------ */

/** jsdom Blob is not a fetch-compatible body, so read it with FileReader. */
const readBlobAsText = (blob: Blob): Promise<string> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener('load', () => resolve(String(reader.result)));
    reader.addEventListener('error', () => reject(reader.error ?? new Error('blob read failed')));
    reader.readAsText(blob);
  });

describe('downloadExportPayload releases the object URL [FEBT1-LE-02][RES-04][RES-20]', () => {
  const OBJECT_URL = 'blob:https://example.test/abcd-1234';
  const RESPONSE = {
    tenant_id: 'tenant-1',
    exported_at: '2026-01-01T00:00:00+00:00',
    schema_version: 3,
    payload: SNAPSHOT,
    summary: { clusters: 2, media_identities: 1 },
  };

  // jsdom implements neither createObjectURL nor revokeObjectURL, which is why
  // this path had no test at all. Stub the gap rather than leave it unexercised.
  let createObjectURL: ReturnType<typeof vi.fn>;
  let revokeObjectURL: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.clearAllMocks();
    createObjectURL = vi.fn(() => OBJECT_URL);
    revokeObjectURL = vi.fn();
    Object.defineProperty(URL, 'createObjectURL', { value: createObjectURL, configurable: true, writable: true });
    Object.defineProperty(URL, 'revokeObjectURL', { value: revokeObjectURL, configurable: true, writable: true });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('clicks a detached anchor and revokes the object URL on the happy path', async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    downloadExportPayload(RESPONSE);

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith(OBJECT_URL);
    expect(document.querySelectorAll('a[download]')).toHaveLength(0);

    const blob = createObjectURL.mock.calls[0][0] as Blob;
    expect(blob.type).toBe('application/json');
    const written = JSON.parse(await readBlobAsText(blob)) as Record<string, unknown>;
    expect(written.data).toEqual(SNAPSHOT);
    expect(written.counts).toEqual({ clusters: 2, media_identities: 1 });
    expect(written.tenant_id).toBe('tenant-1');
  });

  it('names the anchor with a .json download filename', () => {
    let downloadAttr: string | null = null;
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function click(this: HTMLAnchorElement) {
      downloadAttr = this.getAttribute('download');
    });

    downloadExportPayload(RESPONSE);

    expect(downloadAttr).not.toBeNull();
    expect(String(downloadAttr)).toMatch(/^alt-context-retention-export-.+\.json$/);
  });

  it('revokes the object URL and removes the anchor when click() throws', () => {
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {
      throw new Error('download blocked');
    });

    expect(() => downloadExportPayload(RESPONSE)).toThrow('download blocked');

    // RES-20: the scope that acquired both resources released both, on the path
    // where it gave up — not only on the happy path.
    expect(revokeObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith(OBJECT_URL);
    expect(document.querySelectorAll('a[download]')).toHaveLength(0);
  });

  it('downloadExport surfaces a locally authored message for a malformed response [FEBT1-LG-01]', async () => {
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    downloadMutateAsync.mockRejectedValue(new RetentionExportResponseError('Export data response was malformed.'));

    const { result } = renderHook(() => useRetentionPageState());
    act(() => {
      result.current.dispatch({ type: 'SET_EXPORT_JOB_ID', jobId: 'job-1' });
    });
    await act(async () => {
      await result.current.actions.downloadExport();
    });

    expect(createObjectURL).not.toHaveBeenCalled();
    expect(toastSuccess).not.toHaveBeenCalled();
    expect(toastError).toHaveBeenCalledTimes(1);
    expect(String(toastError.mock.calls[0][0])).toBe(
      'The export data returned by the server was malformed; nothing was downloaded.',
    );
  });

  it('downloadExport writes the file and revokes the URL on success', async () => {
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    downloadMutateAsync.mockResolvedValue(RESPONSE);

    const { result } = renderHook(() => useRetentionPageState());
    act(() => {
      result.current.dispatch({ type: 'SET_EXPORT_JOB_ID', jobId: 'job-1' });
    });
    await act(async () => {
      await result.current.actions.downloadExport();
    });

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledTimes(1);
    expect(toastSuccess).toHaveBeenCalledWith('Tenant export downloaded.');
    expect(toastError).not.toHaveBeenCalled();
  });
});
