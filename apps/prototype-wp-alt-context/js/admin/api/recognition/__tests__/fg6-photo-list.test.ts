import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import Ajv from 'ajv';
import { afterEach, beforeEach, describe, expect, expectTypeOf, it, vi } from 'vitest';

vi.mock('../../../utils/http', () => ({
  fetchRequiredApi: vi.fn(),
  stripTrailingSlash: (s: string) => s.replace(/\/$/, ''),
}));
vi.mock('../../config', () => ({
  getEndpoint: () => '/wp-json/alt-context/v1/recognition/clusters',
  getConfig: () => ({ nonce: 'test' }),
}));
import { fetchRequiredApi } from '../../../utils/http';
import { listRecognitionClusters, listRecognitionClusterPage } from '../clusterApiQueries';
import type { ClusterListResponse, ClusterPhotoListResponse } from '../types/cluster';

// Shapes read from the FG6 WordPress envelope service and backend ClusterResponse.
const local = {
  id: 'local',
  label: 'Ada',
  identity_count: 12,
  photo_count: 2,
  member_ids: ['face'],
  representative_identity: { media_id: 7, bbox: { x: 0, y: 0, width: 20, height: 20 } },
  sample_identities: [],
  person_uuid: 'local-person',
  label_state: 'person',
};
const remote = {
  id: 'remote',
  tenant_id: 'tenant',
  label: null,
  is_labeled: false,
  is_auto_label: false,
  identity_count: 12,
  photo_count: null,
  representatives: [{ id: 'face', media_id: '7', bbox: null, is_user_selected: false }],
  person_uuid: null,
  label_state: 'unlabeled',
};
const envelope = (clusters: unknown[] = [local], extra = {}) => ({
  clusters,
  limit: 2,
  total: 1,
  truncated: false,
  ...extra,
});
const mockFetch = vi.mocked(fetchRequiredApi);

beforeEach(() => {
  vi.stubGlobal('window', { location: { origin: 'https://example.test' } });
  mockFetch.mockResolvedValue(envelope());
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetAllMocks();
});

describe('FG6 photo listing transport', () => {
  it('keeps legacy ReturnType numeric and the dynamic opt-in contract nullable', async () => {
    expectTypeOf<Awaited<ReturnType<typeof listRecognitionClusters>>>().toEqualTypeOf<ClusterListResponse>();
    expectTypeOf<Awaited<ReturnType<typeof listRecognitionClusterPage>>>().toEqualTypeOf<ClusterPhotoListResponse>();
    mockFetch.mockResolvedValue(envelope([remote], { total: null, truncated: true }));
    expect((await listRecognitionClusterPage({ min_photos: 2 })).total).toBeNull();
  });
  it.each([1, 2147483647])('accepts producer minimum boundary %s', async (min_photos) => {
    await listRecognitionClusters({ min_photos, search: 'Ada', labeled_only: true });
    const url = new URL(mockFetch.mock.calls[0][0]);
    expect(url.searchParams.get('min_photos')).toBe(String(min_photos));
    expect(url.searchParams.get('search')).toBe('Ada');
    expect(url.searchParams.get('labeled_only')).toBe('true');
  });
  it.each([-1, 1.5, '2', false])('rejects an invalid photo count without using face count: %s', async (photo_count) => {
    mockFetch.mockResolvedValue(envelope([{ ...local, photo_count }]));
    await expect(listRecognitionClusters()).rejects.toThrow('photo_count');
  });
  it('forwards the minimum with offset to the producer and retains local person authority', async () => {
    mockFetch.mockResolvedValue(envelope());
    const page = await listRecognitionClusters({ min_photos: 2, offset: 4, limit: 2 });
    const url = new URL(mockFetch.mock.calls[0][0]);
    expect(url.searchParams.get('min_photos')).toBe('2');
    expect(url.searchParams.get('offset')).toBe('4');
    expect(page.clusters[0]).toEqual(local);
  });
  it('preserves unknown total and remote representatives without manufacturing local member fields', async () => {
    mockFetch.mockResolvedValue(envelope([remote], { total: null, truncated: true }));
    const page = await listRecognitionClusters({ min_photos: 2 });
    expect(page.total).toBeNull();
    expect(page.truncated).toBe(true);
    expect(page.clusters[0]).toEqual(remote);
    expect(page.clusters[0]).not.toHaveProperty('member_ids');
  });
  it('keeps omission identical and does not invent absent photo counts', async () => {
    const old: Partial<typeof local> = { ...local };
    delete old.photo_count;
    mockFetch.mockResolvedValue(envelope([old]));
    const page = await listRecognitionClusters();
    expect(new URL(mockFetch.mock.calls[0][0]).searchParams.has('min_photos')).toBe(false);
    expect(page.clusters[0]).not.toHaveProperty('photo_count');
    expect(page.total).toBe(1);
  });
  it('continues rejecting unknown totals on the legacy unfiltered contract', async () => {
    mockFetch.mockResolvedValue(envelope([], { total: null }));
    await expect(listRecognitionClusters()).rejects.toThrow('numeric total');
  });
  it.each([0, -1, 1.5, NaN, Infinity, 2147483648, null, '2', true])(
    'rejects malformed minima before fetching: %s',
    async (min_photos) => {
      await expect(listRecognitionClusters({ min_photos } as never)).rejects.toThrow('min_photos');
      expect(mockFetch).not.toHaveBeenCalled();
    },
  );
  it.each([undefined, '3', false])('does not confuse malformed total with explicitly unknown: %s', async (total) => {
    mockFetch.mockResolvedValue(envelope([], { total }));
    await expect(listRecognitionClusters({ min_photos: 2 })).rejects.toThrow('numeric total');
  });
  it('preserves cancellation and failure instead of emitting empty success', async () => {
    const controller = new AbortController();
    mockFetch.mockRejectedValue(new Error('producer failed'));
    await expect(listRecognitionClusters({ min_photos: 2 }, controller.signal)).rejects.toThrow('producer failed');
    expect(mockFetch.mock.calls[0][1]?.signal).toBe(controller.signal);
  });
});

describe('FG6 shared schema opt-in fragment', () => {
  const schema = JSON.parse(
    readFileSync(
      resolve(process.cwd(), '../../packages/shared-contracts/schemas/recognition-cluster-list-response.schema.json'),
      'utf8',
    ),
  ) as { $id: string; [key: string]: unknown };
  const ajv = new Ajv({ allErrors: true });
  ajv.addSchema(schema);
  const validate = (value: unknown) => ajv.validate(`${schema.$id}#/definitions/photoFilteredResponse`, value);
  it('validates local and actual remote shapes including nullable total', () => {
    expect(validate(envelope())).toBe(true);
    expect(validate(envelope([remote], { total: null, truncated: true }))).toBe(true);
  });
  it('leaves absent counts unavailable and rejects false photo totals', () => {
    const old: Partial<typeof local> = { ...local };
    delete old.photo_count;
    expect(validate(envelope([old]))).toBe(true);
    for (const photo_count of [-1, 1.2, '2', false]) {
      expect(validate(envelope([{ ...local, photo_count }]))).toBe(false);
    }
  });
  it('keeps the legacy root envelope contract and validates photo_count there', () => {
    expect(ajv.validate(schema.$id, envelope())).toBe(true);
    expect(ajv.validate(schema.$id, envelope([], { total: null }))).toBe(false);
    expect(ajv.validate(schema.$id, envelope([{ ...local, photo_count: -1 }]))).toBe(false);
  });
});
