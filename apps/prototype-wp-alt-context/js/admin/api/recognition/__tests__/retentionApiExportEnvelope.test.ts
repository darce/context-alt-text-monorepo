import { beforeEach, describe, expect, it, vi } from 'vitest';

import { downloadExportJobData, EXPORT_COLLECTION_KEYS, RetentionExportResponseError } from '../retentionApi';

const fetchRequiredApi = vi.fn();

vi.mock('../../../utils/http', () => ({
  fetchRequiredApi: (...args: unknown[]) => fetchRequiredApi(...args),
}));

vi.mock('../../config', () => ({
  getConfig: () => ({
    nonce: 'test-nonce',
    endpoints: { retentionExport: 'https://example.test/wp-json/acx/v1/retention/export' },
  }),
}));

/**
 * The wire shape of `GET /retention/export/{job_id}/data`: `ExportJob.data_json`
 * verbatim, i.e. the bare snapshot from `TenantExportService.export_tenant_data`.
 * No `data`/`payload` wrapper and no `counts`/`summary` field.
 */
const SNAPSHOT = {
  tenant_id: 'tenant-1',
  retention_mode: 'retain_all',
  exported_at: '2026-01-01T00:00:00+00:00',
  schema_version: 3,
  clusters: [{ id: 'cluster-1' }, { id: 'cluster-2' }],
  media_identities: [{ id: 'identity-1' }],
  identity_suggestions: [],
  name_suggestions: [],
  cluster_merge_suggestions: [],
  scan_jobs: [],
};

describe('downloadExportJobData envelope contract [FEBT1-LG-01][rg-015]', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('accepts the documented bare-snapshot shape and derives counts from it', async () => {
    fetchRequiredApi.mockResolvedValue(SNAPSHOT);

    const result = await downloadExportJobData('job-1');

    expect(result.payload).toEqual(SNAPSHOT);
    expect(result.tenant_id).toBe('tenant-1');
    expect(result.exported_at).toBe('2026-01-01T00:00:00+00:00');
    expect(result.schema_version).toBe(3);
    // Derived from the snapshot's own arrays, not invented from an absent field.
    expect(result.summary).toEqual({
      clusters: 2,
      media_identities: 1,
      identity_suggestions: 0,
      name_suggestions: 0,
      cluster_merge_suggestions: 0,
      scan_jobs: 0,
    });
  });

  it('counts only the collections actually present', async () => {
    fetchRequiredApi.mockResolvedValue({ schema_version: 3, clusters: [{ id: 'c' }] });

    const result = await downloadExportJobData('job-1');

    expect(result.summary).toEqual({ clusters: 1 });
  });

  it.each([
    ['a null response', null],
    ['a string response', 'not-json'],
    ['an array response', [SNAPSHOT]],
    ['a response missing schema_version', { clusters: [] }],
    ['a response with a non-integer schema_version', { schema_version: 3.5, clusters: [] }],
    ['a response with no exported collections', { schema_version: 3, tenant_id: 't' }],
    ['a response whose collection is not an array', { schema_version: 3, clusters: { id: 'c' } }],
    // rg-015: the two wrapper shapes the adapter used to silently accept.
    ['a `data`-wrapped envelope', { schema_version: 3, data: SNAPSHOT, counts: { clusters: 2 } }],
    ['a `payload`-wrapped envelope', { schema_version: 3, payload: SNAPSHOT, summary: { clusters: 2 } }],
  ])('rejects %s with an explicit error', async (_label, response) => {
    fetchRequiredApi.mockResolvedValue(response);

    await expect(downloadExportJobData('job-1')).rejects.toThrow(RetentionExportResponseError);
  });

  it('never returns an empty-but-successful document', async () => {
    fetchRequiredApi.mockResolvedValue({});

    // The pre-fix behaviour returned `{ payload: {}, summary: {} }` here, which
    // the caller happily wrote to disk as a successful, empty export.
    await expect(downloadExportJobData('job-1')).rejects.toThrow('Export data response was malformed');
  });

  it('pins the collection keys shared with the backend import contract [rg-005]', () => {
    expect([...EXPORT_COLLECTION_KEYS]).toEqual([
      'clusters',
      'media_identities',
      'identity_suggestions',
      'name_suggestions',
      'cluster_merge_suggestions',
      'scan_jobs',
    ]);
  });
});
