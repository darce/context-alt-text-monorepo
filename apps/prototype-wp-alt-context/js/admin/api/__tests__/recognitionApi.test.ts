import { beforeEach, describe, expect, expectTypeOf, it, vi } from 'vitest';

import * as httpModule from '../../utils/http';
import {
  fetchPendingMergeSuggestions,
  fetchPendingNameSuggestions,
  fetchPendingSuggestions,
  fetchMediaIdentities,
  fetchClusterMembers,
  fetchRetentionStatus,
  fetchSyncStatus,
  fetchTopUnlabeledClusters,
  getRecognitionCluster,
  listRecognitionClusters,
  mergeCluster,
  purgeTenantData,
  pinRepresentative,
  revertMergeCluster,
  cancelScanJob,
  downloadExportJobData,
  exportTenantData,
  scanFaces,
  triggerSync,
  updateRetentionPolicy,
  updateClusterLabel,
  acceptMergeSuggestion,
  EXPORT_COLLECTION_KEYS,
  RetentionExportResponseError,
  type AcceptedMergeSuggestion,
  type AcceptMergeSuggestionRequest,
  type BulkAcceptRequest,
  type BulkAcceptResponse,
  type PendingNameSuggestion,
  type RetentionExportResponse,
} from '../recognition';
import { DATA_SOURCE, PROJECTION_STATUS } from '../recognition/types';

const mockConfig = {
  nonce: 'nonce-123',
  ajaxUrl: '/wp-admin/admin-ajax.php',
  endpoints: {
    retentionPolicy: 'https://example.com/retentionPolicy',
    retentionExport: 'https://example.com/retentionExport',
    retentionPurge: 'https://example.com/retentionPurge',
  } as Record<string, string>,
  devMode: false,
};

vi.mock('../config', () => ({
  getEndpoint: vi.fn((...keys: string[]) => {
    const configuredKey = keys.find((key) => mockConfig.endpoints[key]);
    return configuredKey ? mockConfig.endpoints[configuredKey] : `https://example.com/${keys[0] ?? 'default'}`;
  }),
  getConfig: vi.fn(() => mockConfig),
  isDevMode: vi.fn(() => false),
}));

vi.mock('../../utils/http', () => {
  const requestMock = vi.fn();
  return {
    fetchApi: requestMock,
    fetchRequiredApi: requestMock,
    stripTrailingSlash: (value: string) => (value.endsWith('/') ? value.slice(0, -1) : value),
  };
});

describe('recognitionApi', () => {
  const fetchApiMock = vi.mocked(httpModule.fetchRequiredApi);

  beforeEach(() => {
    vi.clearAllMocks();
    mockConfig.endpoints = {
      retentionPolicy: 'https://example.com/retentionPolicy',
      retentionExport: 'https://example.com/retentionExport',
      retentionPurge: 'https://example.com/retentionPurge',
    };
  });

  it('passes media IDs to fetchMediaIdentities', async () => {
    fetchApiMock.mockResolvedValue({ identities_by_media: {}, data_source: 'backend_proxy' });
    await fetchMediaIdentities([1, 2]);
    expect(fetchApiMock).toHaveBeenCalledTimes(1);
    const [endpoint] = fetchApiMock.mock.calls[0] ?? [];
    const url = new URL(endpoint);
    expect(url.searchParams.getAll('media_ids[]')).toEqual(['1', '2']);
    expect(fetchApiMock).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        method: 'GET',
        restNonce: 'nonce-123',
      }),
    );
  });

  it('sends nonce when fetching media identities', async () => {
    fetchApiMock.mockResolvedValue({ identities_by_media: {}, data_source: 'backend_proxy' });
    await fetchMediaIdentities([99]);
    expect(fetchApiMock).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        method: 'GET',
        restNonce: 'nonce-123',
      }),
    );
  });

  it('normalizes media identity data_source metadata', async () => {
    fetchApiMock.mockResolvedValue({ identities_by_media: {}, data_source: 'backend_proxy' });

    const result = await fetchMediaIdentities([99]);

    expect(result.data_source).toBe(DATA_SOURCE.BACKEND_PROXY);
  });

  it('rejects media identity payloads without canonical metadata', async () => {
    fetchApiMock.mockResolvedValue({ identities_by_media: {} });

    await expect(fetchMediaIdentities([99])).rejects.toThrow(
      'Media identities response must include a valid data_source.',
    );
  });

  it('normalizes top-unlabeled response metadata', async () => {
    fetchApiMock.mockResolvedValue({
      clusters: [],
      limit: 20,
      total: 0,
      truncated: false,
      singleton_count: 0,
      data_source: 'unavailable',
      projection_status: 'bootstrapping',
    });

    const result = await fetchTopUnlabeledClusters('tenant-1', 20);

    expect(result.limit).toBe(20);
    expect(result.total).toBe(0);
    expect(result.truncated).toBe(false);
    expect(result.data_source).toBe(DATA_SOURCE.UNAVAILABLE);
    expect(result.projection_status).toBe(PROJECTION_STATUS.BOOTSTRAPPING);
  });

  it('rejects top-unlabeled payloads without canonical envelope metadata', async () => {
    fetchApiMock.mockResolvedValue({
      clusters: [],
      data_source: 'backend_proxy',
    });

    await expect(fetchTopUnlabeledClusters('tenant-1', 20)).rejects.toThrow(
      'Top-unlabeled clusters response must include a numeric limit.',
    );
  });

  it('accepts backend-proxy top-unlabeled payloads without projection metadata', async () => {
    fetchApiMock.mockResolvedValue({
      clusters: [],
      limit: 20,
      total: 0,
      truncated: false,
      data_source: 'backend_proxy',
    });

    const result = await fetchTopUnlabeledClusters('tenant-1', 20);

    expect(result.limit).toBe(20);
    expect(result.total).toBe(0);
    expect(result.truncated).toBe(false);
    expect(result.data_source).toBe(DATA_SOURCE.BACKEND_PROXY);
    expect(result.singleton_count).toBeUndefined();
    expect(result.projection_status).toBeUndefined();
  });

  it('normalizes cluster-members response metadata', async () => {
    fetchApiMock.mockResolvedValue({
      members: [],
      limit: 500,
      total: 0,
      truncated: false,
    });

    const result = await fetchClusterMembers('cluster-1');

    expect(result).toEqual({
      members: [],
      limit: 500,
      total: 0,
      truncated: false,
    });
    expect(fetchApiMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/cluster-1\/members$/),
      expect.objectContaining({ method: 'GET' }),
    );
  });

  it('forwards optional limit and offset query params on cluster members', async () => {
    fetchApiMock.mockResolvedValue({
      members: [],
      limit: 2,
      total: 5,
      truncated: true,
    });

    await fetchClusterMembers('cluster-1', { limit: 2, offset: 2 });

    const [endpoint] = fetchApiMock.mock.calls[0] ?? [];
    expect(String(endpoint)).toContain('limit=2');
    expect(String(endpoint)).toContain('offset=2');
  });

  it('rejects cluster-members payloads without canonical envelope metadata', async () => {
    fetchApiMock.mockResolvedValue({ members: [] });

    await expect(fetchClusterMembers('cluster-1')).rejects.toThrow(
      'Cluster members response must include a numeric limit.',
    );
  });

  it('normalizes pending suggestion data_source metadata', async () => {
    fetchApiMock.mockResolvedValue({
      suggestions: [],
      total: 0,
      limit: 10,
      offset: 0,
      data_source: 'backend_proxy',
    });

    const result = await fetchPendingSuggestions(10, 0);

    expect(result.data_source).toBe(DATA_SOURCE.BACKEND_PROXY);
  });

  it('rejects pending suggestion envelopes without canonical metadata', async () => {
    fetchApiMock.mockResolvedValue({
      suggestions: [],
      total: 0,
      limit: 10,
      offset: 0,
    });

    await expect(fetchPendingSuggestions(10, 0)).rejects.toThrow(
      'Pending suggestions response must include a valid data_source.',
    );
  });

  it('normalizes pending name suggestion data_source metadata', async () => {
    fetchApiMock.mockResolvedValue({
      suggestions: [],
      total: 0,
      limit: 25,
      offset: 0,
      data_source: 'unavailable',
    });

    const result = await fetchPendingNameSuggestions(0, 25, 0);

    expect(result.data_source).toBe(DATA_SOURCE.UNAVAILABLE);
  });

  it('rejects pending name suggestion envelopes without canonical metadata', async () => {
    fetchApiMock.mockResolvedValue({
      suggestions: [],
      total: 0,
      limit: 25,
      offset: 0,
    });

    await expect(fetchPendingNameSuggestions(0, 25, 0)).rejects.toThrow(
      'Pending name suggestions response must include a valid data_source.',
    );
  });

  it('calls updateClusterLabel with PATCH', async () => {
    fetchApiMock.mockResolvedValue({});
    await updateClusterLabel('cluster-1', 'New Label');
    const [, options] = fetchApiMock.mock.calls[0] ?? [];
    expect(fetchApiMock).toHaveBeenCalledWith(expect.stringContaining('/cluster-1'), expect.any(Object));
    expect(options).toMatchObject({ method: 'PATCH', body: { label: 'New Label' }, restNonce: 'nonce-123' });
  });

  it('calls mergeCluster with POST', async () => {
    fetchApiMock.mockResolvedValue({});
    await mergeCluster('source', 'target-cluster-id', 'Target Label');
    const [, options] = fetchApiMock.mock.calls[0] ?? [];
    expect(fetchApiMock).toHaveBeenCalledWith(expect.stringContaining('/source/merge'), expect.any(Object));
    expect(options).toMatchObject({
      method: 'POST',
      body: { target_cluster_id: 'target-cluster-id', target_label: 'Target Label' },
      restNonce: 'nonce-123',
    });
  });

  it('normalizes backend merge responses for the cluster edit UI', async () => {
    fetchApiMock.mockResolvedValue({
      id: 'target-cluster-id',
      label: 'Target Label',
      identity_count: 7,
    });

    const result = await mergeCluster('source-cluster-id', 'target-cluster-id', 'Target Label');

    expect(result).toEqual({
      source_id: 'source-cluster-id',
      source_label: null,
      target_id: 'target-cluster-id',
      target_label: 'Target Label',
      identities_moved: 0,
      moved_identity_ids: [],
      target_identity_count: 7,
    });
  });

  it('posts revert merge payload', async () => {
    fetchApiMock.mockResolvedValue({});
    await revertMergeCluster({
      targetClusterId: 'target-1',
      movedIdentityIds: ['id-1', 'id-2'],
      sourceLabel: 'Alice',
    });
    expect(fetchApiMock).toHaveBeenCalledWith(expect.any(String), {
      method: 'POST',
      body: {
        target_cluster_id: 'target-1',
        moved_identity_ids: ['id-1', 'id-2'],
        source_label: 'Alice',
      },
      restNonce: 'nonce-123',
    });
  });

  it('posts representative pin state to the representative pin endpoint', async () => {
    fetchApiMock.mockResolvedValue({});

    await pinRepresentative('cluster-1', 'identity-77', true);

    expect(fetchApiMock).toHaveBeenCalledWith(expect.stringContaining('/cluster-1/representatives/identity-77/pin'), {
      method: 'PATCH',
      body: { is_pinned: true },
      restNonce: 'nonce-123',
      signal: undefined,
    });
  });

  it('returns job response from backend', async () => {
    const mockResponse = {
      id: 'job-1',
      type: 'analyze',
      status: 'pending',
      progress: { completed: 0, total: 20 },
      started_at: '2025-01-01T00:00:00Z',
      finished_at: null,
    };
    fetchApiMock.mockResolvedValue(mockResponse);

    const result = await scanFaces({ mediaIds: [1, 2] });
    expect(result.id).toBe('job-1');
    expect(result.status).toBe('pending');
    expect(result.progress?.total).toBe(20);
  });

  it('starts an async export job and returns job_id and status', async () => {
    fetchApiMock.mockResolvedValue({ job_id: 'export-job-1', status: 'pending' });

    const result = await exportTenantData();

    expect(result).toEqual({ job_id: 'export-job-1', status: 'pending' });
    expect(fetchApiMock).toHaveBeenCalledWith(
      expect.stringContaining('/retentionExport'),
      expect.objectContaining({ method: 'POST', restNonce: 'nonce-123' }),
    );
  });

  it('normalizes the flat retention export snapshot the service actually returns', async () => {
    // rg-015: `GET /retention/export/{job_id}/data` returns `ExportJob.data_json`
    // verbatim (retention.py:208-211), i.e. the bare snapshot from
    // `TenantExportService.export_tenant_data`, proxied through unchanged. There
    // is no `data`/`payload` wrapper and no `counts`/`summary` field on the wire.
    fetchApiMock.mockResolvedValue({
      tenant_id: 'tenant-1',
      exported_at: '2026-03-12T12:00:00Z',
      schema_version: 3,
      clusters: [{ id: 'cluster-1' }],
      media_identities: [],
    });

    const result = await downloadExportJobData('export-job-1');

    expect(result.tenant_id).toBe('tenant-1');
    expect(result.exported_at).toBe('2026-03-12T12:00:00Z');
    expect(result.schema_version).toBe(3);
    expect(result.payload).toEqual({
      tenant_id: 'tenant-1',
      exported_at: '2026-03-12T12:00:00Z',
      schema_version: 3,
      clusters: [{ id: 'cluster-1' }],
      media_identities: [],
    });
    // Counts are derived from the snapshot's own arrays, never read from an
    // upstream field that does not exist.
    expect(result.summary).toEqual({ clusters: 1, media_identities: 0 });
    expect(fetchApiMock).toHaveBeenCalledWith(
      expect.stringContaining('/retentionExport/export-job-1/data'),
      expect.objectContaining({ method: 'GET', restNonce: 'nonce-123' }),
    );
  });

  it('derives counts from the arrays even when the response also carries a counts field [rg-015]', async () => {
    // A valid flat snapshot that additionally carries a stray `counts`. rg-015:
    // the adapter must not prefer upstream-supplied metadata it does not have a
    // contract for — the arrays are the only truth about what was exported.
    fetchApiMock.mockResolvedValue({
      schema_version: 3,
      clusters: [{ id: 'cluster-1' }, { id: 'cluster-2' }],
      media_identities: [{ id: 'identity-1' }],
      counts: { clusters: 99, media_identities: 0 },
      summary: { clusters: 0 },
    });

    const result = await downloadExportJobData('export-job-1');

    expect(result.summary).toEqual({ clusters: 2, media_identities: 1 });
    expect(fetchApiMock).toHaveBeenCalledWith(
      expect.stringContaining('/retentionExport/export-job-1/data'),
      expect.objectContaining({ method: 'GET', restNonce: 'nonce-123' }),
    );
  });

  it('rejects the fabricated {counts, data} envelope instead of silently accepting it [FEBT1-LG-01][rg-015]', async () => {
    // The shape this test used to assert as correct. The service never emits it,
    // so accepting it meant an adapter supporting two upstream shapes and
    // inventing `summary` from a field that is not on the wire. `members` is not
    // even an export collection — proof the old expectation was fabricated.
    fetchApiMock.mockResolvedValue({
      tenant_id: 'tenant-1',
      exported_at: '2026-03-12T12:00:00Z',
      schema_version: 1,
      counts: { clusters: 2, members: 3 },
      data: {
        clusters: [{ id: 'cluster-1' }],
      },
    });

    await expect(downloadExportJobData('export-job-1')).rejects.toThrow(RetentionExportResponseError);
    // The request is still issued to the documented endpoint; the rejection is
    // in the adapter, not a short-circuit before the call.
    expect(fetchApiMock).toHaveBeenCalledWith(
      expect.stringContaining('/retentionExport/export-job-1/data'),
      expect.objectContaining({ method: 'GET', restNonce: 'nonce-123' }),
    );
  });

  it('rejects a `payload`-wrapped envelope and an empty response [FEBT1-LG-01][rg-015]', async () => {
    fetchApiMock.mockResolvedValue({ schema_version: 3, payload: { clusters: [] }, summary: { clusters: 0 } });
    await expect(downloadExportJobData('export-job-1')).rejects.toThrow(RetentionExportResponseError);

    fetchApiMock.mockResolvedValue({ schema_version: 3, data: { clusters: [] }, counts: { clusters: 0 } });
    await expect(downloadExportJobData('export-job-1')).rejects.toThrow(RetentionExportResponseError);

    // The pre-fix adapter returned `{ payload: {}, summary: {} }` here, which the
    // caller wrote to disk as a successful, empty export (RLSE-05).
    fetchApiMock.mockResolvedValue({});
    await expect(downloadExportJobData('export-job-1')).rejects.toThrow('Export data response was malformed');
  });

  /**
   * FEBT2-LD2-NEW-03 / FEBT2-LE-NEW-06: the barrel exported the functions but not
   * the types and error class those functions traffic in, so every consumer had
   * to deep-import or lose type safety. These are discrimination guards: the
   * value imports at the top of this file resolve through `../recognition`, so
   * dropping any of them from the barrel turns this file red at import time.
   */
  it('narrows the export-download rejection through the barrel-exported error class [FEBT2-LE-NEW-06]', async () => {
    fetchApiMock.mockResolvedValue({ schema_version: 1, counts: { clusters: 2 }, data: { clusters: [] } });

    await expect(downloadExportJobData('export-job-1')).rejects.toBeInstanceOf(RetentionExportResponseError);
    // Not merely "some Error": the barrel must carry the narrowable subclass, or
    // the fail-loud contract degrades to a generic catch at the barrel callers.
    expect(RetentionExportResponseError.prototype).toBeInstanceOf(Error);
    expect(Object.getPrototypeOf(RetentionExportResponseError.prototype)).toBe(Error.prototype);
  });

  it('exports the canonical export-collection key list through the barrel [rg-015]', () => {
    // The single frontend copy of the wire contract's collection keys. A barrel
    // consumer must be able to reach it without a deep import, otherwise it
    // re-derives the key list and drifts from the backend (rg-005).
    expect([...EXPORT_COLLECTION_KEYS]).toEqual([
      'clusters',
      'media_identities',
      'identity_suggestions',
      'name_suggestions',
      'cluster_merge_suggestions',
      'scan_jobs',
    ]);
  });

  it('keeps the bare-string mutationFn inference on the barrel-exported acceptMergeSuggestion [FEBT2-LD2-NEW-03]', async () => {
    // The bare-`string` overload is declared LAST so `mutationFn: acceptMergeSuggestion`
    // infers `string`. A conditional `infer` resolves an overloaded function
    // against its LAST signature, so reordering the overloads flips this to
    // `AcceptMergeSuggestionRequest` and fails the type-check gate.
    type InferMutationVariables<T> = T extends (variables: infer V) => Promise<unknown> ? V : never;
    expectTypeOf<InferMutationVariables<typeof acceptMergeSuggestion>>().toEqualTypeOf<string>();

    const mergePayload = {
      id: 'merge-suggestion-1',
      cluster_a_id: 'cluster-a',
      cluster_b_id: 'cluster-b',
      similarity: 0.91,
      status: 'accepted',
      source_cluster_id: 'cluster-a',
      target_cluster_id: 'cluster-b',
      moved_identity_ids: ['identity-1'],
    };
    fetchApiMock.mockResolvedValue(mergePayload);

    // Both overloads are reachable through the barrel, and the request object
    // still carries the optional survivor pin to the wire.
    const pinned: AcceptMergeSuggestionRequest = { suggestionId: 'merge-suggestion-1', targetClusterId: 'cluster-b' };
    const accepted: AcceptedMergeSuggestion = await acceptMergeSuggestion(pinned);

    expect(accepted.source_cluster_id).toBe('cluster-a');
    expect(accepted.target_cluster_id).toBe('cluster-b');
    expect(accepted.moved_identity_ids).toEqual(['identity-1']);
    expect(fetchApiMock).toHaveBeenCalledWith(
      expect.stringContaining('/merge-suggestion-1/accept'),
      expect.objectContaining({ method: 'POST', body: { target_cluster_id: 'cluster-b' } }),
    );

    fetchApiMock.mockClear();
    const bare: AcceptedMergeSuggestion = await acceptMergeSuggestion('merge-suggestion-1');
    expect(bare.moved_identity_ids).toEqual(['identity-1']);
    // No survivor pinned => no body, so the server keeps its own ordering.
    expect(fetchApiMock).toHaveBeenCalledWith(
      expect.stringContaining('/merge-suggestion-1/accept'),
      expect.objectContaining({ method: 'POST', body: undefined }),
    );
  });

  it('types schema_version as always present on a normalized export response [FEBT2-LE-NEW-05]', async () => {
    fetchApiMock.mockResolvedValue({ schema_version: 3, clusters: [{ id: 'cluster-1' }] });

    const result: RetentionExportResponse = await downloadExportJobData('export-job-1');

    // Required, not optional: the adapter throws on a missing/non-integer
    // schema_version, so `number | undefined` would force a null-guard on a case
    // the boundary makes unrepresentable.
    expectTypeOf<RetentionExportResponse['schema_version']>().toEqualTypeOf<number>();
    expectTypeOf<RetentionExportResponse['tenant_id']>().toEqualTypeOf<string | undefined>();
    const schemaVersion: number = result.schema_version;
    expect(schemaVersion).toBe(3);
  });

  it('exports the phase-0 suggestion stub types through the recognition barrel', () => {
    const pendingNameSuggestion = {
      id: 'name-suggestion-1',
      cluster_id: 'cluster-1',
      suggested_name: 'Taylor',
      confidence_score: 0.88,
      source: 'roster',
      created_at: '2026-03-19T12:00:00Z',
      expires_at: null,
      representatives: [],
    } satisfies PendingNameSuggestion;
    const bulkAcceptRequest = {
      suggestion_type: 'name',
      min_confidence: 0.75,
    } satisfies BulkAcceptRequest;
    const bulkAcceptResponse = {
      accepted_count: 2,
      skipped_count: 1,
    } satisfies BulkAcceptResponse;

    const representatives: PendingNameSuggestion['representatives'] = pendingNameSuggestion.representatives;

    expectTypeOf(bulkAcceptRequest.min_confidence).toMatchTypeOf<BulkAcceptRequest['min_confidence']>();
    expectTypeOf(bulkAcceptResponse.accepted_count).toMatchTypeOf<BulkAcceptResponse['accepted_count']>();

    expect(pendingNameSuggestion.id).toBe('name-suggestion-1');
    expect(representatives).toEqual([]);
    expect(bulkAcceptRequest.suggestion_type).toBe('name');
    expect(bulkAcceptResponse.accepted_count).toBe(2);
    expect(bulkAcceptResponse.skipped_count).toBe(1);
  });

  it('returns the proxied retention policy payload from updateRetentionPolicy', async () => {
    fetchApiMock.mockResolvedValue({
      retention_mode: 'purge_on_demand',
      last_export_at: '2026-03-12T12:00:00Z',
      last_purge_at: null,
      retention_updated_at: '2026-03-12T12:30:00Z',
    });

    const result = await updateRetentionPolicy({ retention_mode: 'purge_on_demand' });

    expect(result).toEqual({
      retention_mode: 'purge_on_demand',
      last_export_at: '2026-03-12T12:00:00Z',
      last_purge_at: null,
      retention_updated_at: '2026-03-12T12:30:00Z',
    });
    expect(fetchApiMock).toHaveBeenCalledWith(
      expect.stringContaining('/retentionPolicy'),
      expect.objectContaining({
        method: 'PATCH',
        body: { retention_mode: 'purge_on_demand' },
        restNonce: 'nonce-123',
      }),
    );
  });

  it('fetches retention status from the configured endpoint with the admin nonce', async () => {
    mockConfig.endpoints.retentionStatus = 'https://example.com/retentionStatus';
    fetchApiMock.mockResolvedValue({
      available: true,
      policy: {
        retention_mode: 'dispose_after_ack',
        last_export_at: '2026-03-12T12:00:00Z',
        last_purge_at: null,
        retention_updated_at: '2026-03-12T12:30:00Z',
      },
      recent_audit_events: [],
    });

    const result = await fetchRetentionStatus();

    expect(result).toEqual({
      available: true,
      policy: {
        retention_mode: 'dispose_after_ack',
        last_export_at: '2026-03-12T12:00:00Z',
        last_purge_at: null,
        retention_updated_at: '2026-03-12T12:30:00Z',
      },
      recent_audit_events: [],
    });
    expect(fetchApiMock).toHaveBeenCalledWith(
      expect.stringContaining('/retentionStatus'),
      expect.objectContaining({
        method: 'GET',
        restNonce: 'nonce-123',
      }),
    );
  });

  it('returns an unavailable retention status when the endpoint is not configured', async () => {
    const result = await fetchRetentionStatus();

    expect(result).toEqual({
      available: false,
      policy: null,
      recent_audit_events: [],
    });
    expect(fetchApiMock).not.toHaveBeenCalled();
  });

  it('posts purge requests to the retention purge endpoint', async () => {
    fetchApiMock.mockResolvedValue({ deleted_counts: { media_identities: 2 } });

    const result = await purgeTenantData({ scope: 'all', confirm: true });

    expect(result).toEqual({ deleted_counts: { media_identities: 2 } });
    expect(fetchApiMock).toHaveBeenCalledWith(
      expect.stringContaining('/retentionPurge'),
      expect.objectContaining({
        method: 'POST',
        body: { scope: 'all', confirm: true },
        restNonce: 'nonce-123',
      }),
    );
  });

  it('normalizes pending suggestion envelope payloads from the WP proxy', async () => {
    fetchApiMock.mockResolvedValue({
      suggestions: [
        {
          id: 's-1',
          identity_id: 'identity-1',
          cluster_id: 'cluster-1',
          rep_similarity: 0.87,
          member_similarity: null,
          status: 'pending',
        },
      ],
      limit: 10,
      offset: 5,
      data_source: 'backend_proxy',
    });

    const result = await fetchPendingSuggestions(10, 5);

    // COR-3 (rg-015): the boundary no longer forwards an authoritative total.
    expect('total' in result).toBe(false);
    expect(result.limit).toBe(10);
    expect(result.offset).toBe(5);
    expect(result.suggestions[0]).toMatchObject({
      id: 's-1',
      identity_id: 'identity-1',
      suggested_cluster_id: 'cluster-1',
      representative_similarity: 0.87,
      avg_member_similarity: 0.87,
      confidence_score: 0.87,
    });
    expect(result.data_source).toBe(DATA_SOURCE.BACKEND_PROXY);
  });

  it('normalizes pending merge suggestion envelope payloads from the WP proxy', async () => {
    fetchApiMock.mockResolvedValue({
      suggestions: [
        {
          id: 'm-1',
          cluster_a_id: 'cluster-a',
          cluster_b_id: 'cluster-b',
          similarity: 0.93,
          status: 'pending',
        },
      ],
      limit: 25,
      offset: 0,
      data_source: 'backend_proxy',
    });

    const result = await fetchPendingMergeSuggestions(25, 0);

    // COR-3 (rg-015): the boundary no longer forwards an authoritative total.
    expect('total' in result).toBe(false);
    expect(result.limit).toBe(25);
    expect(result.offset).toBe(0);
    expect(result.suggestions[0]).toMatchObject({
      id: 'm-1',
      cluster_a_id: 'cluster-a',
      cluster_b_id: 'cluster-b',
      similarity: 0.93,
      status: 'pending',
      cluster_a_label: null,
      cluster_b_label: null,
    });
    expect(result.data_source).toBe(DATA_SOURCE.BACKEND_PROXY);
  });

  it('builds cluster list query params through URLSearchParams', async () => {
    fetchApiMock.mockResolvedValue({
      clusters: [],
      limit: 20,
      total: 0,
      truncated: false,
    });

    const result = await listRecognitionClusters({
      limit: 20,
      offset: 5,
      labeled_only: true,
      search: 'Alex Carter',
    });

    expect(fetchApiMock).toHaveBeenCalledTimes(1);
    const [endpoint, options] = fetchApiMock.mock.calls[0] ?? [];
    const url = new URL(endpoint);

    expect(url.searchParams.get('limit')).toBe('20');
    expect(url.searchParams.get('offset')).toBe('5');
    expect(url.searchParams.get('labeled_only')).toBe('true');
    expect(url.searchParams.get('search')).toBe('Alex Carter');
    expect(options).toMatchObject({ method: 'GET', restNonce: 'nonce-123' });
    expect(result).toEqual({ clusters: [], limit: 20, total: 0, truncated: false });
  });

  it('rejects cluster list payloads that omit envelope metadata', async () => {
    fetchApiMock.mockResolvedValue({});

    await expect(listRecognitionClusters()).rejects.toThrow('Cluster list response must include a clusters array.');
  });

  it('requests a single cluster detail from the canonical cluster endpoint', async () => {
    fetchApiMock.mockResolvedValue({
      id: 'cluster-9',
      label: 'Cluster 9',
      identity_count: 1,
      member_ids: ['identity-1'],
      representative_identity: { media_id: 1, bbox: { x: 0, y: 0, width: 1, height: 1 } },
      sample_identities: [],
    });

    await getRecognitionCluster('cluster-9');

    expect(fetchApiMock).toHaveBeenCalledWith(expect.stringContaining('/cluster-9'), {
      method: 'GET',
      restNonce: 'nonce-123',
    });
  });

  it('normalizes top-unlabeled representative thumbnail fields', async () => {
    fetchApiMock.mockResolvedValue({
      clusters: [
        {
          id: 'cluster-1',
          tenant_id: 'tenant-1',
          label: null,
          is_labeled: false,
          is_auto_label: false,
          identity_count: 2,
          user_confirmed: false,
          representatives: [
            {
              id: 'rep-1',
              media_id: '101',
              is_user_selected: false,
              thumb_url: 'http://example.test/thumb-101.jpg',
              media_url: ' ',
              bbox: null,
            },
            {
              id: 'rep-2',
              media_id: '202',
              is_user_selected: false,
              thumb_url: 'http://example.test/thumb-202.jpg',
              media_url: 'http://example.test/media-202.jpg',
              bbox: null,
            },
          ],
        },
      ],
      limit: 3,
      total: 5,
      truncated: true,
      singleton_count: 4,
      has_clusters: true,
      data_source: 'local_projection',
      projection_status: 'available',
    });

    const result = await fetchTopUnlabeledClusters('tenant-1', 3);

    expect(result.singleton_count).toBe(4);
    expect(result.limit).toBe(3);
    expect(result.total).toBe(5);
    expect(result.truncated).toBe(true);
    expect(result.clusters[0]?.representatives[0]).toMatchObject({
      thumb_url: 'http://example.test/thumb-101.jpg',
      media_url: null,
    });
    expect(result.clusters[0]?.representatives[1]).toMatchObject({
      thumb_url: 'http://example.test/thumb-202.jpg',
      media_url: 'http://example.test/media-202.jpg',
    });

    const [endpoint] = fetchApiMock.mock.calls[0] ?? [];
    const url = new URL(endpoint);
    expect(url.searchParams.get('tenant_id')).toBe('tenant-1');
    expect(url.searchParams.get('limit')).toBe('3');
  });

  // E21-17-R4-PY-1 / R5-TS: wire is_user_selected → internal is_pinned; strip wire key.
  it.each([
    { label: 'true → is_pinned true', is_user_selected: true, expectedPinned: true },
    { label: 'false → is_pinned false', is_user_selected: false, expectedPinned: false },
    { label: 'absent → is_pinned false', is_user_selected: undefined, expectedPinned: false },
  ])('maps wire is_user_selected ($label)', async ({ is_user_selected, expectedPinned }) => {
    const representative: Record<string, unknown> = {
      id: 'rep-1',
      media_id: '7',
      thumb_url: null,
      media_url: null,
      bbox: null,
    };
    if (is_user_selected !== undefined) {
      representative.is_user_selected = is_user_selected;
    }

    fetchApiMock.mockResolvedValue({
      clusters: [
        {
          id: 'cluster-1',
          tenant_id: 'tenant-1',
          label: null,
          is_labeled: false,
          is_auto_label: false,
          identity_count: 1,
          user_confirmed: false,
          representatives: [representative],
        },
      ],
      limit: 1,
      total: 1,
      truncated: false,
      singleton_count: 0,
      has_clusters: true,
      data_source: 'local_projection',
      projection_status: 'available',
    });

    const result = await fetchTopUnlabeledClusters('tenant-1', 1);
    const normalized = result.clusters[0]?.representatives[0];

    expect(normalized?.is_pinned).toBe(expectedPinned);
    expect(normalized).not.toHaveProperty('is_user_selected');
  });

  // E21-17-R4-PY-2 / R5-TS / R6-TS-1: wire media_id digit string|null → number|null.
  // Canonical wire is untrimmed /^\d+$/; whitespace-padded values reject to null.
  it.each([
    { label: '"7" → 7', wire: '7', expected: 7 },
    { label: '"007" → 7', wire: '007', expected: 7 },
    { label: '" 7 " → null', wire: ' 7 ', expected: null },
    { label: '"7\\n" → null', wire: '7\n', expected: null },
    { label: '" " → null', wire: ' ', expected: null },
    { label: 'null stays null', wire: null, expected: null },
  ])('normalizes wire media_id ($label)', async ({ wire, expected }) => {
    fetchApiMock.mockResolvedValue({
      clusters: [
        {
          id: 'cluster-1',
          tenant_id: 'tenant-1',
          label: null,
          is_labeled: false,
          is_auto_label: false,
          identity_count: 1,
          user_confirmed: false,
          representatives: [
            {
              id: 'rep-1',
              media_id: wire,
              is_user_selected: false,
              thumb_url: null,
              media_url: null,
              bbox: null,
            },
          ],
        },
      ],
      limit: 1,
      total: 1,
      truncated: false,
      singleton_count: 0,
      has_clusters: true,
      data_source: 'local_projection',
      projection_status: 'available',
    });

    const result = await fetchTopUnlabeledClusters('tenant-1', 1);
    expect(result.clusters[0]?.representatives[0]?.media_id).toBe(expected);
  });

  // E21-17-R4-PY-1 / R5-TS: name-suggestion representatives cross the same wire boundary.
  it('maps name-suggestion representative is_user_selected → is_pinned and media_id string', async () => {
    fetchApiMock.mockResolvedValue({
      suggestions: [
        {
          id: 'name-1',
          cluster_id: 'cluster-1',
          suggested_name: 'Pat',
          confidence_score: 0.9,
          source: 'identity',
          created_at: '2026-03-19T12:00:00Z',
          expires_at: null,
          representatives: [
            {
              id: 'rep-1',
              media_id: '42',
              is_user_selected: true,
              thumb_url: null,
              media_url: null,
              bbox: null,
            },
          ],
        },
      ],
      limit: 25,
      offset: 0,
      data_source: 'backend_proxy',
    });

    const result = await fetchPendingNameSuggestions(0, 25, 0);
    const rep = result.suggestions[0]?.representatives?.[0];

    expect(rep?.is_pinned).toBe(true);
    expect(rep?.media_id).toBe(42);
    expect(rep).not.toHaveProperty('is_user_selected');
  });

  it('fetches sync status with nonce', async () => {
    fetchApiMock.mockResolvedValue({
      last_snapshot_version: 10,
      last_synced_at: '2026-02-14 00:00:00',
      is_stale: false,
    });

    await fetchSyncStatus();

    expect(fetchApiMock).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        method: 'GET',
        restNonce: 'nonce-123',
      }),
    );
  });

  it('triggers sync with POST method', async () => {
    fetchApiMock.mockResolvedValue({
      synced: true,
      reason: 'ok',
      last_snapshot_version: 1,
      last_synced_at: '2026-02-18 10:00:00',
      is_stale: false,
    });

    await triggerSync();

    expect(fetchApiMock).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        method: 'POST',
        restNonce: 'nonce-123',
      }),
    );
  });

  it('uses a stable sub-path slash for job mutations when the base endpoint has a trailing slash', async () => {
    const { getEndpoint } = await import('../config');
    vi.mocked(getEndpoint).mockImplementation((...keys: string[]) => `https://example.com/${keys[0] ?? 'default'}/`);
    fetchApiMock.mockResolvedValue({ status: 'acknowledged', snapshot_version: 3 });

    await cancelScanJob('job-4');

    expect(fetchApiMock).toHaveBeenNthCalledWith(
      1,
      'https://example.com/recognitionJobs/job-4/cancel',
      expect.objectContaining({ method: 'POST' }),
    );
  });
});
